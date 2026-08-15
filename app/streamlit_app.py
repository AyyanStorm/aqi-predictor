"""
streamlit_app.py — AQI Predictor, glassmorphism multipage entry point.

Router for the redesigned app (grill-me decisions, all confirmed):
  - True multipage (Option B): st.navigation with four pages —
    Dashboard / Compare / Tracking / Analytics.
  - No permanent sidebar: a sticky glass navbar (navbar.py) carries the
    brand, page links, location chip (opens a modal glass location
    dialog), settings (modal dialog) and refresh.
  - The dynamic country logic (location picker + country_cities) is
    untouched and reused by every page.

The entry point stays the same (`streamlit run app/streamlit_app.py`),
so the Render start command is unchanged.
"""

import sys
from pathlib import Path

import streamlit as st

# `streamlit run app/streamlit_app.py` puts app/ on sys.path, not the
# project root — so `import src` (and `import app.components`) would fail
# with "No module named". Prepend the repo root explicitly (parents[1] of
# this file) so the app works no matter where it's launched from (local
# dev, Render, etc.).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.components.navbar import render_navbar
from app.pages.analytics import render_analytics
from app.pages.compare import render_compare
from app.pages.dashboard import render_dashboard
from app.pages.map import render_map
from app.pages.tracking import render_tracking
from app.theme import inject_theme

st.set_page_config(
    page_title="AQI Predictor",
    page_icon="🌫️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Glassmorphism design system (background, glass cards, navbar, buttons).
inject_theme()

# --- Pages -------------------------------------------------------------
pages = {
    "Dashboard": st.Page(render_dashboard, title="Dashboard",
                         url_path="dashboard", default=True),
    "Map": st.Page(render_map, title="Map", url_path="map"),
    "Compare": st.Page(render_compare, title="Compare", url_path="compare"),
    "Tracking": st.Page(render_tracking, title="Tracking",
                        url_path="tracking"),
    "Analytics": st.Page(render_analytics, title="Analytics",
                         url_path="analytics"),
}

nav = st.navigation(list(pages.values()), position="hidden")

# Sticky glass navbar (brand + nav + location/settings/refresh) renders
# above every page. The active page gets the primary gradient treatment.
render_navbar(pages, active_title=nav.title)

nav.run()
