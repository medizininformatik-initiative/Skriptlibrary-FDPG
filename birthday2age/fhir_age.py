#!/usr/bin/env python3
"""Ersetzt FHIR Patient.birthDate (YYYY | YYYY-MM | YYYY-MM-DD) durch das Alter
zum Stichtag. Der Geburtstag gilt als gehabt, solange er nicht nachweislich
spaeter im Jahr liegt."""

import csv
import sys

REF_YEAR, REF_MONTH = 2026, 9   # Stichtag September 2026

IN_COL = "Patient_birthDate"
OUT_COL = "Patient_Age"


def age_at_ref(birth_date: str):
    """Alter zum Stichtag. None bei leerem/unplausiblem Wert."""
    s = (birth_date or "").strip()
    if not s:
        return None

    parts = s.split("-")
    try:
        year = int(parts[0])
    except ValueError:
        return None
    if not 1900 <= year <= REF_YEAR:
        return None

    age = REF_YEAR - year
    # Nur bei bekanntem Geburtsmonat nach dem Stichtag ist der Geburtstag
    # nachweislich noch nicht gewesen. Reine Jahresangaben bleiben unveraendert.
    if len(parts) > 1 and int(parts[1]) > REF_MONTH:
        age -= 1
    return age


def main(src, dst):
    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = [OUT_COL if c == IN_COL else c for c in reader.fieldnames]
        rows = []
        for r in reader:
            r[IN_COL] = age_at_ref(r[IN_COL])
            rows.append({(OUT_COL if k == IN_COL else k): v for k, v in r.items()})

    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    ok = [r[OUT_COL] for r in rows if r[OUT_COL] is not None]
    print(f"{len(rows)} Zeilen, {len(ok)} mit Alter (min {min(ok)}, max {max(ok)})"
          if ok else f"{len(rows)} Zeilen, kein Alter")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
