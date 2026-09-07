"""NetSage AI — Phase 11 Demo Runner.

Runs the COMPLETE pipeline end-to-end for presentation purposes:

    Case → Rule Checker → AI Diagnosis → Human Review
        → Responsible AI Log → Dashboard

It reads the REAL 33-case dataset (data/cases.csv) so the presenter can show
genuine project data, but it uses TEMPORARY review stores and log files so
the real project review data is never modified:

    - data/cases.csv               : READ ONLY (never touched)
    - data/reviews.json            : NOT used (temp store instead)
    - responsible_ai/ai_corrections.csv : NOT used (temp log instead)

This demo is reproducible and honest:
    - The AI diagnosis engine runs in demo mode and labels its output as
      simulated; no genuine-AI results are fabricated.
    - Review decisions (accept/edit/reject + pending) are created by this
      script as walkthrough examples, not derived from real human reviews.
    - The Responsible AI Log contains ONLY the edited/rejected examples the
      script creates, clearly rooted in this run's temporary review store.

Run:
    py -3.12 demo\run_demo.py
"""

import json
import os
import sys
import tempfile

# Make project imports work when run as a script from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dashboard import calculate_statistics
from src.diagnosis_engine import DiagnosisEngine
from src.dashboard import load_reviews as dash_load_reviews
from src.rule_checker import CLEAN_CONFIG, SAMPLE_BAD_GATEWAY, SAMPLE_DUPLICATE_IP, check
from src.responsible_ai_log import generate_log, load_existing_entries
from src.review import (
    accept_review,
    create_review,
    edit_review,
    list_reviews,
    reject_review,
)


def _line(char="=", width=70):
    print(char * width)


def step(title):
    print()
    _line()
    print(title)
    _line()


def _show(diag):
    print(json.dumps(diag, indent=2))


def main():
    print("NetSage AI — Full-Pipeline Demo")
    _line()
    print("Reading: data/cases.csv (real 33-case dataset)")
    print("Using:   temporary review store + log (real project data untouched)")

    demo_store = os.path.join(tempfile.gettempdir(), "netsage_demo_reviews.json")
    demo_log = os.path.join(tempfile.gettempdir(), "netsage_demo_corrections.csv")
    for f in (demo_store, demo_log):
        if os.path.isfile(f):
            os.remove(f)

    engine = DiagnosisEngine()

    # ------------------------------------------------------------------
    step("STEP 1 — Loading a network case (real data/cases.csv)")
    case = engine.load_case("NET-001")
    print("case_id       :", case["case_id"])
    print("title         :", case["title"])
    print("concept_tag   :", case["concept_tag"])
    print("symptom       :", case["symptom"])
    print("osi_layer     :", case["osi_layer"])
    print("severity      :", case["severity"])

    # ------------------------------------------------------------------
    step("STEP 2 — Rule Checker (deterministic, no AI)")
    print("Duplicate IP config:")
    for f in check(SAMPLE_DUPLICATE_IP):
        print("  [%s] %s" % (f["rule"], f["message"]))
    print("\nBad gateway config:")
    for f in check(SAMPLE_BAD_GATEWAY):
        print("  [%s] %s" % (f["rule"], f["message"]))
    print("\nClean config:")
    print("  findings:", check(CLEAN_CONFIG))

    # ------------------------------------------------------------------
    step("STEP 3 — AI Diagnosis (demo mode, clearly labeled simulated)")
    diag, meta = engine.diagnose(case, force_demo=True)
    print("meta:", json.dumps(meta))
    print("\ndiagnosis (9-field schema):")
    _show(diag)

    # ------------------------------------------------------------------
    step("STEP 4 — Mandatory Human Review (accept / edit / reject / pending)")
    review_ids = {}

    rid = create_review("NET-001", diag, meta, store_path=demo_store)["review_id"]
    accept_review(rid, reviewer_notes="Accepted by engineer review.", store_path=demo_store)
    review_ids["accepted"] = rid

    diag2, meta2 = engine.diagnose(engine.load_case("NET-002"), force_demo=True)
    rid = create_review("NET-002", diag2, meta2, store_path=demo_store)["review_id"]
    edited = {
        "case_id": "NET-002",
        "likely_fault": "Inter-VLAN routing not configured between VLAN 10 and VLAN 20.",
        "osi_layer": "Layer 3",
        "confidence": "high",
        "evidence_used": ["Hosts within a VLAN can ping; cross-VLAN cannot."],
        "recommended_next_command": "show ip route",
        "suggested_fix": ["Configure SVIs or router-on-a-stick for inter-VLAN routing."],
        "reasoning_summary": "Layer 3 routing between VLANs is missing.",
        "uncertainty_or_limitations": "Requires live command confirmation.",
    }
    edit_review(rid, edited, "AI mislabeled the fault; correct VLAN-to-VLAN routing fix.",
                reviewer_notes="Edited by engineer.", store_path=demo_store)
    review_ids["edited"] = rid

    diag3, meta3 = engine.diagnose(engine.load_case("NET-003"), force_demo=True)
    rid = create_review("NET-003", diag3, meta3, store_path=demo_store)["review_id"]
    rejected_final = {
        "case_id": "NET-003",
        "likely_fault": "PC default gateway set to the wrong router interface.",
        "osi_layer": "Layer 3",
        "confidence": "high",
        "evidence_used": ["ipconfig /all shows a gateway outside the PC's network."],
        "recommended_next_command": "ipconfig /all",
        "suggested_fix": ["Set the correct default gateway."],
        "reasoning_summary": "Gateway mismatch confirmed from host config.",
        "uncertainty_or_limitations": "None.",
    }
    reject_review(rid, "AI hypothesis was incorrect; gateway is the verified cause.",
                  final_diagnosis=rejected_final, reviewer_notes="Rejected by engineer.",
                  store_path=demo_store)
    review_ids["rejected"] = rid

    diag4, meta4 = engine.diagnose(engine.load_case("NET-004"), force_demo=True)
    rid = create_review("NET-004", diag4, meta4, store_path=demo_store)["review_id"]
    review_ids["pending"] = rid

    print("Created reviews:")
    for status, rid in review_ids.items():
        print("  %-8s : %s" % (status, rid))

    print("\nDecision counts from the review store:")
    counts = {}
    for r in list_reviews(store_path=demo_store):
        counts[r["review_status"]] = counts.get(r["review_status"], 0) + 1
    print("  ", counts)

    # ------------------------------------------------------------------
    step("STEP 5 — Responsible AI Log (only edited + rejected corrections)")
    summary = generate_log(reviews_path=demo_store, log_path=demo_log)
    print("Reviews examined :", summary["reviews_seen"])
    print("Corrections found:", summary["corrections_found"])
    print("New entries      :", summary["new_entries"])
    print()
    for entry in load_existing_entries(demo_log):
        print("  case_id=%s  decision=%s  review=%s" % (
            entry["case_id"], entry["human_decision"], entry["review_id"]))
        print("    ai       :", entry["ai_diagnosis"][:70])
        print("    final    :", entry["final_approved_diagnosis"][:70])
        print("    reason   :", entry["reason_ai_was_incorrect"][:70])
        print("    lesson   :", entry["lesson_learned"][:70])

    # ------------------------------------------------------------------
    step("STEP 6 — Dashboard statistics (derived live from the demo data)")
    cases = engine.load_all_cases()
    reviews = dash_load_reviews(demo_store)
    stats = calculate_statistics(cases, reviews)
    rev = stats["review_statistics"]
    agr = stats["agreement"]
    print("Total cases     :", stats["total_cases"])
    print("Reviews         : total=%d  pending=%d  accepted=%d  edited=%d  rejected=%d" % (
        rev["total_reviews"], rev["pending"], rev["accepted"], rev["edited"], rev["rejected"]))
    print("Agreement rate  : %.2f%%  (accepted=%d of %d completed; edited+rejected=disagreement)"
          % (agr["agreement_rate"], agr["accepted"], agr["total_completed"]))

    print()
    _line()
    print("Demo complete. Pipeline demonstrated end-to-end.")
    print("Real project data (data/*, responsible_ai/*) was NOT modified.")
    _line()

    # Clean up the temporary demo files we created.
    for f in (demo_store, demo_log):
        if os.path.isfile(f):
            os.remove(f)
            print("Cleaned up temp demo file:", f)


if __name__ == "__main__":
    main()
