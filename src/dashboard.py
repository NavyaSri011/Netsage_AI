"""NetSage AI — Dashboard Generator.

Phase 8 implementation.

Calculates statistics dynamically from actual project data (cases.csv) and
human review records (data/reviews.json).  No statistics are hard-coded;
every number is derived from the live data files at call time.

The module is READ-ONLY with respect to source data:
    - data/cases.csv is never modified.
    - data/reviews.json is never modified.
    - AI diagnoses and human review decisions are never altered.

Charts are generated only when matplotlib is installed.  The core
statistics are always available via the Python stdlib alone.

Public API
----------
    load_cases(path=None)          -> list[dict]
    load_reviews(path=None)        -> list[dict]
    calculate_statistics(cases, reviews) -> dict
    generate_report(stats, output_dir=None) -> str
    generate_charts(stats, output_dir=None) -> list[str]
    generate_dashboard(output_dir=None) -> dict
"""

import csv
import json
import os
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Path defaults
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_CASES_CSV = os.path.join(_PROJECT_ROOT, "data", "cases.csv")
DEFAULT_REVIEWS_JSON = os.path.join(_PROJECT_ROOT, "data", "reviews.json")
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "dashboard")


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_cases(path=None):
    """Load all troubleshooting cases from a CSV file.

    Args:
        path: Path to cases CSV.  Defaults to data/cases.csv.

    Returns:
        A list of dicts, one per row.  Returns an empty list when the file
        does not exist or cannot be parsed.
    """
    path = path or DEFAULT_CASES_CSV
    if not os.path.isfile(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except Exception:
        return []


def load_reviews(path=None):
    """Load all human review records from a JSON file.

    Args:
        path: Path to the reviews JSON store.  Defaults to
              data/reviews.json.

    Returns:
        A list of review record dicts.  Returns an empty list when the
        file does not exist or cannot be parsed.
    """
    path = path or DEFAULT_REVIEWS_JSON
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


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _count_by_key(records, key):
    """Count records grouped by a given key, returning a sorted dict."""
    counter = Counter(str(r.get(key, "unknown")) for r in records)
    return dict(counter.most_common())


def _review_decision_counts(reviews):
    """Count reviews by review_status."""
    statuses = ["pending", "accepted", "edited", "rejected"]
    counts = {s: 0 for s in statuses}
    for r in reviews:
        status = str(r.get("review_status", "pending"))
        if status in counts:
            counts[status] += 1
    return counts


def _agreement_rate(reviews):
    """Calculate AI-vs-human agreement rate from completed reviews.

    Agreement definition (aligned with review.py data model):
        - accepted  → AI diagnosis agreed with by human (AGREEMENT)
        - edited    → human corrected the AI diagnosis (DISAGREEMENT)
        - rejected  → human rejected the AI diagnosis (DISAGREEMENT)
        - pending   → exclude from calculation

    Returns:
        A dict with keys: total_completed, accepted, edited, rejected,
        agreement_rate (float 0-100 or 0.0 if no completed reviews).
    """
    decision = _review_decision_counts(reviews)
    completed = decision["accepted"] + decision["edited"] + decision["rejected"]

    if completed == 0:
        return {
            "total_completed": 0,
            "accepted": decision["accepted"],
            "edited": decision["edited"],
            "rejected": decision["rejected"],
            "agreement_rate": 0.0,
        }

    rate = (decision["accepted"] / completed) * 100.0
    return {
        "total_completed": completed,
        "accepted": decision["accepted"],
        "edited": decision["edited"],
        "rejected": decision["rejected"],
        "agreement_rate": round(rate, 2),
    }


# ---------------------------------------------------------------------------
# Core statistics
# ---------------------------------------------------------------------------

def calculate_statistics(cases, reviews):
    """Calculate all dashboard statistics from actual data.

    Args:
        cases: List of case dicts (from load_cases).
        reviews: List of review record dicts (from load_reviews).

    Returns:
        A structured dict containing every dashboard metric.  All values
        are derived from the provided data — nothing is hard-coded.
    """
    total_cases = len(cases)

    by_concept = _count_by_key(cases, "concept_tag")
    by_osi_layer = _count_by_key(cases, "osi_layer")
    by_severity = _count_by_key(cases, "severity")

    decision = _review_decision_counts(reviews)
    agreement = _agreement_rate(reviews)

    return {
        "total_cases": total_cases,
        "cases_by_concept": by_concept,
        "cases_by_osi_layer": by_osi_layer,
        "cases_by_severity": by_severity,
        "review_statistics": {
            "total_reviews": len(reviews),
            "pending": decision["pending"],
            "accepted": decision["accepted"],
            "edited": decision["edited"],
            "rejected": decision["rejected"],
        },
        "agreement": agreement,
    }


# ---------------------------------------------------------------------------
# Report generation (text summary)
# ---------------------------------------------------------------------------

def generate_report(stats, output_dir=None):
    """Generate a plain-text summary report from calculated statistics.

    Args:
        stats: Dict returned by calculate_statistics().
        output_dir: Directory to write the report file.  Defaults to
                    dashboard/.  The file is always written.

    Returns:
        The generated report text.
    """
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    lines = []
    lines.append("=" * 60)
    lines.append("NetSage AI — Dashboard Summary Report")
    lines.append("=" * 60)
    lines.append("")

    # Case statistics
    lines.append("CASE STATISTICS")
    lines.append("-" * 40)
    lines.append("Total cases: %d" % stats["total_cases"])
    lines.append("")

    lines.append("Cases by networking concept:")
    for concept, count in stats["cases_by_concept"].items():
        lines.append("  %-20s %d" % (concept, count))
    lines.append("")

    lines.append("Cases by OSI layer:")
    for layer, count in stats["cases_by_osi_layer"].items():
        lines.append("  %-20s %d" % (layer, count))
    lines.append("")

    lines.append("Cases by severity:")
    for sev, count in stats["cases_by_severity"].items():
        lines.append("  %-20s %d" % (sev, count))
    lines.append("")

    # Review statistics
    rev = stats["review_statistics"]
    lines.append("HUMAN REVIEW STATISTICS")
    lines.append("-" * 40)
    lines.append("Total reviews:    %d" % rev["total_reviews"])
    lines.append("Pending reviews:  %d" % rev["pending"])
    lines.append("Accepted reviews: %d" % rev["accepted"])
    lines.append("Edited reviews:   %d" % rev["edited"])
    lines.append("Rejected reviews: %d" % rev["rejected"])
    lines.append("")

    # Agreement
    agr = stats["agreement"]
    lines.append("AI vs HUMAN AGREEMENT")
    lines.append("-" * 40)
    lines.append("Completed reviews: %d" % agr["total_completed"])
    if agr["total_completed"] > 0:
        lines.append("Agreement rate:    %.2f%%" % agr["agreement_rate"])
        lines.append("  (accepted = agreement; edited/rejected = disagreement)")
    else:
        lines.append("Agreement rate:    N/A (no completed reviews)")
    lines.append("")
    lines.append("=" * 60)

    report_text = "\n".join(lines)
    report_path = os.path.join(output_dir, "dashboard_report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_text)

    return report_text


# ---------------------------------------------------------------------------
# Chart generation (matplotlib optional)
# ---------------------------------------------------------------------------

def generate_charts(stats, output_dir=None):
    """Generate charts from calculated statistics using matplotlib.

    Charts are only created when matplotlib is installed.  Each chart
    is saved to the output directory.

    Args:
        stats: Dict returned by calculate_statistics().
        output_dir: Directory to save chart images.  Defaults to dashboard/.

    Returns:
        A list of file paths to the generated chart images.
        Returns an empty list if matplotlib is not available.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    generated = []

    chart_specs = [
        ("cases_by_concept", "Cases by Networking Concept", "#4CAF50"),
        ("cases_by_osi_layer", "Cases by OSI Layer", "#2196F3"),
        ("cases_by_severity", "Cases by Severity", "#FF9800"),
    ]

    for key, title, color in chart_specs:
        data = stats.get(key, {})
        if not data:
            continue
        labels = list(data.keys())
        values = list(data.values())
        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.barh(labels, values, color=color)
        ax.set_xlabel("Number of Cases")
        ax.set_title(title)
        ax.invert_yaxis()
        for bar, val in zip(bars, values):
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                    str(val), va="center", fontsize=10)
        fig.tight_layout()
        filename = "%s.png" % key
        filepath = os.path.join(output_dir, filename)
        fig.savefig(filepath, dpi=120)
        plt.close(fig)
        generated.append(filepath)

    # Review decisions pie chart
    rev = stats.get("review_statistics", {})
    review_total = rev.get("total_reviews", 0)
    if review_total > 0:
        rev_labels = []
        rev_values = []
        rev_colors = []
        pie_palette = {
            "pending": "#BDBDBD",
            "accepted": "#4CAF50",
            "edited": "#FF9800",
            "rejected": "#F44336",
        }
        for status in ["pending", "accepted", "edited", "rejected"]:
            count = rev.get(status, 0)
            if count > 0:
                rev_labels.append("%s (%d)" % (status.capitalize(), count))
                rev_values.append(count)
                rev_colors.append(pie_palette[status])

        if rev_values:
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.pie(rev_values, labels=rev_labels, colors=rev_colors,
                   autopct="%1.1f%%", startangle=140)
            ax.set_title("Human Review Decisions")
            fig.tight_layout()
            filepath = os.path.join(output_dir, "review_decisions.png")
            fig.savefig(filepath, dpi=120)
            plt.close(fig)
            generated.append(filepath)

    # AI vs Human agreement bar chart
    agr = stats.get("agreement", {})
    if agr.get("total_completed", 0) > 0:
        agr_labels = ["Accepted\n(Agreement)", "Edited\n(Correction)", "Rejected\n(Disagreement)"]
        agr_values = [agr["accepted"], agr["edited"], agr["rejected"]]
        agr_colors = ["#4CAF50", "#FF9800", "#F44336"]
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.bar(agr_labels, agr_values, color=agr_colors)
        ax.set_ylabel("Number of Reviews")
        ax.set_title("AI vs Human Agreement (Rate: %.1f%%)" % agr["agreement_rate"])
        for i, v in enumerate(agr_values):
            ax.text(i, v + 0.05, str(v), ha="center", fontsize=11)
        fig.tight_layout()
        filepath = os.path.join(output_dir, "agreement.png")
        fig.savefig(filepath, dpi=120)
        plt.close(fig)
        generated.append(filepath)

    return generated


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_dashboard(output_dir=None):
    """Generate the complete dashboard: statistics, report, and charts.

    This is the single-call entry point that loads data, computes
    statistics, writes the text report, and generates any available charts.

    Args:
        output_dir: Directory for all output.  Defaults to dashboard/.

    Returns:
        A dict containing:
            - statistics: the calculated statistics dict
            - report: the text report string
            - charts: list of generated chart file paths
            - output_dir: the directory where output was written
    """
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    cases = load_cases()
    reviews = load_reviews()
    stats = calculate_statistics(cases, reviews)
    report = generate_report(stats, output_dir)
    charts = generate_charts(stats, output_dir)
    return {
        "statistics": stats,
        "report": report,
        "charts": charts,
        "output_dir": output_dir,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = generate_dashboard()
    print(result["report"])
    if result["charts"]:
        print("\nGenerated charts:")
        for c in result["charts"]:
            print("  %s" % c)
    else:
        print("\nNo charts generated (matplotlib not installed).")
