# extract_resources_outside_consent.py

Extracts all resource entries that fall **outside** a patient's consent window from a consent-validation CSV, and 
produces two output files for cleanup / removal workflows.

## Requirements

- Python 3.6+ (no external dependencies — uses only the standard library)

## Input

A CSV file (e.g. `consent_validation.csv`) with at least these columns:

| Column              | Description                                      |
|----------------------|--------------------------------------------------|
| `patient_id`         | Patient identifier                                |
| `resource_type`      | Type of the resource (e.g. FHIR resource type)   |
| `resource_timestamp` | Timestamp of the resource                         |
| `resource_id`        | Resource identifier                               |
| `timestamp_in_window`| `YES`/`NO` — whether the resource falls inside the consent window |

Only rows where `timestamp_in_window` is `NO` (case-insensitive) are extracted.

## Usage

```bash
python extract_resources_outside_consent.py --consent consent_validation_[timstamp].csv
```

## Output

Running the script creates two files in the current directory:

- **`resources_to_remove.csv`** — full details of every out-of-window resource (`patient_id`, `resource_type`, 
  `resource_timestamp`, `resource_id`).
- **`fhir_patient_ids_to_remove.txt`** — unique, sorted list of affected  patient IDs, quoted and comma-separated (one 
  per line), ready to paste   into a SQL `IN (...)` clause.

The script also prints a short summary to the console:

```
Resources extracted: <count>
Unique patients: <count>
Created: resources_to_remove.csv
Created: fhir_patient_ids_to_remove.txt
```

## Notes

- Output filenames are currently fixed (not configurable via CLI).
- Rows with an empty `patient_id` are still included in   `resources_to_remove.csv` but not counted in the patient ID list.