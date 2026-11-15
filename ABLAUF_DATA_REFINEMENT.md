# Ablauf Data Refinement

Reihenfolge der Skripte aus der Skriptlibrary zwischen Extraktion (Aether: TORCH → DIMP → Flattening) und Versand.
Welche Schritte ein Projekt braucht, steht in den Projektunterlagen.

## Inhalt

1. [Überblick](#überblick)
2. [Voraussetzungen](#voraussetzungen)
3. [Schritte](#schritte)
    1. [Consent-Prüfung (optional)](#1-consent-prüfung-optional)
    2. [CRTDL-Filter](#2-crtdl-filter)
    3. [Altersfilter (projektabhängig)](#3-altersfilter-projektabhängig)
    4. [Geburtsdatum auf Alter reduzieren (projektabhängig)](#4-geburtsdatum-auf-alter-reduzieren-projektabhängig)
4. [Reihenfolge](#reihenfolge)
5. [Nicht auszuliefernde Dateien](#nicht-auszuliefernde-dateien)

## Überblick

| Schritt | Skript | Eingabe | Ausgabe |
|---|---|---|---|
| 1. Consent-Prüfung (optional) | `refine_consent_cohort/validate_consent_torch.py` | `jobs/<job>/import` (NDJSON vor DIMP) | `jobs/<job>/consent_report/` |
| 2. CRTDL-Filter | `refine_consent_cohort/filter_by_crtdl.py` | `jobs/<job>/csv` | `jobs/<job>/filter_by_crtdl/` (`*_include.csv`) |
| 3. Altersfilter | `reduce_patients_by_age/reduce_patients_by_age.py` | `jobs/<job>/filter_by_crtdl` | `jobs/<job>/reduce_by_age/` (`*_include_reduced.csv`) |
| 4. Geburtsdatum → Alter | `birthday2age/fhir_age.py` | Patiententabelle aus Schritt 3 | `…_AGE.csv` daneben |

Jeder Schritt schreibt in einen eigenen Ordner, die Eingabedateien bleiben unverändert.

## Voraussetzungen

- Python 3.8+, nur Standardbibliothek
- `Skriptlibrary-FDPG` liegt auf Ebene der DUP-Ordner, alle Befehle laufen aus dem Projektordner der DUP
- Job-ID einmal setzen, dann gelten alle Befehle für diesen Job:

```bash
JOB=jobs/<job-id>
```

## Schritte

### 1. Consent-Prüfung (optional)

Prüft, ob alle exportierten Daten im Consent-Fenster liegen. Mit `--inclusion-check` zusätzlich, wie viele Patienten
die Einschlusskriterien im Export nicht erfüllen, mit IDs vor DIMP. Details:
[refine_consent_cohort/README.md](refine_consent_cohort/README.md).

```bash
python3 ../Skriptlibrary-FDPG/refine_consent_cohort/validate_consent_torch.py \
  --data $JOB/import \
  --crtdl <CRTDL.json> \
  --encounter-shift on --shift-max-days <wie TORCH> \
  --today <Exportdatum JJJJ-MM-TT> \
  --out-dir $JOB/consent_report \
  --inclusion-check
```

Erwartet: `✅ no violations` in `consent_summary.md`.

### 2. CRTDL-Filter

Entfernt Patienten, deren Einschlusskriterien nicht im Export stehen.

```bash
python3 ../Skriptlibrary-FDPG/refine_consent_cohort/filter_by_crtdl.py \
  --crtdl <CRTDL.json> \
  --csv-dir $JOB/csv \
  --out-dir $JOB/filter_by_crtdl
```

`Ausgeschlossen: X` sollte etwa der Anzahl unter `Inclusion check` aus Schritt 1 entsprechen.

### 3. Altersfilter (projektabhängig)

Entfernt Patienten, die bei keiner Diagnose die Altersgrenze des Projekts erreicht hatten. Details:
[reduce_patients_by_age/README.md](reduce_patients_by_age/README.md).

```bash
python3 ../Skriptlibrary-FDPG/reduce_patients_by_age/reduce_patients_by_age.py \
  --csv-dir $JOB/filter_by_crtdl \
  --out-dir $JOB/reduce_by_age \
  --age-threshold <Altersgrenze>
```

Die Berichte des CRTDL-Filters im selben Ordner werden übersprungen.

### 4. Geburtsdatum auf Alter reduzieren (projektabhängig)

```bash
python3 ../Skriptlibrary-FDPG/birthday2age/fhir_age.py \
  "$JOB/reduce_by_age/MII PR Person Patient (Pseudonymisiert)_include_reduced.csv" \
  "$JOB/reduce_by_age/MII PR Person Patient (Pseudonymisiert)_include_reduced_AGE.csv"
```

Ohne Altersfilter entsprechend auf `$JOB/filter_by_crtdl/…_include.csv`.

Die Dateiendung zeigt, welche Schritte gelaufen sind: `_include` (CRTDL-Filter), `_include_reduced` (zusätzlich
Altersfilter), `_AGE` (Geburtsdatum durch Alter ersetzt).

## Reihenfolge

| Regel | Grund |
|---|---|
| CRTDL-Filter vor allen Reduktionen | Einschlusskriterien werden auf dem vollständigen Export geprüft |
| Altersfilter vor `fhir_age.py` | braucht `Patient_birthDate` und genau eine Patiententabelle |
| `fhir_age.py` zuletzt | ersetzt das Geburtsdatum nur in der Tabelle, die ausgeliefert wird |
| Consent-Prüfung unabhängig | läuft auf dem NDJSON vor DIMP, verändert keine Daten |

## Nicht auszuliefernde Dateien

| Datei | Grund |
|---|---|
| Patiententabelle ohne `_AGE` | enthält das Geburtsdatum (wenn das Projekt nur das Alter bekommt) |
| `consent_report/*` | Prüfergebnisse, enthalten IDs vor DIMP |
| `filter_by_crtdl/to_be_excluded.csv`, `inclusion_criteria_matches.csv`, `code_matches.csv` | Berichte, z.T. mit IDs |
| `reduce_by_age/removed_patient.csv` | IDs und Geburtsdaten der entfernten Patienten |
| `*.log` | Protokolle der Skripte |

Bei großen Exporten gibt es für den CRTDL-Filter und die Consent-Prüfung ressourcenschonendere Versionen unter
`refine_consent_cohort/development/` (`*_dev.py`), mit gleichen Ergebnissen.