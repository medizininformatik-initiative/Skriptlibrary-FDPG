#!/usr/bin/env python3
"""
CRTDL-Filter (Entwicklungsversion, ressourcenschonender)

Gleiche Logik und Ergebnisse wie filter_by_crtdl.py, aber mit weniger Arbeitsspeicher:
  - medicationReference -> Patient wird nur für Medication-IDs gemerkt, die in der
    Medikations-Kerntabelle einen ATC-Treffer haben (vorher: für jede Referenz)
  - der Zwischenspeicher für Code-Vergleiche ist begrenzt

Wendet die Einschlusskriterien einer CRTDL auf die geflatteten CSV-Tabellen eines
Exports an und reduziert die Tabellen auf Patienten, bei denen die Kriterien in den
exportierten Daten (also im Einwilligungszeitraum) tatsächlich erfüllt sind.

Ausführliche Beschreibung: README.md, docs/DETAILS_filter.md

Aufruf:
  python3 /pfad/zu/refine_consent_cohort/filter_by_crtdl.py --crtdl CRTDL.json --csv-dir <job>/csv --out-dir <ausgabe>
"""
import argparse
import csv
import json
import os
import platform
import re
import sys
import time
from collections import Counter, defaultdict

VERSION = "2.2.dev"

# Criteria that cannot be checked by code search in the CSVs (consent, demography)
CONSENT_CONTEXTS = {"einwilligung", "consent"}
DEMOGRAPHY_RE = re.compile(r"geschlecht|gender|\balter\b|\bage\b|geburt|birth|\bsex\b", re.IGNORECASE)
# SNOMED code used by the feasibility portal for "current chronological age"
AGE_CODES = {"424144002"}

# Code values whose match result is kept in memory; the cache is emptied when it gets larger
VALUE_CACHE_MAX = 200000

# Default: reference 'Type/ID' -> 'ID' (also strips '/_history/...')
DEFAULT_ID_RE = r"^(?:[A-Za-z]+/)?([^/]+?)(?:/_history/.*)?$"


# --------------------------------------------------------------------------- helpers
def norm_name(name):
    """Normalise table/group names for comparison: lower case, spaces/underscores/dashes removed."""
    return re.sub(r"[\s_\-]+", "", (name or "").lower())


def detect_encoding(path):
    """utf-8 (with/without BOM), fallback latin-1. Reads the file once to be sure."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            for _ in fh:
                pass
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "latin-1"


def detect_delimiter(path, encoding):
    """Pick the most frequent of ',', ';', tab in the header line."""
    with open(path, encoding=encoding, newline="") as fh:
        header = fh.readline()
    return max((",", ";", "\t"), key=header.count)


def normalize_id(value, id_re):
    v = (value or "").strip()
    if not v:
        return ""
    m = re.match(id_re, v)
    if not m:
        return v
    return m.group(1) if m.groups() else m.group(0)


def build_rule(code, system, exact_only):
    """
    Search rule for one CRTDL code, depending on its code system:
      icd    : 'R26' -> R26, R26.1, R26.10, R261 ; 'I67.8' -> I67.8, I67.88
      ops    : prefix ('8-93' -> 8-930, 8-931.0) or range ('3-10...3-13')
      prefix : ATC ('C07' -> C07AB02)
      exact  : everything else (LOINC, SNOMED, ...)
    """
    s = (system or "").lower()
    if exact_only:
        return ("exact", code)
    if "..." in code:
        start, end = [c.strip() for c in code.split("...", 1)]
        return ("range", start.replace(".", ""), end.replace(".", ""))
    if "icd-10" in s or "icd10" in s:
        return ("icd", re.compile(rf"^{re.escape(code)}(?:\.?[0-9A-Za-z]+)?$"))
    if "/ops" in s:
        return ("ops", code.replace(".", ""))
    if "atc" in s:
        return ("prefix", code)
    return ("exact", code)


def rule_matches(rule, value):
    kind = rule[0]
    if kind == "exact":
        return value == rule[1]
    if kind == "icd":
        return bool(rule[1].match(value))
    if kind == "ops":
        # dots are irrelevant for the OPS hierarchy (8-931.0 == 8-9310)
        return value.replace(".", "").startswith(rule[1])
    if kind == "range":
        # compare the leading part of the code with the range bounds (same length)
        head = value.replace(".", "")[:len(rule[1])]
        return rule[1] <= head <= rule[2]
    if kind == "prefix":
        return value.startswith(rule[1])
    return False


def parse_inclusion_groups(crtdl, exact_only=False):
    """
    Inclusion criteria of a CRTDL as AND list of OR groups, ready for rule_matches().
    Shared with validate_consent_torch.py (--inclusion-check).
    Returns (groups, skipped, notes): skipped/notes are (reason, text) / text for the console.
    """
    groups = []        # AND list of groups; each group = OR list of criteria
    skipped = []       # (reason, text) for the console report
    notes = []         # evaluated, but with simplifications
    for raw_group in crtdl.get("cohortDefinition", {}).get("inclusionCriteria", []):
        group, unevaluable = [], []
        for crit in raw_group:
            terms = [t for t in crit.get("termCodes", []) if t.get("code")]
            text = " / ".join(t.get("display") or t["code"] for t in terms)
            ctx = (crit.get("context") or {})
            # consent is handled by TORCH (consent window), not by this script
            if (ctx.get("code") or "").lower() in CONSENT_CONTEXTS:
                skipped.append(("Consent", text))
                continue
            # age / gender cannot be found by code search -> not evaluable
            if any(t["code"] in AGE_CODES for t in terms) or DEMOGRAPHY_RE.search(text):
                unevaluable.append(text)
                continue
            if not terms:
                unevaluable.append(text or "(ohne Code)")
                continue
            group.append({
                "label": next((t.get("display") for t in terms if t.get("display")), terms[0]["code"]),
                "context": ctx.get("code", ""),
                # (crtdl code, rule) per termCode
                "rules": [(t["code"].strip(), build_rule(t["code"].strip(), t.get("system", ""), exact_only))
                          for t in terms],
                "systems": [t.get("system", "") for t in terms],
                # valueFilter / timeRestriction are ignored: code presence counts (permissive -> never excludes wrongly)
                "value_filter": bool(crit.get("valueFilter") or crit.get("attributeFilters")),
                "time_filter": bool(crit.get("timeRestriction")),
            })
        if unevaluable and group:
            # an OR group with a non-evaluable member cannot be used to exclude anybody
            skipped.append(("Gruppe übersprungen (enthält nicht prüfbares Kriterium)",
                            "; ".join(unevaluable + [c["label"] for c in group])))
            continue
        if unevaluable:
            skipped.append(("nicht prüfbar (Alter/Geschlecht)", "; ".join(unevaluable)))
        if group:
            groups.append(group)

    # number the evaluated criteria K1, K2, ... (only after skipping)
    for i, c in enumerate((c for g in groups for c in g), 1):
        c["idx"] = i
        if c["value_filter"]:
            notes.append(f"K{i} {c['label']}: Wertfilter ignoriert (Vorkommen des Codes genügt)")
        if c["time_filter"]:
            notes.append(f"K{i} {c['label']}: Zeiteinschränkung ignoriert")

    return groups, skipped, notes


def reference_group_names(crtdl):
    """Normalised names of includeReferenceOnly groups (their CSVs are reference tables)."""
    return {norm_name(g.get("name")) for g in crtdl.get("dataExtraction", {}).get("attributeGroups", [])
            if g.get("includeReferenceOnly")}


def peak_memory():
    """Peak memory of this process as text, e.g. '1.8 GB'. Not available on Windows."""
    try:
        import resource
    except ImportError:
        return "n/a"
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes
    return f"{(peak if sys.platform == 'darwin' else peak * 1024) / 1024 ** 3:.2f} GB"


def safe_label(text, maxlen=60):
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", text).strip("_")[:maxlen]


class Tee:
    """Write everything that goes to the console also into the log file (filter_by_crtdl.log)."""

    def __init__(self, console, logfile):
        self.console, self.logfile = console, logfile

    def write(self, text):
        self.console.write(text)
        self.logfile.write(text)

    def flush(self):
        # flushed after every write -> the log survives even if the process is killed
        self.console.flush()
        self.logfile.flush()


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="CRTDL-Einschlusskriterien auf geflattete CSV-Tabellen anwenden (README.md beachten)")
    ap.add_argument("--crtdl", required=True, help="Pfad zur CRTDL-JSON")
    ap.add_argument("--csv-dir", required=True, help="Ordner mit den geflatteten CSV-Dateien")
    ap.add_argument("--out-dir", required=True, help="Ausgabeordner (wird angelegt)")
    ap.add_argument("--no-include", action="store_true",
                    help="keine *_include.csv schreiben (nur prüfen)")
    ap.add_argument("--exact-only", action="store_true",
                    help="nur exakte Code-Treffer, keine Hierarchie (ICD/OPS/ATC)")
    ap.add_argument("--search-all-columns", action="store_true",
                    help="Codes in allen Spalten suchen statt nur in Spalten mit 'code' im Namen")
    ap.add_argument("--patient-column", default=None,
                    help="Name der Patienten-Spalte, falls nicht 'patient'/'subject'")
    ap.add_argument("--patient-id-regex", default=None,
                    help="Regex, Gruppe 1 = Patienten-ID (Default: Präfix 'Typ/' entfernen)")
    ap.add_argument("--medication-core", default="MII PR Medikation Medication",
                    help="Tabellenname der Medikations-Kerntabelle (Leerzeichen/_ egal)")
    ap.add_argument("--reference-tables", default="",
                    help="zusätzliche Referenztabellen (Komma-getrennt), die nicht als Kriterium geprüft werden")
    ap.add_argument("--version", action="version", version=f"filter_by_crtdl {VERSION}")
    args = ap.parse_args()

    id_re = args.patient_id_regex or DEFAULT_ID_RE
    try:
        re.compile(id_re)
    except re.error as e:
        sys.exit(f"Ungültiger --patient-id-regex: {e}")

    # ---- log file: everything printed to the console also goes to <out-dir>/filter_by_crtdl.log
    os.makedirs(args.out_dir, exist_ok=True)
    logfile = open(os.path.join(args.out_dir, "filter_by_crtdl.log"), "w", encoding="utf-8", buffering=1)
    sys.stdout = Tee(sys.__stdout__, logfile)
    sys.stderr = Tee(sys.__stderr__, logfile)      # also warnings, error messages and tracebacks
    t_start = time.time()
    print(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}, Python {platform.python_version()}")
    print("Aufruf: " + " ".join(sys.argv))

    # ======================================================================= 1) CRTDL
    with open(args.crtdl, encoding="utf-8") as fh:
        crtdl = json.load(fh)
    cohort = crtdl.get("cohortDefinition", {})

    groups, skipped, notes = parse_inclusion_groups(crtdl, args.exact_only)

    criteria = [c for g in groups for c in g]
    print(f"CRTDL-Filter {VERSION}")
    print("\nBerücksichtigte Einschlusskriterien (Gruppen UND-verknüpft, innerhalb ODER):")
    for g_i, g in enumerate(groups, 1):
        print(f"  Gruppe {g_i}:")
        for c in g:
            rules = ", ".join(f"{code} [{rule[0]}]" for code, rule in c["rules"])
            print(f"    K{c['idx']}: {c['label']} ({rules}) Kontext: {c['context']}")
    for reason, text in skipped:
        print(f"  Nicht berücksichtigt – {reason}: {text}")
    for n in notes:
        print(f"  Hinweis: {n}")
    if cohort.get("exclusionCriteria"):
        print("  Hinweis: exclusionCriteria werden nicht ausgewertet.")
    if not criteria:
        sys.exit("Keine prüfbaren Einschlusskriterien gefunden.")

    # tables flattened from includeReferenceOnly groups: not a patient source, not searched
    ref_groups = reference_group_names(crtdl)
    ref_groups |= {norm_name(x) for x in args.reference_tables.split(",") if x.strip()}
    core_norm = norm_name(args.medication_core)

    # ======================================================================= 2) pass 1: read CSVs
    tables = {}
    all_rules = [(c["idx"], code, rule) for c in criteria for code, rule in c["rules"]]
    value_cache = {}                      # value -> [(crit idx, crtdl code)]
    matched = defaultdict(set)            # crit idx -> patients
    match_log = Counter()                 # (crit idx, crtdl code, value, table, column) -> rows
    core_hits = defaultdict(set)          # Medication id -> crit idx matched in the core table
    universe_patient_table = None         # patients from the Patient table, if found
    universe_union = set()                # fallback: patients from all searched tables

    # the Medication core table is read FIRST: its ATC hits (core_hits) must be known before the
    # medicationReference columns of MedicationAdministration/-Request are read
    files = sorted(os.listdir(args.csv_dir))
    files.sort(key=lambda fn: norm_name(os.path.splitext(fn)[0]) != core_norm)
    for fn in files:
        if not fn.lower().endswith(".csv") or fn.endswith("_include.csv"):
            continue
        path = os.path.join(args.csv_dir, fn)
        name = os.path.splitext(fn)[0]
        enc = detect_encoding(path)
        delim = detect_delimiter(path, enc)
        is_ref = norm_name(name) in ref_groups
        is_core = norm_name(name) == core_norm

        with open(path, encoding=enc, newline="") as fh:
            rd = csv.reader(fh, delimiter=delim)
            header = next(rd, None)
            if not header:
                continue
            lower = [h.strip().lower() for h in header]
            # patient column: explicit, 'patient'/'subject', or 'id' in the Patient table itself
            if args.patient_column:
                pcol = lower.index(args.patient_column.lower()) if args.patient_column.lower() in lower else None
                is_patient_table = False
            elif "patient" in lower or "subject" in lower:
                pcol = lower.index("patient") if "patient" in lower else lower.index("subject")
                is_patient_table = False
            elif "patient" in name.lower() and "id" in lower:
                pcol = lower.index("id")
                is_patient_table = True
            else:
                pcol, is_patient_table = None, False
            code_cols = (list(range(len(header))) if args.search_all_columns
                         else [i for i, h in enumerate(lower) if "code" in h])
            mref_cols = [i for i, h in enumerate(lower) if "medicationreference" in h]
            id_col = lower.index("id") if "id" in lower else None
            search = (not is_ref) or is_core      # the Medication core table is ref-only but carries the ATC codes

            pids_in_table = set()
            for row in rd:
                pid = normalize_id(row[pcol], id_re) if pcol is not None and pcol < len(row) else ""
                if pid:
                    pids_in_table.add(pid)
                # medicationReference -> patient, only for Medication ids with an ATC hit in the core table.
                # Nothing is stored for all other references (no ATC criteria -> core_hits is empty).
                if pid and core_hits:
                    for mc in mref_cols:
                        if mc < len(row):
                            for idx in core_hits.get(normalize_id(row[mc], id_re), ()):
                                matched[idx].add(pid)
                if not search:
                    continue
                for ci in code_cols:
                    if ci >= len(row):
                        continue
                    v = row[ci].strip()
                    if not v:
                        continue
                    if v not in value_cache:
                        # bounded cache: columns with many different values would otherwise fill the memory
                        if len(value_cache) >= VALUE_CACHE_MAX:
                            value_cache.clear()
                        value_cache[v] = [(idx, code) for idx, code, rule in all_rules if rule_matches(rule, v)]
                    for idx, code in value_cache[v]:
                        match_log[(idx, code, v, name, header[ci])] += 1
                        if pid:
                            matched[idx].add(pid)
                        elif is_core and id_col is not None and id_col < len(row):
                            core_hits[normalize_id(row[id_col], id_re)].add(idx)

        tables[name] = {"path": path, "enc": enc, "delim": delim, "pcol": pcol,
                        "is_ref": is_ref, "is_core": is_core, "patients": len(pids_in_table)}
        if is_patient_table:
            universe_patient_table = (universe_patient_table or set()) | pids_in_table
        elif not is_ref:
            universe_union |= pids_in_table

    patients = sorted(universe_patient_table if universe_patient_table else universe_union)
    print(f"\n{len(tables)} CSV-Tabellen gelesen, Patienten: {len(patients)} "
          f"({'aus Patiententabelle' if universe_patient_table else 'aus allen Tabellen'})")
    for name, t in sorted(tables.items()):
        role = "Medikations-Kerntabelle" if t["is_core"] else ("Referenztabelle, nicht durchsucht" if t["is_ref"] else "")
        print(f"  {name}: Trennzeichen '{t['delim']}', Patienten: {t['patients']}" + (f" ({role})" if role else ""))
    if not any(t["is_core"] for t in tables.values()) and any("atc" in s.lower() for c in criteria for s in c["systems"]):
        # without the core table, ATC hits in Medication cannot be linked to patients via medicationReference
        print(f"WARNUNG: Medikations-Kerntabelle '{args.medication_core}' nicht gefunden "
              f"(Leerzeichen/Unterstriche egal). ATC-Kriterien über medicationReference werden dann nicht "
              f"zugeordnet, betroffene Patienten ggf. zu Unrecht ausgeschlossen. "
              f"Tabelle mit --medication-core angeben. Gelesene Tabellen: {', '.join(sorted(tables))}")

    # ======================================================================= 3) report code search
    print("\nCode-Suche:")
    for c in criteria:
        for code, rule in c["rules"]:
            locs, values = Counter(), set()
            for (idx, cc, v, n, col), cnt in match_log.items():
                if idx == c["idx"] and cc == code:
                    locs[(n, col)] += cnt
                    values.add(v)
            if locs:
                where = "; ".join(f"{n} / {col}: {cnt}" for (n, col), cnt in sorted(locs.items()))
                ex = ", ".join(sorted(values)[:8]) + (" ..." if len(values) > 8 else "")
                print(f"  K{c['idx']} {code}: {where}\n      gefundene Codes ({len(values)}): {ex}")
            else:
                print(f"  K{c['idx']} {code}: NICHT GEFUNDEN")
    print("\nPatienten pro Kriterium:")
    for c in criteria:
        print(f"  K{c['idx']} {c['label']}: {len(matched[c['idx']] & set(patients))}")

    # ======================================================================= 4) exclusion
    excluded = {}                         # patient -> numbers of the unmet groups
    for p in patients:
        unmet = [str(g_i) for g_i, g in enumerate(groups, 1) if all(p not in matched[c["idx"]] for c in g)]
        if unmet:
            excluded[p] = unmet

    with open(os.path.join(args.out_dir, "inclusion_criteria_matches.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["patientId"] + [f"K{c['idx']}_{safe_label(c['label'])}" for c in criteria])
        for p in patients:
            w.writerow([p] + [1 if p in matched[c["idx"]] else 0 for c in criteria])
    with open(os.path.join(args.out_dir, "to_be_excluded.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["patientId", "nicht_erfuellte_gruppen"])
        for p in sorted(excluded):
            w.writerow([p, ",".join(excluded[p])])
    with open(os.path.join(args.out_dir, "code_matches.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["kriterium", "crtdl_code", "daten_code", "tabelle", "spalte", "anzahl_zeilen"])
        for (idx, cc, v, n, col), cnt in sorted(match_log.items()):
            w.writerow([f"K{idx}", cc, v, n, col, cnt])

    share = (len(excluded) / len(patients) * 100) if patients else 0
    print(f"\nAusgeschlossen: {len(excluded)} von {len(patients)} Patienten ({share:.1f} %)")
    print(f"Berichte in {args.out_dir}: inclusion_criteria_matches.csv, to_be_excluded.csv, code_matches.csv, "
          f"filter_by_crtdl.log")

    # ======================================================================= 5) pass 2: *_include.csv
    if args.no_include:
        print("--no-include: keine *_include.csv geschrieben.")
        print(f"Höchster Speicherverbrauch: {peak_memory()}")
        print(f"Laufzeit: {time.time() - t_start:.0f} s")
        return
    print("\nGefilterte Tabellen:")
    for name, t in sorted(tables.items()):
        out_path = os.path.join(args.out_dir, f"{name}_include.csv")
        kept = dropped = 0
        with open(t["path"], encoding=t["enc"], newline="") as fin, \
                open(out_path, "w", encoding="utf-8", newline="") as fout:
            rd = csv.reader(fin, delimiter=t["delim"])
            w = csv.writer(fout, delimiter=t["delim"])     # keep the input delimiter
            w.writerow(next(rd))
            for row in rd:
                pid = (normalize_id(row[t["pcol"]], id_re)
                       if t["pcol"] is not None and t["pcol"] < len(row) else "")
                # rows without patient reference (e.g. Medication master data) are kept
                if pid and pid in excluded:
                    dropped += 1
                    continue
                w.writerow(row)
                kept += 1
        print(f"  {name}_include.csv: {kept} behalten, {dropped} entfernt")
    print(f"\nHöchster Speicherverbrauch: {peak_memory()}")
    print(f"Laufzeit: {time.time() - t_start:.0f} s")


if __name__ == "__main__":
    main()