import streamlit as st

from src.diagnosis_engine import DiagnosisEngine
from src.dashboard import load_reviews, calculate_statistics


def show_dashboard():

    st.title("📊 NetSage AI Dashboard")

    st.write(
        "Live statistics derived from the troubleshooting "
        "case dataset and human review records."
    )

    # Load project data
    engine = DiagnosisEngine()
    cases = engine.load_all_cases()
    reviews = load_reviews()

    # Calculate statistics
    stats = calculate_statistics(cases, reviews)

    review_stats = stats["review_statistics"]
    agreement = stats["agreement"]

    # --------------------------------------------
    # MAIN METRICS
    # --------------------------------------------

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total Cases",
        stats["total_cases"]
    )

    col2.metric(
        "Total Reviews",
        review_stats["total_reviews"]
    )

    col3.metric(
        "Completed Reviews",
        agreement["total_completed"]
    )

    col4.metric(
        "AI-Human Agreement",
        f"{agreement['agreement_rate']}%"
    )

    st.divider()

    # --------------------------------------------
    # CASE STATISTICS
    # --------------------------------------------

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🌐 Cases by Networking Concept")

        st.bar_chart(
            stats["cases_by_concept"]
        )

    with col2:
        st.subheader("⚠️ Cases by Severity")

        st.bar_chart(
            stats["cases_by_severity"]
        )

    st.subheader("📡 Cases by OSI Layer")

    st.bar_chart(
        stats["cases_by_osi_layer"]
    )

    st.divider()

    # --------------------------------------------
    # HUMAN REVIEW STATISTICS
    # --------------------------------------------

    st.subheader("👨‍💻 Human Review Statistics")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Pending",
        review_stats["pending"]
    )

    col2.metric(
        "Accepted",
        review_stats["accepted"]
    )

    col3.metric(
        "Edited",
        review_stats["edited"]
    )

    col4.metric(
        "Rejected",
        review_stats["rejected"]
    )

    st.divider()

    # --------------------------------------------
    # AI VS HUMAN AGREEMENT
    # --------------------------------------------

    st.subheader("🤝 AI vs Human Agreement")

    st.metric(
        "Agreement Rate",
        f"{agreement['agreement_rate']}%"
    )

    st.caption(
        "Accepted means the human agreed with the AI diagnosis. "
        "Edited and Rejected mean the human corrected or "
        "disagreed with the AI diagnosis."
    )