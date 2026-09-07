"""NetSage AI — Phase 9 validation for the Responsible AI Log.

A standalone, dependency-light test runner (does NOT require pytest).
Run with the project interpreter:

    python tests/test_responsible_ai_log.py

It uses temporary review stores and log files so the real
data/reviews.json, data/cases.csv, and responsible_ai/ai_corrections.csv
are never touched.

Genuine review records are produced through the actual Human Review
System (src/review.py) to prove the log consumes real data:
    - accepted -> agreement, never logged
    - edited   -> correction, logged
    - rejected -> correction, logged
    - pending  -> excluded

Coverage:
    1.  Edited review is logged as a correction
    2.  Rejected review is logged as a correction
    3.  Accepted review is excluded (agreement)
    4.  Pending review is excluded
    5.  Missing review file -> empty log, no crash
    6.  Empty review list -> empty log
    7.  Unparseable review file -> empty log
    8.  Missing correction reason (defensive) still produces an entry
    9.  Duplicate prevention when the log is regenerated
    10. Source review data remains unchanged
    11. Log structure: doc comments preserved, original schema columns kept
    12. Logged entry carries full traceability fields
    13. Deterministic lesson learned
"""

import csv
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.diagnosis_engine import DIAGNOSIS_KEYS
from src.responsible_ai_log import (
    LOG_HEADER,
    extract_corrections,
    generate_log,
    load_existing_entries,
    load_reviews,
)
from src.review import accept_review, create_review, edit_review, reject_review

ORIGINAL_COLUMNS = [
    "case_id",
    "ai_diagnosis",
    "human_decision",
    "correction_made",
    "reason_ai_was_incorrect",
    "final_approved_diagnosis",
    "lesson_learned",
]


def _diag(case_id, fault):
    """Build a valid 9-field diagnosis dict."""
    return {
        "case_id": case_id,
        "likely_fault": fault,
        "osi_layer": "Layer 2",
        "confidence": "medium",
        "evidence_used": ["Symptom: host cannot reach server in VLAN"],
        "recommended_next_command": "show interfaces switchport",
        "suggested_fix": ["Reassign the port to the correct VLAN"],
        "reasoning_summary": "Port-level issue is the most probable cause.",
        "uncertainty_or_limitations": "No command output captured yet.",
    }


def _build_review_store(path):
    """Create genuine review records via the Human Review System.

    Returns a tuple (store_path, review_ids) for one accepted review,
    two edited reviews, one rejected review, and one pending review.
    """
    store = path

    acc = create_review("NET-101", _diag("NET-101", "Wrong VLAN on access port"),
                        {"source": "test"}, store_path=store)
    accept_review(acc["review_id"], reviewer_notes="AI diagnosis confirmed.",
                  store_path=store)

    ed1 = create_review("NET-102", _diag("NET-102", "Wrong VLAN on access port"),
                        {"source": "test"}, store_path=store)
    edit_review(ed1["review_id"],
                _diag("NET-102", "No inter-VLAN routing configured on the SVIs"),
                "The port already has the correct VLAN; routing to the next VLAN is missing.",
                reviewer_notes="Checked switching config first.", store_path=store)

    ed2 = create_review("NET-103", _diag("NET-103", "Wrong VLAN on access port"),
                        {"source": "test"}, store_path=store)
    edit_review(ed2["review_id"],
                _diag("NET-103", "DHCP scope exhausted on the server"),
                "Ports are correct; the DHCP pool is out of addresses.",
                reviewer_notes=None, store_path=store)

    rej = create_review("NET-104", _diag("NET-104", "Bad DNS server address"),
                        {"source": "test"}, store_path=store)
    reject_review(rej["review_id"],
                  "DNS settings are correct; the actual fault was the default gateway on the PC.",
                  final_diagnosis=_diag("NET-104", "Default gateway missing on the PC"),
                  reviewer_notes="Traced with ipconfig and ping.", store_path=store)

    pend = create_review("NET-105", _diag("NET-105", "Duplicate IP address"),
                         {"source": "test"}, store_path=store)

    return store, {
        "accepted": acc["review_id"],
        "edited_1": ed1["review_id"],
        "edited_2": ed2["review_id"],
        "rejected": rej["review_id"],
        "pending": pend["review_id"],
    }


def _read_log_rows(path):
    """Read logged data rows from the log file (skips comments/header)."""
    with open(path, newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.reader(lines))


def run():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        print("  %-58s %s" % (name, "PASS" if ok else "FAIL") + ("  [%s]" % detail if detail else ""))

    print("NetSage AI — Responsible AI Log validation")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="netsage_p9_") as tmp:
        store = os.path.join(tmp, "reviews.json")
        _, rid = _build_review_store(store)

        # -------------------------------------------------------------
        # 1-4. Correction identification from genuine review records
        corrections = extract_corrections(load_reviews(store))
        by_review_id = {e["review_id"]: e for e in corrections}

        ok = rid["edited_1"] in by_review_id and rid["edited_2"] in by_review_id
        record("edited reviews logged as corrections", ok,
               "edited=%s,%s" % (rid["edited_1"], rid["edited_2"]))

        ok = rid["rejected"] in by_review_id
        record("rejected review logged as correction", ok, "rejected=%s" % rid["rejected"])

        ok = rid["accepted"] not in by_review_id
        record("accepted review excluded (agreement)", ok)

        ok = rid["pending"] not in by_review_id
        record("pending review excluded", ok)

        # -------------------------------------------------------------
        # 8. Missing correction reason (defensive path)
        raw = copy.deepcopy(load_reviews(store))
        raw.append({
            "review_id": "REV-X01",
            "case_id": "NET-900",
            "ai_diagnosis": _diag("NET-900", "Wrong port speed"),
            "review_status": "edited",
            "final_diagnosis": _diag("NET-900", "Bad cable"),
            "correction_reason": "",
            "reviewer_notes": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "reviewed_at": "2026-01-01T00:00:01+00:00",
        })
        entries = extract_corrections(raw)
        missing = [e for e in entries if e["review_id"] == "REV-X01"]
        ok = len(missing) == 1 and missing[0]["reason_ai_was_incorrect"] == ""
        record("missing correction reason handled (empty cell, no crash)", ok)

        # -------------------------------------------------------------
        # 5-7. Missing / empty / unparseable review data
        summary = generate_log(reviews_path=os.path.join(tmp, "nope", "reviews.json"),
                               log_path=os.path.join(tmp, "log_missing.csv"))
        ok = (summary["reviews_seen"] == 0 and summary["total_entries"] == 0
              and os.path.isfile(os.path.join(tmp, "log_missing.csv")))
        record("missing review file -> empty log, file still written", ok)

        empty_store = os.path.join(tmp, "empty.json")
        with open(empty_store, "w", encoding="utf-8") as fh:
            fh.write("[]")
        summary = generate_log(reviews_path=empty_store,
                               log_path=os.path.join(tmp, "log_empty.csv"))
        ok = summary["reviews_seen"] == 0 and summary["total_entries"] == 0
        record("empty review list -> empty log", ok)

        bad_store = os.path.join(tmp, "bad.json")
        with open(bad_store, "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        ok = load_reviews(bad_store) == []
        record("unparseable review file -> empty list, no crash", ok)

        # -------------------------------------------------------------
        # 9. Duplicate prevention on regeneration
        log_path = os.path.join(tmp, "log.csv")
        s1 = generate_log(reviews_path=store, log_path=log_path)
        s2 = generate_log(reviews_path=store, log_path=log_path)
        rows = _read_log_rows(log_path)
        data_rows = rows[1:]
        ok = (s1["new_entries"] == 3 and s2["new_entries"] == 0
              and len(data_rows) == 3
              and s1["total_entries"] == s2["total_entries"] == 3)
        record("regeneration adds no duplicates (3 corrections, idempotent)", ok,
               "run1=%d new, run2=%d new, rows=%d" % (s1["new_entries"], s2["new_entries"], len(data_rows)))

        # -------------------------------------------------------------
        # 10. Source review data remains unchanged
        before = open(store, "rb").read()
        generate_log(reviews_path=store, log_path=os.path.join(tmp, "log2.csv"))
        after = open(store, "rb").read()
        ok = before == after
        record("source review store unchanged after generate_log", ok)

        reviews_before = copy.deepcopy(load_reviews(store))
        extract_corrections(reviews_before)
        ok = reviews_before == load_reviews(store)
        record("extract_corrections is pure (no mutation of inputs)", ok)

        # -------------------------------------------------------------
        # 11. Log structure: doc comments + header, original columns kept
        with open(log_path, "r", encoding="utf-8") as fh:
            raw_text = fh.read()
            first_lines = raw_text.splitlines()[:3]
        ok = all(ln.startswith("#") for ln in first_lines)
        record("log file opens with documentation comment block", ok)

        rows = _read_log_rows(log_path)
        header = [h.strip() for h in rows[0]]
        ok = header == LOG_HEADER
        record("header row matches LOG_HEADER exactly", ok)

        ok = all(col in LOG_HEADER for col in ORIGINAL_COLUMNS)
        record("original placeholder schema columns retained", ok,
               "orig_cols=%d kept" % len(ORIGINAL_COLUMNS))

        # -------------------------------------------------------------
        # 12. Traceability fields present and populated
        entries = load_existing_entries(log_path)
        by_id = {e["review_id"]: e for e in entries}
        edited_entry = by_id.get(rid["edited_1"])
        ok = (edited_entry is not None
              and edited_entry["review_id"] == rid["edited_1"]
              and edited_entry["case_id"] == "NET-102"
              and edited_entry["human_decision"] == "Edited"
              and edited_entry["reason_ai_was_incorrect"]
              and edited_entry["reviewer_notes"] == "Checked switching config first."
              and bool(edited_entry["reviewed_at"]))
        record("edited entry carries review_id/reason/notes/timestamp", ok)

        rejected_entry = by_id.get(rid["rejected"])
        ok = (rejected_entry is not None
              and rejected_entry["human_decision"] == "Rejected"
              and "gateway" in rejected_entry["final_approved_diagnosis"].lower())
        record("rejected entry records human-approved final diagnosis", ok)

        ok = (rejected_entry["human_decision"] == "Rejected"
              and rejected_entry["lesson_learned"].startswith("Lesson:")
              and "root-cause hypothesis" in rejected_entry["lesson_learned"])
        record("lessons learned are deterministic sentences", ok)

        # -------------------------------------------------------------
        # 13. Deterministic lesson learned / briefs
        e1 = by_id[rid["edited_1"]]
        e1b = extract_corrections(load_reviews(store))
        twin = next(e for e in e1b if e["review_id"] == rid["edited_1"])
        ok = (e1["lesson_learned"] == twin["lesson_learned"]
              and e1["ai_diagnosis"] == twin["ai_diagnosis"]
              and e1["correction_made"] == twin["correction_made"])
        record("lesson/diagnosis/correction fields deterministic across runs", ok)

        ok = ("Wrong VLAN" in e1["ai_diagnosis"]
              and "inter-VLAN routing" in e1["final_approved_diagnosis"])
        record("ai_diagnosis and final_diagnosis describe real records", ok)

    # -----------------------------------------------------------------
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print("-" * 60)
    print("Responsible AI Log test results: %d passed, %d failed (of %d)"
          % (passed, failed, total))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run()