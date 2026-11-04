# validate_consent_torch.py – Details

Ausführliche Beschreibung von `validate_consent_torch.py`. Für den schnellen Einstieg siehe [README.md](README.md).

## Inhalt

1. [Zweck](#1-zweck)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Aufruf](#3-aufruf)
4. [Parameter](#4-parameter)
5. [Berechnung des Consent-Fensters](#5-berechnung-des-consent-fensters)
6. [Audit-Dateien](#6-audit-dateien)
7. [Ausgabedateien](#7-ausgabedateien)
8. [Status pro Ressource](#8-status-pro-ressource)
9. [Auswertung](#9-auswertung)
10. [Grenzen und bekannte Effekte](#10-grenzen-und-bekannte-effekte)
11. [Prüfung der Einschlusskriterien (`--inclusion-check`)](#11-prüfung-der-einschlusskriterien---inclusion-check)

---

## 1. Zweck

Das Skript rechnet für jeden Patienten das Consent-Fenster nach, das TORCH beim Export angewendet hat,
und prüft jede exportierte Ressource dagegen. So lässt sich nachweisen, dass der Export nur Daten
enthält, die im Einwilligungszeitraum liegen.

Die Logik folgt TORCH (v1.0.3).

---

## 2. Voraussetzungen

- Python 3.8 oder neuer, nur Standardbibliothek
- TORCH-Ausgabe **vor DIMP** (`jobs/<job>/import`). Nach DIMP sind IDs und Referenzen gehasht und
  passen nicht mehr zu den Audit-Dateien.
- die CRTDL des Exports
- optional, aber empfohlen: TORCH-Audit-Dateien `<batchId>_consent.ndjson`

---

## 3. Aufruf

```bash
python3 /pfad/zu/torch_export_checks/validate_consent_torch.py \
  --data jobs/<job>/import \
  --crtdl <CRTDL.json> \
  --encounter-shift on --shift-class IMP --shift-max-days <wie TORCH> \
  --today <Exportdatum> \
  --out-dir jobs/<job>/consent_report
```

Mit Audit-Dateien zusätzlich `--consent-audit <ordner>`. Mit `--inclusion-check` zusätzlich die Prüfung der
Einschlusskriterien ([Abschnitt 11](#11-prüfung-der-einschlusskriterien---inclusion-check)).

Exit-Code: `0` = keine Verstöße, `2` = Verstöße oder unerwartete Ressourcen gefunden.

---

## 4. Parameter

| Parameter | Pflicht | Standard | Beschreibung |
|---|---|---|---|
| `--data` | ja | – | TORCH-Ausgabe (NDJSON-Dateien oder Ordner), idealerweise `jobs/<job>/import` |
| `--crtdl` | nein* | – | CRTDL, bestimmt die angeforderten Consent-Codes und ob Retro gilt |
| `--codes` | nein* | – | ohne CRTDL: Codes, z.B. `8,6,45,46` |
| `--consent-audit` | nein | – | TORCH-Audit-Dateien `<batchId>_consent.ndjson` (Dateien oder Ordner) |
| `--encounter-shift` | nein | `unknown` | `on`/`off`/`unknown`, wie `TORCH_ENABLE_ENCOUNTER_SHIFT` |
| `--shift-max-days` | nein | `7` | wie `TORCH_ENCOUNTER_SHIFT_MAX_DAYS`, `-1` = ohne Grenze (TORCH < 1.0.3) |
| `--shift-class` | nein | `IMP` | Encounter-Klasse für den Shift, `any` für TORCH < 1.0.3 |
| `--type-to-consent` | nein | eingebaut | eigene `type_to_consent.json` von TORCH |
| `--today` | nein | heute | Exportdatum, für die Prüfung von `.8` |
| `--out-dir` | nein | `consent_report` | Ausgabeordner |
| `--inclusion-check` | nein | aus | Einschlusskriterien der CRTDL im Export prüfen, braucht `--crtdl` ([Abschnitt 11](#11-prüfung-der-einschlusskriterien---inclusion-check)) |

\* Ohne `--crtdl` und `--codes` nimmt das Skript `.8` + `.6` ohne Retro an.

**`--encounter-shift unknown`** rechnet beide Varianten. Ressourcen, die nur mit Shift im Fenster liegen,
bekommen dann den Status `OK_ONLY_WITH_SHIFT`.

---

## 5. Berechnung des Consent-Fensters

1. **Codes aus der CRTDL:** Nur Kriterien mit `context.code = Einwilligung` zählen. Die UND/ODER-Verknüpfung
   wird ignoriert. `.8` und `.6` müssen beide vorkommen. `.45`/`.46` wirken nur, wenn sie in der CRTDL stehen.
2. **Consent-Ressourcen:** nur `status = active`, nur Provisionen mit taggenauem Zeitraum (Beginn **und** Ende).
3. **Encounter-Shift:** Der Beginn einer `.6`-Permit-Provision wird auf den Beginn eines stationären
   Aufenthalts (`class = IMP`) vorgezogen, wenn die Einwilligung während dieses Aufenthalts gegeben wurde.
   Seit TORCH 1.0.3 nur, wenn der Aufenthalt höchstens `--shift-max-days` Tage vor der Einwilligung begann.
   Nur Encounter mit Beginn und Ende zählen.
4. **Retro (`.45`/`.46`):** Überschneidet ein Retro-Permit das `.6`-Permit **derselben** Consent-Ressource,
   wird das Fenster bis 1900-01-01 zurück erweitert. Retro-Denies derselben Ressource werden abgezogen.
5. **Mehrere Consent-Ressourcen:** chronologisch zusammengefasst. Permits zählen nur aus Ressourcen mit
   vollständigem Paket (`.6` und `.8` als Permit). Denies werden abgezogen.
6. **Gate:** Das Exportdatum muss im `.8`-Zeitraum liegen, sonst wird der Patient ausgeschlossen.
7. **Datenfenster:** Schnitt der `.6`-Zeiträume.
8. **Ressourcen:** Erlaubt ist eine Ressource, wenn ihr Datumsfeld (laut `type_to_consent.json`, z.B.
   `Condition.recordedDate`, `Encounter.period`) taggenau ist und vollständig im Fenster liegt.
   Typen ohne Datumsfeld (z.B. `Medication`) sind immer erlaubt.

---

## 6. Audit-Dateien

| | mit Audit (`--consent-audit`) | ohne Audit |
|---|---|---|
| Consent-Ressourcen | genau die, die TORCH genutzt hat | aus dem Export (nur wenn die CRTDL eine Consent-Gruppe hat) |
| Encounter für den Shift | alle, die TORCH genutzt hat | nur die exportierten |
| Ergebnis | exakt | eingeschränkt, ggf. Status `UNCLEAR_SHIFT` |

Ohne Audit funktioniert die Prüfung trotzdem meist gut, weil der stationäre Aufenthalt, der den Shift
auslöst, durch den Shift selbst im Fenster liegt und damit exportiert wird.

**Audit-Dateien von TORCH holen:** TORCH schreibt pro Batch eine Datei `<batchId>_consent.ndjson` mit den
Consent- und Encounter-Ressourcen, die es für die Consent-Berechnung genutzt hat. Sie stehen **nicht** im
`output` des `$extract-data`-Status, sondern in der Task des Jobs:

```bash
curl -s http://<torch-host>/fhir/Task/<jobId>
```

Im Feld `output` stehen Einträge mit `"type": {"text": "Consent audit NDJSON"}` und der URL der Datei in
`valueUrl`, z.B. `http://<fileserver>/<jobId>/<batchId>_consent.ndjson`. Die Dateien liegen im selben
Ergebnisordner wie die Batch-Dateien des Jobs, also unter `TORCH_RESULTS_DIR/<jobId>/` (im Docker-Setup
das gemountete Ergebnis-Volume). Von dort oder über die URLs in einen Ordner kopieren und mit
`--consent-audit <ordner>` übergeben.

Ohne Consent-Kriterien in der CRTDL schreibt TORCH keine Audit-Dateien. Ob die eigene TORCH-Version sie
schreibt, zeigt die Task.

Quellen:
[TORCH API](https://medizininformatik-initiative.github.io/torch/api/api.html),
[TORCH Task API](https://medizininformatik-initiative.github.io/torch/api/task-api.html),
[TORCH Configuration](https://medizininformatik-initiative.github.io/torch/configuration.html) (`TORCH_RESULTS_DIR`, `TORCH_OUTPUT_FILE_SERVER_URL`).

---

## 7. Ausgabedateien

Alle Dateien landen in `--out-dir`, die CSVs mit Trennzeichen `,`.

**`consent_summary.md`** – die Zusammenfassung, als Erstes lesen. Enthält nur Zahlen, keine IDs:

- Einstellungen des Laufs (Consent-Codes, Retro, Shift, Exportdatum) und Hinweise, z.B. fehlende Audit-Dateien
- `Result`: `✅ no violations` oder die Anzahl markierter Ressourcen, darunter die Anzahl pro Status
- `Status per resource type`: dieselben Zahlen pro Ressourcentyp
- `Patients`: wie viele Patienten ein gültiges Fenster haben, mit Retro-Erweiterung, mit Shift, größter Shift in Tagen
- `Inclusion check` (nur mit `--inclusion-check`): wie viele Patienten die Einschlusskriterien im Export
  nicht erfüllen

**`consent_resources.csv`** – eine Zeile pro exportierter Ressource. Hier sieht man Verstöße im Einzelnen.

| Spalte | Bedeutung |
|---|---|
| `patient_id` | `Patient.id` vor DIMP, leer bei Ressourcen ohne Patientenbezug |
| `file` | NDJSON-Datei, aus der die Ressource stammt |
| `resource_type` / `resource_id` | Typ und ID der Ressource |
| `consent_field` | Datumsfeld, das TORCH für die Prüfung nutzt, z.B. `Condition.recordedDate` |
| `date_period` | Datum bzw. Zeitraum aus diesem Feld |
| `status` | Ergebnis der Prüfung, siehe [Abschnitt 8](#8-status-pro-ressource) |
| `note` | Erläuterung, z.B. das Fenster bei einem Verstoß |

Typische Nutzung: nach `status` mit `VIOLATION_` oder `UNEXPECTED_` filtern.

**`consent_patients.csv`** – eine Zeile pro Patient mit seinem Consent-Fenster. Damit lässt sich für
einen Patienten nachvollziehen, welcher Zeitraum exportiert werden durfte.

| Spalte | Bedeutung |
|---|---|
| `patient_id` | `Patient.id` vor DIMP |
| `status` | `OK` = gültige Einwilligung, `VIOLATION_PATIENT_WITHOUT_VALID_CONSENT` = hätte ganz ausgeschlossen werden müssen, `NOT_CHECKABLE_NO_CONSENT` = keine Consent-Daten |
| `consents_total` / `consents_discarded` | Anzahl Consent-Ressourcen und welche TORCH nicht nutzt (z.B. nicht `active`) |
| `window_applied` | **das Fenster, das TORCH angewendet hat**, Format `von..bis`, mehrere Zeiträume mit `;` getrennt (z.B. nach einem Widerruf) |
| `window_no_retro_no_shift` / `window_no_shift` / `window_with_shift` | Fenster in den einzelnen Rechenstufen, um zu sehen, was Retro und Shift ausmachen |
| `retro_applied` | `YES`, wenn das Fenster durch `.45`/`.46` bis 1900 erweitert wurde |
| `shift_applied` / `shift_days_max` / `shift_details` | ob, um wie viele Tage und durch welchen Encounter der Beginn vorgezogen wurde |
| `encounters_for_shift` | Anzahl stationärer Encounter, die für den Shift in Frage kamen |
| `gate_8_merged` / `gate_today_ok` | `.8`-Zeitraum und ob das Exportdatum darin liegt |
| `exclusion_reason` | warum ein Patient hätte ausgeschlossen werden müssen |
| `resources` / `flagged_resources` | Anzahl exportierter und markierter Ressourcen des Patienten |

**`consent_inclusion.csv`** – nur mit `--inclusion-check`: die Patienten, die die Einschlusskriterien im
Export nicht erfüllen, mit `Patient.id` vor DIMP und Fenster. Spalten und Nutzung in
[Abschnitt 11](#11-prüfung-der-einschlusskriterien---inclusion-check).

---

## 8. Status pro Ressource

| Status | Bedeutung |
|---|---|
| `OK` | im `.6`-Fenster (ohne Shift, ohne Retro) |
| `OK_RETRO` | nur durch die Retro-Erweiterung im Fenster |
| `OK_ENCOUNTER_SHIFT` | nur durch den Encounter-Shift im Fenster |
| `OK_ONLY_WITH_SHIFT` | nur mit Shift im Fenster, Einstellung unbekannt |
| `OK_NO_DATE_CHECK` | Typ ohne Datumsfeld, oder die Consent-Ressource selbst |
| `CORE_NOT_FILTERED` | Ressource ohne Patientenbezug (z.B. `core.ndjson`) |
| `TORCH_GENERATED` | von TORCH erzeugt (Provenance) |
| `NO_CONSENT_FILTER` | CRTDL ohne Consent-Kriterien |
| `UNCLEAR_SHIFT` | vor dem Fenster, ein Shift könnte es erklären, Encounter fehlen (Audit nutzen) |
| `NOT_CHECKABLE_NO_CONSENT` | keine Consent-Daten für den Patienten |
| `VIOLATION_OUTSIDE_WINDOW` | **außerhalb** des Fensters, das TORCH hätte anwenden müssen |
| `VIOLATION_PATIENT_WITHOUT_VALID_CONSENT` | Patient hätte ganz ausgeschlossen werden müssen |
| `UNEXPECTED_NO_DAY_PRECISION_DATE` | Datum fehlt oder nicht taggenau, TORCH hätte die Ressource verworfen |
| `UNEXPECTED_TYPE_NOT_MAPPED` | Typ fehlt in `type_to_consent.json`, TORCH hätte ihn verworfen |

---

## 9. Auswertung

1. **`consent_summary.md`:** Steht dort `✅ no violations`, liegt alles Exportierte im berechneten Fenster.
2. **`VIOLATION_*` / `UNEXPECTED_*`:** in `consent_resources.csv` nach Status filtern und Einzelfälle ansehen.
3. **`OK_ONLY_WITH_SHIFT`:** zeigt, dass TORCH mit Shift lief. Dann `--encounter-shift on` setzen.
4. **Einzelner Patient:** in `consent_patients.csv` die Zeile mit seiner `Patient.id` ansehen.

---

## 10. Grenzen und bekannte Effekte

- **Offene Encounter (ohne `period.end`) werden von TORCH bei aktiver Consent-Prüfung nicht exportiert.**
  Ressourcen, die auf sie verweisen (Medikation, Diagnosen, Prozeduren), werden trotzdem exportiert,
  ihre Encounter-Referenz wird maskiert. Betrifft vor allem Daten kurz vor dem Exportdatum.
- Ressourcen ohne taggenaues Datum (z.B. `recordedDate` nur `2021-05`) verwirft TORCH.
- Das Skript prüft nur, was exportiert wurde. Ob TORCH etwas **zu Unrecht weggelassen** hat, sieht es nicht.
- Die Kohortenauswahl von TORCH berücksichtigt das Consent-Fenster nicht. Dafür gibt es den
  [filter_by_crtdl.py](DETAILS_filter.md) und `--inclusion-check`.

---

## 11. Prüfung der Einschlusskriterien (`--inclusion-check`)

**Wozu:** `filter_by_crtdl.py` schließt Patienten aus, deren einschließende Daten nicht im Export stehen.
Erwartet ist, dass diese Daten vor dem Consent-Fenster liegen. Das lässt sich nach DIMP nicht mehr
in den Quelldaten nachsehen, weil die IDs gehasht sind. `--inclusion-check` macht dieselbe Prüfung
vor DIMP und liefert die `Patient.id` der betroffenen Patienten mit ihrem Consent-Fenster.

**Was passiert:**

1. Die Einschlusskriterien werden mit `filter_by_crtdl.py` aus der CRTDL gelesen (gleiche Funktion,
   gleiche Regeln: hierarchische Code-Suche, Consent-, Alters- und Geschlechtskriterien übersprungen).
   `filter_by_crtdl.py` muss deshalb im selben Ordner liegen.
2. Pro Patient werden alle Codes der exportierten Ressourcen gesammelt: `code.coding`,
   `medicationCodeableConcept.coding` und die Codes der über `medicationReference` verknüpften
   Medication.
3. Ein Code zählt für ein Kriterium, wenn er passt **und** das Codesystem stimmt (ICD `C07` ist nicht
   ATC `C07`). Verglichen wird nur der letzte Teil der System-URL, `.../dimdi/icd-10-gm` und
   `.../bfarm/icd-10-gm` gelten als gleich.
4. Patienten, die nicht alle Gruppen erfüllen, kommen mit Consent-Fenster in `consent_inclusion.csv`,
   die Anzahl in den Abschnitt `Inclusion check` von `consent_summary.md`.

**Ausgabe `consent_inclusion.csv`:**

| Spalte | Bedeutung |
|---|---|
| `patient_id` | FHIR-Ressourcen-ID `Patient.id` vor DIMP, wie TORCH sie exportiert. Nicht ein Identifier aus `Patient.identifier`. |
| `unmet_groups` | nicht erfüllte Einschlussgruppen (Nummerierung wie in `consent_summary.md`) |
| `consent_status` | Status des Patienten (wie in `consent_patients.csv`) |
| `window_applied` | angewendetes Fenster, ggf. mehrere Zeiträume |
| `window_start` / `window_end` | frühester Beginn / spätestes Ende des Fensters, leer ohne gültiges Fenster |
| `retro_applied` / `shift_applied` | wie in `consent_patients.csv` |

**Prüfung in den Quelldaten:** Mit `consent_inclusion.csv` lässt sich für alle betroffenen Patienten
nachsehen, wo ihre einschließenden Daten in den Quelldaten liegen. Wie das geht, hängt vom Standort ab
(Datenbank, Tabellen, ob `Patient.id` dort gespeichert ist). Das Vorgehen:

1. Die Patienten aus `consent_inclusion.csv` (`patient_id`, `window_start`, `window_end`) in den
   Quelldaten suchen. Liegt dort nur die Original-ID, muss die Zuordnung zu `Patient.id` so nachgebaut
   werden, wie sie im eigenen ETL entsteht.
2. Auf die einschließenden Codes der CRTDL einschränken (welche im Export gefunden wurden, zeigt
   `code_matches.csv` von `filter_by_crtdl.py`).
3. Das Diagnosedatum mit dem Fenster vergleichen: vor `window_start`, im Fenster oder nach `window_end`.

**Welche Quelldaten:** Die Prüfung muss auf Quelldaten laufen, die **nicht** nach Einwilligung gefiltert
sind. Gesucht werden ja gerade Diagnosen außerhalb des Consent-Fensters. In einem System mit nur
consentierten Daten fehlen sie, die Patienten tauchen dann im Ergebnis gar nicht auf.

**Erwartung:**

- Alle Treffer `vor Fenster`, `retro_applied = NO`: Der Ausschluss ist korrekt, die Diagnose liegt vor
  der Einwilligung.
- Treffer `IM FENSTER`: Die Diagnose hätte exportiert werden müssen. Ursache suchen (Mapping,
  Datumsfeld nicht taggenau, Code im Export anders kodiert).
- Patient ohne Treffer: Das einschließende Kriterium steht in einer anderen Tabelle (Prozedur,
  Medikation) oder wurde über einen Code gefunden, nach dem nicht gesucht wurde.
- `window_start` leer: Patient ohne gültiges Consent-Fenster, siehe `consent_patients.csv`.

**Abweichung zur Anzahl von `filter_by_crtdl.py`:** Kleine Unterschiede sind möglich:

- Referenztabellen (`includeReferenceOnly`, z.B. `Primärdiagnose`) schließt der Filter von der Suche aus.
  Im NDJSON sind das normale Conditions und werden mit durchsucht. Die Consent-Prüfung findet dann
  eher weniger Patienten.
- Der Filter sucht in den CSVs ohne Codesystem, die Consent-Prüfung mit. Die Consent-Prüfung findet
  dann eher mehr Patienten.
