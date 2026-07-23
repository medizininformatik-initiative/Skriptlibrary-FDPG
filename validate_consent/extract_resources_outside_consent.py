#!/usr/bin/env python3
"""
extract_resources_outside_consent.py

Reads a consent-validation CSV and pulls out all resource rows that fall
OUTSIDE the patient's consent window (i.e. rows marked
timestamp_in_window = NO). Writes:
  1. A CSV with the details of every such resource.
  2. A plain-text list of the unique patient IDs affected, formatted as
     a quoted, comma-separated list (handy for pasting into a SQL
     IN (...) clause or similar).

Usage:
    python extract_resources_outside_consent.py --consent consent_validation.csv
"""

import argparse
import csv


def extract_resources(consent_file):
    """
    Parse the consent CSV and collect resources that are outside the
    consent window.

    Args:
        consent_file (str): Path to the input consent-validation CSV.
            Expected columns: patient_id, resource_type,
            resource_timestamp, resource_id, timestamp_in_window.

    Returns:
        tuple:
            resources (list[dict]): One dict per out-of-window resource,
                with keys patient_id, resource_type, resource_timestamp,
                resource_id.
            patient_ids (set[str]): Unique patient IDs that have at
                least one out-of-window resource.
    """
    resources = []
    patient_ids = set()

    with open(consent_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Only keep rows explicitly flagged as NOT within the
            # consent window. Comparison is case-insensitive and
            # whitespace-trimmed to tolerate messy source data.
            if row.get("timestamp_in_window", "").strip().upper() == "NO":
                resource = {
                    "patient_id": row.get("patient_id", ""),
                    "resource_type": row.get("resource_type", ""),
                    "resource_timestamp": row.get("resource_timestamp", ""),
                    "resource_id": row.get("resource_id", "")
                }
                resources.append(resource)

                # Track unique patients so we can produce a
                # deduplicated patient list later.
                if resource["patient_id"]:
                    patient_ids.add(resource["patient_id"])

    return resources, patient_ids


def write_resources_csv(resources, output_file):
    """
    Write the list of out-of-window resources to a CSV file.

    Args:
        resources (list[dict]): Resources returned by extract_resources().
        output_file (str): Path to the CSV file to create.
    """
    fieldnames = [
        "patient_id",
        "resource_type",
        "resource_timestamp",
        "resource_id"
    ]
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )
        writer.writeheader()
        writer.writerows(resources)


def write_patient_list(patient_ids, output_file):
    """
    Write the unique patient IDs to a text file as a quoted,
    comma-separated list (one ID per line, trailing comma on all but
    the last line) — convenient for pasting into a SQL IN (...) clause.

    Args:
        patient_ids (set[str]): Unique patient IDs to write.
        output_file (str): Path to the text file to create.
    """
    with open(output_file, "w", encoding="utf-8") as f:
        for i, patient_id in enumerate(sorted(patient_ids)):
            # No trailing comma after the very last entry.
            comma = "," if i < len(patient_ids) - 1 else ""
            f.write(f"'{patient_id}'{comma}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Extract resources outside of consent window"
    )
    parser.add_argument(
        "--consent",
        required=True,
        help="Consent validation CSV file"
    )
    args = parser.parse_args()

    resources, patient_ids = extract_resources(args.consent)

    # Fixed output filenames (always written to the current directory).
    resources_output = "resources_outside_consent.csv"
    patients_output = "fhir_patient_ids_outside_consent.txt"

    write_resources_csv(
        resources,
        resources_output
    )
    write_patient_list(
        patient_ids,
        patients_output
    )

    # Small summary so the user gets immediate feedback in the terminal.
    print(f"Resources extracted: {len(resources)}")
    print(f"Unique patients: {len(patient_ids)}")
    print(f"Created: {resources_output}")
    print(f"Created: {patients_output}")


if __name__ == "__main__":
    main()