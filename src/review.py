"""NetSage AI — Human Review System.

Phase 7 implementation.

Every AI diagnosis produced by the diagnosis engine is only a RECOMMENDATION.
This module implements the human review workflow that turns a recommendation
into a final, human-approved decision.

Workflow
--------

    AI Diagnosis  ──►  Pending Human Review  ──►  Accept / Edit / Reject
                                                       │
                                                       ▼
                                            Final Human Decision

Review statuses
---------------
    - pending   : awaiting human review (initial state for every new diagnosis)
    - accepted  : human approved the AI diagnosis as-is
    - edited    : human changed the AI diagnosis; edited version becomes final
    - rejected  : human rejected the AI diagnosis; an optional human finding
                  may be recorded as the final decision

Immutability
------------
    The original AI diagnosis is ALWAYS preserved unchanged. All inputs are
    deep-copied when stored and when returned, so neither the caller's dicts
    nor the stored records can be silently mutated. Human decisions are always
    final and the AI output is never used to overwrite them.

Storage
-------
    Reviews are persisted as a JSON array of records in data/reviews.json
    (one record per review). JSON is used because each record contains nested
    structured data (the 9-field diagnosis). The default location can be
    overridden via the `store_path` argument so tests and tools can use a
    temporary store. Phase 8 (Dashboard) and Phase 9 (Responsible AI Log) will
    consume these records.
"""

import copy
import json
import os
import sys
from datetime import datetime, timezone

# Allow running as a standalone script (python src/review.py) or as a package.
if __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.diagnosis_engine import DIAGNOSIS_KEYS

# Valid review transition states.
REVIEW_STATUSES = ("pending", "accepted", "edited", "rejected")

# Default store location: <project_root>/data/reviews.json
DEFAULT_REVIEWS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "reviews.json",
)


class ReviewValidationError(Exception):
    """Raised when a review operation receives invalid input."""


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------

def _now():
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _validate_diagnosis_dict(obj, label):
    """Light validation: a diagnosis must be a dict with all 9 required keys."""
    if not isinstance(obj, dict):
        raise ReviewValidationError("%s must be a dict, got %s." % (label, type(obj).__name__))
    missing = [k for k in DIAGNOSIS_KEYS if k not in obj]
    if missing:
        raise ReviewValidationError(
            "%s missing required diagnosis key(s): %s" % (label, ", ".join(missing)))


def _load_store(path):
    """Load the review records list from a JSON file (empty list if none)."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ReviewValidationError(
            "Could not parse reviews store %s: %s" % (path, exc))
    if not isinstance(data, list):
        raise ReviewValidationError(
            "Reviews store is not a JSON list of records: %s" % path)
    return data


def _save_store(path, records):
    """Atomically persist the reviews list to a JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _next_review_id(records, case_id):
    """Generate the next deterministic review_id, e.g. REV-001."""
    max_num = 0
    for rec in records:
        rid = str(rec.get("review_id", ""))
        if rid.startswith("REV-"):
            try:
                max_num = max(max_num, int(rid[len("REV-"):]))
            except ValueError:
                pass
    return "REV-%03d" % (max_num + 1)


def _find_record(records, review_id):
    for rec in records:
        if rec.get("review_id") == review_id:
            return rec
    return None


def _require_pending(record):
    """A review must be pending before it can be acted upon."""
    if record["review_status"] != "pending":
        raise ReviewValidationError(
            "Review %s is already %s; it cannot be re-reviewed."
            % (record["review_id"], record["review_status"]))


def _require_reason(reason):
    """correction_reason is mandatory for edits and rejections."""
    if not reason or not str(reason).strip():
        raise ReviewValidationError("correction_reason is required.")


# ----------------------------------------------------------------------
# Public API (function style, convenient for a UI/dashboard)
# ----------------------------------------------------------------------

def create_review(case_id, ai_diagnosis, ai_meta=None, store_path=DEFAULT_REVIEWS_FILE):
    """Register a new AI diagnosis as a pending human review.

    Args:
        case_id: The case identifier from data/cases.csv.
        ai_diagnosis: The validated 9-field AI diagnosis dict.
        ai_meta: Optional metadata dict from the diagnosis engine (e.g.
            {"source": "demo", "needs_human_review": True}). The stored copy
            is forced to keep needs_human_review=True.
        store_path: JSON store path (default data/reviews.json).

    Returns:
        The newly created review record (pending).
    """
    case_id = str(case_id).strip()
    if not case_id:
        raise ReviewValidationError("case_id is required.")
    _validate_diagnosis_dict(ai_diagnosis, "ai_diagnosis")

    ai_meta = {} if ai_meta is None else ai_meta
    if not isinstance(ai_meta, dict):
        raise ReviewValidationError("ai_meta must be a dict, got %s." % type(ai_meta).__name__)
    meta = copy.deepcopy(ai_meta)
    meta["needs_human_review"] = True  # invariant: always True until reviewed

    records = _load_store(store_path)
    record = {
        "review_id": _next_review_id(records, case_id),
        "case_id": case_id,
        "ai_diagnosis": copy.deepcopy(ai_diagnosis),
        "ai_meta": meta,
        "review_status": "pending",
        "final_diagnosis": None,
        "correction_reason": None,
        "reviewer_notes": None,
        "created_at": _now(),
        "reviewed_at": None,
    }
    records.append(record)
    _save_store(store_path, records)
    return copy.deepcopy(record)


def accept_review(review_id, reviewer_notes=None, store_path=DEFAULT_REVIEWS_FILE):
    """Accept a pending AI diagnosis as the final human-approved decision.

    The AI diagnosis is preserved unchanged; the final_diagnosis is set to an
    exact copy of the original AI diagnosis (an accept does not allow silently
    modifying the AI output).

    Returns:
        The updated review record with review_status == "accepted".
    """
    records = _load_store(store_path)
    record = _find_record(records, review_id)
    if record is None:
        raise ReviewValidationError("Unknown review_id: %s" % review_id)
    _require_pending(record)

    record["review_status"] = "accepted"
    record["final_diagnosis"] = copy.deepcopy(record["ai_diagnosis"])
    record["reviewer_notes"] = None if reviewer_notes is None else str(reviewer_notes).strip()
    record["reviewed_at"] = _now()

    _save_store(store_path, records)
    return copy.deepcopy(record)


def edit_review(review_id, edited_diagnosis, correction_reason, reviewer_notes=None,
                store_path=DEFAULT_REVIEWS_FILE):
    """Edit a pending AI diagnosis; the human-edited diagnosis becomes final.

    The original AI diagnosis is preserved untouched. A correction_reason is
    mandatory.

    Returns:
        The updated review record with review_status == "edited".
    """
    records = _load_store(store_path)
    record = _find_record(records, review_id)
    if record is None:
        raise ReviewValidationError("Unknown review_id: %s" % review_id)
    _require_pending(record)
    _validate_diagnosis_dict(edited_diagnosis, "edited_diagnosis")
    _require_reason(correction_reason)

    record["review_status"] = "edited"
    record["final_diagnosis"] = copy.deepcopy(edited_diagnosis)
    record["correction_reason"] = str(correction_reason).strip()
    record["reviewer_notes"] = None if reviewer_notes is None else str(reviewer_notes).strip()
    record["reviewed_at"] = _now()

    _save_store(store_path, records)
    return copy.deepcopy(record)


def reject_review(review_id, correction_reason, final_diagnosis=None, reviewer_notes=None,
                  store_path=DEFAULT_REVIEWS_FILE):
    """Reject a pending AI diagnosis.

    The rejected AI diagnosis is NEVER presented as the final decision.
    If the human provides their own final_diagnosis/finding, it is stored
    separately. A correction_reason is mandatory.

    Returns:
        The updated review record with review_status == "rejected".
    """
    records = _load_store(store_path)
    record = _find_record(records, review_id)
    if record is None:
        raise ReviewValidationError("Unknown review_id: %s" % review_id)
    _require_pending(record)
    _require_reason(correction_reason)

    if final_diagnosis is not None:
        _validate_diagnosis_dict(final_diagnosis, "final_diagnosis")
        record["final_diagnosis"] = copy.deepcopy(final_diagnosis)
    else:
        record["final_diagnosis"] = None

    record["review_status"] = "rejected"
    record["correction_reason"] = str(correction_reason).strip()
    record["reviewer_notes"] = None if reviewer_notes is None else str(reviewer_notes).strip()
    record["reviewed_at"] = _now()

    _save_store(store_path, records)
    return copy.deepcopy(record)


def get_review(review_id, store_path=DEFAULT_REVIEWS_FILE):
    """Return a single review record by review_id (a defensive copy)."""
    records = _load_store(store_path)
    record = _find_record(records, review_id)
    if record is None:
        raise ReviewValidationError("Unknown review_id: %s" % review_id)
    return copy.deepcopy(record)


def list_reviews(status=None, store_path=DEFAULT_REVIEWS_FILE):
    """Return all review records, optionally filtered by review status.

    Returns defensive copies so callers cannot mutate stored records.
    """
    records = _load_store(store_path)
    if status is not None:
        status = str(status).strip()
        if status not in REVIEW_STATUSES:
            raise ReviewValidationError(
                "Invalid review status filter: %r (must be one of %s)"
                % (status, ", ".join(REVIEW_STATUSES)))
        records = [r for r in records if r.get("review_status") == status]
    return copy.deepcopy(records)


# ----------------------------------------------------------------------
# Class-style wrapper (kept for compatibility with the Phase 7 placeholder)
# ----------------------------------------------------------------------

class HumanReview:
    """Thin wrapper around the module-level review functions.

    Allows the store path to be fixed per instance, which is convenient for
    tools that work against a specific store (e.g. the default data/reviews.json
    or a temporary store in tests).
    """

    def __init__(self, store_path=DEFAULT_REVIEWS_FILE):
        self.store_path = store_path

    def create(self, case_id, ai_diagnosis, ai_meta=None):
        return create_review(case_id, ai_diagnosis, ai_meta, self.store_path)

    def accept(self, review_id, reviewer_notes=None):
        return accept_review(review_id, reviewer_notes, self.store_path)

    def edit(self, review_id, edited_diagnosis, correction_reason, reviewer_notes=None):
        return edit_review(review_id, edited_diagnosis, correction_reason,
                           reviewer_notes, self.store_path)

    def reject(self, review_id, correction_reason, final_diagnosis=None, reviewer_notes=None):
        return reject_review(review_id, correction_reason, final_diagnosis,
                             reviewer_notes, self.store_path)

    def get(self, review_id):
        return get_review(review_id, self.store_path)

    def list(self, status=None):
        return list_reviews(status, self.store_path)


def _demo():
    """Small end-to-end demonstration of the review workflow."""
    print("NetSage AI Human Review System — demonstration")
    print("=" * 60)

    demo_diagnosis = {
        "case_id": "NET-001",
        "likely_fault": "Access port on the server is assigned to the wrong VLAN.",
        "osi_layer": "Layer 2",
        "confidence": "medium",
        "evidence_used": ["Symptom: host cannot reach server in same VLAN"],
        "recommended_next_command": "show interfaces switchport",
        "suggested_fix": ["Reassign the port with switchport access vlan 10"],
        "reasoning_summary": "Port-level VLAN issue is the most probable cause.",
        "uncertainty_or_limitations": "No command output captured yet.",
    }
    demo_meta = {"source": "demo", "needs_human_review": True}

    reviews = HumanReview()  # uses default data/reviews.json
    created = reviews.create(demo_diagnosis["case_id"], demo_diagnosis, demo_meta)
    print("\n1) Created review %s (status=%s)" % (created["review_id"], created["review_status"]))

    accepted = reviews.accept(created["review_id"], reviewer_notes="Looks correct.")
    print("2) Accepted review %s (status=%s)" % (accepted["review_id"], accepted["review_status"]))
    print("   final_diagnosis == ai_diagnosis:", accepted["final_diagnosis"] == created["ai_diagnosis"])
    print("=" * 60)


if __name__ == "__main__":
    _demo()