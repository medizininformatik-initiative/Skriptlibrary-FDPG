# CRTDL-Filter

Ein Python-Skript, das die Einschlusskriterien einer CRTDL-JSON auf einen Ordner
mit CSV-Tabellen anwendet. Es ermittelt pro Patient, welche Kriterien erfüllt sind,
schließt Patienten nach UND/ODER-Logik aus und erzeugt bereinigte Tabellen.

## Voraussetzungen

- Python 3.8 oder neuer
- Keine externen Bibliotheken (nur Standardbibliothek: `csv`, `json`, `os`, `re`, `argparse`, `collections`)

## Aufruf

```bash
python crtdl_filter.py --crtdl CRTDL_json.json --csv-dir ./csv --out-dir ./output
```

### Parameter

| Parameter | Pflicht | Standard | Beschreibung |
|---|---|---|---|
| `--crtdl` | ja | – | Pfad zur CRTDL-JSON |
| `--csv-dir` | ja | – | Ordner mit den CSV-Dateien |
| `--out-dir` | nein | `output` | Ausgabeordner (wird bei Bedarf angelegt) |
| `--patient-column` | nein | automatisch | Name der Patienten-Spalte, falls nicht `patient`/`subject` bzw. Spalte `id` in der Patientenressource |
| `--patient-id-regex` | nein | `^(?:[A-Za-z]+/)?([^/]+?)(?:/_history/.*)?$` | Regulärer Ausdruck, Gruppe 1 = Patienten-ID |
| `--medication-core` | nein | `MII_PR_Medikation_Medication` | Dateiname (ohne `.csv`) der Medikations-Kerntabelle |
| `--exclude-tables-containing` | nein | `referenz` | Tabellen, deren Dateiname diesen Text enthält, werden nicht als Kriterium geprüft |
| `--exact-only` | nein | aus | Schaltet den Präfix-Match für ICD-10-Codes ab. Dann zählen nur exakte Code-Treffer (Verhalten der Vorgängerversion) |

Hilfe anzeigen: `python crtdl_filter.py --help`

## Was das Skript tut

1. **CRTDL einlesen:** Die Einschlusskriterien stehen unter `cohortDefinition.inclusionCriteria`.
   Consent- und Demografie-Kriterien (Einwilligung, Alter, Geschlecht) werden erkannt und übersprungen.
   Das Skript gibt die berücksichtigten Kriterien aus. Zu jedem Kriterium wird außerdem das Codesystem
   (`system`) jedes Codes gemerkt, da davon das Matching-Verhalten abhängt.
2. **CSV-Ordner einlesen:** Alle `.csv`-Dateien werden geladen (UTF-8 mit oder ohne BOM, sonst Latin-1).
   Bereits erzeugte `*_include.csv` werden ignoriert.
3. **Codes suchen:** Jeder Code wird in allen Zellen gesucht (Leerzeichen am Rand werden entfernt,
   Groß-/Kleinschreibung bleibt unverändert). Ob ein Code exakt oder als Präfix gesucht wird, hängt vom
   Codesystem ab (siehe Abschnitt „Matching von Codes“). Das Skript gibt für jeden Code Tabelle, Spalte
   und die tatsächlich gefundenen Werte aus. Codes ohne Treffer werden als „NICHT GEFUNDEN“ gemeldet.
4. **Patienten zuordnen:**
   - Tabellen mit Patientenbezug: Die Patienten-ID steht in der Spalte `patient` oder `subject`.
     In der Patientenressource (Dateiname enthält „patient“) steht sie in der Spalte `id`.
   - Medikation: Ein Code aus der Medikations-Kerntabelle gilt für alle Patienten, deren Medikationsreferenz
     (Spalten mit `Medicationreference`) auf die jeweilige Medication-ID verweist.
5. **Matrix erstellen:** Pro Patient und Kriterium wird `1` (erfüllt) oder `0` (nicht erfüllt) vermerkt.
6. **Ausschluss bestimmen:** Eine Gruppe ist erfüllt, sobald mindestens ein Kriterium darin 1 ist. Ein Patient wird ausgeschlossen, wenn mindestens eine Gruppe nicht erfüllt ist, also wenn alle Kriterien dieser Gruppe 0 sind.
7. **Dateien schreiben:** Die Ergebnisdateien werden im Ausgabeordner abgelegt.

## Matching von Codes

Die Suche unterscheidet zwei Modi:

- **Präfix-Match (Standard für ICD-10-Codes):** Ein Kriterium mit dem Code `R26` findet auch die
  Unterkategorien `R26.1`, `R26.10` und `R261` (ohne Punkt). Ein Kriterium `R26.1` findet `R26.1`
  und dessen Unterkategorien, aber nicht `R26.2`.
- **Exakt (alle anderen Codesysteme, z. B. SNOMED CT, LOINC, OPS):** Nur identische Werte zählen.
  Diese Systeme sind nicht hierarchisch, ein Präfix-Match würde falsche Treffer erzeugen.

Ob ein Code als ICD-10 gilt, wird am Feld `system` des `termCode` erkannt: Enthält es `icd-10` oder
`icd10` (z. B. `http://fhir.de/CodeSystem/bfarm/icd-10-gm`), wird der Präfix-Match angewendet.

Technisch entspricht der Präfix-Match für einen Code `X` dem Muster `^X(?:\.?[0-9A-Za-z]+)?$`.

Beispiel für die Konsolenausgabe:

```
K1 R26: Diagnose / Condition_code_codingIcd10gm_code | gefundene Werte: R26 (1x), R26.1 (1x), R26.2 (1x)
K2 R26.1: Diagnose / Condition_code_codingIcd10gm_code | gefundene Werte: R26.1 (1x)
```

## Logik der Kriterien

- Die **äußere Liste** der `inclusionCriteria` ist eine **UND-Verknüpfung** von Gruppen.
- Die **innere Liste** einer Gruppe ist eine **ODER-Verknüpfung** von Kriterien.
- Mehrere `termCodes` innerhalb eines Kriteriums gelten ebenfalls als ODER.
- Ein Patient fällt heraus, sobald in einer Gruppe **alle** Kriterien `0` sind.

## Ausgabedateien

| Datei | Inhalt |
|---|---|
| `Inclusion_Criteria_Matches.csv` | Erste Spalte `patientId`, danach je Kriterium eine Spalte mit `1`/`0`. Trennzeichen `;`. |
| `to-be-excluded.csv` | Eine Spalte `patientId` mit allen ausgeschlossenen Patienten. |
| `<Originaldatei>_include.csv` | Je Eingabedatei eine Kopie ohne Zeilen ausgeschlossener Patienten. Trennzeichen `;`. |

Tabellen ohne Patientenbezug (z. B. `MII_PR_Medikation_Medication`) werden unverändert kopiert,
da sich ihre Zeilen keinem Patienten zuordnen lassen.

Die Konsole zeigt zusätzlich:
- die berücksichtigten und ausgeschlossenen Kriterien,
- die Fundstellen jedes Codes (Tabelle / Spalte), die gefundenen Werte bzw. „NICHT GEFUNDEN“,
- die Anzahl der Patienten und Zeilen je Datei.

## Hinweise und Grenzen

- Der Präfix-Match ist breit: Ein Kriterium `R2` würde auch `R26`, `R27` usw. treffen. Kriterien sollten
  deshalb möglichst genau gewählt werden (z. B. Kategorie-Ebene wie `R26`, nicht Kapitel-Ebene).
- Ein Präfix-Match greift nur bei ICD-10-Codes. Ob das gewünscht ist, lässt sich mit `--exact-only` steuern.
- Referenzierte Fälle und referenzierte Medikation (Dateien mit „referenz“ im Namen) werden weder als Kriterium
  geprüft noch als Patientenquelle genutzt. Sie werden aber nach Patienten gefiltert, wenn diese ausgeschlossen sind.
- Ein Code ohne Treffer führt dazu, dass das zugehörige Kriterium für alle Patienten `0` ist. Steht er in einer UND-Gruppe,
  werden damit alle Patienten ausgeschlossen. Die Konsolenausgabe weist darauf hin.
- Die Medikationsverknüpfung ist implementiert, wurde aber nur mit Testdaten geprüft, die keine Medikationscodes enthalten.
- Die Spaltenerkennung für Patienten sucht nur nach den oben genannten Namen. Abweichende Spaltennamen
  musst du mit `--patient-column` angeben.
- Das Matching prüft jede Zelle gegen jeden Code per Regex. Für sehr große Tabellen kann das langsam werden.

## Testdaten

Im Ordner `refine_consent_cohort_v2` liegen eine Test-CRTDL (`CRTDL_test.json`) und ein Diagnose-Datensatz
(`Diagnose_mit_R26_Testfaellen.csv`) mit drei Testfällen:
- Patient 11: R26 (erfüllt K1, nicht K2)
- Patient 26: R26.1 (erfüllt K1 und K2)
- Patient 27: R26.2 (erfüllt K1 als Unterkategorie von R26, nicht K2)
