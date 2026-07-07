# Consent Validation Script

This script validates the consent logic applied to TORCH FHIR NDJSON exports against the MII consent specification. It verifies that clinical resources are included only when they fall within the patient's effective consent period.

## Features

The validator checks:

- **Step 4:** Consent validity gate (`.8`)
- **Step 4:** Consent data window (`.6`)
- **Step 5:** Encounter-based adjustment of the consent start date
- **Step 6:** Retrospective consent modifiers (`.45` and `.46`)
- Whether each clinical resource timestamp falls within the final effective consent window

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

If no output filename is provided, the script automatically generates a timestamped CSV file.

---

## Input

The input must be a TORCH FHIR NDJSON export where each line contains a single FHIR Bundle.

---

## Output

The generated CSV contains:

| Column | Description |
|---------|-------------|
| `gate_8_active_today` | Indicates whether the consent validity period (`.8`) is currently active |
| `window_6_start` / `window_6_end` | Original consent data window |
| `effective_window_start` / `effective_window_end` | Final consent window after applying encounter and retrospective logic |
| `encounter_overlap_detected` | Indicates whether an overlapping encounter shifted the consent start date |
| `effective_window_start_shifted_to` | Final adjusted consent start date |
| `retro_45_present` / `retro_46_present` | Indicates whether retrospective consent modifiers were present |
| `resource_timestamp` | Timestamp extracted from the clinical resource |
| `timestamp_in_window` | Whether the resource falls within the effective consent window |
| `validation_notes` | Explanation of adjustments or validation findings |

---

# Validating Consent Policies

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

---

## Validation Logic

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

## Exit Summary

After processing, the script reports:

- Number of patients processed
- Number of CSV rows written
- Number of clinical resources found outside the effective consent window

These summary statistics provide a quick overview of the validation results.
