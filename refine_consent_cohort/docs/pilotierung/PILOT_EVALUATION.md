# Pilot-Evaluation `refine_consent_cohort` (Standort: Magdeburg)

## Ausgangslage

TORCH wählt die Kohorte über alle Daten eines Patienten aus, exportiert aber nur Daten aus dem
Einwilligungszeitraum. Liegen die einschließenden Diagnosen außerhalb, ist der Patient in der
Ausleitung, die Diagnose aber nicht. Das Skript soll solche Patienten nachträglich aus den CSV-Tabellen
entfernen.

## Pilot

Getestet an einer vollständigen Ausleitung (**VERT-CARE**, Einschlusskriterien: ICD-Codes, Consent mit
Retro-Nutzung und Encounter-Shift).

**Ergebnis:**

- Alle Einschlusskriterien werden gefunden. Die hierarchische Suche greift bei Codes ohne
  Nachkommastelle (z.B. `R26` → `R26.0`–`R26.8`, `G43` → `G43.0`–`G43.9`), da in den Daten endständig
  kodiert wird.
- Consent- und Alterskriterien werden erkannt und übersprungen.
- Die Referenztabelle `Primärdiagnose` (`includeReferenceOnly`) wird erkannt, nicht durchsucht, aber
  mitgefiltert.
- Die Patientenmenge kommt aus der Patiententabelle.
- Weniger als 5 % der Patienten werden ausgeschlossen.
- Die Consent-Prüfung (`validate_consent_torch.py`) zeigt: Alle exportierten Ressourcen liegen im
  Consent-Fenster, das nach der TORCH-Logik nachgerechnet wurde. Keine Verstöße.
- Die Prüfung der Einschlusskriterien vor DIMP (`--inclusion-check`) findet dieselben Patienten wie
  der Filter nach DIMP. Alle ohne Retro-Erweiterung.
- Gegen die Quelldaten geprüft: Bei allen ausgeschlossenen Patienten liegen die einschließenden
  Diagnosen vor dem Consent-Fenster, keine im Fenster. Der Ausschluss ist korrekt.

**Consent-Prüfung:**

- Gelaufen ohne Audit-Dateien, mit Encounter-Shift (Klasse `IMP`, Grenze wie in TORCH konfiguriert).
- Keine Verstöße. Ein Großteil der Patienten hat eine Retro-Einwilligung, ihr Fenster reicht bis 1900
  zurück. Bei einem kleinen Teil wurde der Beginn durch einen stationären Aufenthalt vorgezogen, die
  Grenze für den Shift wurde nie überschritten.
- Laufende Fälle: TORCH exportiert nur abgeschlossene Encounter (mit `period.end`). Medikationsgaben
  laufender Fälle werden trotzdem exportiert, ihre Encounter-Referenz ist maskiert.

## Änderungen

- Ordner `refine_consent_cohort` ([README](../../README.md)) mit zwei Skripten:
  - `filter_by_crtdl.py` (Version 2.0, vorher `crtdl_filter.py`): Verarbeitung im Streaming,
    Erkennung von Kodierung und Trennzeichen, OPS-Bereiche, ATC über die Medikations-Kerntabelle,
    Referenztabellen werden mitgefiltert, Prüflauf mit `--no-include`, exakte Suche mit `--exact-only`.
    Berichte heißen jetzt `to_be_excluded.csv`, `inclusion_criteria_matches.csv`, `code_matches.csv`.
  - `validate_consent_torch.py` (Consent-Prüfung vor DIMP) mit neuer Option `--inclusion-check`:
    prüft die Einschlusskriterien vor DIMP und listet die betroffenen Patienten mit ihrem
    Consent-Fenster auf. Damit lassen sich die Ausschlüsse in den eigenen Quelldaten nachprüfen.
- Neues README mit Quickstart, Details in `docs/DETAILS_filter.md` und `docs/DETAILS_consent.md`.
- Tests mit künstlichen Daten (`development/`).
- Nur Python-Standardbibliothek, Aufruf von überall per Pfad.

## Aufwand

| Tätigkeit                                                                                                 | Aufwand (Schätzung) |
|-----------------------------------------------------------------------------------------------------------|---------------------|
| Pilotierung und Validierung (Ausführen, Consent-Prüfung, Abgleich mit Quelldaten, README & Dokumentation) | ca. 4 Stunden       |

## Hinweise

- Für den produktiven Betrieb ist die Consent-Prüfung (`validate_consent_torch.py`) optional, aber
  empfohlen. Für die Filterung mit `filter_by_crtdl.py` ist sie nicht nötig. Im Pilot wurde sie genutzt,
  um die Ausschlüsse nachzuvollziehen.
- Große Teile von README und Dokumentation wurden mit KI-Unterstützung erstellt. Sie wurden quer gelesen
  und mit dem Pilot abgeglichen, einzelne Ungenauigkeiten sind trotzdem möglich. Hinweise gerne als Issue.
