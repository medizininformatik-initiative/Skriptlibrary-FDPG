#!/usr/bin/env python3
"""
CRTDL-Filter

Liest eine CRTDL-JSON und einen Ordner mit CSV-Tabellen ein, ermittelt die
Einschlusskriterien (ohne Consent/Alter/Geschlecht), prüft pro Patient, ob die
Codes vorkommen, und erzeugt:
  - Inclusion_Criteria_Matches.csv  (1/0 pro Patient und Kriterium)
  - to-be-excluded.csv              (Patienten, die UND/ODER-Logik ausschließt)
  - <Original>_include.csv          (je CSV-Datei, ohne ausgeschlossene Patienten)

Verknüpfung:
  - Patienten-ID wird in Tabellen über Spalte 'patient' / 'subject' gefunden,
    in der Patientenressource (Dateiname enthält 'patient') über Spalte 'id'.
  - Referenzen wie 'Patient/<ID>' werden auf '<ID>' normalisiert. Andere
    Formate lassen sich mit --patient-id-regex (Gruppe 1 = ID) anpassen.
  - Medikation: Codes, die in der Medikations-Kerntabelle vorkommen, gelten für
    alle Patienten, deren Medikationsreferenz (…Medicationreference…) auf die
    jeweilige Medication-ID verweist.

Logik:
  - Äußere Liste der inclusionCriteria = UND, innere Liste = ODER.
  - Codes innerhalb eines Kriteriums (termCodes) sind ODER-verknüpft.
  - Ausschluss: Patient fällt raus, wenn in einer UND-Gruppe ALLE Kriterien 0 sind.

Aufruf:
  python crtdl_filter.py --crtdl CRTDL.json --csv-dir ./csv --out-dir ./output
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

# Consent-/Demografie-Kriterien, die nicht berücksichtigt werden
CONSENT_RE = re.compile(
    r"einwilligung|consent|geschlecht|gender|\balter\b|\bage\b|geburt|birth|\bsex\b",
    re.IGNORECASE,
)
# Standard: Referenz 'Typ/ID' -> 'ID'
DEFAULT_ID_RE = r"^(?:[A-Za-z]+/)?([^/]+?)(?:/_history/.*)?$"


def read_csv_rows(path):
    """CSV mit UTF-8 (mit/ohne BOM) lesen, Fallback Latin-1."""
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                return list(csv.reader(fh))
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Kann {path} nicht lesen")


def normalize_id(value, id_re):
    v = (value or "").strip()
    if not v:
        return ""
    m = re.match(id_re, v)
    if not m:
        return v
    return m.group(1) if m.groups() else m.group(0)


def is_consent(criterion):
    text = " ".join(t.get("display", "") for t in criterion.get("termCodes", []))
    text += " " + criterion.get("context", {}).get("display", "")
    return bool(CONSENT_RE.search(text))


def find_patient_col(header, filename, override):
    lower = [h.strip().lower() for h in header]
    if override:
        return lower.index(override.lower()) if override.lower() in lower else None
    for cand in ("patient", "subject"):
        if cand in lower:
            return lower.index(cand)
    if "patient" in filename.lower() and "id" in lower:  # Patientenressource
        return lower.index("id")
    return None


def safe_label(text, maxlen=60):
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", text).strip("_")[:maxlen]


def main():
    ap = argparse.ArgumentParser(description="CRTDL-Einschlusskriterien auf CSV-Tabellen anwenden")
    ap.add_argument("--crtdl", required=True, help="Pfad zur CRTDL-JSON")
    ap.add_argument("--csv-dir", required=True, help="Ordner mit den CSV-Dateien")
    ap.add_argument("--out-dir", default="output", help="Ausgabeordner (Default: ./output)")
    ap.add_argument("--patient-column", default=None,
                    help="Name der Patienten-Spalte, falls nicht 'patient'/'subject'/Patientenressource 'id'")
    ap.add_argument("--patient-id-regex", default=None,
                    help="Regex, Gruppe 1 = Patienten-ID (Default: Präfix 'Typ/' entfernen)")
    ap.add_argument("--medication-core", default="MII_PR_Medikation_Medication",
                    help="Dateiname (ohne .csv) der Medikations-Kerntabelle")
    ap.add_argument("--exclude-tables-containing", default="referenz",
                    help="Tabellen, deren Dateiname dies enthält, werden nicht als Kriterium geprüft "
                         "(Default: 'referenz' -> referenzierte Fälle/Medikation)")
    args = ap.parse_args()

    id_re = args.patient_id_regex or DEFAULT_ID_RE
    try:
        re.compile(id_re)
    except re.error as e:
        sys.exit(f"Ungültiger --patient-id-regex: {e}")

    # ---------- 1) CRTDL einlesen ----------
    with open(args.crtdl, encoding="utf-8") as fh:
        crtdl = json.load(fh)
    raw_groups = crtdl.get("cohortDefinition", {}).get("inclusionCriteria", [])

    groups = []          # Liste von UND-Gruppen; jede Gruppe = Liste von ODER-Kriterien
    skipped = []
    crit_counter = 0
    for raw_group in raw_groups:
        group = []
        for crit in raw_group:
            if is_consent(crit):
                skipped.append(" / ".join(t.get("display", t.get("code", "?")) for t in crit.get("termCodes", [])))
                continue
            codes = [t["code"].strip() for t in crit.get("termCodes", []) if t.get("code")]
            if not codes:
                continue
            crit_counter += 1
            label = next((t.get("display") for t in crit["termCodes"] if t.get("display")), codes[0])
            group.append({
                "idx": crit_counter,
                "label": label,
                "codes": codes,
                "context": crit.get("context", {}).get("code", ""),
            })
        if group:
            groups.append(group)

    criteria = [c for g in groups for c in g]
    print("Folgende Einschlusskriterien werden berücksichtigt:")
    for g_i, g in enumerate(groups, 1):
        op = "ODER" if len(g) > 1 else "UND"
        print(f"  Gruppe {g_i} (verknüpft mit UND zu anderen Gruppen; innerhalb: {op}):")
        for c in g:
            print(f"    K{c['idx']}: {c['label']} [{', '.join(c['codes'])}] (Kontext: {c['context']})")
    if skipped:
        print("Ausgeschlossen (Consent/Alter/Geschlecht):", "; ".join(skipped))
    if not criteria:
        sys.exit("Keine Einschlusskriterien gefunden.")

    # ---------- 2) CSV-Ordner einlesen ----------
    tables = {}
    for fn in sorted(os.listdir(args.csv_dir)):
        if not fn.lower().endswith(".csv") or fn.endswith("_include.csv"):
            continue
        name = os.path.splitext(fn)[0]
        rows = read_csv_rows(os.path.join(args.csv_dir, fn))
        if not rows:
            continue
        header = rows[0]
        lower = [h.strip().lower() for h in header]
        pcol = find_patient_col(header, name, args.patient_column)
        pids = [normalize_id(r[pcol], id_re) if pcol is not None and pcol < len(r) else ""
                for r in rows[1:]]
        mref_cols = [i for i, h in enumerate(lower) if "medicationreference" in h]
        tables[name] = {
            "file": fn, "header": header, "rows": rows[1:], "pcol": pcol,
            "pids": pids, "mref_cols": mref_cols,
            "id_col": lower.index("id") if "id" in lower else None,
            "fn": os.path.join(args.csv_dir, fn),
        }
    print(f"\n{len(tables)} CSV-Tabellen eingelesen.")

    matchable = {n: t for n, t in tables.items()
                 if args.exclude_tables_containing.lower() not in n.lower()}
    excluded_tables = sorted(set(tables) - set(matchable))
    if excluded_tables:
        print("Nicht als Kriterium geprüft (Referenz-Tabellen):", ", ".join(excluded_tables))

    core_name = args.medication_core
    if core_name not in tables:
        print(f"WARNUNG: Medikations-Kerntabelle '{core_name}' nicht gefunden.")

    # ---------- 3) Patienten-Universum ----------
    universe = set()
    for n, t in matchable.items():
        universe.update(p for p in t["pids"] if p)
    print(f"Patienten gesamt (aus Tabellen ohne Referenz-Tabellen): {len(universe)}")

    # ---------- 4) Codes suchen ----------
    code_set = {c for crit in criteria for c in crit["codes"]}
    hits = defaultdict(list)  # code -> [(tabellenname, zeilenindex, spaltenindex)]
    for n, t in matchable.items():
        for ri, row in enumerate(t["rows"]):
            for ci, val in enumerate(row):
                v = val.strip()
                if v in code_set:
                    hits[v].append((n, ri, ci))

    print("\nCode-Suche (Tabelle / Spalte):")
    for crit in criteria:
        for code in crit["codes"]:
            locs = sorted({(n, tables[n]["header"][ci]) for n, _, ci in hits.get(code, [])})
            if locs:
                print(f"  K{crit['idx']} {code}: " + "; ".join(f"{n} / {col}" for n, col in locs))
            else:
                print(f"  K{crit['idx']} {code}: NICHT GEFUNDEN")

    # ---------- 5) Medikations-Verknüpfung ----------
    # Medication-ID -> Patienten, über Medicationreference-Spalten
    med_patients = defaultdict(set)
    for n, t in matchable.items():
        if not t["mref_cols"] or t["pcol"] is None:
            continue
        for ri, row in enumerate(t["rows"]):
            pid = t["pids"][ri]
            if not pid:
                continue
            for mc in t["mref_cols"]:
                if mc < len(row):
                    mid = normalize_id(row[mc], id_re)
                    if mid:
                        med_patients[mid].add(pid)

    core = tables.get(core_name)
    core_ids = {}
    if core and core["id_col"] is not None:
        for ri, row in enumerate(core["rows"]):
            core_ids[ri] = normalize_id(row[core["id_col"]], id_re)

    # ---------- 6) Matrix: Patient x Kriterium ----------
    matched = {c["idx"]: set() for c in criteria}
    for crit in criteria:
        for code in crit["codes"]:
            for n, ri, _ in hits.get(code, []):
                t = tables[n]
                if t["pcol"] is not None and t["pids"][ri]:
                    matched[crit["idx"]].add(t["pids"][ri])
                elif n == core_name:
                    mid = core_ids.get(ri, "")
                    matched[crit["idx"]].update(med_patients.get(mid, set()))

    # Patienten-Universum um alle Medikations-Patienten ergänzen
    # (die Pid-Liste aus Tabellen mit Patientenbezug ist bereits vollständig)
    patients = sorted(universe)

    matches_path = os.path.join(args.out_dir, "Inclusion_Criteria_Matches.csv")
    os.makedirs(args.out_dir, exist_ok=True)
    with open(matches_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["patientId"] + [f"K{c['idx']}_{safe_label(c['label'])}" for c in criteria])
        for p in patients:
            w.writerow([p] + [1 if p in matched[c["idx"]] else 0 for c in criteria])
    print(f"\n{matches_path} geschrieben ({len(patients)} Patienten).")

    # ---------- 7) Ausschlusslogik ----------
    excluded = set()
    for p in patients:
        for g in groups:
            if all(p not in matched[c["idx"]] for c in g):
                excluded.add(p)
                break
    excl_path = os.path.join(args.out_dir, "to-be-excluded.csv")
    with open(excl_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["patientId"])
        for p in sorted(excluded):
            w.writerow([p])
    print(f"{excl_path} geschrieben ({len(excluded)} Patienten ausgeschlossen).")

    # ---------- 8) *_include.csv erzeugen ----------
    for n, t in tables.items():
        out_path = os.path.join(args.out_dir, f"{n}_include.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(t["header"])
            if t["pcol"] is None:
                # Tabelle ohne Patientenbezug (z. B. Medication-Stammdaten): unverändert übernehmen
                w.writerows(t["rows"])
                kept, dropped = len(t["rows"]), 0
                note = "ohne Patientenbezug, unverändert"
            else:
                kept = dropped = 0
                for row, pid in zip(t["rows"], t["pids"]):
                    if pid in excluded:
                        dropped += 1
                    else:
                        w.writerow(row)
                        kept += 1
                note = f"{dropped} Zeilen entfernt"
        print(f"  {out_path}: {kept} Zeilen behalten ({note})")


if __name__ == "__main__":
    main()
