#!/usr/bin/env python3
"""
Reduce CSV files based on each patient's latest qualifying procedure.

Rules implemented:
- Find all CSV files in the script's current working directory.
- Identify the procedure CSV by filename containing "procedure".
- In the procedure CSV, find rows where config["identifying_column"] equals
  config["identifying_code"].
- For each patient, determine the latest qualifying procedure timestamp.
  For procedure periods, the period end is preferred over datetime/start.
- Do NOT remove rows from the procedure CSV. It is copied unchanged to *_reduced.csv.
- For all other CSV files, detect timestamp columns by column-name keywords and
  by checking whether values can actually be parsed as dates/times.
- Remove an entire row if any detected timestamp in that row is after the
  patient's latest qualifying procedure timestamp.
- Write reduced CSVs as [original_filename]_reduced.csv.
- Write removed rows summary to removed_datapoints.csv.

Only Python standard library is used.
"""

import calendar
import csv
import json
import os
import re
from datetime import datetime, timezone, time

CONFIG_FILE = "config.json"
DEFAULT_TIMESTAMP_KEYS = ["date", "time", "period", "start", "end"]

PROCEDURE_TIMESTAMP_PRIORITY = [
    "Procedure_performed_X_Performedperiod_end",
    "Procedure_performed_X_Performeddatetime",
    "Procedure_performed_X_Performedperiod_start",
]

DATE_YEAR_RE = re.compile(r"^\d{4}$")
DATE_YEAR_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    required = ["identifying_column", "identifying_code", "mode_of_action"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing required config parameter(s): {missing}")

    config.setdefault("patient_column", "patient")
    config.setdefault("timestamp_column_keywords", DEFAULT_TIMESTAMP_KEYS)
    config.setdefault("procedure_filename_keyword", "procedure")
    config.setdefault("timestamp_detection_sample_rows", 200)
    config.setdefault("minimum_parseable_values_for_timestamp_column", 1)

    if config["mode_of_action"].lower() != "after":
        raise ValueError("Currently only mode_of_action = 'after' is supported.")

    return config


def sniff_dialect(filename):
    with open(filename, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(8192)

    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def csv_files_in_current_folder():
    result = []
    for filename in os.listdir("."):
        lower = filename.lower()
        if not lower.endswith(".csv"):
            continue
        if lower.endswith("_reduced.csv"):
            continue
        if lower == "removed_datapoints.csv":
            continue
        result.append(filename)
    return sorted(result)


def find_procedure_file(csv_files, config):
    keyword = config["procedure_filename_keyword"].lower()
    matches = [f for f in csv_files if keyword in f.lower()]

    if not matches:
        raise FileNotFoundError(
            f"No procedure CSV found. Expected a filename containing '{keyword}'."
        )
    if len(matches) > 1:
        raise RuntimeError(
            "More than one possible procedure CSV found: " + ", ".join(matches)
        )
    return matches[0]


def reduced_filename(filename):
    base, ext = os.path.splitext(filename)
    return f"{base}_reduced{ext}"


def normalize_datetime(dt):
    """Return a timezone-aware UTC datetime for safe comparison."""
    if dt.tzinfo is None:
        # Treat timezone-less timestamps as UTC rather than local machine time.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_timestamp(value):
    """
    Parse FHIR-like dates/timestamps.

    Supports:
    - YYYY
    - YYYY-MM
    - YYYY-MM-DD
    - full ISO datetimes, with or without timezone
    - Z timezone suffix
    - common German date formats

    For partial dates, the latest possible instant is used:
    - YYYY -> Dec 31 23:59:59.999999
    - YYYY-MM -> last day of month 23:59:59.999999
    - YYYY-MM-DD -> same day 23:59:59.999999

    This is conservative for the rule "remove if timestamp is after procedure".
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    # Remove surrounding quotes that sometimes appear in exported CSV values.
    s = s.strip('"').strip("'").strip()
    if not s:
        return None

    if DATE_YEAR_RE.match(s):
        year = int(s)
        return datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)

    if DATE_YEAR_MONTH_RE.match(s):
        year, month = map(int, s.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    if DATE_FULL_RE.match(s):
        year, month, day = map(int, s.split("-"))
        return datetime(year, month, day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    # FHIR/ISO often uses Z for UTC.
    iso = s.replace("Z", "+00:00")

    # Support compact timezone offsets like +0100 if encountered.
    if re.search(r"[+-]\d{4}$", iso):
        iso = iso[:-5] + iso[-5:-2] + ":" + iso[-2:]

    try:
        return normalize_datetime(datetime.fromisoformat(iso))
    except ValueError:
        pass

    fallback_formats = [
        "%d.%m.%Y",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%Y/%m/%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
    ]

    for fmt in fallback_formats:
        try:
            dt = datetime.strptime(s, fmt)
            if "%H" not in fmt:
                dt = datetime.combine(dt.date(), time.max)
            return normalize_datetime(dt)
        except ValueError:
            continue

    return None


def get_row_procedure_timestamp(row):
    """
    Get the relevant procedure timestamp for one procedure row.
    Period end is preferred. If absent, datetime is used. If absent, start is used.
    """
    for col in PROCEDURE_TIMESTAMP_PRIORITY:
        ts = parse_timestamp(row.get(col))
        if ts is not None:
            return ts
    return None


def build_latest_procedure_timestamps(procedure_file, config):
    patient_col = config["patient_column"]
    identifying_col = config["identifying_column"]
    identifying_code = str(config["identifying_code"]).strip()

    latest_by_patient = {}

    dialect = sniff_dialect(procedure_file)
    with open(procedure_file, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, dialect=dialect)

        if not reader.fieldnames:
            raise RuntimeError(f"Procedure file has no header: {procedure_file}")

        missing_cols = [
            col for col in [patient_col, identifying_col]
            if col not in reader.fieldnames
        ]
        if missing_cols:
            raise RuntimeError(
                f"Procedure file is missing required column(s): {missing_cols}"
            )

        for row in reader:
            code = str(row.get(identifying_col, "")).strip()
            if code != identifying_code:
                continue

            patient = str(row.get(patient_col, "")).strip()
            if not patient:
                continue

            ts = get_row_procedure_timestamp(row)
            if ts is None:
                continue

            if patient not in latest_by_patient or ts > latest_by_patient[patient]:
                latest_by_patient[patient] = ts

    return latest_by_patient


def candidate_timestamp_columns(fieldnames, config):
    keys = [k.lower() for k in config["timestamp_column_keywords"]]
    candidates = []
    for col in fieldnames:
        lower = col.lower()
        if any(key in lower for key in keys):
            candidates.append(col)
    return candidates


def detect_timestamp_columns(filename, fieldnames, config):
    """
    Detect timestamp columns using both name matching and value parsing.
    A column must contain a keyword and at least N parseable non-empty values
    in the sample rows.
    """
    candidates = candidate_timestamp_columns(fieldnames, config)
    if not candidates:
        return []

    parseable_counts = {col: 0 for col in candidates}
    sample_limit = int(config["timestamp_detection_sample_rows"])
    min_parseable = int(config["minimum_parseable_values_for_timestamp_column"])

    dialect = sniff_dialect(filename)
    with open(filename, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, dialect=dialect)
        for idx, row in enumerate(reader):
            if idx >= sample_limit:
                break
            for col in candidates:
                value = row.get(col)
                if value is not None and str(value).strip():
                    if parse_timestamp(value) is not None:
                        parseable_counts[col] += 1

    return [col for col in candidates if parseable_counts[col] >= min_parseable]


def copy_csv_unchanged(input_file, output_file):
    dialect = sniff_dialect(input_file)
    with open(input_file, "r", encoding="utf-8-sig", newline="") as infile, \
         open(output_file, "w", encoding="utf-8", newline="") as outfile:
        reader = csv.reader(infile, dialect=dialect)
        writer = csv.writer(outfile, dialect=dialect)
        for row in reader:
            writer.writerow(row)


def process_non_procedure_file(filename, latest_by_patient, config, removed_rows):
    patient_col = config["patient_column"]
    output_file = reduced_filename(filename)
    dialect = sniff_dialect(filename)

    with open(filename, "r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile, dialect=dialect)
        fieldnames = reader.fieldnames

        if not fieldnames:
            copy_csv_unchanged(filename, output_file)
            return {"file": filename, "kept": 0, "removed": 0, "timestamp_columns": []}

        if patient_col not in fieldnames:
            # Cannot link rows to patients; copy unchanged.
            copy_csv_unchanged(filename, output_file)
            return {
                "file": filename,
                "kept": None,
                "removed": 0,
                "timestamp_columns": [],
                "note": f"No '{patient_col}' column; copied unchanged.",
            }

        timestamp_cols = detect_timestamp_columns(filename, fieldnames, config)

        kept = 0
        removed = 0

        with open(output_file, "w", encoding="utf-8", newline="") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames, dialect=dialect)
            writer.writeheader()

            for row in reader:
                patient = str(row.get(patient_col, "")).strip()

                # Keep rows that cannot be linked to a qualifying procedure.
                if not patient or patient not in latest_by_patient:
                    writer.writerow(row)
                    kept += 1
                    continue

                procedure_ts = latest_by_patient[patient]
                after_timestamps = []

                for col in timestamp_cols:
                    ts = parse_timestamp(row.get(col))
                    if ts is not None and ts > procedure_ts:
                        after_timestamps.append((col, ts))

                if after_timestamps:
                    # Remove entire row if any timestamp is after latest procedure.
                    removed_col, removed_ts = max(after_timestamps, key=lambda item: item[1])
                    removed_rows.append({
                        "patient": patient,
                        "source file name": filename,
                        "timestamp procedure": procedure_ts.isoformat(),
                        "timestamp removed datapoint": removed_ts.isoformat(),
                    })
                    removed += 1
                else:
                    writer.writerow(row)
                    kept += 1

    return {
        "file": filename,
        "kept": kept,
        "removed": removed,
        "timestamp_columns": timestamp_cols,
    }


def write_removed_datapoints(removed_rows):
    fieldnames = [
        "patient",
        "source file name",
        "timestamp procedure",
        "timestamp removed datapoint",
    ]
    with open("removed_datapoints.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(removed_rows)


def write_reduction_report(report_rows):
    fieldnames = ["file", "kept", "removed", "timestamp_columns", "note"]
    with open("reduction_report.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in report_rows:
            writer.writerow({
                "file": row.get("file"),
                "kept": row.get("kept"),
                "removed": row.get("removed"),
                "timestamp_columns": "; ".join(row.get("timestamp_columns", [])),
                "note": row.get("note", ""),
            })


def main():
    config = load_config()
    csv_files = csv_files_in_current_folder()
    procedure_file = find_procedure_file(csv_files, config)

    latest_by_patient = build_latest_procedure_timestamps(procedure_file, config)

    removed_rows = []
    report_rows = []

    for filename in csv_files:
        if filename == procedure_file:
            copy_csv_unchanged(filename, reduced_filename(filename))
            report_rows.append({
                "file": filename,
                "kept": "all",
                "removed": 0,
                "timestamp_columns": [],
                "note": "Procedure file copied unchanged by design.",
            })
        else:
            report_rows.append(
                process_non_procedure_file(
                    filename=filename,
                    latest_by_patient=latest_by_patient,
                    config=config,
                    removed_rows=removed_rows,
                )
            )

    write_removed_datapoints(removed_rows)
    write_reduction_report(report_rows)

    print("Done.")
    print(f"Procedure file: {procedure_file}")
    print(f"Patients with qualifying procedure: {len(latest_by_patient)}")
    print(f"Removed datapoints: {len(removed_rows)}")
    print("Created *_reduced.csv files, removed_datapoints.csv, and reduction_report.csv")


if __name__ == "__main__":
    main()
