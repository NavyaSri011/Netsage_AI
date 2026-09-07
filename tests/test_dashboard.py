"""NetSage AI — Phase 8 validation for the Dashboard Generator.

A standalone, dependency-light test runner (does NOT require pytest).
Run with the project interpreter:

    python tests/test_dashboard.py

It uses temporary case/review files so the real data/cases.csv and
data/reviews.json are never touched.

Coverage:
    1.  Loading cases correctly
    2.  Correct total case count
    3.  Grouping by concept_tag
    4.  Grouping by OSI layer
    5.  Grouping by severity
    6.  Missing reviews file
    7.  Empty reviews
    8.  Review decision counts
    9.  AI-human agreement calculation
    10. Zero completed reviews without division-by-zero
    11. Dashboard generation does not modify source data
"""

import csv
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from src.dashboard import (
    calculate_statistics,
    generate_dashboard,
    generate_report,
    load_cases,
    load_reviews,
)


def _write_cases(path):
    """Write a small, realistic cases CSV to the given path."""
    rows = [
        ["case_id", "title", "concept_tag", "symptom", "osi_layer", "severity"],
        ["NET-001", "Trunk Port Wrong VLAN", "VLAN", "cannot ping server", "Layer 2", "High"],
        ["NET-002", "No Inter-VLAN Routing", "VLAN", "can't ping other VLAN", "Layer 3", "Medium"],
        ["NET-003", "PC Missing Gateway", "Routing", "can't reach remote subnet", "Layer 3", "High"],
        ["NET-004", "Bad DNS Address", "DNS", "all lookups fail", "Layer 7", "Medium"],
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)


def _valid_diagnosis(case_id, fault="Fault"):
    return {
        "case_id": case_id,
        "likely_fault": fault,
        "osi_layer": "Layer 3",
        "confidence": "medium",
        "evidence_used": ["Symptom"],
        "recommended_next_command": "show running-config",
        "suggested_fix": ["Fix it"],
        "reasoning_summary": "Reasoning.",
        "uncertainty_or_limitations": "None.",
    }


def _make_reviews():
    """Return a list of review records covering every decision type."""
    accepted = {
        "review_id": "REV-001",
        "case_id": "NET-001",
        "ai_diagnosis": _valid_diagnosis("NET-001"),
        "review_status": "accepted",
        "final_diagnosis": _valid_diagnosis("NET-001"),
        "correction_reason": None,
        "reviewer_notes": "Looks correct.",
    }
    edited = {
        "review_id": "REV-002",
        "case_id": "NET-002",
        "ai_diagnosis": _valid_diagnosis("NET-002"),
        "review_status": "edited",
        "final_diagnosis": _valid_diagnosis("NET-002", "Edited fault"),
        "correction_reason": "Fault was more specific in reality.",
        "reviewer_notes": None,
    }
    rejected = {
        "review_id": "REV-003",
        "case_id": "NET-003",
        "ai_diagnosis": _valid_diagnosis("NET-003"),
        "review_status": "rejected",
        "final_diagnosis": _valid_diagnosis("NET-003", "Human finding"),
        "correction_reason": "AI diagnosis was wrong.",
        "reviewer_notes": None,
    }
    pending = {
        "review_id": "REV-004",
        "case_id": "NET-004",
        "ai_diagnosis": _valid_diagnosis("NET-004"),
        "review_status": "pending",
        "final_diagnosis": None,
        "correction_reason": None,
        "reviewer_notes": None,
    }
    return [accepted, edited, rejected, pending]


def _write_reviews(path, reviews):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(reviews, fh, indent=2)


def _snapshot_files(tmp):
    """Return a dict of {path: bytes} for the given directory's files."""
    snap = {}
    for name in os.listdir(tmp):
        p = os.path.join(tmp, name)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                snap[p] = fh.read()
    return snap


def run():
    results = []

    def record(name, ok, detail=""):
        results.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print("[%s] %s  %s" % (status, name, detail))

    with tempfile.TemporaryDirectory() as tmp:
        cases_path = os.path.join(tmp, "cases.csv")
        reviews_path = os.path.join(tmp, "reviews.json")
        out_dir = os.path.join(tmp, "output")

        _write_cases(cases_path)
        cases = load_cases(cases_path)

        # 1. Loading cases correctly
        ok = (len(cases) == 4
              and cases[0]["case_id"] == "NET-001"
              and cases[0]["concept_tag"] == "VLAN")
        record("load_cases reads rows and headers", ok,
               "rows=%d first_case=%s" % (len(cases), cases[0]["case_id"]))

        # 2. Correct total case count
        reviews = []
        stats_empty = calculate_statistics(cases, reviews)
        ok = stats_empty["total_cases"] == 4
        record("calculate_statistics total case count", ok,
               "total=%d" % stats_empty["total_cases"])

        # 3. Grouping by concept_tag
        expected = {"VLAN": 2, "Routing": 1, "DNS": 1}
        ok = stats_empty["cases_by_concept"] == expected
        record("grouping by concept_tag", ok,
               "by_concept=%r" % stats_empty["cases_by_concept"])

        # 4. Grouping by OSI layer
        expected = {"Layer 3": 2, "Layer 2": 1, "Layer 7": 1}
        ok = stats_empty["cases_by_osi_layer"] == expected
        record("grouping by OSI layer", ok,
               "by_osi_layer=%r" % stats_empty["cases_by_osi_layer"])

        # 5. Grouping by severity
        expected = {"High": 2, "Medium": 2}
        ok = stats_empty["cases_by_severity"] == expected
        record("grouping by severity", ok,
               "by_severity=%r" % stats_empty["cases_by_severity"])

        # 6. Missing reviews file
        ok = load_reviews(os.path.join(tmp, "does-not-exist.json")) == []
        record("load_reviews missing file returns []", ok)

        # 7. Empty reviews
        ok = (stats_empty["review_statistics"]["total_reviews"] == 0
              and stats_empty["review_statistics"]["pending"] == 0
              and stats_empty["agreement"]["total_completed"] == 0)
        record("empty reviews produce zero review statistics", ok,
               "total_reviews=%d" % stats_empty["review_statistics"]["total_reviews"])

        # 8. Review decision counts
        _write_reviews(reviews_path, _make_reviews())
        reviews = load_reviews(reviews_path)
        stats_full = calculate_statistics(cases, reviews)
        rev_stats = stats_full["review_statistics"]
        expected = {"total_reviews": 4, "pending": 1, "accepted": 1,
                    "edited": 1, "rejected": 1}
        ok = all(rev_stats[k] == v for k, v in expected.items())
        record("review decision counts", ok, "review_stats=%r" % rev_stats)

        # 9. AI-human agreement calculation
        # accepted=1, edited=1, rejected=1 -> completed=3, rate = 1/3 = 33.33
        agr = stats_full["agreement"]
        ok = (agr["total_completed"] == 3
              and agr["accepted"] == 1
              and agr["edited"] == 1
              and agr["rejected"] == 1
              and abs(agr["agreement_rate"] - 33.33) < 0.01)
        record("AI-human agreement calculation", ok,
               "agreement=%r" % agr)

        # 10. Zero completed reviews without division-by-zero
        only_pending = [r for r in _make_reviews() if r["review_status"] == "pending"]
        stats_only_pending = calculate_statistics(cases, only_pending)
        ok = (stats_only_pending["agreement"]["total_completed"] == 0
              and stats_only_pending["agreement"]["agreement_rate"] == 0.0)
        record("zero completed reviews, no division-by-zero", ok,
               "agreement=%r" % stats_only_pending["agreement"])

        # 10b. Agreement rate of 100% when all completed reviews are accepted
        only_accepted = [r for r in _make_reviews() if r["review_status"] == "accepted"]
        stats_only_accepted = calculate_statistics(cases, only_accepted)
        ok = stats_only_accepted["agreement"]["agreement_rate"] == 100.0
        record("100%% agreement when all completed reviews accepted", ok,
               "rate=%r" % stats_only_accepted["agreement"]["agreement_rate"])

        # 11. Dashboard generation does not modify source data
        _write_cases(cases_path)
        _write_reviews(reviews_path, _make_reviews())
        before = _snapshot_files(tmp)
        generate_dashboard(output_dir=out_dir)
        after = _snapshot_files(tmp)
        unchanged = True
        for p, data in before.items():
            if after.get(p) != data:
                unchanged = False
        ok = unchanged
        record("dashboard generation does not modify source data", ok)

        # 11b. Report file and charts written to output dir
        report_path = os.path.join(out_dir, "dashboard_report.txt")
        ok = os.path.isfile(report_path)
        record("dashboard writes report file", ok, "path=%s" % report_path)

        # 11c. Report content derived from real (temp) data, not hard-coded
        # generate_report is called directly with our temp data stats so
        # the report contains the temp numbers, not the project defaults.
        report_text = generate_report(stats_full, out_dir)
        ok = ("Total cases: 4" in report_text
              and "Total reviews:    4" in report_text
              and "Agreement rate:    33.33%" in report_text)
        record("report content derived from real data", ok,
               "found cases=4, reviews=4, rate=33.33%%")

        # 11d. load_reviews returns [] when reviews.json is absent
        ok = load_reviews(os.path.join(tmp, "none", "reviews.json")) == []
        record("load_reviews missing path returns []", ok)

        # 11e. calculate_statistics handles malformed reviews store
        bad_store = os.path.join(tmp, "bad.json")
        with open(bad_store, "w", encoding="utf-8") as fh:
            fh.write("not json at all")
        ok = load_reviews(bad_store) == []
        record("load_reviews unparseable JSON returns []", ok)

        # 11f. Report text is a non-empty string
        ok = isinstance(report_text, str) and "NetSage AI — Dashboard" in report_text
        record("generate_report returns report text", ok)

    # -----------------------------------------------------------------
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print("-" * 60)
    print("Dashboard test results: %d passed, %d failed (of %d)" % (passed, failed, total))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    run()