"""
map.py — the Map page: Interactive Global AQI Map.

The flagship map surface: full-width glass map panel with the global
heat layer + top-15-per-country city markers (deck.gl), EPA legend,
selected-city info card, and refresh control. Two-way sync with the
app-wide selected location (grill-me Q6): clicking a marker selects that
city everywhere; selecting a city elsewhere re-centers the map.
"""

import streamlit as st

from app.components.aqi_map import render_aqi_map
from src.utils.logger import get_logger

logger = get_logger(__name__)


def render_map():
    """The Map page body (called by the st.navigation router)."""
    st.markdown(
        '<div class="aqi-page-title"><span class="aqi-gradient-text">'
        "Global AQI Map</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="aqi-sub">Live US EPA AQI across the world — heat '
        "field + major cities. Click a marker to select that city.</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    try:
        with st.container(border=True):
            render_aqi_map()
    except Exception as e:
        logger.warning(f"Map page error: {e}")
        st.warning("Map unavailable right now — please try again in a minute.")
