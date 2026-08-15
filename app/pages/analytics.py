"""
analytics.py — the Analytics page: Top-10 cities for the selected
country (dynamic, never hardcoded).

Reuses the existing dynamic leaderboard component: the country follows
the selected city (New York -> USA, London -> UK, Dubai -> UAE,
Karachi -> Pakistan, Tokyo -> Japan), ranked by live AQI worst-first.
"""

import streamlit as st

from app.components.leaderboard import render_leaderboard
from src.utils.logger import get_logger

logger = get_logger(__name__)


def render_analytics():
    """The Analytics page body (called by the st.navigation router)."""
    st.markdown(
        '<div class="aqi-page-title"><span class="aqi-gradient-text">'
        "Analytics</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="aqi-sub">The dirtiest air right now — ranked for '
        "the country of the city you selected.</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    loc = st.session_state.get("location", {})
    try:
        with st.container(border=True):
            render_leaderboard(loc.get("country"))
    except Exception as e:
        logger.warning(f"Analytics page error: {e}")
        st.warning("Top-10 section unavailable right now.")
