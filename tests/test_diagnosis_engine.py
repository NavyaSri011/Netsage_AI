"""NetSage AI - Phase 5 pilot validation for the Diagnosis Engine.

This is a standalone, dependency-light test runner (does NOT require pytest).
Run with the project Python 3.12 interpreter:

    py -3.12 tests/test_diagnosis_engine.py

It verifies, for a small pilot subset (3 cases):
    1. Case loading from cases.csv
    2. Prompt placeholder substitution
    3. Demo mode works (no API key) and labels source=demo
    4. 9-field JSON schema validation
    5. Invalid JSON rejection (DiagnosisValidationError, output NOT repaired)
    6. Live mode is NOT attempted when no API key is available

It does NOT create ai_diagnoses.csv, does not call a real model when no
key is present, and does not modify cases.csv.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.diagnosis_engine import (
    DiagnosisEngine,
    DiagnosisValidationError,
    DIAGNOSIS_KEYS,
    parse_raw_response,
    validate_diagnosis,
)

# A small production-only pilot subset (NOT all 33 cases).
PILOT_CASES = ["NET-001", "NET-007", "NET-025"]


def run():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print("[%s] %s  %s" % (status, name, detail))

    engine = DiagnosisEngine()

    # 1. Case loading
    print("\n--- Case loading (pilot subset: %s) ---" % ", ".join(PILOT_CASES))
    cases = engine.load_cases(PILOT_CASES)
    record("load_cases returns 3", len(cases) == 3)
    record("each case has unique case_id", len({c["case_id"] for c in cases}) == 3)

    # 2. Prompt substitution
    print("\n--- Prompt substitution ---")
    prompt = engine.build_prompt(cases[0])
    subst_ok = (
        "NET-001" in prompt
        and cases[0]["title"] in prompt
        and cases[0]["symptom"] in prompt
        and "{case_id}" not in prompt
    )
    record("placeholders substituted", subst_ok)

    # 3. Demo mode (no key) works and is labeled
    print("\n--- Demo mode ---")
    diag, meta = engine.diagnose(cases[0], force_demo=True)
    record("demo returns (diagnosis, meta)", isinstance(diag, dict) and isinstance(meta, dict))
    record("meta.source == demo", meta.get("source") == "demo")
    record("meta.needs_human_review is always true", meta.get("needs_human_review") is True)
    record("demo likely_fault marked simulated", "DEMO" in diag["likely_fault"])

    # 4. 9-field schema validation on real demo output
    print("\n--- 9-field JSON validation ---")
    keys_present = set(DIAGNOSIS_KEYS).issubset(set(diag.keys()))
    no_extra = set(diag.keys()) == set(DIAGNOSIS_KEYS)
    record("all 9 keys present", keys_present)
    record("no extra fields on diagnosis object", no_extra)
    record("confidence is valid", diag["confidence"] in ("high", "medium", "low"))

    # Also validate via the public validator
    try:
        normalize = validate_diagnosis(diag)
        record("validate_diagnosis accepts demo output", normalize == diag)
    except DiagnosisValidationError as exc:
        record("validate_diagnosis accepts demo output", False, str(exc))

    # 5. Invalid JSON rejection (must NOT be repaired/fabricated)
    print("\n--- Invalid JSON rejection ---")
    bad_inputs = [
        "this is not json at all",
        "{invalid json",  # malformed
        '{"case_id": "NET-001"}',  # valid json but missing mandatory fields
        '{"case_id":"NET-001","likely_fault":"x","osi_layer":"L3","confidence":"wrong","evidence_used":[],"recommended_next_command":"c","suggested_fix":[],"reasoning_summary":"r","uncertainty_or_limitations":"u"}',  # bad confidence
    ]
    for i, bad in enumerate(bad_inputs):
        try:
            parse_raw_response(bad)
            record("rejects invalid input #%d" % (i + 1), False, "unexpectedly accepted")
        except DiagnosisValidationError:
            record("rejects invalid input #%d" % (i + 1), True)

    # Confirm valid JSON with all 9 fields (and a code fence) parses fine
    valid = {
        "case_id": "NET-025",
        "likely_fault": "interface administratively down",
        "osi_layer": "Layer 1",
        "confidence": "high",
        "evidence_used": ["admin down state"],
        "recommended_next_command": "show interfaces",
        "suggested_fix": ["no shutdown"],
        "reasoning_summary": "admin down state confirms shutdown.",
        "uncertainty_or_limitations": "none",
    }
    try:
        ok = parse_raw_response("```json\n%s\n```" % json.dumps(valid))
        record("accepts valid fenced JSON", ok == valid)
    except DiagnosisValidationError as exc:
        record("accepts valid fenced JSON", False, str(exc))

    # 6. Live mode not attempted without a key
    print("\n--- Live mode when no API key ---")
    before = os.environ.get("OPENAI_API_KEY")
    os.environ.pop("OPENAI_API_KEY", None)
    with_regular = engine.diagnose(cases[0])  # no key -> demo path, no API call
    record("no key -> demo path (no API call attempted)", with_regular[1]["source"] == "demo")
    record("no key -> needs_human_review true", with_regular[1].get("needs_human_review") is True)
    # Calling _live_diagnosis without a key must raise clearly, not fabricate
    try:
        engine._live_diagnosis(cases[0])
        record("_live_diagnosis without key raises", False, "did not raise")
    except DiagnosisValidationError:
        record("_live_diagnosis without key raises", True)
    if before is None:
        os.environ.pop("OPENAI_API_KEY", None)
    else:
        os.environ["OPENAI_API_KEY"] = before

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n=========================================")
    print("PILOT RESULT: %d/%d checks PASSED" % (passed, total))
    print("=========================================")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())