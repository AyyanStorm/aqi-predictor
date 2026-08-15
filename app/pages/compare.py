"""
compare.py — the Compare page: Multi-City Historical vs Predicted AQI.

Reuses the existing comparison component unchanged (same data, same
controls) inside a glass panel. This page previously lived in the
single-page dashboard; it now has its own top-nav page.
"""

import streamlit as st

from app.components.comparison import render_comparison
from app.theme import glass_theme
from src.utils.logger import get_logger

logger = get_logger(__name__)


def render_compare():
    """The Compare page body (called by the st.navigation router)."""
    st.markdown(
        '<div class="aqi-page-title"><span class="aqi-gradient-text">'
        "Compare Cities</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="aqi-sub">Historical vs predicted AQI side by side '
        "for up to 6 cities worldwide.</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    try:
        with st.container(border=True):
            render_comparison()
    except Exception as e:
        logger.warning(f"Comparison page error: {e}")
        st.warning("Comparison section unavailable right now.")
