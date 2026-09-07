import streamlit as st

from src.responsible_ai_log import (
    generate_log,
    load_existing_entries
)


def show_responsible_ai():

    st.title("🛡️ Responsible AI Log")

    st.write(
        "This page shows AI diagnoses that required "
        "human correction."
    )

    st.info(
        "Only Edited and Rejected reviews are included. "
        "Accepted and Pending reviews are not AI corrections."
    )

    # Generate/update the log from real review records
    summary = generate_log()

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Reviews Examined",
        summary["reviews_seen"]
    )

    col2.metric(
        "AI Corrections Found",
        summary["corrections_found"]
    )

    col3.metric(
        "Total Log Entries",
        summary["total_entries"]
    )

    st.divider()

    entries = load_existing_entries()

    if not entries:

        st.warning(
            "No AI corrections have been recorded yet. "
            "Edit or Reject diagnoses through Human Review."
        )

        return

    st.subheader("📋 Human Corrections")

    for entry in entries:

        title = (
            f"{entry['case_id']} — "
            f"{entry['human_decision']}"
        )

        with st.expander(title):

            st.write("### 🤖 Original AI Diagnosis")
            st.write(entry["ai_diagnosis"])

            st.write("### ✏️ Human Decision")
            st.write(entry["human_decision"])

            st.write("### 🔄 Correction Made")
            st.write(entry["correction_made"])

            st.write("### ❗ Why the AI Was Incorrect")
            st.write(entry["reason_ai_was_incorrect"])

            st.write("### 👨‍💻 Final Human Diagnosis")
            st.write(entry["final_approved_diagnosis"])

            st.write("### 📚 Lesson Learned")
            st.write(entry["lesson_learned"])

            st.caption(
                f"Review ID: {entry['review_id']}"
            )