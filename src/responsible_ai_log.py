"""NetSage AI — Responsible AI Log.

Phase 9 implementation.

Records REAL human corrections of AI diagnoses. Corrections are derived
exclusively from genuine human review records produced by the Human Review
System (src/review.py, data/reviews.json).

Correction rules (aligned with the review.py data model):
    - accepted  -> agreement, NOT an AI correction (excluded)
    - edited    -> AI correction (logged)
    - rejected  -> AI correction (logged)
    - pending   -> still awaiting human review (excluded)

Primary output: responsible_ai/ai_corrections.csv

    The columns reuse the schema established by the Phase 9 placeholder file
    (case_id, ai_diagnosis, human_decision, correction_made,
    reason_ai_was_incorrect, final_approved_diagnosis, lesson_learned) and
    extend it with three traceability fields required by this phase
    (review_id, reviewer_notes, reviewed_at).

Integrity guarantees
--------------------
    - NEVER modifies data/cases.csv, original AI diagnoses, or human review
      records.  All review data is loaded and passed by value.
    - Missing or empty review files produce an empty log (no crash).
    - Regenerating the log is idempotent: already-logged review_ids are
      skipped, so no duplicate entries are created.
    - Nothing is fabricated: entries exist only when a human actually edited
      or rejected an AI diagnosis.

Public API
----------
    load_reviews(path=None)             -> list[dict]
    extract_corrections(reviews)        -> list[dict]  (pure, no I/O)
    load_existing_entries(path=None)    -> list[dict]
    generate_log(reviews_path=None, log_path=None) -> dict
"""

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

# Make imports work when run as a standalone script or as a package.
if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.diagnosis_engine import DIAGNOSIS_KEYS

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_REVIEWS_FILE = os.path.join(_PROJECT_ROOT, "data", "reviews.json")
DEFAULT_LOG_FILE = os.path.join(_PROJECT_ROOT, "responsible_ai", "ai_corrections.csv")

# Review statuses that represent a human correction of the AI diagnosis.
CORRECTION_STATUSES = ("edited", "rejected")

# Log columns.  The first seven reuse the Phase 9 placeholder schema;
# the final three add the traceability fields required by this phase.
LOG_HEADER = [
    "case_id",
    "ai_diagnosis",
    "human_decision",
    "correction_made",
    "reason_ai_was_incorrect",
    "final_approved_diagnosis",
    "lesson_learned",
    "review_id",
    "reviewer_notes",
    "reviewed_at",
]

STATUS_LABELS = {
    "pending": "Pending",
    "accepted": "Accepted",
    "edited": "Edited",
    "rejected": "Rejected",
}

DOC_COMMENT = [
    "# ============================================================",
    "# NetSage AI — Responsible AI Log",
    "# ============================================================",
    "# Purpose:",
    "#   Record cases where an AI diagnosis required human correction.",
    "#",
    "# Rows are generated ONLY from genuine human review records",
    "# (data/reviews.json). Nothing is fabricated.",
    "#",
    "# Columns:",
    "#   case_id                  — Reference to the case in data/cases.csv",
    "#   ai_diagnosis             — What the AI diagnosed (brief)",
    "#   human_decision           — Accepted / Edited / Rejected",
    "#   correction_made          — What the human changed",
    "#   reason_ai_was_incorrect  — Why the AI was wrong/incomplete",
    "#   final_approved_diagnosis — The human-approved final diagnosis",
    "#   lesson_learned           — What the correction taught us",
    "#   review_id                — Reference to the review in data/reviews.json",
    "#   reviewer_notes           — Notes left by the human reviewer",
    "#   reviewed_at              — ISO timestamp of the human decision",
    "#",
    "# RULES:",
    "#   accepted = agreement (never logged); pending = excluded;",
    "#   edited/rejected = corrections (logged).",
    "#   Regenerating this log does not create duplicates.",
    "# ============================================================",
]


def _now():
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------
# Loading review records (safe, read-only)
# ----------------------------------------------------------------------

def load_reviews(path=None):
    """Load all human review records from a JSON file.

    Args:
        path: Path to the reviews JSON store.  Defaults to
              data/reviews.json.

    Returns:
        A list of review record dicts.  Returns an empty list when the
        file does not exist, is empty, or cannot be parsed — the module
        must never crash because review data is missing or malformed.
    """
    path = path or DEFAULT_REVIEWS_FILE
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


# ----------------------------------------------------------------------
# Pure transformation helpers (no file I/O)
# ----------------------------------------------------------------------

def _as_dict(value):
    """Coerce a stored diagnosis value into a dict ({} when invalid)."""
    return value if isinstance(value, dict) else {}


def _humanize(value):
    """Render a diagnosis field value as a compact string."""
    if value is None:
        return "none"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value) if value else "none"
    return str(value).strip()


def _brief(diagnosis):
    """One-line deterministic summary of a diagnosis dict."""
    diag = _as_dict(diagnosis)
    if not diag:
        return "none"
    bits = []
    fault = str(diag.get("likely_fault") or "").strip()
    if fault:
        bits.append(fault)
    parts = []
    layer = str(diag.get("osi_layer") or "").strip()
    conf = str(diag.get("confidence") or "").strip()
    if layer:
        parts.append(layer)
    if conf:
        parts.append("confidence=" + conf)
    if parts:
        bits.append("(" + "; ".join(parts) + ")")
    return " ".join(bits) if bits else str(diagnosis)


def _correction_made(review):
    """Describe, deterministically, what the human changed vs. the AI."""
    ai = _as_dict(review.get("ai_diagnosis"))
    final = _as_dict(review.get("final_diagnosis"))
    if not ai and not final:
        return "Human decision overrides the AI diagnosis."
    if not final:
        return "AI diagnosis rejected; no alternative final diagnosis recorded."
    changes = []
    for key in DIAGNOSIS_KEYS:
        a = ai.get(key)
        f = final.get(key)
        if a != f:
            changes.append("%s: '%s' -> '%s'"
                           % (key.replace("_", " "), _humanize(a), _humanize(f)))
    if not changes:
        return "Final diagnosis differs from but mirrors the AI diagnosis."
    return " | ".join(changes)


def _lesson_learned(review):
    """Deterministic lesson learned derived from the actual correction."""
    status = str(review.get("review_status") or "")
    ai = _as_dict(review.get("ai_diagnosis"))
    final = _as_dict(review.get("final_diagnosis"))
    lessons = []
    if ai.get("likely_fault") != final.get("likely_fault"):
        lessons.append("the AI root-cause hypothesis required human correction")
    if ai.get("osi_layer") != final.get("osi_layer"):
        lessons.append("the AI misclassified the problem OSI layer")
    if ai.get("confidence") != final.get("confidence"):
        lessons.append("the AI confidence estimate did not match human judgment")
    if ai.get("suggested_fix") != final.get("suggested_fix"):
        lessons.append("the AI suggested fix did not address the verified root cause")
    if not ai and final and status == "rejected":
        lessons.append("the AI finding was discarded in favor of a human diagnosis")
    if not lessons:
        base = ("the human reviewer rejected the AI diagnosis"
                if status == "rejected"
                else "the human reviewer corrected the AI diagnosis")
        lessons.append(base)
    return "Lesson: %s." % "; ".join(lessons)


def _entry_from_review(review):
    """Build one log entry (dict) from a genuine review record."""
    status = str(review.get("review_status") or "")
    reason = review.get("correction_reason")
    notes = review.get("reviewer_notes")
    return {
        "case_id": str(review.get("case_id") or ""),
        "ai_diagnosis": _brief(review.get("ai_diagnosis")),
        "human_decision": STATUS_LABELS.get(status, status.capitalize()),
        "correction_made": _correction_made(review),
        "reason_ai_was_incorrect": "" if reason is None else str(reason).strip(),
        "final_approved_diagnosis": _brief(review.get("final_diagnosis")),
        "lesson_learned": _lesson_learned(review),
        "review_id": str(review.get("review_id") or ""),
        "reviewer_notes": "" if notes is None else str(notes).strip(),
        "reviewed_at": str(review.get("reviewed_at") or review.get("created_at") or ""),
    }


def extract_corrections(reviews, statuses=CORRECTION_STATUSES):
    """Return log entries for every genuine human correction.

    Pure function: performs no file I/O and never mutates the input
    review records.

    Args:
        reviews: List of review record dicts.
        statuses: Statuses treated as corrections (default edited/rejected).

    Returns:
        A list of log entry dicts, sorted by review_id for determinism.
        Accepted and pending reviews are excluded.
    """
    entries = []
    for review in reviews or []:
        if not isinstance(review, dict):
            continue
        status = str(review.get("review_status") or "")
        if status in statuses:
            entries.append(_entry_from_review(review))
    entries.sort(key=lambda e: (e["review_id"], e["case_id"]))
    return entries


# ----------------------------------------------------------------------
# Reading/writing the CSV log
# ----------------------------------------------------------------------

def _read_csv_rows(path):
    """Read a CSV file skipping blank lines and '#' comment rows."""
    with open(path, newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.reader(lines))


def _encode_row(row):
    """CSV-encode a list of cell values without a trailing newline."""
    out = io.StringIO()
    csv.writer(out, lineterminator="").writerow(row)
    return out.getvalue()


def load_existing_entries(path=None):
    """Load previously logged entries from the CSV log file.

    Robust to the documented comment/header layout: comment lines are
    skipped wherever they appear, the first remaining row is the header.

    Returns:
        A list of entry dicts (keyed by the file's header).  Empty list
        when the file is missing or has no usable header.
    """
    path = path or DEFAULT_LOG_FILE
    if not os.path.isfile(path):
        return []
    try:
        rows = _read_csv_rows(path)
    except OSError:
        return []
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    if not header or header[0] != "case_id":
        return []
    entries = []
    for row in rows[1:]:
        if not row:
            continue
        cell = [c.strip() for c in row]
        if not any(cell):
            continue
        entries.append(dict(zip(header, cell)))
    return entries


def _dedup_key(entry):
    """Identity key for deduplication, preferring the review_id."""
    review_id = str(entry.get("review_id") or "").strip()
    if review_id:
        return ("review_id", review_id)
    # Legacy entry (no review_id): fall back to a content-based key.
    return ("legacy", "%s|%s|%s" % (
        str(entry.get("case_id") or ""),
        str(entry.get("reviewed_at") or ""),
        str(entry.get("reason_ai_was_incorrect") or ""),
    ))


def _write_log(path, entries):
    """Atomically write the log file: doc comment block, header, entries."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    lines = []
    lines.extend(DOC_COMMENT)
    lines.append(_encode_row(LOG_HEADER))
    for entry in entries:
        row = [str(entry.get(col) or "") for col in LOG_HEADER]
        lines.append(_encode_row(row))
    text = "\n".join(lines) + "\n"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def generate_log(reviews_path=None, log_path=None):
    """Regenerate the responsible AI log from genuine review records.

    Reads human review records, extracts every edited/rejected AI diagnosis,
    merges them into the existing log (skipping review_ids already logged),
    and writes the log file atomically.

    Args:
        reviews_path: Path to the reviews store.  Defaults to
                      data/reviews.json.
        log_path: Path to the log CSV.  Defaults to
                  responsible_ai/ai_corrections.csv.

    Returns:
        A dict: reviews_seen, corrections_found, existing_entries,
        new_entries, total_entries, log_path.
    """
    reviews_path = reviews_path or DEFAULT_REVIEWS_FILE
    log_path = log_path or DEFAULT_LOG_FILE

    reviews = load_reviews(reviews_path)
    corrections = extract_corrections(reviews)
    existing = load_existing_entries(log_path)

    seen = set()
    merged = []
    for entry in existing:
        key = _dedup_key(entry)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)

    new_entries = 0
    for entry in corrections:
        key = _dedup_key(entry)
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
        new_entries += 1

    merged.sort(key=lambda e: (e.get("review_id") or "", e.get("case_id") or ""))
    _write_log(log_path, merged)

    return {
        "reviews_seen": len(reviews),
        "corrections_found": len(corrections),
        "existing_entries": len(existing),
        "new_entries": new_entries,
        "total_entries": len(merged),
        "log_path": log_path,
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

if __name__ == "__main__":
    summary = generate_log()
    print("NetSage AI — Responsible AI Log")
    print("=" * 60)
    print("Reviews examined:      %d" % summary["reviews_seen"])
    print("Corrections found:     %d" % summary["corrections_found"])
    print("Existing entries:      %d" % summary["existing_entries"])
    print("New entries logged:    %d" % summary["new_entries"])
    print("Total log entries:     %d" % summary["total_entries"])
    print("Log file:              %s" % summary["log_path"])
    print("=" * 60)