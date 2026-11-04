#!/usr/bin/env python3
"""
Tests für filter_by_crtdl.py und validate_consent_torch.py --inclusion-check (nur Standardbibliothek).

Aufruf (von überall):
  python3 /pfad/zu/torch_export_checks/test_filter_by_crtdl.py
"""
import csv
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "filter_by_crtdl.py")
CONSENT_SCRIPT = os.path.join(HERE, "validate_consent_torch.py")
DATA = os.path.join(HERE, "testdaten")


def run(case, *extra):
    """Run the filter on a test case; return (stdout, out_dir)."""
    out = tempfile.mkdtemp(prefix="filter_by_crtdl_test_")
    cmd = [sys.executable, SCRIPT, "--crtdl", os.path.join(DATA, case, "crtdl.json"),
           "--csv-dir", os.path.join(DATA, case, "csv"), "--out-dir", out, *extra]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout, out


def excluded(out_dir):
    with open(os.path.join(out_dir, "to_be_excluded.csv"), encoding="utf-8") as fh:
        return {r["patientId"]: r["nicht_erfuellte_gruppen"] for r in csv.DictReader(fh, delimiter=";")}


class Fall1Standard(unittest.TestCase):
    """ICD/OPS/ATC hierarchy, reference table, Medication core, mixed delimiters."""

    @classmethod
    def setUpClass(cls):
        cls.stdout, cls.out = run("fall1_standard")

    def test_excluded_patients(self):
        # p3: no Betablocker (group 2); p5: OPS outside range + G43 only in a non-code column;
        # p6: G43 only in the reference table 'Primärdiagnose'
        self.assertEqual(excluded(self.out), {"p3": "2", "p5": "1", "p6": "1"})

    def test_hierarchy(self):
        self.assertIn("gefundene Codes (2): G43.1, G430", self.stdout)      # ICD with/without dot
        self.assertIn("gefundene Codes (1): I67.88", self.stdout)           # ICD code with dot as prefix
        self.assertIn("gefundene Codes (1): 3-100", self.stdout)            # OPS range, 3-200 not
        self.assertIn("gefundene Codes (1): C07AB02", self.stdout)          # ATC via Medication core

    def test_consent_and_age_skipped(self):
        self.assertIn("Nicht berücksichtigt – Consent", self.stdout)
        self.assertIn("nicht prüfbar (Alter/Geschlecht)", self.stdout)

    def test_include_keeps_delimiter_and_master_data(self):
        with open(os.path.join(self.out, "MII PR Prozedur Procedure_include.csv"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        self.assertEqual(lines, ["id;patient;Procedure_code_codingOps_code", "x1;Patient/p4;3-100"])
        with open(os.path.join(self.out, "MII_PR_Medikation_Medication_include.csv"), encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 3)                # header + 2 rows, unfiltered


class Fall2Sonderfaelle(unittest.TestCase):
    """OR group with age is skipped, time restriction ignored, latin-1, no patient table, --exact-only."""

    def test_default(self):
        stdout, out = run("fall2_sonderfaelle", "--no-include")
        self.assertIn("Gruppe übersprungen", stdout)
        self.assertIn("Zeiteinschränkung ignoriert", stdout)
        self.assertIn("exclusionCriteria werden nicht ausgewertet", stdout)
        self.assertEqual(excluded(out), {"p2": "1"})                        # R27 does not match R26
        self.assertFalse(any(f.endswith("_include.csv") for f in os.listdir(out)))

    def test_exact_only(self):
        _, out = run("fall2_sonderfaelle", "--no-include", "--exact-only")
        self.assertEqual(set(excluded(out)), {"p1", "p2"})                  # R26.8 no longer counts


class Fall3Consent(unittest.TestCase):
    """validate_consent_torch.py --inclusion-check on NDJSON: same code search, code system respected."""

    @classmethod
    def setUpClass(cls):
        case = os.path.join(DATA, "fall3_consent")
        cls.out = tempfile.mkdtemp(prefix="consent_inclusion_test_")
        subprocess.run([sys.executable, CONSENT_SCRIPT, "--data", os.path.join(case, "import"),
                        "--crtdl", os.path.join(case, "crtdl.json"), "--encounter-shift", "off",
                        "--today", "2026-10-21", "--out-dir", cls.out, "--inclusion-check"],
                       capture_output=True, text=True, check=True)

    def test_unmet_groups(self):
        # p1: G43.1 + ATC via medicationReference (core); p2: OPS range + medicationCodeableConcept;
        # p3: no Betablocker; p4: ICD C07 must not count as ATC C07
        with open(os.path.join(self.out, "consent_inclusion.csv"), encoding="utf-8") as fh:
            rows = {r["patient_id"]: r for r in csv.DictReader(fh)}
        self.assertEqual({p: r["unmet_groups"] for p, r in rows.items()}, {"p3": "2", "p4": "1,2"})
        self.assertEqual(rows["p3"]["window_start"], "2022-01-01")

    def test_summary(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "consent_inclusion.sql")))  # no site-specific SQL
        with open(os.path.join(self.out, "consent_summary.md"), encoding="utf-8") as fh:
            self.assertIn("**2 of 4 patients**", fh.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
