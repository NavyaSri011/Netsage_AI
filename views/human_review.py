import streamlit as st

from src.review import (
    create_review,
    accept_review,
    edit_review,
    reject_review
)


def show_human_review():

    # No diagnosis yet
    if not st.session_state.get("diagnosis"):
        st.title("👨‍💻 Human Review")
        st.info(
            "Run a troubleshooting analysis first, then send "
            "the diagnosis for human review."
        )
        return

    diagnosis = st.session_state.diagnosis
    meta = st.session_state.diagnosis_meta

    st.title("👨‍💻 Mandatory Human Review")

    # --------------------------------------------
    # CREATE REVIEW
    # --------------------------------------------

    if st.session_state.get("review") is None:

        st.warning(
            "The AI diagnosis is only a recommendation. "
            "A human reviewer must accept, edit, or reject it."
        )

        if st.button(
            "📋 Send Diagnosis for Human Review",
            use_container_width=True
        ):

            st.session_state.review = create_review(
                case_id=diagnosis["case_id"],
                ai_diagnosis=diagnosis,
                ai_meta=meta
            )

            st.rerun()

        return


    review = st.session_state.review

    st.info(
        f"Review ID: {review['review_id']} | "
        f"Status: {review['review_status'].upper()}"
    )


    # --------------------------------------------
    # PENDING REVIEW
    # --------------------------------------------

    if review["review_status"] == "pending":

        col1, col2, col3 = st.columns(3)

        # ACCEPT
        with col1:

            if st.button(
                "✅ Accept",
                use_container_width=True
            ):

                st.session_state.review = accept_review(
                    review["review_id"],
                    reviewer_notes="Approved by human reviewer."
                )

                st.rerun()


        # EDIT
        with col2:

            if st.button(
                "✏️ Edit",
                use_container_width=True
            ):

                st.session_state.show_edit_form = True
                st.session_state.show_reject_form = False


        # REJECT
        with col3:

            if st.button(
                "❌ Reject",
                use_container_width=True
            ):

                st.session_state.show_reject_form = True
                st.session_state.show_edit_form = False


    # --------------------------------------------
    # EDIT FORM
    # --------------------------------------------

    if (
        review["review_status"] == "pending"
        and st.session_state.get("show_edit_form")
    ):

        st.subheader("✏️ Edit AI Diagnosis")

        edited_fault = st.text_area(
            "Likely Root Cause",
            value=diagnosis["likely_fault"]
        )

        edited_osi = st.selectbox(
            "OSI Layer",
            [
                "Layer 1",
                "Layer 2",
                "Layer 3",
                "Layer 4",
                "Layer 5",
                "Layer 6",
                "Layer 7"
            ]
        )

        edited_confidence = st.selectbox(
            "Confidence",
            ["low", "medium", "high"]
        )

        edited_command = st.text_input(
            "Recommended Next Command",
            value=diagnosis["recommended_next_command"]
        )

        edited_fix = st.text_area(
            "Suggested Fix (one step per line)",
            value="\n".join(diagnosis["suggested_fix"])
        )

        correction_reason = st.text_area(
            "Why was the AI diagnosis corrected?"
        )

        if st.button(
            "Save Edited Diagnosis",
            use_container_width=True
        ):

            if not correction_reason.strip():

                st.error("Please provide a correction reason.")

            else:

                edited_diagnosis = diagnosis.copy()

                edited_diagnosis[
                    "likely_fault"
                ] = edited_fault

                edited_diagnosis[
                    "osi_layer"
                ] = edited_osi

                edited_diagnosis[
                    "confidence"
                ] = edited_confidence

                edited_diagnosis[
                    "recommended_next_command"
                ] = edited_command

                edited_diagnosis[
                    "suggested_fix"
                ] = [
                    fix.strip()
                    for fix in edited_fix.split("\n")
                    if fix.strip()
                ]

                st.session_state.review = edit_review(
                    review["review_id"],
                    edited_diagnosis,
                    correction_reason,
                    reviewer_notes="Edited by human reviewer."
                )

                st.session_state.show_edit_form = False

                st.rerun()


    # --------------------------------------------
    # REJECT FORM
    # --------------------------------------------

    if (
        review["review_status"] == "pending"
        and st.session_state.get("show_reject_form")
    ):

        st.subheader("❌ Reject AI Diagnosis")

        reason = st.text_area(
            "Why is the AI diagnosis incorrect?"
        )

        if st.button(
            "Confirm Rejection",
            use_container_width=True
        ):

            if reason.strip():

                st.session_state.review = reject_review(
                    review["review_id"],
                    correction_reason=reason,
                    reviewer_notes="Rejected by human reviewer."
                )

                st.session_state.show_reject_form = False

                st.rerun()

            else:

                st.error("Please provide a rejection reason.")


    # --------------------------------------------
    # FINAL STATUS
    # --------------------------------------------

    if review["review_status"] == "accepted":

        st.success(
            "✅ FINAL HUMAN DECISION: "
            "The AI diagnosis has been accepted."
        )


    elif review["review_status"] == "edited":

        st.success(
            "✏️ FINAL HUMAN DECISION: "
            "The diagnosis was corrected by the human reviewer."
        )

        final = review["final_diagnosis"]

        st.write("### Final Human Diagnosis")
        st.write("**Likely Root Cause:**", final["likely_fault"])
        st.write("**OSI Layer:**", final["osi_layer"])
        st.write("**Confidence:**", final["confidence"])

        st.write("### Correction Reason")
        st.write(review["correction_reason"])


    elif review["review_status"] == "rejected":

        st.error(
            "❌ FINAL HUMAN DECISION: "
            "The AI diagnosis has been rejected."
        )

        st.write(
            "**Reason:**",
            review["correction_reason"]
        )