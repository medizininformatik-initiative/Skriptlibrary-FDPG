#!/usr/bin/env python3
"""
validate_consent_torch.py - checks TORCH output against the TORCH consent logic.

Successor of Skriptlibrary-FDPG/validate_consent (v3). The logic follows the TORCH
implementation (v1.0.3, docs/implementation/consent.md and ConsentCalculator /
ConsentValidator / ConsentProvisions in the TORCH source code):

  1. Consent codes are read from the CRTDL (context.code == "Einwilligung"); the boolean
     combination is ignored. .8 and .6 must occur together. .45/.46 only take effect if
     they are also part of the CRTDL.
  2. Only Consent resources with status=active; only provisions with a day-precise
     period (start AND end).
  3. Encounter shift (TORCH_ENABLE_ENCOUNTER_SHIFT): the start of a .6 permit provision
     is moved to the earliest encounter start if
     encounter.start < provision.start <= encounter.end. Only encounters with a
     day-precise start AND end count (open encounters never do).
     Since TORCH 1.0.3: only inpatient encounters (class IMP) are used, and the
     provision is not shifted at all if the earliest matching encounter starts more than
     TORCH_ENCOUNTER_SHIFT_MAX_DAYS (default 7) days before the provision start
     (--shift-class / --shift-max-days; use "any" / -1 for older TORCH versions).
  4. Retro (.45/.46): if a retro permit overlaps the .6 permit of the SAME Consent
     resource, [1900-01-01, .6 end] is added; retro denies of the same resource are
     subtracted from that extension.
  5. Consent resources are folded chronologically (dateTime, then id): permits only
     count from resources carrying the full package (.6 AND .8 permit); denies of a
     code (from any resource) are subtracted.
  6. Gate: today (or --today = extraction date) must lie within the merged .8 period.
  7. Data window = intersection of the .6 periods.
  8. Consent resources themselves are counted as OK_NO_DATE_CHECK (source of the check).
  9. A resource is allowed if its date field according to type_to_consent.json is
     day-precise and lies completely within one window segment. Types with an empty
     field are always allowed; types missing from the mapping are dropped by TORCH.

Consent / encounter sources
  --consent-audit  TORCH files <batchId>_consent.ndjson (Task.output "Consent audit NDJSON").
                   They contain EXACTLY the consents and encounters TORCH used
                   -> exact recalculation incl. encounter shift. Recommended.
  without audit    Consents/encounters are read from the output. Only works if the
                   CRTDL contains consent and encounter groups; the encounter shift can
                   then only be checked partially (the output only contains exported
                   encounters) -> status UNCLEAR_SHIFT.

IMPORTANT: run on the data BEFORE DIMP (jobs/<job>/import/) - after DIMP, IDs and
references are hashed and no longer match the audit files.

Usage (examples)
  python3 validate_consent_torch.py --data jobs/<job>/import --crtdl crtdl.json \\
      --consent-audit audit/ --encounter-shift on --today 2026-08-20 --out-dir consent_report
  python3 validate_consent_torch.py --data jobs/<job>/import --crtdl crtdl.json \\
      --encounter-shift unknown

Inclusion check (--inclusion-check, needs --crtdl and filter_by_crtdl.py in the same folder)
  Checks per patient whether the inclusion criteria of the CRTDL are fulfilled by the EXPORTED
  resources (same code search as filter_by_crtdl.py). Patients without a fulfilled criterion are
  the ones filter_by_crtdl.py excludes - here with their IDs BEFORE DIMP and their consent window.
  consent_inclusion.csv   patients without fulfilled criterion: unmet groups, window, retro, shift.
                          Basis for checking these patients in the local source data (see docs/DETAILS_consent.md)

Output (--out-dir)
  consent_resources.csv   one row per checked resource with status and note
  consent_patients.csv    one row per patient: windows with/without shift, retro, gate
  consent_summary.md      counts per status plus reading guide
  consent_validation.log  run log: parameters, input files, progress, duration, peak memory,
                          traceback on error. Contains no patient IDs -> can be shared.
Exit code 0 = no violations, 2 = violations/unexpected resources found, 1 = aborted with error.
Python standard library only (.zst needs the `zstandard` module or the `zstd` binary).
"""

import argparse
import csv
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta

VERSION = "4.1"

CONSENT_SYSTEM = "urn:oid:2.16.840.1.113883.3.1937.777.24.5.3"
OID = "2.16.840.1.113883.3.1937.777.24.5.3."
C8, C6, C45, C46 = OID + "8", OID + "6", OID + "45", OID + "46"
SHORT = {C8: ".8", C6: ".6", C45: ".45", C46: ".46"}
GATE_CODES = {C8}
DATA_CODES = {C6}
RETRO_OF = {C6: {C45, C46}}
LOOKBACK = date(1900, 1, 1)
ENCOUNTER_PROFILE = "https://www.medizininformatik-initiative.de/fhir/core/modul-fall/StructureDefinition/KontaktGesundheitseinrichtung"

# TORCH mappings/type_to_consent.json (TORCH v1.0.1, unchanged in v1.0.3). Can be overridden with --type-to-consent.
DEFAULT_TYPE_TO_CONSENT = {
    "MedicationStatement": "MedicationStatement.effective", "List": "List.date",
    "MedicationRequest": "MedicationRequest.authoredOn", "Medication": "",
    "MedicationAdministration": "MedicationAdministration.effective",
    "Observation": "Observation.effective", "Procedure": "Procedure.performed", "Device": "",
    "Substance": "", "Organization": "", "Specimen": "Specimen.collection.collected",
    "Condition": "Condition.recordedDate", "DocumentReference": "DocumentReference.date",
    "Questionnaire": "", "Consent": "Consent.dateTime", "ResearchStudy": "",
    "QuestionnaireResponse": "", "Provenance": "Provenance.recorded", "Patient": "",
    "Encounter": "Encounter.period", "Task": "Task.authoredOn",
    "FamilyMemberHistory": "FamilyMemberHistory.date", "DiagnosticReport": "DiagnosticReport.effective",
    "ServiceRequest": "ServiceRequest.authoredOn", "RiskAssessment": "RiskAssessment.occurrence",
}

# Resources created by TORCH itself - not subject to the consent check.
TORCH_GENERATED = {"Provenance"}

STATUS_HELP = {
    "OK": "Date lies within the .6 window (no shift, no retro).",
    "OK_RETRO": "Within the window only due to the retro extension (.45/.46 -> 1900-01-01).",
    "OK_ENCOUNTER_SHIFT": "Within the window only due to the encounter shift; shift is enabled.",
    "OK_ONLY_WITH_SHIFT": "Within the window only with encounter shift; whether TORCH ran with shift is unknown -> clarify TORCH_ENABLE_ENCOUNTER_SHIFT.",
    "OK_NO_DATE_CHECK": "Resource type has no date field in type_to_consent.json -> always allowed.",
    "CORE_NOT_FILTERED": "Core resource (no patient reference, e.g. core.ndjson/Medication) -> not filtered by TORCH.",
    "TORCH_GENERATED": "Created by TORCH (Provenance) -> not part of the consent check.",
    "NO_CONSENT_FILTER": "CRTDL contains no consent criteria -> TORCH does not filter by consent.",
    "UNCLEAR_SHIFT": "Lies BEFORE the window; an encounter shift could explain it, but the required encounters are not available (provide audit files).",
    "NOT_CHECKABLE_NO_CONSENT": "No consent data for this patient (audit missing or consent not in output).",
    "VIOLATION_OUTSIDE_WINDOW": "Date lies outside the consent window TORCH should have applied.",
    "VIOLATION_PATIENT_WITHOUT_VALID_CONSENT": "Patient should have been excluded (incomplete consent, gate failed or empty window).",
    "UNEXPECTED_NO_DAY_PRECISION_DATE": "Date field missing, not day-precise or open period -> TORCH would have dropped the resource.",
    "UNEXPECTED_TYPE_NOT_MAPPED": "Resource type missing in type_to_consent.json -> TORCH would have dropped the resource.",
}
BAD_PREFIXES = ("VIOLATION", "UNEXPECTED")

DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


# --------------------------------------------------------------------------- logging
# One logger for the whole script. Until setup_logging() runs, warnings still reach the console
# (Python's fallback handler). Rule: never log patient IDs, only counts and file names.
log = logging.getLogger("validate_consent_torch")
LOG_FILE = "consent_validation.log"
PROGRESS_RESOURCES = 50000   # log a progress line every N resources while loading
PROGRESS_PATIENTS = 500      # log a progress line every N patients while checking


def setup_logging(out_dir):
    """Log to <out_dir>/consent_validation.log (overwritten per run) and to the console (stderr)."""
    log.setLevel(logging.INFO)
    fmt_ = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    # file handler flushes after every line -> the log survives even if the process is killed (OOM)
    fh = logging.FileHandler(os.path.join(out_dir, LOG_FILE), mode="w", encoding="utf-8")
    fh.setFormatter(fmt_)
    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt_)
    log.addHandler(fh)
    log.addHandler(ch)


def peak_memory():
    """Peak memory (RSS) of this process as text, e.g. '1.8 GB'. Not available on Windows."""
    try:
        import resource
    except ImportError:
        return "n/a"
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    return f"{peak_bytes / 1024 ** 3:.2f} GB"


def file_size(path):
    try:
        return f"{os.path.getsize(path) / 1024 ** 2:.1f} MB"
    except OSError:
        return "?"


# --------------------------------------------------------------------------- read NDJSON
def _open_text(path):
    if path.endswith(".zst"):
        try:
            import zstandard  # type: ignore
            return io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(open(path, "rb")), encoding="utf-8")
        except ImportError:
            if not shutil.which("zstd"):
                log.error(f"{path}: .zst file, but neither Python module 'zstandard' nor 'zstd' available")
                sys.exit(1)
            proc = subprocess.Popen(["zstd", "-dc", path], stdout=subprocess.PIPE)
            return io.TextIOWrapper(proc.stdout, encoding="utf-8")
    return open(path, encoding="utf-8")


def expand_paths(paths, suffixes=(".ndjson", ".ndjson.zst", ".json"), skip_audit=False):
    """Resolve files and directories (non-recursive) to a sorted list of files."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                full = os.path.join(p, name)
                if not (os.path.isfile(full) and name.endswith(suffixes)):
                    continue
                # TORCH audit files (<batchId>_consent.ndjson) are not exported data -> belong to --consent-audit
                if skip_audit and name.endswith(("_consent.ndjson", "_consent.ndjson.zst")):
                    log.warning(f"skipping audit file in --data: {name} (use --consent-audit)")
                    continue
                out.append(full)
        elif os.path.isfile(p):
            out.append(p)
        else:
            log.warning(f"path not found: {p}")
    return out


def iter_lines(path):
    """Yield (line number, object) per NDJSON line."""
    with _open_text(path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield lineno, json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(f"{path}:{lineno}: JSON error: {exc}")


def resources_of(obj):
    """Resources of a Bundle (entry.resource) or a single resource."""
    if not isinstance(obj, dict):
        return []
    if obj.get("resourceType") == "Bundle":
        return [e["resource"] for e in obj.get("entry", []) if isinstance(e, dict) and e.get("resource")]
    return [obj]


PATIENT_REF_FIELDS = ("subject", "patient", "beneficiary", "individual")


def patient_ref(resource):
    """Patient ID of a resource (Patient.id or subject/patient reference), else None."""
    if resource.get("resourceType") == "Patient":
        return resource.get("id")
    for field in PATIENT_REF_FIELDS:
        ref = resource.get(field)
        if isinstance(ref, dict):
            r = ref.get("reference", "")
            if r.startswith("Patient/"):
                return r.split("/", 1)[1]
    return None


# --------------------------------------------------------------------------- periods
def to_day(value):
    """Day-precise date from a date/dateTime/instant string, else None (like Period.fromHapi)."""
    if not isinstance(value, str):
        return None
    m = DAY_RE.match(value)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def to_period(value):
    """FHIR value -> (start, end) or None. dateTime -> [d, d]; Period needs start AND end."""
    if isinstance(value, str):
        d = to_day(value)
        return (d, d) if d else None
    if isinstance(value, dict) and ("start" in value or "end" in value):
        s, e = to_day(value.get("start")), to_day(value.get("end"))
        if s is None or e is None or e < s:
            return None
        return (s, e)
    return None


def merge(periods):
    out = []
    for s, e in sorted(periods):
        if out and not out[-1][1] < s - timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def subtract(periods, deny):
    ds, de = deny
    out = []
    for s, e in periods:
        if max(s, ds) > min(e, de):
            out.append((s, e))
            continue
        if ds > s:
            out.append((s, ds - timedelta(days=1)))
        if de < e:
            out.append((de + timedelta(days=1), e))
    return out


def intersect(a, b):
    out = []
    for s1, e1 in a:
        for s2, e2 in b:
            s, e = max(s1, s2), min(e1, e2)
            if s <= e:
                out.append((s, e))
    return merge(out)


def within(periods, p):
    return any(s <= p[0] and p[1] <= e for s, e in periods)


def contains(periods, d):
    return any(s <= d <= e for s, e in periods)


def fmt(periods):
    if periods is None:
        return ""
    return "; ".join(f"{s}..{e}" for s, e in periods) if periods else "(empty)"


# --------------------------------------------------------------------------- CRTDL
def crtdl_consent_codes(crtdl):
    codes = set()

    def walk(groups):
        for group in groups or []:
            for crit in group:
                if (crit.get("context") or {}).get("code") == "Einwilligung":
                    for tc in crit.get("termCodes", []):
                        codes.add(tc.get("code"))

    cd = crtdl.get("cohortDefinition", {})
    walk(cd.get("inclusionCriteria"))
    walk(cd.get("exclusionCriteria"))
    return codes


# --------------------------------------------------------------------------- consent
def parse_consent(res, wanted):
    """Consent -> (dict(id, dateTime, provisions=[(code, (s,e), permit)]), None) or (None, reason)."""
    if res.get("status") != "active":
        return None, f"status={res.get('status')} (TORCH only fetches active)"
    dt = res.get("dateTime")
    if not dt:
        return None, "no Consent.dateTime (TORCH: ConsentViolatedException)"
    provs = []
    for prov in (res.get("provision") or {}).get("provision", []) or []:
        period = to_period(prov.get("period")) if prov.get("period") else None
        if period is None:
            continue
        permit = prov.get("type") == "permit"
        for cc in prov.get("code", []) or []:
            for coding in cc.get("coding", []) or []:
                if coding.get("system") == CONSENT_SYSTEM and coding.get("code") in wanted:
                    provs.append((coding["code"], period, permit))
    return {"id": res.get("id", ""), "dateTime": dt, "provisions": provs}, None


def encounter_periods(encounters):
    out = []
    for enc in encounters:
        p = to_period(enc.get("period"))
        if p:
            out.append((p, enc.get("id", "")))
    return out


def shift_provisions(consent, enc_periods, notes, max_days=7):
    """Encounter shift for .6 permits (ConsentProvisions.updateByEncounters, TORCH 1.0.3).
    max_days < 0 = no limit (TORCH < 1.0.3)."""
    new = []
    for code, (s, e), permit in consent["provisions"]:
        if permit and code in DATA_CODES:
            # encounters with start before the provision start that still run on that day
            cands = [(ep[0], eid) for ep, eid in enc_periods if ep[0] < s and not ep[1] < s]
            if cands:
                # earliest encounter wins (ties broken by ID, as in TORCH)
                start, eid = min(cands)
                if max_days >= 0 and start < s - timedelta(days=max_days):
                    # TORCH 1.0.3: earliest encounter too far back -> provision is NOT shifted at all
                    notes.append(f"Consent {consent['id']}: .6 start {s} NOT shifted, Encounter {eid} starts "
                                 f"{(s - start).days} days earlier (> {max_days})")
                else:
                    notes.append(f"Consent {consent['id']}: .6 start {s} -> {start} (Encounter {eid}, {(s - start).days} days)")
                    s = start
        new.append((code, (s, e), permit))
    return {**consent, "provisions": new}


def calculate(consents, codes, retro_codes, today, enc_periods=None, use_retro=True, max_days=7):
    """Re-implementation of ConsentCalculator. Returns (window|None, gate periods, reason, notes)."""
    notes = []
    if enc_periods is not None:
        consents = [shift_provisions(c, enc_periods, notes, max_days) for c in consents]
    ordered = sorted(consents, key=lambda c: (c["dateTime"] or "", c["id"]))
    state = {c: [] for c in codes}
    for c in ordered:
        permit_codes = {code for code, _, permit in c["provisions"] if permit and code in codes}
        full = codes <= permit_codes
        for code in codes:
            contribution = []
            if full:
                own = next((p for cd, p, pm in c["provisions"] if pm and cd == code), None)
                if own:
                    contribution = [own]
                    rcodes = RETRO_OF.get(code, set()) & retro_codes if use_retro else set()
                    overlaps = any(pm and cd in rcodes and max(own[0], p[0]) <= min(own[1], p[1])
                                   for cd, p, pm in c["provisions"])
                    if overlaps:
                        ext = [(LOOKBACK, own[1])]
                        for cd, p, pm in c["provisions"]:
                            if not pm and cd in rcodes:
                                ext = subtract(ext, p)
                        contribution = merge(contribution + ext)
                        notes.append(f"Consent {c['id']}: retro extension of .6 from {LOOKBACK}")
            combined = merge(state[code] + contribution)
            for cd, p, pm in c["provisions"]:
                if not pm and cd == code:
                    combined = subtract(combined, p)
            state[code] = combined
    if any(not state[c] for c in codes):
        missing = ",".join(SHORT[c] for c in codes if not state[c])
        return None, state.get(C8), f"no permitted period for {missing}", notes
    gate = state.get(C8, [])
    if not all(contains(state[g], today) for g in codes & GATE_CODES):
        return None, gate, f"gate .8 does not contain {today}", notes
    window = None
    for c in codes & DATA_CODES:
        window = state[c] if window is None else intersect(window, state[c])
    if not window:
        return None, gate, "data window empty", notes
    return window, gate, "", notes


# --------------------------------------------------------------------------- date field
def field_values(resource, fhirpath):
    """Minimal FHIRPath: 'Type.a.b', choice types (effective -> effectiveDateTime/-Period)."""
    parts = fhirpath.split(".")[1:]
    nodes = [resource]
    for part in parts:
        nxt = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            keys = [part] if part in node else [k for k in node if k.startswith(part) and k[len(part):][:1].isupper()]
            for k in keys:
                v = node[k]
                nxt.extend(v if isinstance(v, list) else [v])
        nodes = nxt
    return nodes


def resource_periods(resource, fhirpath):
    return [p for p in (to_period(v) for v in field_values(resource, fhirpath)) if p]


def sys_key(system):
    """Code system without host/version: .../dimdi/icd-10-gm and .../bfarm/icd-10-gm both -> icd-10-gm."""
    return system.rstrip("/").split("/")[-1].split(":")[-1].lower()


# --------------------------------------------------------------------------- loading
def load_data(paths):
    """Patient ID -> list of resources; plus core resources (no patient reference)."""
    by_patient, core = defaultdict(list), []
    files = expand_paths(paths, skip_audit=True)
    log.info(f"--data: {len(files)} file(s)")
    for path in files:
        log.info(f"  {os.path.basename(path)} ({file_size(path)})")
    n_res = 0
    for path in files:
        n_file = 0
        for _, obj in iter_lines(path):
            res = resources_of(obj)
            bundle_pat = next((r.get("id") for r in res if r.get("resourceType") == "Patient"), None)
            for r in res:
                pid = patient_ref(r) or bundle_pat
                (by_patient[pid] if pid else core).append((r, os.path.basename(path)))
                n_res += 1
                n_file += 1
                # progress: shows how far loading got if the process is killed (e.g. out of memory)
                if n_res % PROGRESS_RESOURCES == 0:
                    log.info(f"  loading: {n_res} resources, {len(by_patient)} patients, peak memory {peak_memory()}")
        log.info(f"  read {os.path.basename(path)}: {n_file} resources")
    if not files:
        log.warning("no NDJSON files found in --data")
    log.info(f"loaded {n_res} resources: {len(by_patient)} patients, {len(core)} core resources, "
             f"peak memory {peak_memory()}")
    return by_patient, core


def load_audit(paths):
    consents, encounters = defaultdict(list), defaultdict(list)
    files = expand_paths(paths)
    log.info(f"--consent-audit: {len(files)} file(s)")
    for path in files:
        log.info(f"  {os.path.basename(path)} ({file_size(path)})")
        for _, obj in iter_lines(path):
            for r in resources_of(obj):
                pid = patient_ref(r)
                if r.get("resourceType") == "Consent":
                    consents[pid].append(r)
                elif r.get("resourceType") == "Encounter":
                    encounters[pid].append(r)
    log.info(f"loaded audit: {sum(len(v) for v in consents.values())} consents, "
             f"{sum(len(v) for v in encounters.values())} encounters, peak memory {peak_memory()}")
    return consents, encounters


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", nargs="+", required=True, help="TORCH output (NDJSON files/directory), ideally jobs/<job>/import")
    ap.add_argument("--crtdl", help="CRTDL JSON (determines requested consent codes and retro)")
    ap.add_argument("--consent-audit", nargs="+", help="TORCH <batchId>_consent.ndjson (files/directory)")
    ap.add_argument("--encounter-shift", choices=["on", "off", "unknown"], default="unknown",
                    help="TORCH_ENABLE_ENCOUNTER_SHIFT of the TORCH instance (TORCH default: on)")
    ap.add_argument("--shift-max-days", type=int, default=7,
                    help="TORCH_ENCOUNTER_SHIFT_MAX_DAYS (TORCH 1.0.3 default: 7; -1 = no limit for TORCH < 1.0.3)")
    ap.add_argument("--shift-class", default="IMP",
                    help="encounter class used for the shift (TORCH 1.0.3: IMP; 'any' for TORCH < 1.0.3)")
    ap.add_argument("--type-to-consent", help="path to TORCH mappings/type_to_consent.json (default: built-in, TORCH v1.0.1-v1.0.3)")
    ap.add_argument("--today", help="date of the TORCH extraction (YYYY-MM-DD) for the .8 gate check; default today")
    ap.add_argument("--codes", help="without CRTDL: comma-separated requested codes, e.g. 8,6,45,46")
    ap.add_argument("--out-dir", default="consent_report")
    ap.add_argument("--inclusion-check", action="store_true",
                    help="also check the CRTDL inclusion criteria against the exported resources "
                         "(writes consent_inclusion.csv; needs --crtdl and filter_by_crtdl.py next to this script)")
    ap.add_argument("--version", action="version", version=f"validate_consent_torch {VERSION}")
    args = ap.parse_args()

    # out-dir first, so the log file can be written from the start
    os.makedirs(args.out_dir, exist_ok=True)
    setup_logging(args.out_dir)
    t_start = time.time()
    log.info(f"validate_consent_torch {VERSION}, Python {platform.python_version()}, {platform.system()}")
    log.info("parameters: " + ", ".join(f"--{k.replace('_', '-')}={v}" for k, v in vars(args).items()))

    today = date.fromisoformat(args.today) if args.today else date.today()
    t2c = DEFAULT_TYPE_TO_CONSENT
    if args.type_to_consent:
        with open(args.type_to_consent, encoding="utf-8") as fh:
            t2c = json.load(fh)

    # ---- requested codes
    crtdl_obj = None
    if args.crtdl:
        with open(args.crtdl, encoding="utf-8") as fh:
            crtdl_obj = json.load(fh)
        requested = crtdl_consent_codes(crtdl_obj)
    elif args.codes:
        requested = {OID + c.strip().lstrip(".") for c in args.codes.split(",")}
    else:
        requested = {C8, C6}
        log.warning("neither --crtdl nor --codes: assuming .8 + .6 without retro.")
    enforce = bool(requested)
    codes = requested & {C8, C6}
    retro_codes = requested & {C45, C46}
    ignored = requested - {C8, C6, C45, C46}
    header_notes = []
    if not enforce:
        header_notes.append("CRTDL contains NO consent criteria -> TORCH does not apply a consent filter.")
    elif codes != {C8, C6}:
        header_notes.append("CRTDL contains only one of .8/.6 -> TORCH rejects such a request (ConsentFormatException). Check!")
    if ignored:
        header_notes.append("Consent codes in the CRTDL ignored by TORCH: " + ", ".join(sorted(ignored)))
    log.info(f"consent codes: {', '.join(SHORT.get(c, c) for c in sorted(requested)) or '-'}, gate date {today}")

    # ---- inclusion check: same criteria parsing and code search as filter_by_crtdl.py
    incl_groups, incl_skipped = [], []
    if args.inclusion_check:
        if not crtdl_obj:
            log.error("--inclusion-check needs --crtdl")
            sys.exit(1)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from filter_by_crtdl import parse_inclusion_groups, rule_matches
        except ImportError:
            log.error("--inclusion-check needs filter_by_crtdl.py in the same folder as this script")
            sys.exit(1)
        incl_groups, incl_skipped, _ = parse_inclusion_groups(crtdl_obj)
        log.info(f"inclusion check: {len(incl_groups)} group(s), "
                 f"{sum(len(g) for g in incl_groups)} criteria, {len(incl_skipped)} skipped")
        if not incl_groups:
            header_notes.append("Inclusion check: no checkable inclusion criteria in the CRTDL.")

    t_phase = time.time()
    by_patient, core = load_data(args.data)
    log.info(f"loading data took {time.time() - t_phase:.0f} s")
    # Medication (no patient reference, core resources): id -> codes, for medicationReference
    core_med_codes = {r.get("id"): [(c.get("system", ""), c.get("code", "")) for c in (r.get("code") or {}).get("coding", [])]
                      for r, _ in core if r.get("resourceType") == "Medication"}
    incl_rows = []
    incl_cache = {}   # code value -> set of criterion idx it fulfils
    if args.consent_audit:
        consents_raw, encounters_raw = load_audit(args.consent_audit)
        source = "audit"
    else:
        consents_raw, encounters_raw = defaultdict(list), defaultdict(list)
        for pid, items in by_patient.items():
            for r, _ in items:
                if r.get("resourceType") == "Consent":
                    consents_raw[pid].append(r)
                elif r.get("resourceType") == "Encounter":
                    encounters_raw[pid].append(r)
        source = "output"
        header_notes.append("No audit files: consents/encounters read from the output. Encounter shift can only be checked partially.")
        if enforce and not any(consents_raw.values()):
            header_notes.append("The output contains NO Consent resources (CRTDL without consent group). "
                                "Fetch the audit files <batchId>_consent.ndjson from TORCH (Task.output) and pass them with --consent-audit.")
    if source == "audit" and by_patient and not (set(by_patient) & set(consents_raw)):
        header_notes.append("NO patient ID from the output occurs in the audit - is the script running on DIMP output (hashed IDs)? Run it on jobs/<job>/import.")
    # notes contain no patient IDs -> also into the log
    for n in header_notes:
        log.warning(n)

    shift_mode = args.encounter_shift
    res_rows, pat_rows = [], []
    status_count = Counter()
    type_status = defaultdict(Counter)

    t_phase = time.time()
    n_patients = len(by_patient)
    log.info(f"checking {n_patients} patients (consent source: {source}, encounter shift: {shift_mode})")
    for i_pat, pid in enumerate(sorted(by_patient, key=str), 1):
        if i_pat % PROGRESS_PATIENTS == 0:
            log.info(f"  checked {i_pat}/{n_patients} patients, peak memory {peak_memory()}")
        items = by_patient[pid]
        parsed, skipped = [], []
        for r in consents_raw.get(pid, []):
            c, why = parse_consent(r, codes | retro_codes)
            (parsed.append(c) if c else skipped.append(f"{r.get('id')}: {why}"))
        encs = encounters_raw.get(pid, [])
        if source == "output":
            # TORCH only uses encounters of the MII Fall profile for the shift
            encs = [e for e in encs if ENCOUNTER_PROFILE in "|".join((e.get("meta") or {}).get("profile", []))
                    or not (e.get("meta") or {}).get("profile")]
        # TORCH 1.0.3: only inpatient encounters (Encounter.class = IMP) are used for the shift.
        # Applied to the audit as well: the audit can also contain other classes (e.g. AMB).
        if args.shift_class != "any":
            encs = [e for e in encs if (e.get("class") or {}).get("code") == args.shift_class]
        eps = encounter_periods(encs)

        have_consent = bool(consents_raw.get(pid))
        empty = (None, None, "", [])
        w_plain, gate, _, _ = calculate(parsed, codes, retro_codes, today, None, use_retro=False) if enforce and have_consent else empty
        w_base, _, why_base, n_base = calculate(parsed, codes, retro_codes, today, None) if enforce and have_consent else empty
        w_shift, _, why_shift, n_shift = calculate(parsed, codes, retro_codes, today, eps, max_days=args.shift_max_days) if enforce and have_consent else empty

        if shift_mode == "off":
            w_eff, why_eff = w_base, why_base
        elif shift_mode == "on":
            w_eff, why_eff = w_shift, why_shift
        else:  # unknown: most permissive assumption, difference is flagged
            w_eff, why_eff = (w_shift, why_shift) if w_shift else (w_base, why_base)

        patient_excluded = enforce and have_consent and w_eff is None
        pat_status = ("NO_CONSENT_FILTER" if not enforce else
                      "NOT_CHECKABLE_NO_CONSENT" if not have_consent else
                      "VIOLATION_PATIENT_WITHOUT_VALID_CONSENT" if patient_excluded else "OK")
        n_bad = 0
        for r, fname in items:
            rtype = r.get("resourceType", "?")
            rid = r.get("id", "")
            field = t2c.get(rtype)
            periods = resource_periods(r, field) if field else []
            per_str = "; ".join(f"{s}..{e}" if s != e else str(s) for s, e in periods)
            note = ""
            if rtype in TORCH_GENERATED:
                st = "TORCH_GENERATED"
            elif not enforce:
                st = "NO_CONSENT_FILTER"
            elif rtype == "Consent":
                # Consent is the source of the check itself -> counted the same way with and without audit
                st = "OK_NO_DATE_CHECK"
                note = "Consent resource itself (source of the check)"
            elif rtype not in t2c:
                st = "UNEXPECTED_TYPE_NOT_MAPPED"
            elif field == "":
                st = "OK_NO_DATE_CHECK"
            elif not have_consent:
                st = "NOT_CHECKABLE_NO_CONSENT"
            elif patient_excluded:
                st = "VIOLATION_PATIENT_WITHOUT_VALID_CONSENT"
                note = why_eff
            elif not periods:
                st = "UNEXPECTED_NO_DAY_PRECISION_DATE"
                note = f"field {field} has no day-precise value / open period"
            else:
                ok = lambda w: w is not None and any(within(w, p) for p in periods)  # noqa: E731
                if ok(w_plain):
                    st = "OK"
                elif ok(w_base):
                    st = "OK_RETRO"
                elif ok(w_shift) and shift_mode == "on":
                    st = "OK_ENCOUNTER_SHIFT"
                elif ok(w_shift) and shift_mode == "unknown":
                    st = "OK_ONLY_WITH_SHIFT"
                else:
                    before = w_eff and all(p[1] <= max(e for _, e in w_eff) and p[0] < min(s for s, _ in w_eff) for p in periods)
                    if shift_mode != "off" and source == "output" and before:
                        st = "UNCLEAR_SHIFT"
                    else:
                        st = "VIOLATION_OUTSIDE_WINDOW"
                        if shift_mode == "off" and ok(w_shift):
                            note = "would be allowed WITH encounter shift -> did TORCH run with shift after all?"
                        else:
                            note = f"window {fmt(w_eff)}"
            if st.startswith(BAD_PREFIXES):
                n_bad += 1
            status_count[st] += 1
            type_status[rtype][st] += 1
            res_rows.append({
                "patient_id": pid, "file": fname, "resource_type": rtype, "resource_id": rid,
                "consent_field": field if field is not None else "(not mapped)",
                "date_period": per_str, "status": st, "note": note,
            })
        pat_rows.append({
            "patient_id": pid, "status": pat_status, "consent_source": source,
            "consents_total": len(consents_raw.get(pid, [])), "consents_discarded": " | ".join(skipped),
            "encounters_for_shift": len(eps),
            "gate_8_merged": fmt(gate), "gate_today_ok": ("" if gate is None else ("YES" if contains(gate, today) else "NO")),
            "window_no_retro_no_shift": fmt(w_plain), "window_no_shift": fmt(w_base),
            "window_with_shift": fmt(w_shift), "window_applied": fmt(w_eff),
            "exclusion_reason": why_eff, "shift_details": " | ".join(n for n in n_shift if "Encounter" in n),
            "shift_applied": "YES" if any("->" in n for n in n_shift) else "NO",
            # largest applied shift of this patient in days (from the notes "... -> start (Encounter X, N days)")
            "shift_days_max": max((int(m.group(1)) for n in n_shift if "->" in n
                                   for m in [re.search(r", (\d+) days\)", n)] if m), default=""),
            "retro_applied": "YES" if any("retro" in n for n in n_base) else "NO",
            "resources": len(items), "flagged_resources": n_bad,
        })

        if incl_groups:
            # all codes of the exported resources (code.coding, medicationCodeableConcept, medicationReference)
            # as (system, code): unlike the CSVs, NDJSON keeps the system (ICD C07 != ATC C07)
            pcodes = set()
            for r, _ in items:
                if r.get("resourceType") == "Consent":
                    continue
                for key in ("code", "medicationCodeableConcept"):
                    pcodes.update((c.get("system", ""), c.get("code", "")) for c in (r.get(key) or {}).get("coding", []))
                # Encounter.class is a single Coding (not a CodeableConcept), e.g. IMP for an inpatient stay
                cls = r.get("class") if r.get("resourceType") == "Encounter" else None
                if isinstance(cls, dict) and cls.get("code"):
                    pcodes.add((cls.get("system", ""), cls["code"]))
                mref = (r.get("medicationReference") or {}).get("reference", "")
                if mref:
                    pcodes.update(core_med_codes.get(mref.split("/")[-1], []))
            hit = set()
            for sv in pcodes:
                if sv[1] and sv not in incl_cache:
                    incl_cache[sv] = {c["idx"] for g in incl_groups for c in g
                                      if not sv[0] or not any(c["systems"]) or sys_key(sv[0]) in {sys_key(x) for x in c["systems"]}
                                      for _, rule in c["rules"] if rule_matches(rule, sv[1])}
                hit |= incl_cache.get(sv, set())
            unmet = [str(g_i) for g_i, g in enumerate(incl_groups, 1) if not any(c["idx"] in hit for c in g)]
            if unmet:
                incl_rows.append({
                    "patient_id": pid, "unmet_groups": ",".join(unmet), "consent_status": pat_status,
                    "window_applied": fmt(w_eff),
                    # first start / last end of the applied window, for comparing source dates with the window
                    "window_start": str(min(s_ for s_, _ in w_eff)) if w_eff else "",
                    "window_end": str(max(e_ for _, e_ in w_eff)) if w_eff else "",
                    "retro_applied": pat_rows[-1]["retro_applied"], "shift_applied": pat_rows[-1]["shift_applied"],
                })
    log.info(f"checking patients took {time.time() - t_phase:.0f} s, peak memory {peak_memory()}")

    for r, fname in core:
        st = "CORE_NOT_FILTERED" if r.get("resourceType") not in TORCH_GENERATED else "TORCH_GENERATED"
        status_count[st] += 1
        type_status[r.get("resourceType", "?")][st] += 1
        res_rows.append({"patient_id": "", "file": fname, "resource_type": r.get("resourceType"),
                         "resource_id": r.get("id", ""), "consent_field": "", "date_period": "",
                         "status": st, "note": ""})

    # patients with consent in the audit but without data -> informational
    only_audit = sorted(set(consents_raw) - set(by_patient) - {None}, key=str)

    with open(os.path.join(args.out_dir, "consent_resources.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(res_rows[0].keys()) if res_rows else ["status"])
        w.writeheader()
        w.writerows(res_rows)
    with open(os.path.join(args.out_dir, "consent_patients.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pat_rows[0].keys()) if pat_rows else ["patient_id"])
        w.writeheader()
        w.writerows(pat_rows)

    if incl_groups:
        with open(os.path.join(args.out_dir, "consent_inclusion.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["patient_id", "unmet_groups", "consent_status", "window_applied",
                                               "window_start", "window_end", "retro_applied", "shift_applied"])
            w.writeheader()
            w.writerows(incl_rows)

    bad = sum(n for s, n in status_count.items() if s.startswith(BAD_PREFIXES))
    unclear = sum(n for s, n in status_count.items() if s.startswith(("UNCLEAR", "NOT_CHECKABLE", "OK_ONLY_WITH_SHIFT")))
    lines = [
        "# Consent validation (TORCH logic)", "",
        f"- Data: {', '.join(args.data)}",
        f"- Consent source: **{source}**" + (" (TORCH audit, exact)" if source == "audit" else " (output, limited)"),
        f"- Requested codes (CRTDL): {', '.join(SHORT.get(c, c) for c in sorted(requested)) or '-'}",
        f"- Retro active: {'yes (' + ', '.join(SHORT[c] for c in sorted(retro_codes)) + ')' if retro_codes else 'no'}",
        f"- Encounter shift: **{shift_mode}** (class {args.shift_class}, max {args.shift_max_days if args.shift_max_days >= 0 else 'unlimited'} days)",
        f"- Gate reference date (.8): {today}",
        f"- Patients in output: {len(by_patient)} · resources: {len(res_rows)}",
        "",
        ]
    if header_notes:
        lines += ["## Notes", ""] + [f"- ⚠ {n}" for n in header_notes] + [""]
    verdict = "✅ no violations" if not bad else f"❌ {bad} flagged resources"
    if unclear:
        verdict += f" · ⚠ {unclear} not conclusively checkable"
    lines += ["## Result", "", f"**{verdict}**", "", "| Status | Count | Meaning |", "|---|---:|---|"]
    for st, n in sorted(status_count.items(), key=lambda x: (not x[0].startswith(BAD_PREFIXES), x[0])):
        lines.append(f"| {st} | {n} | {STATUS_HELP.get(st, '')} |")
    lines += ["", "## Status per resource type", "", "| Type | " + " | ".join(sorted(status_count)) + " |",
              "|---|" + "---:|" * len(status_count)]
    for rtype in sorted(type_status):
        lines.append(f"| {rtype} | " + " | ".join(str(type_status[rtype].get(s, 0)) for s in sorted(status_count)) + " |")
    pstat = Counter(p["status"] for p in pat_rows)
    # patient overview as a table with an explanation per row
    PATIENT_HELP = {
        "OK": "Patient has a valid consent (gate .8 on the extraction day and a non-empty .6 window) -> may be in the output.",
        "VIOLATION_PATIENT_WITHOUT_VALID_CONSENT": "Patient is in the output, but according to the recalculation TORCH should have excluded him.",
        "NOT_CHECKABLE_NO_CONSENT": "No Consent resource found for the patient (audit missing or consent not in output) -> not checkable.",
        "NO_CONSENT_FILTER": "CRTDL contains no consent criteria -> no consent check.",
    }
    n_pat = len(pat_rows)
    lines += ["", "## Patients", "",
              f"{n_pat} patients in the output. A patient can appear in several of the rows below "
              "(e.g. retro extension AND encounter shift).", "",
              "| Patients | Count | Meaning |", "|---|---:|---|"]
    for k, v in sorted(pstat.items()):
        lines.append(f"| status {k} | {v} | {PATIENT_HELP.get(k, '')} |")
    shift_note = "" if shift_mode == "on" else f" Calculated only - with `--encounter-shift {shift_mode}` it is not known whether TORCH applied it."
    lines.append(f"| with retro extension | {sum(1 for p in pat_rows if p['retro_applied'] == 'YES')} | "
                 "The .6 window was extended back to 1900-01-01 because the same Consent resource also permits .45/.46 "
                 "(retrospective use). Older data of these patients may be exported. |")
    lines.append(f"| with encounter shift | {sum(1 for p in pat_rows if p['shift_applied'] == 'YES')} | "
                 "The .6 start was moved back to the start of an inpatient stay that began shortly before the consent "
                 "and was still running on the consent day - so the whole stay counts." + shift_note + " |")
    lines.append(f"| shift blocked by max days | {sum(1 for p in pat_rows if 'NOT shifted' in p['shift_details'])} | "
                 f"An inpatient stay would have qualified, but it began more than {args.shift_max_days if args.shift_max_days >= 0 else 'the allowed number of'} days before the consent "
                 "-> TORCH 1.0.3 does not shift at all, the .6 start stays the consent date. |")
    # size of the applied shifts (days the .6 start was moved back); patient IDs only in consent_patients.csv
    shift_days = [p["shift_days_max"] for p in pat_rows if p["shift_days_max"] != ""]
    if shift_days:
        dist = Counter(shift_days)
        lines.append(f"| largest encounter shift | {max(shift_days)} days | Largest number of days a .6 start was moved back "
                     "(per patient in column `shift_days_max` of consent_patients.csv). |")
        lines.append("| shift days distribution | " + ", ".join(f"{d} d: {n}" for d, n in sorted(dist.items())) +
                     " | Days moved back -> number of patients (largest shift per patient). |")
    if only_audit:
        lines.append(f"| in audit, not in output | {len(only_audit)} | Consent in the TORCH audit, but no data in the output "
                     "(excluded by TORCH, e.g. by mustHave, or no data). |")
    if incl_groups:
        crit_txt = "; ".join(" OR ".join(c["label"] for c in g) for g in incl_groups)
        lines += ["", "## Inclusion check", "",
                  f"Checked inclusion groups (AND): {crit_txt}",
                  ] + [f"- not checked ({reason}): {text}" for reason, text in incl_skipped] + [
                  "",
                  f"**{len(incl_rows)} of {len(pat_rows)} patients** do not fulfil all inclusion groups with the exported "
                  "resources. filter_by_crtdl.py should exclude about the same number.",
                  "",
                  "| Patients | Count |", "|---|---:|",
                  f"| with retro extension | {sum(1 for r in incl_rows if r['retro_applied'] == 'YES')} |",
                  f"| with encounter shift | {sum(1 for r in incl_rows if r['shift_applied'] == 'YES')} |",
                  f"| without valid consent window | {sum(1 for r in incl_rows if not r['window_start'])} |",
                  "",
                  "Details per patient (FHIR ID, unmet groups, consent window): consent_inclusion.csv.",
                  ]
    lines += ["", "## Reading guide", "",
              "- `window_no_shift` vs. `window_with_shift` in consent_patients.csv shows the effect of the encounter shift.",
              "- `--encounter-shift unknown` calculates both variants; resources with `OK_ONLY_WITH_SHIFT` show that TORCH ran with shift (or that something is wrong).",
              "- Without audit files the script only knows the exported encounters. TORCH, however, uses ALL inpatient encounters of the patient (profile KontaktGesundheitseinrichtung, class IMP, with start+end) -> `UNCLEAR_SHIFT`.",
              "- Since TORCH 1.0.3 a .6 start is not shifted at all if the earliest matching encounter starts more than TORCH_ENCOUNTER_SHIFT_MAX_DAYS days earlier (`shift blocked by max days`).",
              "- With active consent, TORCH neither uses nor exports open encounters (without period.end).",
              "- Resources without a day-precise date (e.g. recordedDate only '2021-05') are dropped by TORCH.",
              ""]
    with open(os.path.join(args.out_dir, "consent_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))

    # ---- end of run: counts only, no patient IDs
    log.info(f"result: {len(by_patient)} patients, {len(res_rows)} resources, {bad} flagged, {unclear} not conclusively checkable")
    for st, n in sorted(status_count.items()):
        log.info(f"  {st}: {n}")
    if incl_groups:
        log.info(f"inclusion check: {len(incl_rows)} of {len(pat_rows)} patients do not fulfil all inclusion groups")
    log.info(f"reports written to {args.out_dir}/")
    log.info(f"finished in {time.time() - t_start:.0f} s, peak memory {peak_memory()}, exit code {2 if bad else 0}")
    sys.exit(2 if bad else 0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:
        # full traceback into the log before aborting (MemoryError, KeyboardInterrupt, unexpected errors).
        # A process killed by the system (OOM killer, "Killed") cannot log anything - the last progress
        # line in the log then shows how far it got.
        if log.handlers:
            log.exception(f"aborted: {type(exc).__name__}: {exc} (peak memory {peak_memory()})")
        else:
            raise
        sys.exit(1)
