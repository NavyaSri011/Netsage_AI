import streamlit as st
from src.diagnosis_engine import DiagnosisEngine


def show_troubleshooter():

    st.title("🌐 NetSage AI")
    st.subheader("AI-Assisted Network Troubleshooting with Human Review")

    engine = DiagnosisEngine()
    cases = engine.load_all_cases()

    case_options = {
        f"{case['case_id']} — {case['title']}": case
        for case in cases
    }

    selected_name = st.selectbox(
        "🧪 Select a Network Troubleshooting Case",
        list(case_options.keys())
    )

    selected_case = case_options[selected_name]

    st.subheader("📥 Network Evidence")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**Case ID:**", selected_case["case_id"])
        st.write("**Networking Concept:**", selected_case["concept_tag"])
        st.write("**Severity:**", selected_case["severity"])

    with col2:
        st.write("**Reference OSI Layer:**", selected_case["osi_layer"])
        st.write(
            "**Verification Method:**",
            selected_case["verification_method"]
        )

    st.write("### 📝 Symptom")
    st.write(selected_case["symptom"])

    st.write("### 🗺️ Topology Note")
    st.write(selected_case["topology_note"])

    st.write("### 💻 Show-Command Output")

    if selected_case["show_outputs"] == "PENDING_CAPTURE":
        st.warning("No Packet Tracer command output captured yet.")
    else:
        st.code(selected_case["show_outputs"])

    st.divider()

    if st.button(
        "🔍 Run Troubleshooting Analysis",
        use_container_width=True
    ):

        diagnosis, meta = engine.diagnose(
            selected_case,
            force_demo=True
        )

        st.session_state.diagnosis = diagnosis
        st.session_state.diagnosis_meta = meta
        st.session_state.review = None

        st.rerun()

    # ------------------------------------------------
    # AI DIAGNOSIS
    # ------------------------------------------------

    if st.session_state.diagnosis:

        diagnosis = st.session_state.diagnosis
        meta = st.session_state.diagnosis_meta

        st.subheader("🧠 AI Troubleshooting Diagnosis")

        st.info(
            "AI output is a recommendation only. "
            "Human review is required."
        )

        col1, col2, col3 = st.columns(3)

        col1.metric("OSI Layer", diagnosis["osi_layer"])
        col2.metric("Confidence", diagnosis["confidence"])
        col3.metric("Source", meta["source"])

        st.write("### 🔎 Likely Root Cause")
        st.write(diagnosis["likely_fault"])

        st.write("### 📌 Evidence Used")
        for evidence in diagnosis["evidence_used"]:
            st.write("•", evidence)

        st.write("### 🖥️ Recommended Next Command")
        st.code(diagnosis["recommended_next_command"])

        st.write("### 🛠️ Recommended Fix")
        for fix in diagnosis["suggested_fix"]:
            st.write("•", fix)

        st.write("### 📝 Reasoning Summary")
        st.write(diagnosis["reasoning_summary"])

        st.write("### ⚠️ Uncertainty / Limitations")
        st.write(diagnosis["uncertainty_or_limitations"])

        # Send to review button
        st.divider()

        st.subheader("👨‍💻 Mandatory Human Review")

        if st.session_state.review is None:

            if st.button(
                "📋 Send Diagnosis for Human Review",
                use_container_width=True
            ):
                st.session_state.review_requested = True
                st.rerun()

        else:

            st.info(
                f"Review Status: "
                f"{st.session_state.review['review_status'].upper()}"
            )