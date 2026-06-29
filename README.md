# Skriptlibrary-FDPG

## Ausführen der Pipeline:
aether pipeline start somno-pipeline.yml Somnolink_18_06_2026_v0.9.json


## Zum Validieren des CONSENT Handling:
validate_consent_v2.py
python3 validate_consent.py import/[patienten].ndjson [output.csv]


### Das Somnolink Projekt hat eine Zusatzanforderung an die Minimierung der Daten (Datensparsamkeit) aus dem Antrag die aktuell nicht von TORCH wahrgenommen werden kann. Deshalb wird dieses Skript zugesteuert.
Das Skript entfernt alle Datenpunkte des Patienten nach dem Zeitpunkt des performed.date der Prozedur (Somnographie).


## Das Skript:
script/reduce_csvs.py
## Die Config zum Skript:
config/config.json

Das Skript muss im CSV Ordner des DUP-Pipeline Ordner jobs/[job-hash]/csv/ mit der config Datei abgelegt werden und wie folgt ausgeführt werden:
python3 reduce_csvs.py
output sind *_reduced.csv Dateien mit den reduzierten Inhalten sowie removed_datapoints.csv (enthält die entfernten Datenpunkte) und reduction_report.csv (logs)
