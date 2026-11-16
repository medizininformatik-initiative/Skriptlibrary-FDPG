# Altersfilter (`reduce_patients_by_age.py`)

Entfernt Patienten, die bei **keiner** Diagnose mindestens die Altersgrenze erreicht hatten, und alle ihre Zeilen aus
allen CSV-Tabellen eines Exports. Die Originaldateien bleiben unverändert.

Python 3.8+, nur Standardbibliothek.

## Inhalt

- [Aufruf](#aufruf)
- [Parameter](#parameter)
- [Konfiguration](#konfiguration)
- [Ablauf im Skript](#ablauf-im-skript)
- [Ausgaben](#ausgaben)
- [Wichtig](#wichtig)

## Aufruf

```bash
python3 /pfad/zu/reduce_patients_by_age/reduce_patients_by_age.py \
  --csv-dir jobs/<job>/filter_by_crtdl \
  --out-dir jobs/<job>/reduce_by_age \
  --age-threshold 18
```

Das Skript ist von überall aufrufbar. Gelesen werden alle `.csv` in `--csv-dir`, geschrieben wird nur in `--out-dir`.

Beispiel, aufgerufen im Projektordner der DUP, nach dem CRTDL-Filter (`Skriptlibrary-FDPG` liegt auf Ebene der DUPs):

```bash
python3 ../Skriptlibrary-FDPG/reduce_patients_by_age/reduce_patients_by_age.py \
  --csv-dir jobs/20261021_1242_1a2b3c4d/filter_by_crtdl \
  --out-dir jobs/20261021_1242_1a2b3c4d/reduce_by_age \
  --age-threshold 18
```

## Parameter

| Parameter | Pflicht | Standard | Beschreibung |
|---|---|---|---|
| `--csv-dir` | ja | – | Ordner mit den CSV-Dateien |
| `--out-dir` | ja | – | Ausgabeordner (wird angelegt) |
| `--age-threshold` | nein | `19` | Mindestalter bei mindestens einer Diagnose |
| `--config` | nein | – | `config.yaml` mit allen Einstellungen (siehe [Konfiguration](#konfiguration)) |
| `--person-table` | nein | automatisch | Name der Patiententabelle, falls mehrere Dateien `Person` im Namen haben |
| `--condition-table` | nein | automatisch | Name der Diagnosetabelle, falls mehrere Dateien `Condition` im Namen haben |

Parameter haben Vorrang vor `--config`.

## Konfiguration

Ohne `--config` gelten die eingebauten Standardwerte. Sie stehen auch in `config.yaml` und passen zu den Tabellen aus
dem Flattening. Eine eigene Datei braucht man nur bei abweichenden Spaltennamen oder für eine projektspezifische
Einstellung, z.B. `config_<projekt>.yaml` im DUP-Ordner.

| Einstellung | Standard | Bedeutung |
|---|---|---|
| `patient_column` | `patient` | Patientenspalte in den Tabellen |
| `alternate_patient_columns` | `subject`, … | weitere mögliche Namen der Patientenspalte |
| `person_id_column` | `id` | ID-Spalte der Patiententabelle |
| `birthdate_column` | `Patient_birthDate` | Geburtsdatum in der Patiententabelle |
| `person_file_contains` | `Person` | Teil des Dateinamens der Patiententabelle |
| `condition_file_contains` | `Condition` | Teil des Dateinamens der Diagnosetabelle |
| `diagnosis_date_columns` | `Condition_onset_…`, `Condition_recordedDate` | Datumsspalten der Diagnosen, mindestens eine muss vorhanden sein |
| `age_threshold` | `19` | Mindestalter |
| `mode` | `remove_if_younger` | derzeit einzige Möglichkeit |

## Ablauf im Skript

1. **Patiententabelle lesen:** Geburtsdatum pro Patient. Unvollständige Daten zählen ab dem frühesten Tag
   (`1990` → `1990-01-01`).
2. **Diagnosetabelle lesen:** Alter bei jeder Diagnose aus allen konfigurierten Datumsspalten. Spalten auf `period_end`
   zählen bis zum spätesten Tag (`2021` → `2021-12-31`).
3. **Entscheiden:** Ein Patient bleibt, wenn **mindestens eine** Diagnose bei einem Alter `>= --age-threshold` liegt.
   Entfernt werden Patienten ohne gültiges Geburtsdatum, ohne Diagnose mit Datum oder nur mit jüngeren Diagnosen.
4. **Tabellen schreiben:** Jede Tabelle wird zeilenweise gelesen und ohne die entfernten Patienten als
   `<Tabelle>_reduced.csv` geschrieben. Patiententabellen werden über die Spalte `id` gefiltert, alle anderen über die
   Patientenspalte. Tabellen ohne Patientenbezug (z.B. Medikations-Kerntabelle) werden unverändert kopiert.

Patienten-Referenzen werden vor dem Vergleich vereinheitlicht: `Patient/123`, `urn:uuid:123` und `123` sind gleich.

## Ausgaben

| Datei | Was steht drin |
|---|---|
| `<Tabelle>_reduced.csv` | jede Eingabetabelle ohne die entfernten Patienten, gleiche Spalten und Trennzeichen wie das Original |
| `removed_patient.csv` | entfernte Patienten mit Geburtsdatum und allen Diagnosedaten, eine Zeile pro Diagnosedatum |
| `reduce_patients_by_age.log` | Konsolenausgabe mit Aufruf, Einstellungen, Anzahl Ausgeschlossener, Laufzeit |

Auf der Konsole bzw. im Log steht u.a. `Ausgeschlossen: X von Y Patienten` und pro Tabelle `behalten` / `entfernt`.

## Wichtig

- Gefiltert wird nach dem **Alter bei der Diagnose**, nicht nach dem heutigen Alter.
- `removed_patient.csv` enthält Patienten-IDs und Geburtsdaten: nur lokal, nicht ausliefern.
- Das Skript braucht `Patient_birthDate`. Es muss deshalb **vor** einer Reduktion des Geburtsdatums auf das Alter
  laufen (z.B. `birthday2age`).
- Gibt es mehrere Dateien mit `Person` im Namen (z.B. eine zusätzliche `…_AGE.csv`), mit `--person-table` angeben,
  welche das Geburtsdatum enthält. Die anderen werden trotzdem über `id` gefiltert.
- Ergebnisse sind identisch mit Version 1 des Skripts, das in seinem eigenen Ordner arbeitete.
- Die Berichte des CRTDL-Filters (`code_matches.csv`, `inclusion_criteria_matches.csv`, `to_be_excluded.csv`) werden
  übersprungen, wenn `--csv-dir` der Ausgabeordner von `filter_by_crtdl.py` ist.