# fhir_age.py

Ersetzt in einer CSV die Spalte `Patient_birthDate` (FHIR `Patient.birthDate`) durch das Alter zu einem festen Stichtag.

## Verwendung

```bash
python3 fhir_age.py input.csv output.csv
```

Nur Standardbibliothek, keine Abhängigkeiten (Python ≥ 3.7).

## Verhalten

- Akzeptiert alle drei nach FHIR erlaubten `date`-Präzisionen: `YYYY`, `YYYY-MM`, `YYYY-MM-DD`
- Die Spalte wird **an Ort und Stelle umbenannt** zu `Patient_Age`; Spaltenposition und alle übrigen Spalten bleiben unverändert
- Leere, nicht-numerische oder unplausible Werte (Jahr < 1900 oder > Stichtagsjahr) ergeben ein leeres Feld

## Konfiguration

Im Kopf des Skripts:

```python
REF_YEAR, REF_MONTH = 2026, 9   # Stichtag
IN_COL  = "Patient_birthDate"
OUT_COL = "Patient_Age"
```

## Rundungskonvention

Das Alter ist `REF_YEAR − Geburtsjahr`, vermindert um 1, wenn der Geburtsmonat **nachweislich** nach dem Stichtagsmonat liegt.

| Eingabe      | Stichtag 09/2026 | Begründung                                |
|--------------|------------------|-------------------------------------------|
| `1969`       | 57               | Monat unbekannt → Geburtstag gilt als gehabt |
| `1969-08`    | 57               | Geburtstag war                            |
| `1969-09`    | 57               | Gleichstand → gilt als gehabt             |
| `1969-10`    | 56               | Geburtstag noch nicht gewesen             |

## Einschränkungen

**Unschärfe ±1 Jahr bei reinen Jahresangaben.** Bei `YYYY` ist das tatsächliche Alter zum Stichtag entweder der ausgegebene Wert oder eins weniger. Für Kohortenselektion an einer Altersgrenze (z.B. „≥ 18") heißt das: Randfälle sind nicht trennscharf, und die gewählte Konvention liefert systematisch eher zu viele Treffer.

**Keine Obergrenzen-Aggregation.** Sehr hohe Alterswerte sind in einem Standort-Datensatz faktisch re-identifizierend. Vor produktivem Einsatz sollte alles ab 90 in eine Kategorie zusammengefasst werden — sonst hebt der Ausreißer die vorgelagerte Generalisierung des Geburtsdatums wieder auf.

**Stichtagsbezug.** Der berechnete Wert gilt nur für den konfigurierten Stichtag und ist nicht idempotent über Exportzeitpunkte hinweg. Ein ereignisbezogenes Alter (berechnet gegen `Encounter.period.start` o.ä.) ist für die meisten Auswertungen aussagekräftiger.
