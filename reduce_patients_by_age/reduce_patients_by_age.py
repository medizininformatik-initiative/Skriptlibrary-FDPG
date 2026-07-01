#!/usr/bin/env python3
"""
Reduce CSV files by removing patients who do not have any diagnosis date
at or after the configured age threshold.

Usage:
  1. Put this script and config.ini in the folder containing the CSV files.
  2. Adjust config.ini if needed.
  3. Run: python3 reduce_patients_by_age.py

No third-party libraries are required.
"""

import csv
import configparser
import os
import re
from datetime import datetime, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.ini")

DEFAULT_CONFIG = {
    "patient_column": "patient",
    "person_id_column": "id",
    "birthdate_column": "Patient_birthDate",
    "condition_file_contains": "Condition",
    "person_file_contains": "Person",
    "diagnosis_date_columns": (
        "Condition_onset_X_Onsetdatetime,"
        "Condition_onset_X_Onsetperiod_end,"
        "Condition_onset_X_Onsetperiod_start,"
        "Condition_recordedDate"
    ),
    "age_threshold": "19",
    "mode": "remove_if_younger",
}


def create_default_config_if_missing():
    if os.path.exists(CONFIG_FILE):
        return
    config = configparser.ConfigParser()
    config["settings"] = DEFAULT_CONFIG
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        config.write(f)
    print(f"Created default config file: {CONFIG_FILE}")


def read_config():
    create_default_config_if_missing()
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE, encoding="utf-8")
    s = config["settings"]
    return {
        "patient_column": s.get("patient_column", DEFAULT_CONFIG["patient_column"]),
        "person_id_column": s.get("person_id_column", DEFAULT_CONFIG["person_id_column"]),
        "birthdate_column": s.get("birthdate_column", DEFAULT_CONFIG["birthdate_column"]),
        "condition_file_contains": s.get("condition_file_contains", DEFAULT_CONFIG["condition_file_contains"]),
        "person_file_contains": s.get("person_file_contains", DEFAULT_CONFIG["person_file_contains"]),
        "diagnosis_date_columns": [
            x.strip() for x in s.get("diagnosis_date_columns", DEFAULT_CONFIG["diagnosis_date_columns"]).split(",")
            if x.strip()
        ],
        "age_threshold": int(s.get("age_threshold", DEFAULT_CONFIG["age_threshold"])),
        "mode": s.get("mode", DEFAULT_CONFIG["mode"]).strip().lower(),
    }


def list_source_csvs():
    csvs = []
    for name in os.listdir(SCRIPT_DIR):
        if not name.lower().endswith(".csv"):
            continue
        if name.endswith("_reduced.csv") or name == "removed_patient.csv":
            continue
        csvs.append(os.path.join(SCRIPT_DIR, name))
    return sorted(csvs)


def find_one_csv(csvs, contains_text):
    matches = [p for p in csvs if contains_text.lower() in os.path.basename(p).lower()]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one CSV containing '{contains_text}', found {len(matches)}: "
            + ", ".join(os.path.basename(x) for x in matches)
        )
    return matches[0]


def sniff_dialect(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def read_rows(path):
    dialect = sniff_dialect(path)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, dialect=dialect)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    return fieldnames, rows, dialect


def write_rows(path, fieldnames, rows, dialect):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, dialect=dialect, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_partial_date(value, end_of_period=False):
    """
    Parse date-like strings such as YYYY, YYYY-MM, YYYY-MM-DD, or datetime strings.
    For birthdates, use earliest plausible date: YYYY -> YYYY-01-01, YYYY-MM -> YYYY-MM-01.
    For diagnosis dates, use earliest date by default. If end_of_period=True, partial
    dates use the latest plausible month/day.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    # Keep the leading date part from values such as 2020-05-03T12:30:00+01:00
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", value)
    if not m:
        return None

    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else (12 if end_of_period else 1)
    day = int(m.group(3)) if m.group(3) else (31 if end_of_period else 1)

    # Clamp invalid/imprecise day values to the last valid day of the month.
    while day >= 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def calculate_age_years(birth_date, diagnosis_date):
    if birth_date is None or diagnosis_date is None:
        return None
    age = diagnosis_date.year - birth_date.year
    if (diagnosis_date.month, diagnosis_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def normalize_patient_reference(value):
    """
    Normalize patient references so 'Patient/abc', 'urn:uuid:abc', and 'abc'
    can be compared as much as possible.
    """
    if value is None:
        return ""
    v = str(value).strip()
    if not v:
        return ""
    for sep in ("/", ":"):
        if sep in v:
            v = v.split(sep)[-1]
    return v.strip()


def output_name(path):
    base, ext = os.path.splitext(path)
    return base + "_reduced" + ext


def main():
    cfg = read_config()
    if cfg["mode"] != "remove_if_younger":
        raise RuntimeError("Currently supported mode: remove_if_younger")

    csvs = list_source_csvs()
    if not csvs:
        raise RuntimeError("No CSV files found in the script folder.")

    condition_csv = find_one_csv(csvs, cfg["condition_file_contains"])
    person_csv = find_one_csv(csvs, cfg["person_file_contains"])

    person_fields, person_rows, person_dialect = read_rows(person_csv)
    condition_fields, condition_rows, _ = read_rows(condition_csv)

    for required in (cfg["person_id_column"], cfg["birthdate_column"]):
        if required not in person_fields:
            raise RuntimeError(f"Missing column '{required}' in {os.path.basename(person_csv)}")
    if cfg["patient_column"] not in condition_fields:
        raise RuntimeError(f"Missing column '{cfg['patient_column']}' in {os.path.basename(condition_csv)}")

    present_diag_cols = [c for c in cfg["diagnosis_date_columns"] if c in condition_fields]
    if not present_diag_cols:
        raise RuntimeError("None of the configured diagnosis_date_columns exist in the Condition CSV.")

    birthdates = {}
    patient_display_id = {}
    for row in person_rows:
        raw_id = row.get(cfg["person_id_column"], "")
        pid = normalize_patient_reference(raw_id)
        if not pid:
            continue
        birthdates[pid] = parse_partial_date(row.get(cfg["birthdate_column"], ""), end_of_period=False)
        patient_display_id[pid] = raw_id

    patients_with_diagnosis_at_or_after_threshold = set()
    diagnosis_log = {}  # pid -> list of (diagnosis_raw, diagnosis_date, birth_raw, source_file)

    for row in condition_rows:
        pid = normalize_patient_reference(row.get(cfg["patient_column"], ""))
        if not pid:
            continue
        birth_date = birthdates.get(pid)
        if birth_date is None:
            diagnosis_log.setdefault(pid, [])
            continue
        for col in present_diag_cols:
            raw_diag = row.get(col, "")
            # Period end is interpreted as end of the imprecise period; other fields use earliest date.
            diag_date = parse_partial_date(raw_diag, end_of_period=col.lower().endswith("period_end"))
            if diag_date is None:
                continue
            diagnosis_log.setdefault(pid, []).append((raw_diag, diag_date, row.get(cfg["patient_column"], ""), os.path.basename(condition_csv)))
            age = calculate_age_years(birth_date, diag_date)
            if age is not None and age >= cfg["age_threshold"]:
                patients_with_diagnosis_at_or_after_threshold.add(pid)

    all_patients = {normalize_patient_reference(r.get(cfg["person_id_column"], "")) for r in person_rows}
    all_patients.discard("")
    removed_patients = all_patients - patients_with_diagnosis_at_or_after_threshold

    # Write reduced copies of all CSV files.
    for path in csvs:
        fields, rows, dialect = read_rows(path)
        if path == person_csv:
            id_col = cfg["person_id_column"]
            reduced = [r for r in rows if normalize_patient_reference(r.get(id_col, "")) not in removed_patients]
        elif cfg["patient_column"] in fields:
            reduced = [r for r in rows if normalize_patient_reference(r.get(cfg["patient_column"], "")) not in removed_patients]
        else:
            # File has no patient reference column; copy unchanged.
            reduced = rows
        write_rows(output_name(path), fields, reduced, dialect)

    removed_path = os.path.join(SCRIPT_DIR, "removed_patient.csv")
    with open(removed_path, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["patient", "source file name", "timestamp birthdate", "timestamp diagnosis"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for pid in sorted(removed_patients):
            birth_raw = ""
            for r in person_rows:
                if normalize_patient_reference(r.get(cfg["person_id_column"], "")) == pid:
                    birth_raw = r.get(cfg["birthdate_column"], "")
                    break
            entries = diagnosis_log.get(pid, [])
            if entries:
                for raw_diag, _diag_date, _patient_ref, source_file in entries:
                    writer.writerow({
                        "patient": patient_display_id.get(pid, pid),
                        "source file name": source_file,
                        "timestamp birthdate": birth_raw,
                        "timestamp diagnosis": raw_diag,
                    })
            else:
                writer.writerow({
                    "patient": patient_display_id.get(pid, pid),
                    "source file name": os.path.basename(condition_csv),
                    "timestamp birthdate": birth_raw,
                    "timestamp diagnosis": "",
                })

    print(f"Condition CSV: {os.path.basename(condition_csv)}")
    print(f"Person CSV:    {os.path.basename(person_csv)}")
    print(f"Patients total: {len(all_patients)}")
    print(f"Patients kept:  {len(all_patients - removed_patients)}")
    print(f"Patients removed: {len(removed_patients)}")
    print(f"Wrote reduced CSV files and {os.path.basename(removed_path)}")


if __name__ == "__main__":
    main()
