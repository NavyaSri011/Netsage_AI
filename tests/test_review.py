"""NetSage AI - Phase 7 validation for the Human Review System.

A standalone, dependency-light test runner (does NOT require pytest).
Run with the project Python 3.12 interpreter:

    py -3.12 tests/test_review.py

It uses a temporary review store so the real data/reviews.json is never
created or modified by the test run.

Coverage:
    A. Pending review creation
    B. Accept workflow
    C. Edit workflow
    D. Reject workflow
    E. Invalid input validation
    F. Integration with the diagnosis engine (demo mode)
"""

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.diagnosis_engine import DiagnosisEngine
from src.review import (
    HumanReview,
    ReviewValidationError,
    accept_review,
    create_review,
    edit_review,
    get_review,
    list_reviews,
    reject_review,
)

VALID_DIAGNOSIS = {
    "case_id": "NET-001",
    "likely_fault": "Access port is assigned to the wrong VLAN.",
    "osi_layer": "Layer 2",
    "confidence": "medium",
    "evidence_used": ["Symptom: host cannot reach server in same VLAN"],
    "recommended_next_command": "show interfaces switchport",
    "suggested_fix": ["Reassign the port with switchport access vlan 10"],
    "reasoning_summary": "Port-level VLAN issue is the most probable cause.",
    "uncertainty_or_limitations": "No command output captured yet.",
}

EDITED_DIAGNOSIS = {
    "case_id": "NET-001",
    "likely_fault": "The server access port is in VLAN 20 instead of VLAN 10.",
    "osi_layer": "Layer 2",
    "confidence": "high",
    "evidence_used": [
        "Symptom: host cannot reach server in VLAN 10",
        "Confirmed with show interfaces switchport",
    ],
    "recommended_next_command": "show vlan brief",
    "suggested_fix": ["switchport access vlan 10", "Verify with show vlan brief"],
    "reasoning_summary": "Human reviewer confirmed the VLAN mismatch.",
    "uncertainty_or_limitations": "None after confirmation.",
}


def run():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print("[%s] %s  %s" % (status, name, detail))

    with tempfile.TemporaryDirectory() as tmp:
        store = os.path.join(tmp, "reviews.json")

        # ------------------------------------------------------------
        # A. Pending review creation
        # ------------------------------------------------------------
        print("\n--- A. Pending Review Creation ---")
        created = create_review("NET-001", VALID_DIAGNOSIS, {"source": "demo"}, store)
        record("new review is pending", created["review_status"] == "pending")
        record("has review_id", bool(str(created.get("review_id", "")).strip()))
        record("case_id recorded", created["case_id"] == "NET-001")
        record("original AI diagnosis preserved", created["ai_diagnosis"] == VALID_DIAGNOSIS)
        record("ai_meta keeps needs_human_review True", created["ai_meta"].get("needs_human_review") is True)
        record("no final decision yet", created["final_diagnosis"] is None)
        record("reviewed_at is None while pending", created["reviewed_at"] is None)

        stored = get_review(created["review_id"], store)
        record("stored record deep-copies ai_diagnosis (not same object)",
               stored["ai_diagnosis"] == VALID_DIAGNOSIS
               and stored["ai_diagnosis"] is not VALID_DIAGNOSIS)

        # ------------------------------------------------------------
        # B. Accept workflow
        # ------------------------------------------------------------
        print("\n--- B. Accept Workflow ---")
        accepted = accept_review(created["review_id"], reviewer_notes="Looks correct.", store_path=store)
        record("status becomes accepted", accepted["review_status"] == "accepted")
        record("final diagnosis matches AI diagnosis",
               accepted["final_diagnosis"] == VALID_DIAGNOSIS)
        record("original AI diagnosis unchanged in record",
               accepted["ai_diagnosis"] == VALID_DIAGNOSIS)
        record("review timestamp recorded", bool(accepted.get("reviewed_at")))

        # Ensure the caller's original dict was not mutated.
        record("caller ai_diagnosis dict not mutated", VALID_DIAGNOSIS["likely_fault"].startswith("Access port"))

        # ------------------------------------------------------------
        # C. Edit workflow
        # ------------------------------------------------------------
        print("\n--- C. Edit Workflow ---")
        created2 = create_review("NET-002", VALID_DIAGNOSIS, None, store)
        edited = edit_review(
            created2["review_id"],
            EDITED_DIAGNOSIS,
            correction_reason="AI hypothesis was too generic; human confirmed the exact fault.",
            reviewer_notes="Refined the root cause.",
            store_path=store,
        )
        record("status becomes edited", edited["review_status"] == "edited")
        record("final diagnosis contains human changes",
               edited["final_diagnosis"] == EDITED_DIAGNOSIS
               and edited["final_diagnosis"] != VALID_DIAGNOSIS)
        record("original AI diagnosis remains unchanged",
               edited["ai_diagnosis"] == VALID_DIAGNOSIS)
        record("correction_reason stored", bool(str(edited.get("correction_reason", "")).strip()))
        record("reviewer_notes stored", (edited.get("reviewer_notes") or "").startswith("Refined"))

        missing_reason = False
        try:
            edit_review(created2["review_id"], EDITED_DIAGNOSIS, "", store_path=store)
        except ReviewValidationError:
            missing_reason = True
        record("edit without correction_reason raises", missing_reason)

        # ------------------------------------------------------------
        # D. Reject workflow
        # ------------------------------------------------------------
        print("\n--- D. Reject Workflow ---")
        created3 = create_review("NET-003", VALID_DIAGNOSIS, None, store)
        rejected = reject_review(
            created3["review_id"],
            correction_reason="AI hypothesis contradicted by the confirmed evidence.",
            final_diagnosis=EDITED_DIAGNOSIS,
            store_path=store,
        )
        record("status becomes rejected", rejected["review_status"] == "rejected")
        record("correction_reason required and stored", bool(str(rejected.get("correction_reason", "")).strip()))
        record("final diagnosis stored separately when provided",
               rejected["final_diagnosis"] == EDITED_DIAGNOSIS)
        record("rejected final differs from AI diagnosis",
               rejected["final_diagnosis"] != rejected["ai_diagnosis"])

        created4 = create_review("NET-004", VALID_DIAGNOSIS, None, store)
        rejected_no_final = reject_review(
            created4["review_id"], correction_reason="Incorrect.", store_path=store)
        record("reject without final diagnosis keeps final_diagnosis None",
               rejected_no_final["final_diagnosis"] is None)
        record("rejected AI diagnosis not presented as final",
               rejected_no_final["final_diagnosis"] is None)

        missing_reason2 = False
        try:
            reject_review(created4["review_id"], "", store_path=store)
        except ReviewValidationError:
            missing_reason2 = True
        record("reject without correction_reason raises", missing_reason2)

        # ------------------------------------------------------------
        # E. Invalid input validation
        # ------------------------------------------------------------
        print("\n--- E. Invalid Inputs ---")
        invalid_status = False
        try:
            list_reviews(status="bogus", store_path=store)
        except ReviewValidationError:
            invalid_status = True
        record("invalid review status filter rejected", invalid_status)

        acted_twice = False
        try:
            accept_review(created["review_id"], store_path=store)  # already accepted
        except ReviewValidationError:
            acted_twice = True
        record("re-reviewing an accepted review raises", acted_twice)

        bad_diag = False
        try:
            create_review("NET-005", {"case_id": "NET-005"}, None, store)
        except ReviewValidationError:
            bad_diag = True
        record("create_review with malformed AI diagnosis raises", bad_diag)

        bad_case = False
        try:
            create_review("", VALID_DIAGNOSIS, None, store)
        except ReviewValidationError:
            bad_case = True
        record("create_review with empty case_id raises", bad_case)

        unknown = False
        try:
            get_review("REV-999", store)
        except ReviewValidationError:
            unknown = True
        record("unknown review_id raises", unknown)

        # listing by status reflects real transitions (derived, not hard-coded)
        all_recs = list_reviews(store_path=store)
        statuses_seen = {r["review_status"] for r in all_recs}
        filter_ok = True
        for st in statuses_seen:
            subset = [r for r in list_reviews(status=st, store_path=store)]
            expected = [r for r in all_recs if r["review_status"] == st]
            if subset != expected:
                filter_ok = False
                break
        record("list_reviews(status=...) returns exactly the matching records", filter_ok)

        # list returns defensive copies
        br = list_reviews(store_path=store)[0]
        before = copy.deepcopy(br)
        br["ai_diagnosis"]["likely_fault"] = "MUTATED"
        after = get_review(br["review_id"], store)
        record("list/get return defensive copies (mutation does not persist)",
               after["ai_diagnosis"]["likely_fault"] == before["ai_diagnosis"]["likely_fault"])

        # ------------------------------------------------------------
        # F. Integration with DiagnosisEngine (demo mode)
        # ------------------------------------------------------------
        print("\n--- F. Integration with Diagnosis Engine ---")
        engine = DiagnosisEngine()
        case = engine.load_case("NET-007")
        diag, meta = engine.diagnose(case, force_demo=True)
        record("engine.needs_human_review True before review", meta.get("needs_human_review") is True)
        original_diag = copy.deepcopy(diag)

        rev = create_review(case["case_id"], diag, meta, store)
        record("review accepts diagnosis_engine (diagnosis, meta) output",
               rev["ai_diagnosis"] == diag and rev["case_id"] == "NET-007")

        final = accept_review(rev["review_id"], reviewer_notes="OK", store_path=store)
        record("human review does not modify original AI output",
               final["ai_diagnosis"] == original_diag)
        record("stored ai_meta.needs_human_review still True after review",
               get_review(rev["review_id"], store)["ai_meta"].get("needs_human_review") is True)
        record("final human decision stored separately from AI output",
               final["final_diagnosis"] == original_diag
               and final["final_diagnosis"] is not final["ai_diagnosis"])

        # Rule checker findings remain separate from AI diagnosis / human decision.
        from src.rule_checker import check
        rule_findings = check({"hosts": [
            {"name": "PC_A", "ip": "192.168.10.10", "mask": "255.255.255.0",
             "gateway": "192.168.10.1", "dns": "192.168.10.5"},
            {"name": "PC_B", "ip": "192.168.10.10", "mask": "255.255.255.0",
             "gateway": "192.168.10.1", "dns": "192.168.10.5"},
        ]})
        stored_review = get_review(rev["review_id"], store)
        record("rule checker findings are NOT embedded in review record",
               stored_review["ai_diagnosis"].get("rule_findings") is None
               and stored_review["final_diagnosis"].get("rule_findings") is None
               and "rule_findings" not in stored_review)
        record("rule checker detected the duplicate IP independently",
               any(f["rule"] == "duplicate_ip" for f in rule_findings))

        # HumanReview class wrapper works with the same store
        wr = HumanReview(store)
        w_created = wr.create("NET-008", VALID_DIAGNOSIS)
        w_rec = wr.get(w_created["review_id"])
        record("HumanReview class wrapper works", w_created["review_status"] == "pending"
               and w_rec["case_id"] == "NET-008")

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n=========================================")
    print("REVIEW SYSTEM RESULT: %d/%d checks PASSED" % (passed, total))
    print("=========================================")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())