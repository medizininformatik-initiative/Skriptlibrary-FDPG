# filter_by_crtdl.py – Details

Ausführliche Beschreibung zu Funktion und Nutzung. Für den schnellen Einstieg siehe [README.md](../README.md).

## Inhalt

1. [Hintergrund](#1-hintergrund)
2. [Voraussetzungen](#2-voraussetzungen)
3. [Aufruf](#3-aufruf)
4. [Parameter](#4-parameter)
5. [Empfohlener Ablauf](#5-empfohlener-ablauf)
6. [Ablauf im Skript](#6-ablauf-im-skript)
7. [Geprüfte Kriterien](#7-geprüfte-kriterien)
8. [Code-Suche (Hierarchie)](#8-code-suche-hierarchie)
9. [Rollen der Tabellen](#9-rollen-der-tabellen)
10. [Ausgabedateien](#10-ausgabedateien)
11. [Konsolenausgabe](#11-konsolenausgabe)
12. [Zusammenspiel mit der Consent-Prüfung](#12-zusammenspiel-mit-der-consent-prüfung)
13. [Grenzen](#13-grenzen)
14. [Tests](#14-tests)

---

## 1. Hintergrund

TORCH wählt die Kohorte über **alle** Daten eines Patienten aus. Beim Export liefert TORCH aber nur
die Daten, die im **Einwilligungszeitraum** liegen (Consent-Fenster `.6`, ggf. erweitert durch
Retro-Einwilligung oder Encounter-Shift).

Dadurch kann ein Patient in der Kohorte sein, obwohl seine **einschließende** Diagnose nicht im Export
steht, z.B.:

- Eine ältere Diagnose erfüllt das Einschlusskriterium → Patient kommt in die Kohorte
- Die Einwilligung wurde Jahre später gegeben, retrospektive Nutzung abgelehnt → Daten erst ab der Einwilligung im Export
- Die einschließende Diagnose fehlt im Export, der Patient ist trotzdem in der Ausleitung

Das Skript prüft die Einschlusskriterien noch einmal **auf den exportierten CSVs** und entfernt
Patienten, bei denen sie dort nicht erfüllt sind.

---

## 2. Voraussetzungen

- Python 3.8 oder neuer
- keine externen Bibliotheken
- geflattete CSVs eines Exports (nach DIMP), ein Ordner pro Job, z.B. `jobs/<job>/csv`
- die CRTDL, mit der der Export erzeugt wurde

---

## 3. Aufruf

Das Skript ist **von überall** aufrufbar. Alle Pfade werden relativ zum aktuellen Ordner oder absolut
angegeben, das Skript selbst braucht keinen bestimmten Arbeitsordner.

```bash
python3 /pfad/zu/refine_consent_cohort/filter_by_crtdl.py \
  --crtdl  CRTDL.json \
  --csv-dir jobs/<job>/csv \
  --out-dir jobs/<job>/filter_by_crtdl
```

---

## 4. Parameter

| Parameter | Pflicht | Standard | Beschreibung |
|---|---|---|---|
| `--crtdl` | ja | – | Pfad zur CRTDL-JSON |
| `--csv-dir` | ja | – | Ordner mit den geflatteten CSV-Dateien |
| `--out-dir` | ja | – | Ausgabeordner (wird angelegt) |
| `--no-include` | nein | aus | nur prüfen, keine `*_include.csv` schreiben |
| `--exact-only` | nein | aus | nur exakte Code-Treffer, keine Hierarchie |
| `--search-all-columns` | nein | aus | Codes in allen Spalten suchen statt nur in Spalten mit `code` im Namen |
| `--patient-column` | nein | automatisch | Name der Patienten-Spalte, falls nicht `patient`/`subject` |
| `--patient-id-regex` | nein | `Typ/`-Präfix entfernen | Regex, Gruppe 1 = Patienten-ID |
| `--medication-core` | nein | `MII PR Medikation Medication` | Name der Medikations-Kerntabelle (Leerzeichen/Unterstriche egal) |
| `--reference-tables` | nein | – | zusätzliche Referenztabellen, Komma-getrennt (siehe [9](#9-rollen-der-tabellen)) |

---

## 5. Empfohlener Ablauf

1. **Prüflauf** ohne gefilterte Tabellen:
```bash
   python3 filter_by_crtdl.py --crtdl <crtdl> --csv-dir <job>/csv --out-dir <job>/filter_by_crtdl --no-include
```
2. **Konsolenausgabe prüfen** (siehe [11](#11-konsolenausgabe)): Werden alle Kriterien gefunden?
   Ist der Anteil ausgeschlossener Patienten plausibel?
3. **Stichprobe** der ausgeschlossenen Patienten prüfen (siehe [12](#12-zusammenspiel-mit-der-consent-prüfung)).
4. **Filterlauf** ohne `--no-include`, danach die `*_include.csv` ausliefern.

---

## 6. Ablauf im Skript

1. **CRTDL lesen:** Einschlusskriterien aus `cohortDefinition.inclusionCriteria` bestimmen und nach
   Prüfbarkeit sortieren (siehe [7](#7-geprüfte-kriterien)). Gruppen mit
   `includeReferenceOnly` aus `dataExtraction` merken (Referenztabellen).
2. **CSVs lesen (1. Durchgang):** Jede Datei einmal zeilenweise lesen. Kodierung (UTF-8 mit/ohne BOM,
   sonst Latin-1) und Trennzeichen (`,` `;` Tab) werden pro Datei erkannt. Dabei:
    - Patienten-IDs sammeln,
    - in den Code-Spalten nach den Kriteriencodes suchen,
    - Medikationsreferenzen (`…medicationReference…`) den Patienten zuordnen.
3. **Medikation auflösen:** Codes aus der Medikations-Kerntabelle gelten für alle Patienten, deren
   Medikationsreferenz auf die jeweilige Medication-ID zeigt.
4. **Ausschluss bestimmen:** Ein Patient wird ausgeschlossen, wenn in mindestens einer UND-Gruppe
   kein einziges Kriterium erfüllt ist.
5. **Berichte schreiben** (siehe [10](#10-ausgabedateien)).
6. **CSVs filtern (2. Durchgang):** Jede Datei erneut lesen und ohne die Zeilen ausgeschlossener
   Patienten als `*_include.csv` schreiben. Das ursprüngliche Trennzeichen bleibt erhalten.

Die Dateien werden nie vollständig in den Speicher geladen, das Skript funktioniert also auch bei
großen Exporten.

---

## 7. Geprüfte Kriterien

| Kriterium | Behandlung |
|---|---|
| Diagnose, Prozedur, Labor, Medikation | Code wird geprüft |
| Einwilligung | übersprungen, das macht TORCH |
| Alter, Geschlecht | nicht prüfbar, die ganze ODER-Gruppe wird übersprungen |
| Wertfilter (z.B. Laborwert > x), Zeiteinschränkung | nur der Code wird geprüft, nicht Wert oder Zeitraum |
| `exclusionCriteria` | nicht ausgewertet |

Dadurch schließt das Skript im Zweifel eher zu wenige als zu viele Patienten aus.

Umsetzung: `filter_by_crtdl.py`, Funktion `parse_inclusion_groups` (ab Zeile 109).

---

## 8. Code-Suche (Hierarchie)

Wie ein Code gesucht wird, hängt vom Codesystem (`system`) im `termCode` ab:

| System | Regel | Beispiel |
|---|---|---|
| ICD-10-GM (`icd-10`/`icd10`) | Code und Unterkategorien, mit oder ohne Punkt | `R26` → `R26`, `R26.8`, `R268`; `I67.8` → `I67.88` |
| OPS (`/ops`) | Präfix, Punkte egal | `8-93` → `8-930`, `8-931.0` |
| OPS-Bereich | `start...ende`, Grenzen eingeschlossen | `3-10...3-13` → `3-100`, `3-13x`, nicht `3-20x` |
| ATC (`atc`) | Präfix | `C07` → `C07AB02` |
| alle anderen (LOINC, SNOMED, …) | exakt | `2823-3` → nur `2823-3` |

Bei SNOMED und LOINC sieht man den Codes die Hierarchie nicht an. Steht in der CRTDL ein Oberbegriff
und in den Daten nur Unterbegriffe, findet das Skript nichts und schließt die Patienten zu Unrecht aus.
Beispiel im [README](../README.md#2-konsolenausgabe-prüfen).

Mit `--exact-only` wird überall exakt verglichen.

Gesucht wird nur in Spalten, deren Name `code` enthält (z.B. `Condition_code_codingIcd10gm_code`).
Codes in anderen Spalten, z.B. in Freitexten, zählen nicht. Mit `--search-all-columns` lässt sich das
abschalten.

---

## 9. Rollen der Tabellen

Die Tabellennamen kommen aus dem Flattening und sind vorgegeben. Das Skript erkennt die Rollen
automatisch. Beispiel VERT-CARE:

| Tabelle                                                                                                                                                                                              | Behandlung |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| `MII PR Person Patient (Pseudonymisiert)`                                                                                                                                                            | Patiententabelle, Spalte `id` ist der Patient. Bestimmt die Menge aller Patienten und wird gefiltert. |
| `MII PR Diagnose Condition`, `MII PR Prozedur Procedure`, `MII PR Medikation MedicationAdministration` / `MedicationRequest`, `MII PR Fall …`, `MII PR Labor …`, `Profile - MI-I - Consent - Einwilligung` | Spalte `patient` verweist auf den Patienten. Werden durchsucht und gefiltert. |
| `Primärdiagnose`                                                                                                                                                                                     | Referenztabelle (`includeReferenceOnly` in der CRTDL). Wird **nicht** durchsucht, die Diagnosen stehen schon in `MII PR Diagnose Condition`. Wird gefiltert. |
| `MII PR Medikation Medication`                                                                                                                                                                       | Medikations-Kerntabelle ohne Patientenbezug. Wird nach ATC-Codes durchsucht, bleibt unverändert. |

Nur wenn Namen abweichen: `--patient-column`, `--reference-tables`, `--medication-core`.

**Medikations-Kerntabelle:** ATC-Codes in `MII PR Medikation Medication` werden über `medicationReference`
den Patienten zugeordnet. Heißt die Tabelle anders, kommt die Warnung `Medikations-Kerntabelle … nicht gefunden`
mit der Liste der gelesenen Tabellen. Die Codes werden dann zwar in der Code-Suche gefunden, aber keinem
Patienten zugeordnet („Patienten pro Kriterium“ = `0`), diese Patienten werden zu Unrecht ausgeschlossen.
Abhilfe: `--medication-core "<Name der Medication-Tabelle>"`. Stehen die ATC-Codes direkt in
MedicationAdministration/MedicationRequest oder gibt es keine Medication-Ressource, wird die Kerntabelle nicht
gebraucht und die Warnung ist harmlos.

---

## 10. Ausgabedateien

Alle Dateien landen in `--out-dir`. Die Berichte haben das Trennzeichen `;`, die gefilterten Tabellen
behalten das Trennzeichen des Originals.

**`to_be_excluded.csv`** – die ausgeschlossenen Patienten.

```text
patientId;nicht_erfuellte_gruppen
<Patient.id>;1
<Patient.id>;1,2
```

| Spalte | Bedeutung |
|---|---|
| `patientId` | FHIR-Ressourcen-ID `Patient.id` **nach** DIMP (gehasht), wie in der Spalte `id` der Patiententabelle und `patient` der übrigen Tabellen. Nicht ein Identifier aus `Patient.identifier` und nicht die ID vor DIMP, daher nicht direkt in den Quelldaten auffindbar. |
| `nicht_erfuellte_gruppen` | Nummern der Einschlussgruppen ohne Treffer, kommagetrennt. Die Nummern entsprechen `Gruppe 1`, `Gruppe 2`, … in der Konsolenausgabe. |

Die Anzahl der Zeilen ist das `X` aus `Ausgeschlossen: X von Y`.

**`inclusion_criteria_matches.csv`** – für jeden Patienten, welche Kriterien er erfüllt.

```text
patientId;K1_<Bezeichnung>;K2_<Bezeichnung>;K3_<Bezeichnung>
<Patient.id>;1;0;1
<Patient.id>;0;0;1
```

Eine Spalte pro Kriterium (`K<Nummer>_<Bezeichnung>`, Nummern wie in der Konsolenausgabe), `1` = mindestens
ein passender Code, `0` = keiner. Ausgeschlossen wird, wer in einer Gruppe bei allen Kriterien `0` hat.
Nützlich, um bei einem einzelnen Patienten nachzuvollziehen, warum er drin ist oder nicht.

**`code_matches.csv`** – welche Codes in den Daten tatsächlich gefunden wurden.

```text
kriterium;crtdl_code;daten_code;tabelle;spalte;anzahl_zeilen
K1;R26;R26.0;MII PR Diagnose Condition;Condition_code_codingIcd10gm_code;<Anzahl>
K1;R26;R26.8;MII PR Diagnose Condition;Condition_code_codingIcd10gm_code;<Anzahl>
```

| Spalte | Bedeutung |
|---|---|
| `kriterium` | Kriterium aus der Konsolenausgabe |
| `crtdl_code` | Code aus der CRTDL |
| `daten_code` | Code, der in den Daten gefunden wurde, z.B. eine Unterkategorie |
| `tabelle` / `spalte` | wo er gefunden wurde |
| `anzahl_zeilen` | in wie vielen Zeilen |

Hier sieht man, ob die hierarchische Suche das Richtige findet: Jeder `daten_code` sollte fachlich zum
`crtdl_code` gehören. Ein Kriterium ohne Zeile hier ist in der Konsole `NICHT GEFUNDEN`.

**`<Tabelle>_include.csv`** – die gefilterten Tabellen, die ausgeliefert werden.

- eine Datei pro Eingabetabelle, Name wie das Original plus `_include`
- gleiche Spalten, gleiche Reihenfolge, gleiches Trennzeichen und gleiche Kodierung wie das Original
- alle Zeilen der ausgeschlossenen Patienten sind entfernt, auch in Referenztabellen wie `Primärdiagnose`
- Tabellen ohne Patientenbezug (Medikations-Kerntabelle) werden unverändert kopiert
- die Konsole zeigt pro Tabelle `behalten` und `entfernt`
- mit `--no-include` werden sie nicht geschrieben

---

## 11. Konsolenausgabe

- **Berücksichtigte Einschlusskriterien:** Gruppen und Kriterien mit Suchregel (`icd`, `ops`, `range`,
  `prefix`, `exact`). Darunter, was übersprungen wurde und warum.
- **Tabellen:** erkanntes Trennzeichen, Patienten pro Tabelle, Rolle. Bei ATC-Kriterien ggf. die Warnung zur
  Medikations-Kerntabelle (siehe [9](#9-rollen-der-tabellen)).
- **Code-Suche:** pro Code die Fundstellen und die gefundenen Codes. `NICHT GEFUNDEN` heißt meist, dass
  der Code bei allen Patienten nur vor der Einwilligung dokumentiert ist. Beispiele und Ausnahmen
  (SNOMED, LOINC) im [README](../README.md#2-konsolenausgabe-prüfen).
- **Patienten pro Kriterium** und **Ausgeschlossen: X von Y (Z %)**.

Ein hoher Anteil Ausgeschlossener ist ein Warnsignal (im Pilot lag er unter 5 %).

---

## 12. Zusammenspiel mit der Consent-Prüfung

Das Skript arbeitet auf den CSVs **nach** DIMP. Es weiß nichts über Einwilligungen, es sieht nur, ob
ein Kriterium im Export steht. Zwei Prüfungen ergänzen es:

**a) Ist der Export selbst korrekt?** `validate_consent_torch.py` ([DETAILS_consent.md](DETAILS_consent.md)) rechnet das Consent-Fenster pro
Patient nach der TORCH-Logik nach und prüft jede exportierte Ressource dagegen. Läuft auf `import/`
(vor DIMP).

```bash
python3 /pfad/zu/refine_consent_cohort/validate_consent_torch.py \
  --data jobs/<job>/import --crtdl <crtdl> \
  --encounter-shift on --shift-class IMP --shift-max-days <wie TORCH> \
  --today <Exportdatum> --out-dir jobs/<job>/consent_report \
  --inclusion-check
```

**b) Liegen die einschließenden Diagnosen der Ausgeschlossenen wirklich außerhalb des Fensters?**
Die IDs in `to_be_excluded.csv` sind `Patient.id` nach DIMP (gehasht) und lassen sich nicht direkt in den Quelldaten
suchen. Deshalb prüft die Consent-Prüfung mit `--inclusion-check` dieselben Kriterien vor DIMP, für
alle Patienten:

1. Anzahl im Abschnitt `Inclusion check` von `consent_summary.md` mit `Ausgeschlossen: X` vergleichen.
2. `consent_inclusion.csv` enthält pro Patient `Patient.id` vor DIMP, nicht erfüllte Gruppen und Consent-Fenster
   (`window_start`, `window_end`, `retro_applied`, `shift_applied`).
3. Diese Patienten in den Quelldaten (ohne Consent-Filter) nachsehen
   (Vorgehen in [DETAILS_consent.md](DETAILS_consent.md#11-prüfung-der-einschlusskriterien---inclusion-check)).

Erwartung: Die Diagnosen liegen **vor** dem Fenster, und es gibt keine Retro-Einwilligung
(`.45`/`.46` als `deny` oder nicht vorhanden). Liegt eine Diagnose **im** Fenster und fehlt trotzdem
im Export, ist das ein Hinweis auf ein anderes Problem (Mapping, DIMP, Flattening).

---

## 13. Grenzen

- Alter, Geschlecht, `exclusionCriteria`, Wert- und Zeitfilter werden nicht ausgewertet (siehe [7](#7-geprüfte-kriterien)).
- Kriterien auf Ressourcen, die die CRTDL gar nicht extrahiert, können nie gefunden werden. Das Skript
  meldet sie als `NICHT GEFUNDEN`.
- SNOMED- und LOINC-Oberbegriffe in der CRTDL werden nicht in Unterbegriffe aufgelöst (siehe [8](#8-code-suche-hierarchie)).
- Die Patientenspalte wird nur unter `patient`/`subject` bzw. `id` gesucht, sonst `--patient-column`.
- Das Skript filtert nach **Patienten**. Einzelne Ressourcen außerhalb des Consent-Fensters entfernt
  es nicht, das ist Aufgabe von TORCH.

---

## 14. Tests

**Wozu:** Die Tests prüfen, ob die Skripte noch richtig rechnen. Sie laufen auf kleinen, künstlichen
Testdaten mit wenigen ausgedachten Patienten (`p1`, `p2`, …), bei denen vorher feststeht, wer
ausgeschlossen werden muss. Die Testdaten wurden mit KI generiert und enthalten keine echten
Patientendaten. Für eine Ausleitung braucht man sie nicht.

**Wann:**

- nach jeder Änderung an `filter_by_crtdl.py` oder `validate_consent_torch.py`
- wenn man eine neue Version aus dem Repository geholt hat und sicher sein will, dass sie läuft

**Wie:** Ein Befehl, von überall aufrufbar. Die Tests finden ihre Testdaten selbst und schreiben nur in
einen temporären Ordner, nichts in die eigenen Daten.

```bash
python3 /pfad/zu/refine_consent_cohort/development/test_filter_by_crtdl.py
```

**Ergebnis:** Pro Test eine Zeile, am Ende die Zusammenfassung:

```text
test_excluded_patients (__main__.Fall1Standard.test_excluded_patients) ... ok
...
Ran 8 tests in 2.3s

OK
```

- `OK`: alles in Ordnung.
- `FAILED (failures=1)` o.ä.: Ein Ergebnis weicht von der Erwartung ab. Darüber steht, welcher Test
  und was erwartet bzw. herausgekommen ist. Meist hat eine Änderung am Skript die Code-Suche oder die
  Ausschlusslogik verändert. Dann die Änderung prüfen, bevor das Skript für eine Ausleitung genutzt wird.

**Testdaten** (`development/testdaten/`): Jeder Fall ist ein Ordner mit einer CRTDL und Daten im selben Format wie
eine echte Ausleitung.

| Fall | Inhalt | Was geprüft wird |
|---|---|---|
| `fall1_standard` | `crtdl.json`, `csv/` (Patient, Diagnose, Prozedur, Medikation, Primärdiagnose) | ICD mit/ohne Punkt (`G43.1`, `G430`), ICD-Code mit Punkt als Präfix (`I67.8` → `I67.88`), OPS-Bereich (`3-100` ja, `3-200` nein), ATC über Medikations-Kerntabelle, Code nur in Freitextspalte zählt nicht, Code nur in Referenztabelle zählt nicht, Consent/Alter übersprungen, Trennzeichen `;` bleibt erhalten |
| `fall2_sonderfaelle` | `crtdl.json`, `csv/Diagnose.csv` | ODER-Gruppe mit Alter wird übersprungen, `timeRestriction` wird ignoriert, Hinweis auf `exclusionCriteria`, Latin-1-Datei, keine Patiententabelle, `R27` passt nicht auf `R26`, `--exact-only` |
| `fall3_consent` | `crtdl.json`, `import/` (NDJSON wie TORCH-Ausgabe) | `validate_consent_torch.py --inclusion-check`: ICD-Unterkategorie, OPS-Bereich, ATC über `medicationReference` und `medicationCodeableConcept`, ICD `C07` zählt nicht als ATC `C07` |

Man kann die Skripte auch von Hand auf einen Fall loslassen, um zu sehen, wie die Ausgabe aussieht:

```bash
python3 /pfad/zu/refine_consent_cohort/filter_by_crtdl.py \
  --crtdl   /pfad/zu/refine_consent_cohort/development/testdaten/fall1_standard/crtdl.json \
  --csv-dir /pfad/zu/refine_consent_cohort/development/testdaten/fall1_standard/csv \
  --out-dir /tmp/test_filter --no-include
```

Erwartet: `p3`, `p5` und `p6` werden ausgeschlossen.

**Neuen Fall ergänzen** (z.B. nach einem Fehler in einer echten Ausleitung): Ordner unter `development/testdaten/`
mit `crtdl.json` und `csv/` anlegen, nur künstliche IDs und Daten verwenden, und in
`development/test_filter_by_crtdl.py` eine Klasse nach dem Muster der vorhandenen ergänzen.