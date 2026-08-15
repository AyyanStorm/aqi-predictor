"""
navbar.py — sticky top glassmorphism navigation bar + dialogs.

Replaces the old permanent left sidebar. Everything the sidebar did is
reorganised (grill-me decisions):
  - Location control -> modal glass dialog (st.dialog): search, matches,
    "Use my location", dynamic "Or pick any other city from {Country}".
  - Model selection  -> glass Settings dialog.
  - Refresh forecast -> navbar action that clears the forecast cache.

The bar itself is Streamlit-native (columns of styled buttons + brand
HTML) so it stays interactive and testable; the glass look comes from
app/theme.py CSS. Active page gets the primary (gradient) treatment.
"""

import streamlit as st

from app.components.location_picker import location_picker
from app.forecast_service import clear_forecast_cache
from src.utils.geo import short_country
from src.utils.logger import get_logger

logger = get_logger(__name__)

LOCATION_KEY = "location"
MODEL_KEY = "model_name"


def _current_loc():
    """The active location dict (defaults to Karachi on first load)."""
    if LOCATION_KEY in st.session_state:
        return st.session_state[LOCATION_KEY]
    from app.components.location_picker import default_location
    st.session_state[LOCATION_KEY] = default_location()
    return st.session_state[LOCATION_KEY]


def _city_label(loc):
    """Short city label for the navbar chip ('London' from
    'London, England, United Kingdom')."""
    name = loc.get("name") or "Unknown"
    return name.split(",")[0].strip()


def _country_label(loc):
    country = short_country(loc.get("country"))
    return country or "?"


# ------------------------------------------------------------------
# Dialogs
# ------------------------------------------------------------------
@st.dialog("📍 Change location", width="large")
def location_dialog():
    """Modal glass location panel — the old sidebar picker, in a dialog.

    Stays open across the GPS/IP/search reruns (grill-me Q3, Option A),
    so the multi-step flow completes inside the panel. Picking a city
    updates session_state["location"]; close with the ✕ / outside click.
    """
    loc = location_picker(in_dialog=True)
    st.caption(f"Active: **{_city_label(loc)}** · {_country_label(loc)}")


@st.dialog("⚙️ Settings", width="small")
def settings_dialog():
    """Glass settings panel — model selection moved out of the navbar."""
    st.markdown("**Model**")
    st.text_input(
        "Model (optional)",
        value=st.session_state.get(MODEL_KEY, ""),
        key=MODEL_KEY,
        placeholder="default = production",
        help="Registry model family, e.g. 'lgbm'. Empty uses the "
             "current production model.",
        label_visibility="collapsed",
    )
    st.caption("The selected model applies to the next forecast fetch.")


# ------------------------------------------------------------------
# Navbar
# ------------------------------------------------------------------
def render_navbar(pages, active_title):
    """
    Render the sticky glass navbar.

    Parameters
    ----------
    pages : dict[str, st.Page]
        title -> page object (for st.switch_page).
    active_title : str
        Title of the currently selected page.
    """
    loc = _current_loc()

    with st.container(key="aqi-navbar"):
        cols = st.columns(
            [1.7, 1, 1, 1, 1, 2.1, 1.9, 1.15, 1.15], gap="small"
        )
        with cols[0]:
            st.markdown(
                '<div class="brand"><span class="logo">🌫️</span>'
                '<span>AQI Predictor</span></div>',
                unsafe_allow_html=True,
            )
        for i, title in enumerate(("Dashboard", "Compare", "Tracking", "Analytics")):
            with cols[1 + i]:
                if st.button(
                    title,
                    key=f"nav_{title.lower()}",
                    type="primary" if title == active_title else "secondary",
                    width="stretch",
                    help=f"Go to {title}",
                ):
                    st.switch_page(pages[title])

        with cols[5]:
            st.markdown(
                f'<div class="chip"><span class="live-dot"></span>'
                f'Live forecast</div>',
                unsafe_allow_html=True,
            )
        with cols[6]:
            if st.button(
                f"📍 {_city_label(loc)}, {_country_label(loc)}",
                key="nav_location",
                width="stretch",
                help="Change city — search any city worldwide",
            ):
                location_dialog()
        with cols[7]:
            if st.button("⚙️", key="nav_settings", help="Settings",
                         width="stretch"):
                settings_dialog()
        with cols[8]:
            if st.button("🔄", key="nav_refresh",
                         help="Refresh forecast (clear cache)",
                         width="stretch"):
                clear_forecast_cache()
                st.rerun()
