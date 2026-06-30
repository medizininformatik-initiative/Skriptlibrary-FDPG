# Skriptlibrary-FDPG

## Introduction
This library builds on the Data-Use-Pipeline described here:
https://medizininformatik-initiative.github.io/dataportal/data-node/dup-pipeline.html

The DUP-Pipeline outputs either 1) project specific FHIR Bundles (NDJSON), 2) pseudonomized, de-identified FHIR Bundles, or 3) multiple CSVs (one per Feature) linked by logical references

Scripts provided here execute additional steps that are designed to support validation and further refinement of the data at the sites.

## Validate TORCH CONSENT Handling:
validate_consent_v2.py
python3 validate_consent.py import/[patienten].ndjson [output.csv]

outputs a output.csv that contains validation wether the datapoints in the TORCH extracted NDJSON are covered by the consent policies


## Further removal of relative datapoints after selection of variables by TORCH
This Script removes datapoints in the CSV output relative to a defining criteria (in this case all datapoints after procedure "Somnography")


### Script:
script/reduce_csvs.py
### Config:
config/config.json

Script and config must be present and executed in the folder jobs/[job-hash]/csv/ 
python3 reduce_csvs.py
output files are:
*_reduced.csv with the reduced csv files, 
removed_datapoints.csv contains datapoints that were removed
reduction_report.csv (logs)
