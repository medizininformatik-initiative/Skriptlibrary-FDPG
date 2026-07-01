# Patient Age Filter

## Overview

`reduce_patients_by_age.py` filters a collection of FHIR resource CSV
files based on the patient's age at diagnosis.

For this project, patients **younger than 20 years** at the time of
diagnosis are removed together with **all associated records** from all
CSV files. The original CSV files are preserved; filtered copies are
written with the suffix `_reduced.csv`.

## Requirements

-   Python 3.8+
-   No external Python packages (Python standard library only)

## Configuration

The script reads its settings from `config.yaml`.

``` yaml
patient_age: 20

mode: remove_if_younger

diagnosis_columns:
  - Condition_onset_X_Onsetdatetime
  - Condition_onset_X_Onsetperiod_end
  - Condition_onset_X_Onsetperiod_start
  - Condition_recordedDate
```

## Input

The script automatically searches the directory containing the script
for CSV files and identifies the **Person** and **Condition** CSVs.

The Person CSV must contain: - `id` - `Patient_birthDate`

The Condition CSV must contain: - `patient`

Patient references are expected in the format `Patient/<identifier>` and
are automatically matched to `Person.id`.

## Supported date formats

-   YYYY
-   YYYY-MM
-   YYYY-MM-DD

## Filtering logic

1.  Read each patient's birth date.
2.  Find all Condition records.
3.  Extract diagnosis dates from the configured columns.
4.  Calculate the patient's age at diagnosis.
5.  Keep the patient if at least one diagnosis occurred at or above the
    configured age.
6.  Otherwise remove the patient and all associated records from every
    CSV file.

## Output

### Reduced datasets

Each input CSV generates:

`<original_filename>_reduced.csv`

### removed_patient.csv

Columns: - patient - source file name - timestamp birthdate - timestamp
diagnosis - reason

Reasons: - no_condition_record - no_valid_diagnosis_date -
diagnosis_before_threshold - missing_birthdate - birth_after_diagnosis

### kept_patients.csv

Columns: - patient - source file name - timestamp birthdate - timestamp
diagnosis - reason

### patient_filter_warnings.csv

Contains warnings for: - missing patient columns - ambiguous patient
columns - unexpected patient identifier formats - malformed patient
references

## Running

``` bash
python reduce_patients_by_age.py
```

## Project summary

**Das Skript entfernt Patienten, die zum Zeitpunkt ihrer Diagnose jünger
als 20 Jahre sind, einschließlich aller zugehörigen Datenpunkte aus
sämtlichen CSV-Dateien des Datensatzes.**
