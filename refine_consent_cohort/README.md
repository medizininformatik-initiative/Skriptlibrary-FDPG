# CRTDL-Filter

Ein Python-Skript, das die Einschlusskriterien einer CRTDL-JSON auf einen Ordner
mit CSV-Tabellen anwendet. Es ermittelt pro Patient, welche Kriterien erfüllt sind,
schließt Patienten nach UND/ODER-Logik aus und erzeugt bereinigte Tabellen.

## Voraussetzungen

- Python 3.8 oder neuer
- Keine externen Bibliotheken (nur Standardbibliothek: `csv`, `json`, `os`, `re`, `argparse`)

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

Hilfe anzeigen: `python crtdl_filter.py --help`

## Was das Skript tut

1. **CRTDL einlesen:** Die Einschlusskriterien stehen unter `cohortDefinition.inclusionCriteria`.
   Consent- und Demografie-Kriterien (Einwilligung, Alter, Geschlecht) werden erkannt und übersprungen.
   Das Skript gibt die berücksichtigten Kriterien aus.
2. **CSV-Ordner einlesen:** Alle `.csv`-Dateien werden geladen (UTF-8 mit oder ohne BOM, sonst Latin-1).
   Bereits erzeugte `*_include.csv` werden ignoriert.
3. **Codes suchen:** Jeder Code wird exakt (ohne Groß-/Kleinschreibung zu verändern, nach Entfernen von
   Leerzeichen) in allen Zellen gesucht. Das Skript gibt für jeden Code Tabelle und Spalte aus.
   Codes ohne Treffer werden gemeldet.
4. **Patienten zuordnen:**
   - Tabellen mit Patientenbezug: Die Patienten-ID steht in der Spalte `patient` oder `subject`.
     In der Patientenressource (Dateiname enthält „patient“) steht sie in der Spalte `id`.
   - Medikation: Ein Code aus der Medikations-Kerntabelle gilt für alle Patienten, deren Medikationsreferenz
     (Spalten mit `Medicationreference`) auf die jeweilige Medication-ID verweist.
5. **Matrix erstellen:** Pro Patient und Kriterium wird `1` (erfüllt) oder `0` (nicht erfüllt) vermerkt.
6. **Ausschluss bestimmen:** Ein Patient wird ausgeschlossen, wenn in einer UND-Gruppe alle Kriterien `0` sind.
7. **Dateien schreiben:** Die Ergebnisdateien werden im Ausgabeordner abgelegt.

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
- die Fundstellen jedes Codes (Tabelle / Spalte) bzw. „NICHT GEFUNDEN“,
- die Anzahl der Patienten und Zeilen je Datei.

## Hinweise und Grenzen

- Referenzierte Fälle und referenzierte Medikation (Dateien mit „referenz“ im Namen) werden weder als Kriterium
  geprüft noch als Patientenquelle genutzt. Sie werden aber nach Patienten gefiltert, wenn diese ausgeschlossen sind.
- Ein Code ohne Treffer führt dazu, dass das zugehörige Kriterium für alle Patienten `0` ist. Steht er in einer UND-Gruppe,
  werden damit alle Patienten ausgeschlossen. Die Konsolenausgabe weist darauf hin.
- Die Medikationsverknüpfung ist implementiert, wurde aber nur mit Testdaten geprüft, die keine Medikationscodes enthalten.
- Die Spaltenerkennung für Patienten sucht nur nach den oben genannten Namen. Abweichende Spaltennamen
  musst du mit `--patient-column` angeben.

