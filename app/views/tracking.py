"""
tracking.py — the Tracking page: prediction tracking + accuracy.

Reuses the existing accuracy component (MAPE headline, ±15 hit-rate,
EPA category match, per-city graph + global average) unchanged, inside
a glass layout. The automatic per-browser save still happens on the
Dashboard when a forecast is generated.
"""

import streamlit as st

from app.components.accuracy import get_user_id, render_accuracy
from src.utils.logger import get_logger

logger = get_logger(__name__)


def render_tracking():
    """The Tracking page body (called by the st.navigation router)."""
    st.markdown(
        '<div class="aqi-page-title"><span class="aqi-gradient-text">'
        "Tracking & Accuracy</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="aqi-sub">Every forecast you generate is saved '
        "automatically; actual AQI fills in as time passes.</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    loc = st.session_state.get("location", {})
    try:
        _user_id = get_user_id()
        render_accuracy(_user_id, loc)
    except Exception as e:
        logger.warning(f"Tracking page error: {e}")
        st.warning("Tracking section unavailable right now.")
