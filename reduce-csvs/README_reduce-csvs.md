# CSV Reduction Script

This script reduces a folder of CSV files based on each patient's latest qualifying procedure. It was designed for MII/FHIR-style CSV exports and uses only the Python standard library.

## Files

Place these files in the same folder as the CSV files you want to process:

```text
reduce_csvs.py
config.json
*.csv
```

The script scans all CSV files in the current folder. Existing `*_reduced.csv`, `removed_datapoints.csv`, and report files are ignored as inputs.

## Purpose

The script identifies patients who have a qualifying procedure, for example procedure code `1-790`, and determines the latest timestamp of that qualifying procedure for each patient.

For every other CSV file, rows belonging to those patients are compared against that patient's latest qualifying procedure timestamp. Rows that occur only after the procedure are removed. Original files are not modified.

## Configuration

Edit `config.json` before running the script.

Example:

```json
{
  "identifying_column": "Procedure_code_codingOps_code",
  "identifying_code": "1-790",
  "mode_of_action": "after",
  "patient_column": "patient",
  "procedure_filename_keyword": "procedure",
  "timestamp_column_keywords": ["date", "time", "period", "start", "end"],
  "timestamp_detection_sample_rows": 200,
  "minimum_parseable_values_for_timestamp_column": 1
}
```

### Configuration fields

| Field | Meaning |
|---|---|
| `identifying_column` | Column in the procedure CSV used to identify the relevant procedure code. |
| `identifying_code` | Procedure code to search for, for example `1-790`. |
| `mode_of_action` | Currently only `after` is supported. |
| `patient_column` | Column used to link rows across CSV files. Default is `patient`. |
| `procedure_filename_keyword` | Keyword used to identify the procedure CSV filename. Default is `procedure`. |
| `timestamp_column_keywords` | Column-name keywords used to find possible timestamp columns. |
| `timestamp_detection_sample_rows` | Number of rows sampled to verify whether a candidate timestamp column contains parseable timestamps. |
| `minimum_parseable_values_for_timestamp_column` | Minimum number of parseable sampled values required before a candidate column is treated as a timestamp column. |

## Procedure timestamp handling

The procedure CSV is identified by filename. The filename must contain the configured `procedure_filename_keyword`, for example `procedure`.

For qualifying procedure rows, the script looks for the procedure timestamp in this order:

1. `Procedure_performed_X_Performedperiod_end`
2. `Procedure_performed_X_Performeddatetime`
3. `Procedure_performed_X_Performedperiod_start`

For each patient, the latest qualifying procedure timestamp is used as the cutoff timestamp.

The procedure CSV itself is copied unchanged to a corresponding `*_reduced.csv` file. No procedure rows are removed.

## Timestamp detection in other CSV files

For non-procedure CSV files, timestamp columns are detected in two steps:

1. The column name must contain one of the configured timestamp keywords, for example `date`, `time`, `period`, `start`, or `end`.
2. The script checks sampled values in the column and only uses the column if enough values can actually be parsed as dates or timestamps.

This avoids treating unrelated columns as timestamps merely because their names contain words like `start` or `end`.

## Supported timestamp formats

The script supports common FHIR-style and CSV timestamp formats, including:

```text
YYYY
YYYY-MM
YYYY-MM-DD
YYYY-MM-DDTHH:MM:SS
YYYY-MM-DDTHH:MM:SSZ
YYYY-MM-DDTHH:MM:SS+01:00
YYYY-MM-DDTHH:MM:SS.123Z
DD.MM.YYYY
DD.MM.YYYY HH:MM
DD.MM.YYYY HH:MM:SS
```

Empty values are ignored.

Partial dates are interpreted conservatively as the latest possible instant in that period:

| Input | Interpreted as |
|---|---|
| `2024` | `2024-12-31 23:59:59.999999 UTC` |
| `2024-05` | last day of May 2024 at `23:59:59.999999 UTC` |
| `2024-05-02` | `2024-05-02 23:59:59.999999 UTC` |

Timezone-aware timestamps are normalized to UTC before comparison. Timestamps without a timezone are treated as UTC.

## Row removal logic

For each non-procedure row linked to a patient with a qualifying procedure:

- The row is kept if it has no parseable timestamps.
- The row is kept if any timestamp is before the procedure timestamp.
- The row is kept if any timestamp is equal to the procedure timestamp.
- The row is kept if a period starts before or exactly at the procedure timestamp, even if the period end is after the procedure timestamp.
- The row is removed only if all parseable timestamps in that row are strictly after the procedure timestamp.

In short:

```text
remove row only when every parsed timestamp in the row is > latest procedure timestamp
```

This means the script is conservative: if a row contains any timestamp indicating that the datapoint may belong before or at the procedure time, the row is kept.

## Running the script

Open a terminal in the folder containing the script, config file, and CSV files.

On Linux or macOS:

```bash
python3 reduce_csvs.py
```

On Windows:

```bash
python reduce_csvs.py
```

or:

```bash
py reduce_csvs.py
```

## Output files

The script creates one reduced CSV for every input CSV:

```text
original_filename_reduced.csv
```

For example:

```text
MII PR Diagnose Condition.csv
MII PR Diagnose Condition_reduced.csv
```

The original CSV files are not changed.

The script also creates:

```text
removed_datapoints.csv
reduction_report.csv
```

### `removed_datapoints.csv`

This file lists the rows that were removed. It contains:

| Column | Meaning |
|---|---|
| `patient` | Patient identifier. |
| `source file name` | CSV file from which the row was removed. |
| `timestamp procedure` | Latest qualifying procedure timestamp for that patient. |
| `timestamp removed datapoint` | Representative timestamp from the removed row. |

### `reduction_report.csv`

This file summarizes processing per source file. It contains:

| Column | Meaning |
|---|---|
| `file` | Processed CSV file. |
| `kept` | Number of rows kept. |
| `removed` | Number of rows removed. |
| `timestamp_columns` | Timestamp columns detected and used for comparison. |
| `note` | Additional information, for example if a file was copied unchanged. |

## Example terminal output

```text
Done.
Procedure file: MII PR Prozedur Procedure.csv
Patients with qualifying procedure: 7
Removed datapoints: 25
Created *_reduced.csv files, removed_datapoints.csv, and reduction_report.csv
```

## Important notes

- The script must be run from the folder containing the CSV files.
- The folder should contain exactly one procedure CSV matching `procedure_filename_keyword`.
- Rows from files without the configured patient column are copied unchanged.
- Rows from patients without a qualifying procedure are kept.
- The procedure CSV is never reduced; it is copied unchanged.
- The script uses only Python standard-library modules and does not require installing packages.
