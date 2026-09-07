import streamlit as st

from views.troubleshooter import show_troubleshooter
from views.human_review import show_human_review
from views.dashboard_page import show_dashboard
from views.responsible_ai_page import show_responsible_ai
# -------------------------------------------------
# PAGE CONFIGURATION
# -------------------------------------------------

st.set_page_config(
    page_title="NetSage AI",
    page_icon="🌐",
    layout="wide"
)


# -------------------------------------------------
# SESSION STATE DEFAULTS
# -------------------------------------------------

defaults = {
    "diagnosis": None,
    "diagnosis_meta": None,
    "review": None,
    "review_requested": False,
    "show_edit_form": False,
    "show_reject_form": False,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# -------------------------------------------------
# SIDEBAR NAVIGATION
# -------------------------------------------------

st.sidebar.title("🌐 NetSage AI")

st.sidebar.caption(
    "AI-Assisted Network Troubleshooting "
    "with Mandatory Human Review"
)

page = st.sidebar.radio(
    "Navigation",
    [
        "🔧 Troubleshooter",
        "👨‍💻 Human Review",
        "📊 Dashboard",
        "🛡️ Responsible AI Log",
    ]
)


# -------------------------------------------------
# PAGE ROUTING
# -------------------------------------------------

if page == "🔧 Troubleshooter":

    show_troubleshooter()


elif page == "👨‍💻 Human Review":

    show_human_review()


elif page == "📊 Dashboard":

    show_dashboard()


elif page == "🛡️ Responsible AI Log":

    show_responsible_ai()