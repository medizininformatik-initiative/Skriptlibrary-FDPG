# Consent Validation Script

This script validates the consent logic applied to TORCH FHIR NDJSON exports against the MII consent specification. It verifies that clinical resources are included only when they fall within the patient's effective consent period.

1. [Features](#features)
2. [Requirements](#requirements)
3. [Usage](#usage)
4. [Input](#input)
5. [Output](#output)
6. [Validating Consent Policies](#validating-consent-policies)
7. [Notes](#notes)
8. [Script Version v3](#script-version-v3)
9. [Exit Summary](#exit-summary)

## Features

The validator checks:

- **Step 4:** Consent validity gate (`.8`)
- **Step 4:** Consent data window (`.6`)
- **Step 5:** Encounter-based adjustment of the consent start date
- **Step 6:** Retrospective consent modifiers (`.45` and `.46`)
- Whether each clinical resource timestamp falls within the final effective consent window

The following consent OIDs are evaluated:

| Code | OID | Role |
|------|-----|------|
| MDAT wissenschaftlich nutzen EU DSGVO NIVEAU | `2.16.840.1.113883.3.1937.777.24.5.3.8` | Validity gate (today-in-period check) |
| MDAT erheben | `2.16.840.1.113883.3.1937.777.24.5.3.6` | Data-extraction window |
| MDAT retrospektiv speichern, verarbeiten | `2.16.840.1.113883.3.1937.777.24.5.3.45` | Retrospective modifier for `.6` (optional) |
| MDAT retrospektiv wissenschaftlich nutzen EU DSGVO NIVEAU | `2.16.840.1.113883.3.1937.777.24.5.3.46` | Retrospective modifier for `.6` (optional) |

The output is a CSV report containing one row per clinical resource together with the consent evaluation that was applied.

---

## Requirements

- Python 3.7 or newer
- No external Python libraries required

---

## Usage

```bash
python3 validate_consent.py <input.ndjson> [output.csv]
```

### Example

```bash
python3 validate_consent.py patient_export.ndjson validation_results.csv
```

### Example (job pipeline)

```bash
python3 validate_consent_v3.py ../jobs/[job_hash]/import/[hash].ndjson
```

If no output filename is provided, the script automatically generates a timestamped CSV file.

---

## Input

The input must be a TORCH FHIR NDJSON export where each line contains a single FHIR Bundle.

---

## Output

The generated CSV contains:

| Column | Description | Example |
|---------|-------------|---------|
| `patient_id` | ID of the patient from the FHIR Patient resource | `123456` |
| `consent_id` | ID of the Consent resource used | `consent-001` |
| `consent_datetime` | Creation timestamp of the consent (`Consent.dateTime`) | `2024-05-17T08:15:00+02:00` |
| `gate_8_start` | Start of the `.8` validity period | `2023-01-01` |
| `gate_8_end` | End of the `.8` validity period | `2025-12-31` |
| `gate_8_active_today` | Indicates whether the consent validity period (`.8`) is currently active | `YES`, `NO (...)` |
| `window_6_start` | Original start of the `.6` data window | `2023-01-01` |
| `window_6_end` | Original end of the `.6` data window | `2024-12-31` |
| `retro_45_present` | Indicates whether a retrospective `.45` (permit) provision is present | `YES`, `NO` |
| `retro_46_present` | Indicates whether a retrospective `.46` (permit) provision is present | `YES`, `NO` |
| `effective_window_start` | Final consent window start after applying encounter and retrospective logic | `2022-11-15` |
| `effective_window_end` | Final consent window end | `2024-12-31` |
| `encounter_overlap_detected` | Indicates whether an overlapping encounter shifted the consent start date | `YES`, `NO` |
| `effective_window_start_shifted_to` | Final adjusted consent start date used for the check | `2022-11-15`, `1900-01-01` |
| `resource_type` | Type of the checked FHIR resource | `Observation`, `Condition`, `Procedure` |
| `resource_id` | ID of the checked resource | `obs-123` |
| `resource_timestamp` | Timestamp extracted from the clinical resource, used for the check | `2023-06-01` |
| `timestamp_in_window` | Result of the time window check | `YES`, `NO`, `NO_TIMESTAMP`, `CANNOT_CHECK`, `N/A` |
| `validation_notes` | Explanation of adjustments or validation findings (e.g. encounter adjustments, retrospective provisions, or resources outside the allowed period) | free text |

### Interpretation of `timestamp_in_window`

| Value | Meaning |
|-------|---------|
| `YES` | The resource timestamp falls within the effective consent window. |
| `NO` | The resource timestamp falls outside the effective consent window. |
| `NO_TIMESTAMP` | No checkable timestamp could be determined for the resource. |
| `CANNOT_CHECK` | The consent window could not be determined. |
| `N/A` | No clinical resources present in the bundle. |

### Interpretation of `gate_8_active_today`

| Value | Meaning |
|-------|---------|
| `YES` | The consent is currently valid. |
| `NO (today outside [...])` | The current date is outside the validity period. |
| `NO (.8 missing)` | No `.8` provision present. |
| `NO (unparseable .8 dates)` | The date values could not be parsed. |

---

## Validating Consent Policies

To validate consent handling:

1. Export patient data from TORCH as NDJSON.
2. Run the validator on the exported file.
3. Open the generated CSV.
4. Review the validation results for each clinical resource.

### Expected Results

Resources expected to be released according to the patient's consent should have:

```
timestamp_in_window = YES
```

Resources marked

```
timestamp_in_window = NO
```

fall outside the calculated consent window and should be reviewed. The `validation_notes` column explains why a resource failed validation or whether encounter adjustments or retrospective modifiers affected the effective consent period.

### Validation Logic

The script applies the following consent evaluation sequence:

1. Verify that the consent validity period (`.8`) is active.
2. Read the consent data window (`.6`).
3. Extend the consent start date if an overlapping encounter began before the consent window.
4. Apply retrospective consent modifiers (`.45` and `.46`) within the same Consent resource.
5. Determine the final effective consent window.
6. Check whether each clinical resource timestamp falls within that window.

---

## Notes

- Structural FHIR resources (such as `Patient`, `Consent`, `Bundle`, and `Provenance`) are excluded from timestamp validation.
- Clinical timestamps are extracted using resource-specific date fields with fallback fields when necessary.
- The validator flags retrospective deny provisions for manual review, as exact subtraction of denied periods is performed by the TORCH server.

---

## Script Version v3

### Change to Consent Selection

The validation logic has been updated to support patients with multiple `Consent` resources.

**Previous behavior**
* The first `Consent` resource in the bundle (`consent_list[0]`) was always used for validation.
* If a later consent contained relevant changes (e.g., retrospective modifiers `.45` or `.46`), these were not taken into account.

**New behavior**
* Validation now always uses the `Consent` resource with the most recent `dateTime` timestamp.
* All further validation steps (`.8` validity check, `.6` data window, encounter adjustment, and the evaluation of the retrospective modifiers `.45` and `.46`) are now carried out exclusively on the basis of this most recent consent.

**Code change**
The previous code
```python
consent = consent_list[0]
```
was replaced with
```python
# Use the most recent Consent (by dateTime)
def consent_sort_key(consent):
    d = parse_date(consent.get("dateTime"))
    return d or DATE_MIN
consent = max(consent_list, key=consent_sort_key)
```

---

## Exit Summary

After processing, the script reports:

- Number of patients processed
- Number of CSV rows written
- Number of clinical resources found outside the effective consent window

These summary statistics provide a quick overview of the validation results.
