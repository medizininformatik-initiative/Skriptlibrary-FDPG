# Patient Age Filter

## Overview

`reduce_patients_by_age.py` removes patients who **do not have at least
one diagnosis at or after the configured age threshold** and removes all
associated records from every CSV file in the dataset. Filtered files
are written as new files with the suffix `_reduced.csv`; the original
files remain unchanged.

## Requirements

-   Python 3
-   Python standard library only (no third-party packages)

## Configuration

The script uses an **INI** configuration file (`config.ini`).

The following settings are available:

-   `patient_column`
-   `person_id_column`
-   `birthdate_column`
-   `condition_file_contains`
-   `person_file_contains`
-   `diagnosis_date_columns`
-   `age_threshold`
-   `mode` (currently only `remove_if_younger`)

If `config.ini` is missing, the script automatically creates one with
default values.

## Input

The script automatically scans its own directory for CSV files and
identifies:

-   one Person CSV (filename contains the configured
    `person_file_contains` string)
-   one Condition CSV (filename contains the configured
    `condition_file_contains` string)

### Required columns

**Person**

-   `id`
-   `Patient_birthDate`

**Condition**

-   `patient`

Other resource CSVs are filtered if they contain the configured patient
column.

## Patient matching

Patient identifiers are normalized before comparison.

Examples:

-   `Patient/12345` → `12345`
-   `urn:uuid:12345` → `12345`
-   `12345` → `12345`

This allows matching between the Person and Condition resources even
when different FHIR reference formats are used.

## Supported date formats

Birth dates and diagnosis dates may be stored as:

-   `YYYY`
-   `YYYY-MM`
-   `YYYY-MM-DD`
-   ISO datetime strings (for example `YYYY-MM-DDTHH:MM:SS`)

Partial dates are interpreted conservatively when calculating age.

## Filtering logic

For each patient:

1.  Read the birth date from the Person resource.
2.  Find all Condition records.
3.  Read the configured diagnosis date columns.
4.  Calculate the age for every valid diagnosis date.
5.  Keep the patient if **at least one diagnosis** occurred at or above
    the configured age threshold.
6.  Otherwise remove the patient from every CSV file.

## Output

### Reduced datasets

For every input CSV:

`<original_filename>_reduced.csv`

### removed_patient.csv

Columns:

-   patient
-   source file name
-   timestamp birthdate
-   timestamp diagnosis

Patients without a diagnosis date receive an empty `timestamp diagnosis`
field.

## Notes and limitations

-   Only the filtering mode `remove_if_younger` is implemented.
-   Only one Person CSV and one Condition CSV are expected.
-   Files without the configured patient column are copied unchanged.
-   The script prints a summary showing the number of patients found,
    kept, and removed.

## Running

``` bash
python reduce_patients_by_age.py
```

## Project summary

**Das Skript entfernt Patienten, die zum Zeitpunkt ihrer Diagnose jünger
als 20 Jahre sind, einschließlich aller zugehörigen Datenpunkte aus
sämtlichen CSV-Dateien des Datensatzes.**
