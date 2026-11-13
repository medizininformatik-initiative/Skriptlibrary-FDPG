# Prüfskripte für TORCH-Exporte

TORCH wählt die Kohorte über alle Daten eines Patienten aus, exportiert aber nur Daten aus dem
Einwilligungszeitraum. Liegt die einschließende Diagnose außerhalb, ist der Patient in der Ausleitung,
die Diagnose aber nicht. Diese Patienten filtert `filter_by_crtdl.py` heraus.

| Skript | Zweck | läuft auf | Details |
|---|---|---|---|
| `filter_by_crtdl.py` | entfernt Patienten ohne erfüllte Einschlusskriterien aus den CSVs | `csv/` (nach DIMP) | [DETAILS_filter.md](docs/DETAILS_filter.md) |
| `validate_consent_torch.py` | **optional:** prüft, ob alle exportierten Daten im Consent-Fenster liegen, und zeigt die Ausschlüsse mit IDs vor DIMP | `import/` (vor DIMP) | [DETAILS_consent.md](docs/DETAILS_consent.md) |

Python 3.8+, nur Standardbibliothek.

## Inhalt

- [Quickstart](#quickstart)
  - [1. Filter ausführen](#1-filter-ausführen)
  - [2. Konsolenausgabe prüfen](#2-konsolenausgabe-prüfen)
  - [3. Ausliefern](#3-ausliefern)
- [Ausgaben](#ausgaben)
- [Wichtig](#wichtig)
- [Optional: Ausschlüsse genauer nachprüfen](#optional-ausschlüsse-genauer-nachprüfen)
- [Weiteres](#weiteres)

## Quickstart

### 1. Filter ausführen

```bash
python3 /pfad/zu/refine_consent_cohort/filter_by_crtdl.py \
  --crtdl <CRTDL.json> \
  --csv-dir jobs/<job>/csv \
  --out-dir jobs/<job>/filter_by_crtdl
```

Beispiel, aufgerufen im Projektordner der DUP:

```bash
python3 ~/Skriptlibrary-FDPG/refine_consent_cohort/filter_by_crtdl.py \
  --crtdl PROJEKT_v01.json \
  --csv-dir jobs/20261021_1242_1a2b3c4d/csv \
  --out-dir jobs/20261021_1242_1a2b3c4d/filter_by_crtdl
```

Weitere Parameter sind optional, siehe [DETAILS_filter.md](docs/DETAILS_filter.md#4-parameter).

### 2. Konsolenausgabe prüfen

**Code-Suche:** Zu jedem Kriterium der CRTDL steht, welche Codes in den CSVs gefunden wurden.

```text
Code-Suche:
  K1 R26: MII PR Diagnose Condition / Condition_code_codingIcd10gm_code: 312
      gefundene Codes (3): R26.0, R26.1, R26.8
  K2 H51.9: NICHT GEFUNDEN
```

- `K1`: Gesucht wurde `R26`, gefunden wurden die Unterkodes `R26.0`, `R26.1` und `R26.8` in 312 Zeilen.
  Das Kriterium wurde gefunden.
- `K2`: `H51.9` steht in keiner Zeile der CSVs. Über dieses Kriterium kann also kein Patient
  eingeschlossen werden.

`NICHT GEFUNDEN` heißt meist: Der Code ist bei allen Patienten nur vor der Einwilligung dokumentiert
und wurde deshalb nicht exportiert. Patienten, die nur über diesen Code eingeschlossen wurden, werden
ausgeschlossen. Das ist genau die Bereinigung, für die das Skript da ist.

**SNOMED und LOINC in der CRTDL.** Ein Beispiel:

- Die CRTDL hat als Kriterium den SNOMED-Code `73211009` „Diabetes mellitus“, also einen Oberbegriff.
- In den Daten eines Patienten steht `44054006` „Diabetes mellitus Typ 2“, ein Unterbegriff davon.
- Bei der Kohortenauswahl wird der Oberbegriff über die Terminologie in alle Unterbegriffe aufgelöst.
  Der Patient wird eingeschlossen.
- Das Skript vergleicht bei SNOMED exakt: `73211009` ist nicht `44054006`. Es findet nichts und schließt
  den Patienten aus, obwohl er die Diagnose im Export hat.

Bei ICD, OPS und ATC passiert das nicht. Dort steckt die Hierarchie im Code selbst: `R26.8` beginnt mit
`R26`, also erkennt das Skript `R26.8` als Unterbegriff von `R26`. Bei SNOMED und LOINC sieht man den
Codes die Hierarchie nicht an, dafür bräuchte das Skript einen Terminologieserver. Nutzt eine CRTDL
SNOMED- oder LOINC-Oberbegriffe (z.B. bei Bioproben oder Laborgruppen), die Ausschlüsse daher genau
prüfen.

**Nicht berücksichtigt:** Manche Kriterien der CRTDL kann das Skript nicht prüfen. Sie werden
aufgelistet und übersprungen, das ist so gewollt.

```text
  Nicht berücksichtigt – Consent: MDAT wissenschaftlich nutzen EU DSGVO NIVEAU
  Nicht berücksichtigt – nicht prüfbar (Alter/Geschlecht): Gegenwärtiges chronologisches Alter
```

- **Consent:** Die Einwilligung hat TORCH schon beim Export geprüft.
- **Alter, Geschlecht:** Dafür sucht das Skript nicht nach Codes. Wegen dieser Kriterien wird also
  niemand ausgeschlossen. Beispiel: Die CRTDL verlangt „Alter > 17 UND Migräne“. Das Skript prüft nur
  die Migräne. Steht das Alter in derselben ODER-Gruppe wie eine Diagnose, z.B. „Alter > 65 ODER
  Migräne“, wird die ganze Gruppe übersprungen. Sonst würde ein Patient, der nur über das Alter
  eingeschlossen wurde, wegen fehlender Migräne zu Unrecht entfernt.

**Anzahl der Ausgeschlossenen:** steht am Ende.

```text
Ausgeschlossen: 42 von 1500 Patienten (2.8 %)
```

Ausgeschlossen werden Patienten, deren einschließende Daten nicht im Export stehen, meist weil sie vor
der Einwilligung liegen. Erwartet ist ein kleiner Anteil wie hier (im Pilot unter 5 %). Werden z.B. 40 %
ausgeschlossen, stimmt meist etwas mit den Codes oder Tabellen nicht, dann die Code-Suche oben prüfen.

### 3. Ausliefern

Ausgeliefert werden die `*_include.csv` aus `jobs/<job>/filter_by_crtdl/`.

## Ausgaben

| Datei | Was steht drin | Wofür |
|---|---|---|
| `<Tabelle>_include.csv` | jede Eingabetabelle ohne die ausgeschlossenen Patienten, gleiche Spalten und Trennzeichen wie das Original | **wird ausgeliefert** |
| `to_be_excluded.csv` | ausgeschlossene Patienten (`Patient.id` nach DIMP) und die Nummern der nicht erfüllten Gruppen | Anzahl und Gruppen prüfen |
| `inclusion_criteria_matches.csv` | eine Zeile pro Patient, pro Kriterium `1` (erfüllt) oder `0` | nachsehen, welches Kriterium ein Patient erfüllt |
| `code_matches.csv` | welche Codes in den Daten auf welches Kriterium gepasst haben, mit Tabelle, Spalte und Anzahl | prüfen, ob die Code-Suche das Richtige findet |

Spalten und Beispiele: [DETAILS_filter.md](docs/DETAILS_filter.md#10-ausgabedateien).

## Wichtig

- Der Filter prüft nicht Alter, Geschlecht, Wert- und Zeitfilter und `exclusionCriteria`. Im Zweifel
  bleibt ein Patient drin.
- Patienten-IDs sind die FHIR-Ressourcen-ID `Patient.id`, **nicht** ein Identifier aus
  `Patient.identifier` (z.B. Pseudonym oder PID). Nach DIMP ist `Patient.id` gehasht.

## Optional: Ausschlüsse genauer nachprüfen

Wer nachvollziehen will, ob die Ausschlüsse stimmen, kann zusätzlich `validate_consent_torch.py` auf den
NDJSON-Dateien in `import/` laufen lassen. Dort liegen die Bundles immer ungedimpt, die IDs lassen sich
also in den eigenen Quelldaten finden.

```bash
python3 /pfad/zu/refine_consent_cohort/validate_consent_torch.py \
  --data jobs/<job>/import \
  --crtdl <CRTDL.json> \
  --encounter-shift on --shift-max-days <wie TORCH> \
  --today <Exportdatum> \
  --out-dir jobs/<job>/consent_report \
  --inclusion-check
```

Beispiel, aufgerufen im Projektordner der DUP:

```bash
python3 ~/Skriptlibrary-FDPG/refine_consent_cohort/validate_consent_torch.py \
  --data jobs/20261021_1242_1a2b3c4d/import \
  --crtdl PROJEKT_v01.json \
  --encounter-shift on --shift-max-days 7 \
  --today 2026-10-21 \
  --out-dir jobs/20261021_1242_1a2b3c4d/consent_report \
  --inclusion-check
```

Für `--inclusion-check` muss `filter_by_crtdl.py` im selben Ordner liegen, das Skript nutzt dessen
Logik für die Einschlusskriterien. Ohne `--inclusion-check` läuft `validate_consent_torch.py` allein.

`--encounter-shift` wie `TORCH_ENABLE_ENCOUNTER_SHIFT`, `--shift-max-days` wie
`TORCH_ENCOUNTER_SHIFT_MAX_DAYS`. Die Prüfung bildet die Logik von **TORCH 1.0.3** nach, für ältere
Versionen siehe [DETAILS_consent.md](docs/DETAILS_consent.md#4-parameter).

Ergebnis in `jobs/<job>/consent_report/`:

- `consent_summary.md`: Erwartet ist `✅ no violations`. Unter `Inclusion check` steht, wie viele
  Patienten die Einschlusskriterien im Export nicht erfüllen. Das sollte etwa `X` aus der
  Filterausgabe entsprechen.
- `consent_inclusion.csv`: die ausgeschlossenen Patienten mit `Patient.id` vor DIMP und ihrem
  Consent-Fenster. Damit lassen sich die einschließenden Diagnosen in den Quelldaten (ohne
  Consent-Filter) nachsehen. Erwartet: Sie liegen vor `window_start`.
- `consent_validation.log`: Protokoll des Laufs mit Parametern, Eingabedateien, Fortschritt, Laufzeit
  und Speicherverbrauch. Bei einem Abbruch steht hier der Fehler. Enthält keine Patienten-IDs und kann
  bei Problemen weitergegeben werden.

**Bei Abbruch:** `consent_validation.log` ansehen. Steht am Ende kein Fehler, sondern bricht das Log
einfach ab (auf der Konsole meist nur `Killed`), hat das System den Prozess beendet, meist wegen zu wenig
Arbeitsspeicher. Die letzte Fortschrittszeile zeigt, wie weit das Skript kam und wie viel Speicher es
bis dahin belegt hatte.

Weitere Ausgaben und das Vorgehen: [DETAILS_consent.md](docs/DETAILS_consent.md).

## Weiteres

- `docs/`: ausführliche Beschreibung beider Skripte, `docs/pilotierung/`: Bericht zur Pilotierung
- `development/`: Tests und künstliche Testdaten, nur nach Änderungen an den Skripten nötig
  ([Tests](docs/DETAILS_filter.md#14-tests)). Dazu `filter_by_crtdl_dev.py`, eine ressourcenschonendere
  Version des Filters mit gleichen Ergebnissen, noch im Test. Bei Speicherproblemen mit großen Exporten
  kann sie statt `filter_by_crtdl.py` genutzt werden.