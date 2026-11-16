#!/usr/bin/env python3
"""
Altersfilter

Entfernt Patienten, die bei keiner Diagnose mindestens --age-threshold Jahre alt waren, und alle ihre
Zeilen aus allen CSV-Tabellen eines Exports. Die Originaldateien bleiben unverändert, die gefilterten
Tabellen werden als <Tabelle>_reduced.csv in --out-dir geschrieben.

Ausführliche Beschreibung: README.md

Aufruf:
  python3 /pfad/zu/reduce_patients_by_age/reduce_patients_by_age.py --csv-dir <job>/filter_by_crtdl --out-dir <ausgabe>
  python3 ... --config config.yaml          (Einstellungen aus einer Datei, Parameter überschreiben sie)
"""
import argparse
import csv
import os
import platform
import re
import sys
import time
from datetime import date

VERSION = "2.0"

# Defaults, identical to config.yaml (can be overridden by --config and by single parameters)
DEFAULTS = {
    "patient_column": "patient",
    "alternate_patient_columns": ["subject", "Patient", "patient_reference", "Patient_reference"],
    "person_id_column": "id",
    "birthdate_column": "Patient_birthDate",
    "condition_file_contains": "Condition",
    "person_file_contains": "Person",
    "diagnosis_date_columns": ["Condition_onset_X_Onsetdatetime", "Condition_onset_X_Onsetperiod_end",
                               "Condition_onset_X_Onsetperiod_start", "Condition_recordedDate"],
    "age_threshold": 19,
    "mode": "remove_if_younger",
}
LOG_FILE = "reduce_patients_by_age.log"
REMOVED_FILE = "removed_patient.csv"
SUFFIX = "_reduced"
# reports written by filter_by_crtdl.py into the same folder as the *_include.csv -> not filtered, not copied
REPORT_FILES = {"code_matches.csv", "inclusion_criteria_matches.csv", "to_be_excluded.csv"}

csv.field_size_limit(10 ** 9)   # flattened columns can be long


# --------------------------------------------------------------------------- helpers (used in loops)
def parse_partial_date(value, end_of_period=False):
    """
    YYYY, YYYY-MM, YYYY-MM-DD or a datetime string -> date (None if not parseable).
    Partial dates: earliest date (YYYY -> YYYY-01-01); with end_of_period=True the latest (YYYY -> YYYY-12-31).
    Same logic as version 1 of the script.
    """
    value = str(value or "").strip()
    # keep the leading date part of values such as 2020-05-03T12:30:00+01:00
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", value)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else (12 if end_of_period else 1)
    day = int(m.group(3)) if m.group(3) else (31 if end_of_period else 1)
    # clamp day 31 to the last valid day of the month (e.g. 2021-02 with end_of_period -> 2021-02-28)
    while day >= 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def normalize_patient_reference(value):
    """'Patient/abc', 'urn:uuid:abc' and 'abc' all -> 'abc'."""
    v = str(value or "").strip()
    for sep in ("/", ":"):
        if sep in v:
            v = v.split(sep)[-1]
    return v.strip()


def open_csv(path):
    """Open a CSV with detected encoding (utf-8 with/without BOM, else latin-1) and delimiter (, ; tab |)."""
    enc = "utf-8-sig"
    try:
        with open(path, encoding=enc) as fh:
            for _ in fh:
                pass
    except UnicodeDecodeError:
        enc = "latin-1"
    with open(path, encoding=enc, newline="") as fh:
        header = fh.readline()
    delim = max((",", ";", "\t", "|"), key=header.count)
    return open(path, encoding=enc, newline=""), delim


class Tee:
    """Write everything that goes to the console also into the log file."""

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
        description="Patienten ohne Diagnose ab einer Altersgrenze aus allen CSV-Tabellen entfernen (README.md beachten)")
    ap.add_argument("--csv-dir", required=True, help="Ordner mit den CSV-Dateien, z.B. <job>/filter_by_crtdl")
    ap.add_argument("--out-dir", required=True, help="Ausgabeordner (wird angelegt)")
    ap.add_argument("--config", help="optionale config.yaml mit den Einstellungen (Parameter haben Vorrang)")
    ap.add_argument("--age-threshold", type=int, help=f"Mindestalter bei einer Diagnose (Default {DEFAULTS['age_threshold']})")
    ap.add_argument("--person-table", help="Name der Patiententabelle, falls nicht eindeutig über 'Person' im Dateinamen")
    ap.add_argument("--condition-table", help="Name der Diagnosetabelle, falls nicht eindeutig über 'Condition' im Dateinamen")
    ap.add_argument("--version", action="version", version=f"reduce_patients_by_age {VERSION}")
    args = ap.parse_args()

    # ---- log file: everything printed to the console also goes to <out-dir>/reduce_patients_by_age.log
    os.makedirs(args.out_dir, exist_ok=True)
    logfile = open(os.path.join(args.out_dir, LOG_FILE), "w", encoding="utf-8", buffering=1)
    sys.stdout = Tee(sys.__stdout__, logfile)
    sys.stderr = Tee(sys.__stderr__, logfile)      # also error messages and tracebacks
    t_start = time.time()
    print(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}, Python {platform.python_version()}")
    print("Aufruf: " + " ".join(sys.argv))
    print(f"Altersfilter {VERSION}")

    # ======================================================================= 1) settings
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    if args.config:
        # minimal YAML reader (standard library only): "key: value" and lists of "  - value"
        current_list = None
        with open(args.config, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.split("#", 1)[0].rstrip()
                if not line.strip():
                    continue
                if line.lstrip().startswith("- ") and current_list is not None:
                    cfg[current_list].append(line.lstrip()[2:].strip().strip('"\''))
                    continue
                key, _, value = line.partition(":")
                key, value = key.strip(), value.strip().strip('"\'')
                if value:
                    cfg[key] = int(value) if key == "age_threshold" else value
                    current_list = None
                else:
                    # a list follows on the next lines
                    cfg[key], current_list = [], key
    if args.age_threshold is not None:
        cfg["age_threshold"] = args.age_threshold
    if cfg["mode"] != "remove_if_younger":
        sys.exit("Nur mode: remove_if_younger wird unterstützt.")
    print(f"Altersgrenze: mindestens eine Diagnose mit Alter >= {cfg['age_threshold']}")

    # ======================================================================= 2) find the tables
    if not os.path.isdir(args.csv_dir):
        sys.exit(f"--csv-dir nicht gefunden: {args.csv_dir}")
    # all CSVs, but not our own output (in case --out-dir == --csv-dir) and not the reports of
    # filter_by_crtdl.py (they are no data tables and would only be copied unchanged)
    all_csv = sorted(fn for fn in os.listdir(args.csv_dir) if fn.lower().endswith(".csv"))
    files = [fn for fn in all_csv
             if not fn.endswith(SUFFIX + ".csv") and fn != REMOVED_FILE and fn not in REPORT_FILES]
    skipped = [fn for fn in all_csv if fn in REPORT_FILES]
    if skipped:
        print(f"Übersprungen (Berichte des CRTDL-Filters): {', '.join(skipped)}")
    if not files:
        sys.exit(f"Keine CSV-Dateien in {args.csv_dir}")

    def pick(explicit, contains, what):
        # explicit table name (with or without .csv) or exactly one file containing the text
        if explicit:
            name = explicit if explicit.lower().endswith(".csv") else explicit + ".csv"
            if name not in files:
                sys.exit(f"{what} '{name}' nicht in {args.csv_dir}")
            return name
        matches = [fn for fn in files if contains.lower() in fn.lower()]
        if len(matches) != 1:
            sys.exit(f"Genau eine Datei mit '{contains}' im Namen erwartet ({what}), gefunden: "
                     f"{', '.join(matches) or 'keine'}. Mit --{what.lower()}-table angeben.")
        return matches[0]

    person_fn = pick(args.person_table, cfg["person_file_contains"], "Person")
    condition_fn = pick(args.condition_table, cfg["condition_file_contains"], "Condition")
    print(f"Patiententabelle: {person_fn}")
    print(f"Diagnosetabelle:  {condition_fn}")

    def patient_col_of(header):
        # patient reference column: configured name first, then the alternatives
        for c in [cfg["patient_column"]] + cfg["alternate_patient_columns"]:
            if c in header:
                return c
        return None

    # ======================================================================= 3) birth dates (patient table)
    birthdates = {}        # patient id -> birth date (None if not parseable)
    birth_raw = {}         # patient id -> birth date as in the file (for removed_patient.csv)
    display_id = {}        # patient id -> id as in the file
    fh, delim = open_csv(os.path.join(args.csv_dir, person_fn))
    with fh:
        rd = csv.DictReader(fh, delimiter=delim)
        for required in (cfg["person_id_column"], cfg["birthdate_column"]):
            if required not in (rd.fieldnames or []):
                sys.exit(f"Spalte '{required}' fehlt in {person_fn}")
        for row in rd:
            raw_id = row.get(cfg["person_id_column"], "")
            pid = normalize_patient_reference(raw_id)
            if not pid:
                continue
            # several rows per patient are possible (flattening); the last one wins, as before
            birthdates[pid] = parse_partial_date(row.get(cfg["birthdate_column"], ""))
            birth_raw.setdefault(pid, row.get(cfg["birthdate_column"], ""))   # first row, as before
            display_id[pid] = raw_id
    print(f"\nPatienten in der Patiententabelle: {len(birthdates)}, "
          f"ohne gültiges Geburtsdatum: {sum(1 for b in birthdates.values() if b is None)}")

    # ======================================================================= 4) age at diagnosis (condition table)
    kept = set()               # patients with at least one diagnosis at or above the threshold
    diagnosis_log = {}         # pid -> [raw diagnosis date], only for patients NOT (yet) kept
    fh, delim = open_csv(os.path.join(args.csv_dir, condition_fn))
    with fh:
        rd = csv.DictReader(fh, delimiter=delim)
        header = rd.fieldnames or []
        pcol = patient_col_of(header)
        if pcol is None:
            sys.exit(f"Keine Patientenspalte ({cfg['patient_column']}) in {condition_fn}")
        date_cols = [c for c in cfg["diagnosis_date_columns"] if c in header]
        if not date_cols:
            sys.exit(f"Keine der Datumsspalten {cfg['diagnosis_date_columns']} in {condition_fn}")
        print(f"Datumsspalten der Diagnosen: {', '.join(date_cols)}")
        n_diag = 0
        for row in rd:
            pid = normalize_patient_reference(row.get(pcol, ""))
            if not pid or pid in kept:
                continue
            birth = birthdates.get(pid)
            if birth is None:
                diagnosis_log.setdefault(pid, [])
                continue
            for col in date_cols:
                raw = row.get(col, "")
                # period end = end of an imprecise period, all other fields = earliest date
                d = parse_partial_date(raw, end_of_period=col.lower().endswith("period_end"))
                if d is None:
                    continue
                n_diag += 1
                age = d.year - birth.year - ((d.month, d.day) < (birth.month, birth.day))
                if age >= cfg["age_threshold"]:
                    kept.add(pid)
                    diagnosis_log.pop(pid, None)   # kept -> no need to remember its diagnoses
                    break
                diagnosis_log.setdefault(pid, []).append(raw)

    removed = set(birthdates) - kept
    share = len(removed) / len(birthdates) * 100 if birthdates else 0
    print(f"\nAusgeschlossen: {len(removed)} von {len(birthdates)} Patienten ({share:.1f} %)")
    print(f"  davon ohne gültiges Geburtsdatum: {sum(1 for p in removed if birthdates[p] is None)}")
    print(f"  davon ohne Diagnose mit Datum:     {sum(1 for p in removed if birthdates[p] is not None and not diagnosis_log.get(p))}")

    # ======================================================================= 5) removed_patient.csv
    with open(os.path.join(args.out_dir, REMOVED_FILE), "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(["patient", "source file name", "timestamp birthdate", "timestamp diagnosis"])
        for pid in sorted(removed):
            entries = diagnosis_log.get(pid) or [""]   # one row with empty diagnosis if there is none
            for raw in entries:
                w.writerow([display_id.get(pid, pid), condition_fn, birth_raw.get(pid, ""), raw])

    # ======================================================================= 6) write <Tabelle>_reduced.csv
    print(f"\nBerichte in {args.out_dir}: {REMOVED_FILE}, {LOG_FILE}")
    print("\nGefilterte Tabellen:")
    for fn in files:
        fin, delim = open_csv(os.path.join(args.csv_dir, fn))
        out_fn = os.path.splitext(fn)[0] + SUFFIX + ".csv"
        kept_rows = dropped = 0
        with fin, open(os.path.join(args.out_dir, out_fn), "w", encoding="utf-8", newline="") as fout:
            rd = csv.reader(fin, delimiter=delim)
            w = csv.writer(fout, delimiter=delim)      # keep the input delimiter
            header = next(rd, [])
            w.writerow(header)
            # patient table(s): filtered by the id column (also e.g. a second copy like ..._AGE.csv),
            # all other tables by their patient column
            is_person = fn == person_fn or (cfg["person_file_contains"].lower() in fn.lower()
                                            and patient_col_of(header) is None)
            col = cfg["person_id_column"] if is_person else patient_col_of(header)
            idx = header.index(col) if col in header else None
            for row in rd:
                if idx is not None and idx < len(row) and normalize_patient_reference(row[idx]) in removed:
                    dropped += 1
                    continue
                w.writerow(row)
                kept_rows += 1
        note = "" if idx is not None else " (keine Patientenspalte, unverändert)"
        print(f"  {out_fn}: {kept_rows} behalten, {dropped} entfernt{note}")

    print(f"\nLaufzeit: {time.time() - t_start:.0f} s")


if __name__ == "__main__":
    main()