#!/usr/bin/env python3
"""
validate_consent.py
Validates TORCH FHIR NDJSON output (one Bundle per line) against MII
consent logic:
  Step 4  .8 validity gate
  Step 4  .6 data window
  Step 5  Encounter-based start adjustment (non-gate codes only)
  Step 6  Retrospective modifier logic (.45/.46 permit/deny, same Consent only)

New CSV columns:
  encounter_overlap_detected   YES / NO
  effective_window_start_shifted_to   final start date (or reason string)

Usage:  python3 validate_consent.py <input.ndjson> [output.csv]
Deps:   Python 3.7+, no external libraries
"""

import csv
import json
import sys
from datetime import date, datetime

# ----- MII consent OIDs ---------------------------------------------------
OID_6  = "2.16.840.1.113883.3.1937.777.24.5.3.6"
OID_8  = "2.16.840.1.113883.3.1937.777.24.5.3.8"
OID_45 = "2.16.840.1.113883.3.1937.777.24.5.3.45"
OID_46 = "2.16.840.1.113883.3.1937.777.24.5.3.46"

RETRO_OIDS = {OID_45, OID_46}

# Resource types to skip for timestamp checking (structural / meta)
SKIP_TYPES = {
    "Patient", "Consent", "Provenance", "Bundle",
    "OperationOutcome", "Organization", "Practitioner",
    "PractitionerRole", "Location", "Device",
}

# Priority-ordered date fields per resource type
DATE_FIELDS = {
    "Observation":              ["effectiveDateTime", "effectivePeriod.start", "issued"],
    "Condition":                ["recordedDate", "onsetDateTime", "onsetPeriod.start"],
    "Encounter":                ["period.start"],
    "Procedure":                ["performedDateTime", "performedPeriod.start"],
    "MedicationStatement":      ["effectiveDateTime", "effectivePeriod.start"],
    "MedicationAdministration": ["effectiveDateTime", "effectivePeriod.start"],
    "DiagnosticReport":         ["effectiveDateTime", "effectivePeriod.start", "issued"],
    "ImagingStudy":             ["started"],
    "Specimen":                 ["collection.collectedDateTime"],
    "ServiceRequest":           ["authoredOn"],
    "MedicationRequest":        ["authoredOn"],
    "AllergyIntolerance":       ["recordedDate", "onsetDateTime"],
    "Immunization":             ["occurrenceDateTime"],
    "ClinicalImpression":       ["date"],
}

FALLBACK_FIELDS = ["date", "dateTime", "period.start", "meta.lastUpdated"]

DATE_MIN = date(1900, 1, 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_nested(obj, dotted_path):
    """Safely get a nested dict value using dot notation."""
    parts = dotted_path.split(".")
    for part in parts:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def parse_date(s):
    """Parse ISO date or datetime string → date object, or None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def date_in_window(d: date, start: date, end: date) -> bool:
    return start <= d <= end


def periods_overlap(s1: date, e1: date, s2, e2) -> bool:
    """
    Return True if [s1,e1] and [s2,e2] overlap (inclusive, open-ended support).
    e2 may be None to represent an open-ended Encounter.
    """
    if e2 is None:
        # open-ended encounter: overlaps if encounter starts before or on e1
        return s2 <= e1
    return s1 <= e2 and s2 <= e1


# ---------------------------------------------------------------------------
# Provision helpers
# ---------------------------------------------------------------------------

def find_provisions(consent_resource, target_oid, perm_type=None):
    """Return all sub-provisions matching a code OID (and optionally type)."""
    results = []
    top_provision = consent_resource.get("provision", {})
    for prov in top_provision.get("provision", []):
        if perm_type and prov.get("type") != perm_type:
            continue
        for code_block in prov.get("code", []):
            for coding in code_block.get("coding", []):
                if coding.get("code") == target_oid:
                    results.append(prov)
                    break
    return results


def provision_period(prov):
    """Return (start: date|None, end: date|None) for a provision."""
    period = prov.get("period", {})
    return parse_date(period.get("start")), parse_date(period.get("end"))


# ---------------------------------------------------------------------------
# Encounter extraction
# ---------------------------------------------------------------------------

def get_encounter_periods(resources):
    """
    Return list of (enc_start: date, enc_end: date|None) from all Encounter
    resources in the bundle.
    """
    periods = []
    for enc in resources.get("Encounter", []):
        period = enc.get("period", {})
        enc_start = parse_date(period.get("start"))
        enc_end   = parse_date(period.get("end"))   # may be None (ongoing)
        if enc_start is not None:
            periods.append((enc_start, enc_end))
    return periods


# ---------------------------------------------------------------------------
# Step 5 — Encounter-based start adjustment
# ---------------------------------------------------------------------------

def apply_encounter_adjustment(prov_6_start: date, prov_6_end: date,
                                encounter_periods):
    """
    For a single .6 provision window [prov_6_start, prov_6_end]:
    find all Encounters that overlap this window AND start before prov_6_start.
    Return (adjusted_start: date, encounter_overlap: bool, earliest_enc_start: date|None).
    """
    if prov_6_start is None or prov_6_end is None:
        return prov_6_start, False, None

    earliest_enc = None
    for enc_start, enc_end in encounter_periods:
        if not periods_overlap(prov_6_start, prov_6_end, enc_start, enc_end):
            continue
        if enc_start < prov_6_start:
            if earliest_enc is None or enc_start < earliest_enc:
                earliest_enc = enc_start

    if earliest_enc is not None:
        return earliest_enc, True, earliest_enc
    return prov_6_start, False, None


# ---------------------------------------------------------------------------
# Step 6 — Retrospective modifier logic (within same Consent)
# ---------------------------------------------------------------------------

def apply_retro_modifiers(consent, window_start: date, window_end: date):
    """
    Within the given Consent resource:
      1. Collect all .45/.46 permit provisions that overlap [window_start, window_end].
         If any exist → extend window_start to 1900-01-01.
      2. Subtract all .45/.46 deny provisions (from the same Consent) from the
         retro-extended period.  Each deny carves out a gap; we record the largest
         contiguous block that contains window_start after subtraction (conservative:
         if window_start itself is carved out we report the effect).
    Returns:
      retro_applied (bool), retro_deny_applied (bool),
      final_start (date), notes_fragments (list[str])
    """
    retro_permit_provs = []
    for oid in (OID_45, OID_46):
        retro_permit_provs.extend(find_provisions(consent, oid, "permit"))

    retro_deny_provs = []
    for oid in (OID_45, OID_46):
        retro_deny_provs.extend(find_provisions(consent, oid, "deny"))

    notes = []
    retro_applied = False
    retro_deny_applied = False
    final_start = window_start

    if window_start is None or window_end is None:
        return False, False, window_start, notes

    # Step 6a: any overlapping retro permit → push start to 1900-01-01
    for prov in retro_permit_provs:
        ps, pe = provision_period(prov)
        if ps is None:
            ps = DATE_MIN
        if pe is None:
            pe = window_end  # treat open-ended as covering through window end
        if periods_overlap(window_start, window_end, ps, pe):
            retro_applied = True
            final_start = DATE_MIN
            notes.append(
                f"retro modifier permit overlaps window → start shifted to {DATE_MIN}"
            )
            break  # one overlap is enough to trigger

    # Step 6b: subtract retro deny provisions (same Consent) from final window
    # We check whether any deny interval covers/overlaps the now-extended window.
    # For auditability we record which deny intervals were found and their effect.
    if retro_applied:
        deny_intervals = []
        for prov in retro_deny_provs:
            ps, pe = provision_period(prov)
            if ps is None:
                continue  # deny without a period is not actionable
            if pe is None:
                pe = window_end
            deny_intervals.append((ps, pe))

        if deny_intervals:
            retro_deny_applied = True
            deny_strs = [f"[{s},{e}]" for s, e in deny_intervals]
            notes.append(
                f"retro deny interval(s) found: {', '.join(deny_strs)}; "
                "these subtract from the retro-extended period — "
                "TORCH server applies exact subtraction; this validator flags for review"
            )

    return retro_applied, retro_deny_applied, final_start, notes


# ---------------------------------------------------------------------------
# Timestamp extraction
# ---------------------------------------------------------------------------

def extract_timestamp(resource):
    """Return the best date string for consent window checking."""
    rtype = resource.get("resourceType", "")
    fields = DATE_FIELDS.get(rtype, []) + FALLBACK_FIELDS
    for field in fields:
        val = get_nested(resource, field)
        if val and isinstance(val, str):
            return val
    return None


# ---------------------------------------------------------------------------
# Bundle processing
# ---------------------------------------------------------------------------

def process_bundle(bundle, today: date):
    entries = bundle.get("entry", [])
    resources = {}
    for e in entries:
        r = e.get("resource")
        if r:
            resources.setdefault(r["resourceType"], []).append(r)

    # --- Patient ---
    patient_list = resources.get("Patient", [])
    patient_id = patient_list[0]["id"] if patient_list else "UNKNOWN"

    # --- Consent ---
    consent_list = resources.get("Consent", [])

    _no_consent_row = {
        "patient_id":                    patient_id,
        "consent_id":                    "NOT_FOUND",
        "consent_datetime":              "N/A",
        "gate_8_start":                  "NOT_FOUND",
        "gate_8_end":                    "NOT_FOUND",
        "gate_8_active_today":           "NO (no Consent resource)",
        "window_6_start":                "NOT_FOUND",
        "window_6_end":                  "NOT_FOUND",
        "retro_45_present":              "NO",
        "retro_46_present":              "NO",
        "effective_window_start":        "NOT_FOUND",
        "effective_window_end":          "NOT_FOUND",
        "encounter_overlap_detected":    "NO",
        "effective_window_start_shifted_to": "N/A",
        "resource_type":                 "N/A",
        "resource_id":                   "N/A",
        "resource_timestamp":            "N/A",
        "timestamp_in_window":           "CANNOT_CHECK",
        "validation_notes":              "no Consent resource in bundle",
    }

    if not consent_list:
        return [_no_consent_row]

    consent = consent_list[0]
    consent_id       = consent.get("id", "N/A")
    consent_datetime = consent.get("dateTime", "N/A")

    # --- .8 gate (never encounter-adjusted) ---
    prov_8 = find_provisions(consent, OID_8, "permit")
    if prov_8:
        gate_8_start_str = prov_8[0].get("period", {}).get("start", "NOT_FOUND")
        gate_8_end_str   = prov_8[0].get("period", {}).get("end",   "NOT_FOUND")
        g8s = parse_date(gate_8_start_str)
        g8e = parse_date(gate_8_end_str)
        if g8s and g8e:
            gate_8_active = "YES" if date_in_window(today, g8s, g8e) else \
                f"NO (today={today} outside [{gate_8_start_str},{gate_8_end_str}])"
        else:
            gate_8_active = "NO (unparseable .8 dates)"
    else:
        gate_8_start_str = gate_8_end_str = "NOT_FOUND"
        gate_8_active = "NO (.8 missing)"

    # --- .6 window (raw) ---
    prov_6 = find_provisions(consent, OID_6, "permit")
    if prov_6:
        window_6_start_str = prov_6[0].get("period", {}).get("start", "NOT_FOUND")
        window_6_end_str   = prov_6[0].get("period", {}).get("end",   "NOT_FOUND")
    else:
        window_6_start_str = window_6_end_str = "NOT_FOUND"

    w6s = parse_date(window_6_start_str)
    w6e = parse_date(window_6_end_str)

    # --- Step 5: Encounter adjustment ---
    enc_periods = get_encounter_periods(resources)
    adj_start, enc_overlap, earliest_enc = apply_encounter_adjustment(w6s, w6e, enc_periods)
    encounter_overlap_detected = "YES" if enc_overlap else "NO"

    # Track what drove the shift, step by step
    shift_reason_parts = []
    if enc_overlap:
        shift_reason_parts.append(
            f"encounter-adjusted from {window_6_start_str} to {earliest_enc} "
            f"(earliest overlapping encounter start)"
        )

    # Working start after step 5
    step5_start = adj_start  # date or None

    # --- Step 6: Retro modifier logic ---
    retro_applied, retro_deny_applied, final_start, retro_notes = \
        apply_retro_modifiers(consent, step5_start, w6e)

    shift_reason_parts.extend(retro_notes)

    # has_45 / has_46 (permit only, for the existing summary columns)
    has_45 = "YES" if find_provisions(consent, OID_45, "permit") else "NO"
    has_46 = "YES" if find_provisions(consent, OID_46, "permit") else "NO"

    # Final effective window
    eff_start = final_start
    eff_end   = w6e

    # Represent the final effective start as a string for the CSV
    if eff_start is not None:
        eff_start_str = str(eff_start)
    elif window_6_start_str != "NOT_FOUND":
        eff_start_str = window_6_start_str
    else:
        eff_start_str = "NOT_FOUND"

    eff_end_str = window_6_end_str  # end is never shifted by steps 5/6

    # Human-readable shift summary for new column
    if shift_reason_parts:
        shifted_to_str = str(eff_start) if eff_start else eff_start_str
    elif eff_start is not None:
        shifted_to_str = str(eff_start)
    else:
        shifted_to_str = "N/A (window not parseable)"

    # --- Base row ---
    base_row = {
        "patient_id":           patient_id,
        "consent_id":           consent_id,
        "consent_datetime":     consent_datetime,
        "gate_8_start":         gate_8_start_str,
        "gate_8_end":           gate_8_end_str,
        "gate_8_active_today":  gate_8_active,
        "window_6_start":       window_6_start_str,
        "window_6_end":         window_6_end_str,
        "retro_45_present":     has_45,
        "retro_46_present":     has_46,
        "effective_window_start":          eff_start_str,
        "effective_window_end":            eff_end_str,
        "encounter_overlap_detected":      encounter_overlap_detected,
        "effective_window_start_shifted_to": shifted_to_str,
    }

    # --- Clinical resources ---
    rows = []
    clinical = [r for rtype, rlist in resources.items()
                if rtype not in SKIP_TYPES
                for r in rlist]

    if not clinical:
        rows.append({**base_row,
                     "resource_type":      "N/A",
                     "resource_id":        "N/A",
                     "resource_timestamp": "N/A",
                     "timestamp_in_window": "N/A",
                     "validation_notes":   "no clinical resources in bundle"})
        return rows

    for res in clinical:
        rtype = res.get("resourceType", "Unknown")
        rid   = res.get("id", "N/A")
        ts    = extract_timestamp(res)
        ts_date = parse_date(ts) if ts else None
        ts_str  = ts if ts else "N/A"

        notes_parts = list(shift_reason_parts)  # carry forward shift notes

        if eff_start is None or eff_end is None:
            in_window = "CANNOT_CHECK"
            notes_parts.append("consent window missing or unparseable")
        elif ts_date is None:
            in_window = "NO_TIMESTAMP"
            notes_parts.append(f"no extractable timestamp for {rtype}")
        elif date_in_window(ts_date, eff_start, eff_end):
            in_window = "YES"
        else:
            in_window = "NO"
            notes_parts.append(
                f"{ts_date} outside effective window [{eff_start_str}, {eff_end_str}]"
            )

        if retro_deny_applied:
            notes_parts.append(
                "retro deny present in same Consent — manual review recommended "
                "for exact period subtraction"
            )

        rows.append({**base_row,
                     "resource_type":      rtype,
                     "resource_id":        rid,
                     "resource_timestamp": ts_str,
                     "timestamp_in_window": in_window,
                     "validation_notes":   " | ".join(notes_parts) if notes_parts else ""})
    return rows


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: validate_consent.py <input.ndjson> [output.csv]",
              file=sys.stderr)
        sys.exit(1)

    input_path  = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else \
        f"consent_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    today = date.today()

    fieldnames = [
        "patient_id", "consent_id", "consent_datetime",
        "gate_8_start", "gate_8_end", "gate_8_active_today",
        "window_6_start", "window_6_end",
        "retro_45_present", "retro_46_present",
        "effective_window_start", "effective_window_end",
        "encounter_overlap_detected",
        "effective_window_start_shifted_to",
        "resource_type", "resource_id", "resource_timestamp",
        "timestamp_in_window", "validation_notes",
    ]

    total_rows      = 0
    total_patients  = 0
    issues          = 0

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        with open(input_path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    bundle = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[WARN] Line {lineno}: JSON parse error: {e}",
                          file=sys.stderr)
                    continue

                total_patients += 1
                rows = process_bundle(bundle, today)
                for row in rows:
                    writer.writerow(row)
                    total_rows += 1
                    if row.get("timestamp_in_window") not in (
                        "YES", "N/A", "NO_TIMESTAMP", "CANNOT_CHECK"
                    ):
                        issues += 1

    print(f"Done. Output: {output_path}",             file=sys.stderr)
    print(f"Patients processed: {total_patients}",    file=sys.stderr)
    print(f"CSV rows written:   {total_rows}",        file=sys.stderr)
    print(f"Resources outside window: {issues}",      file=sys.stderr)


if __name__ == "__main__":
    main()
