# Prüfskripte für TORCH-Exporte

TORCH wählt die Kohorte über alle Daten eines Patienten aus, exportiert aber nur Daten aus dem
Einwilligungszeitraum. Liegt die einschließende Diagnose außerhalb, ist der Patient in der Ausleitung,
die Diagnose aber nicht. Diese Patienten filtert `filter_by_crtdl.py` heraus.

| Skript | Zweck | läuft auf | Details |
|---|---|---|---|
| `validate_consent_torch.py` | prüft, ob alle exportierten Daten im Consent-Fenster liegen | `import/` (vor DIMP) | [DETAILS_consent.md](DETAILS_consent.md) |
| `filter_by_crtdl.py` | entfernt Patienten ohne erfüllte Einschlusskriterien aus den CSVs | `csv/` (nach DIMP) | [DETAILS_filter.md](DETAILS_filter.md) |

Python 3.8+, nur Standardbibliothek. Die Consent-Prüfung bildet die Logik von **TORCH 1.0.3** nach.

## Quickstart

**1. Consent-Prüfung** (optional, empfohlen; für die Filterung nicht nötig)

`--encounter-shift` wie `TORCH_ENABLE_ENCOUNTER_SHIFT`, `--shift-max-days` wie
`TORCH_ENCOUNTER_SHIFT_MAX_DAYS`. Grenze und Klasse `IMP` gibt es erst ab TORCH 1.0.3, für ältere
Versionen: `--shift-max-days -1 --shift-class any`.

```bash
python3 /pfad/zu/torch_export_checks/validate_consent_torch.py \
  --data jobs/<job>/import \
  --crtdl <CRTDL.json> \
  --encounter-shift on --shift-class IMP --shift-max-days <wie TORCH> \
  --today <Exportdatum> \
  --out-dir jobs/<job>/consent_report \
  --inclusion-check
```

Erwartung in `consent_summary.md`: `✅ no violations`. Unter `Inclusion check` steht, wie viele Patienten
die Einschlusskriterien im Export nicht erfüllen.

**2. Filter, Prüflauf**

```bash
python3 /pfad/zu/torch_export_checks/filter_by_crtdl.py \
  --crtdl <CRTDL.json> \
  --csv-dir jobs/<job>/csv \
  --out-dir jobs/<job>/filter_by_crtdl \
  --no-include
```

**3. Konsolenausgabe prüfen**

- **Code-Suche:** Zu jedem Kriterium stehen die gefundenen Codes, z.B. `R26` → `R26.0, R26.8`.
  Steht dort `NICHT GEFUNDEN`, kommt der Code in keiner Tabelle vor. Dann erfüllt kein Patient dieses
  Kriterium, und es werden womöglich zu viele ausgeschlossen. Prüfen, ob der Code in den Daten anders
  geschrieben ist oder in einer anderen Spalte steht.
- **Nicht berücksichtigt:** Consent-, Alters- und Geschlechtskriterien werden hier aufgelistet und
  übersprungen. Das ist so gewollt.
- **`Ausgeschlossen: X von Y (Z %)`:** Ausgeschlossen werden Patienten, deren einschließende Daten nicht
  im Export stehen, meist weil sie vor der Einwilligung liegen. Erwartet ist ein kleiner Anteil (im Pilot
  unter 5 %). Ein großer Anteil deutet auf ein Problem mit Codes oder Tabellen hin.
- **Vergleich mit Schritt 1:** `X` sollte etwa der Anzahl unter `Inclusion check` in `consent_summary.md`
  entsprechen. Beide prüfen dasselbe, einmal vor und einmal nach DIMP.

**4. Filterlauf:** derselbe Aufruf ohne `--no-include`. Ausgeliefert werden die `*_include.csv`.

## Ausgaben

**Consent-Prüfung** (`consent_report/`):

| Datei | Was steht drin | Wofür |
|---|---|---|
| `consent_summary.md` | Ergebnis (`✅ no violations` oder Anzahl Verstöße), Anzahl pro Status und Ressourcentyp, Patientenübersicht, Abschnitt `Inclusion check`. Nur Zahlen. | als Erstes lesen |
| `consent_resources.csv` | eine Zeile pro exportierter Ressource mit Datum und Status, z.B. `OK`, `OK_RETRO`, `VIOLATION_OUTSIDE_WINDOW` | Verstöße einzeln ansehen: nach `status` filtern |
| `consent_patients.csv` | eine Zeile pro Patient mit seinem Consent-Fenster, Retro und Shift | Fenster eines Patienten nachsehen |
| `consent_inclusion.csv` | nur mit `--inclusion-check`: Patienten, die die Einschlusskriterien im Export nicht erfüllen, mit `Patient.id` vor DIMP und Fenster | Ausschlüsse in den Quelldaten prüfen |

**Filter** (`filter_by_crtdl/`):

| Datei | Was steht drin | Wofür |
|---|---|---|
| `to_be_excluded.csv` | ausgeschlossene Patienten (`Patient.id` nach DIMP) und die Nummern der nicht erfüllten Gruppen | Anzahl und Gruppen prüfen |
| `inclusion_criteria_matches.csv` | eine Zeile pro Patient, pro Kriterium `1` (erfüllt) oder `0` | nachsehen, welches Kriterium ein Patient erfüllt |
| `code_matches.csv` | welche Codes in den Daten auf welches Kriterium gepasst haben, mit Tabelle, Spalte und Anzahl | prüfen, ob die Code-Suche das Richtige findet |
| `<Tabelle>_include.csv` | jede Eingabetabelle ohne die ausgeschlossenen Patienten, gleiche Spalten und Trennzeichen wie das Original (nicht bei `--no-include`) | **wird ausgeliefert** |

Spalten und Beispiele: [DETAILS_consent.md](DETAILS_consent.md#7-ausgabedateien), [DETAILS_filter.md](DETAILS_filter.md#10-ausgabedateien).

## Prüfung der ausgeschlossenen Patienten

`consent_inclusion.csv` enthält die ausgeschlossenen Patienten mit `Patient.id` vor DIMP und ihrem
Consent-Fenster. Damit lassen sich alle in den eigenen Quelldaten nachsehen.

Erwartung: Die einschließenden Diagnosen liegen vor `window_start`, `retro_applied` ist `NO`.
Dafür Quelldaten ohne Consent-Filter nehmen. Vorgehen: [DETAILS_consent.md](DETAILS_consent.md#11-prüfung-der-einschlusskriterien---inclusion-check).


## Wichtig

- Consent-Prüfung nur vor DIMP, danach passen die IDs nicht mehr.
- Patienten-IDs in allen Ausgaben sind die FHIR-Ressourcen-ID `Patient.id`, **nicht** ein Identifier
  aus `Patient.identifier` (z.B. Pseudonym oder PID). DIMP ersetzt `Patient.id` durch einen Hash, deshalb
  unterscheiden sich die IDs vor DIMP (`consent_report/`) und nach DIMP (`filter_by_crtdl/`).
- Der Filter prüft nicht Alter, Geschlecht, Wert- und Zeitfilter und `exclusionCriteria`. Im Zweifel
  bleibt ein Patient drin.
