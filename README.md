# Skriptlibrary-FDPG

## Introduction
This library builds on the Data-Use-Pipeline described here:
https://medizininformatik-initiative.github.io/dataportal/data-node/dup-pipeline.html

The DUP-Pipeline outputs either 1) project specific FHIR Bundles (NDJSON), 2) pseudonomized, de-identified FHIR Bundles, or 3) multiple CSVs (one per Feature) linked by logical references

Scripts provided here execute additional steps that are designed to support validation and further refinement of the data at the sites.

---

## Order of the data refinement steps

Which scripts run in which order between extraction and delivery (in German):
[ABLAUF_DATA_REFINEMENT.md](ABLAUF_DATA_REFINEMENT.md)

---

## refine_consent_cohort - Remove patients whose inclusion criteria are not in the export

TORCH selects the cohort on all data of a patient but exports only data within the consent window. `filter_by_crtdl.py`
removes patients whose inclusion criteria are not fulfilled in the exported CSVs. `validate_consent_torch.py` (optional)
checks the TORCH consent handling on the NDJSON before DIMP.

Details and usage (in German): [refine_consent_cohort/README.md](refine_consent_cohort/README.md)

---

## Validate TORCH CONSENT Handling:

> Superseded by `refine_consent_cohort/validate_consent_torch.py` (follows the TORCH 1.0.3 consent logic, see above).

validate_consent_v2.py
```bash
python3 validate_consent.py import/[patienten].ndjson [output.csv]
```
outputs a output.csv that contains validation wether the datapoints in the TORCH extracted NDJSON are covered by the consent policies

---

## reduce-csvs - Further removal of relative datapoints after selection of variables by TORCH
This Script removes datapoints in the CSV output relative to a defining criteria (in this case all datapoints after procedure "Somnography")


### Script:
reduce-csvs/reduce_csvs.py
### Config:
reduce-csvs/config.json

Script and config must be present and executed in the folder jobs/[job-hash]/csv/ 
```bash
python3 reduce_csvs.py
```
output files are:
*_reduced.csv with the reduced csv files, 
removed_datapoints.csv contains datapoints that were removed
reduction_report.csv (logs)

---

## reduce_patients_by_age - Remove patients by age at diagnosis

Removes patients who did not reach the age threshold at any diagnosis, and all their rows from every CSV.

Details and usage (in German): [reduce_patients_by_age/README.md](reduce_patients_by_age/README.md)

---

## birthday2age - Replace the birth date by the age

Replaces `Patient.birthDate` in the patient CSV by the age.