"""
location_picker.py — Day 18: three-tier geolocation widget for the sidebar.

The roadmap's location detection, in one component:

  Tier 1  Browser geolocation   — streamlit-js-eval calls the JS
                                  Geolocation API. Precise, but requires
                                  user permission and HTTPS.
  Tier 2  IP-based              — ipapi.co (fallback: ipwho.is, ip-api.com)
                                  when permission is denied.
  Tier 3  Manual search         — text box → Open-Meteo Geocoding API.
                                  Always works; this is what a reviewer
                                  will actually use.

Everything resolves to a location dict that lives in st.session_state:

    {"name": "Karachi", "lat": 24.8608, "lon": 67.0104, "source": "browser"}

    source ∈ {"browser", "ip", "search", "quick-pick"} — shown in the UI
    so it's obvious WHICH tier won, and lets us debug silently.

The 10 training cities stay available as a quick-pick dropdown (the
Day 17 default), so the widget never takes a capability away.
"""

import streamlit as st
from streamlit_js_eval import get_geolocation

from src.config import CITIES
from src.utils.geo import geocode, locate_by_ip, reverse_geocode
from src.utils.logger import get_logger

logger = get_logger(__name__)

LOCATION_KEY = "location"


def _label(result):
    """One-line label for a geocoding result: 'Name, Region, Country'."""
    parts = [result.get("name"), result.get("admin1"), result.get("country")]
    return ", ".join(p for p in parts if p)


def _default_location():
    return {
        "name": "Karachi",
        "lat": CITIES["Karachi"]["lat"],
        "lon": CITIES["Karachi"]["lon"],
        "source": "quick-pick",
    }


def _apply_quick_pick():
    """on_change callback: quick-pick dropdown changed."""
    city = st.session_state["geo_quick"]
    st.session_state[LOCATION_KEY] = {
        "name": city,
        "lat": CITIES[city]["lat"],
        "lon": CITIES[city]["lon"],
        "source": "quick-pick",
    }


def _apply_search_match():
    """on_change callback: user picked a geocoding search match."""
    results = st.session_state.get("geo_results", [])
    choice = st.session_state["geo_match"]
    labels = [_label(r) for r in results]
    r = results[labels.index(choice)]
    st.session_state[LOCATION_KEY] = {
        "name": _label(r),
        "lat": r["latitude"],
        "lon": r["longitude"],
        "source": "search",
    }
    logger.info(f"Location set by search: {_label(r)}")


def location_picker():
    """
    Render the three-tier location widget; return the active location.

    Returns
    -------
    dict
        {"name", "lat", "lon", "source"} — persisted across reruns in
        st.session_state["location"].
    """
    st.session_state.setdefault(LOCATION_KEY, _default_location())
    loc = st.session_state[LOCATION_KEY]

    st.subheader("📍 Location")

    # ---- Tier 1 (+ Tier 2 fallback): automatic detection ----
    if st.button("🎯 Use my location", use_container_width=True):
        with st.spinner("Detecting location…"):
            geo = get_geolocation()
            if geo and geo.get("coords"):
                lat = geo["coords"]["latitude"]
                lon = geo["coords"]["longitude"]
                name = reverse_geocode(lat, lon) or f"{lat:.2f}, {lon:.2f}"
                st.session_state[LOCATION_KEY] = {
                    "name": name, "lat": lat, "lon": lon, "source": "browser",
                }
                logger.info(f"Location set by browser geolocation: {name}")
            else:
                # Permission denied / not HTTPS / unsupported → Tier 2.
                ip = locate_by_ip()
                if ip and ip.get("latitude"):
                    lat, lon = ip["latitude"], ip["longitude"]
                    name = (reverse_geocode(lat, lon)
                            or ip.get("city")
                            or f"{lat:.2f}, {lon:.2f}")
                    st.session_state[LOCATION_KEY] = {
                        "name": name, "lat": lat, "lon": lon, "source": "ip",
                    }
                    logger.info(f"Location set by IP: {name}")
                else:
                    st.warning(
                        "Couldn't detect your location automatically — "
                        "use the search box below."
                    )
        st.rerun()

    st.caption(
        "Browser GPS needs permission + HTTPS. If it fails we fall back "
        "to your IP (city-level), then to manual search."
    )

    # ---- Tier 3: manual search (always available) ----
    query = st.text_input(
        "Search any city",
        key="geo_query",
        placeholder="e.g. Sialkot, Dubai, London",
        help="Open-Meteo Geocoding API — free, no key, worldwide.",
    )
    if query.strip():
        results = geocode(query.strip())
        st.session_state["geo_results"] = results
        if results:
            labels = [_label(r) for r in results]
            # index=None + placeholder on purpose: with a pre-selected
            # first match (index=0), Streamlit's on_change never fires —
            # the widget's value doesn't CHANGE, so the callback is
            # skipped and the picked city never gets applied. Forcing an
            # explicit pick guarantees a change event -> _apply_search_match.
            st.selectbox(
                "Matches",
                labels,
                index=None,
                placeholder="Select a match…",
                key="geo_match",
                on_change=_apply_search_match,
            )
        else:
            st.caption("No matches — try another spelling.")

    # ---- Quick pick: the 10 training cities (Day 17 default) ----
    city_names = list(CITIES)
    default_idx = city_names.index(loc["name"]) if loc["name"] in city_names else 0
    st.selectbox(
        "Or pick a Pakistan city",
        city_names,
        index=default_idx,
        key="geo_quick",
        on_change=_apply_quick_pick,
    )

    st.caption(f"Active: **{loc['name']}** · source: `{loc['source']}`")
    return st.session_state[LOCATION_KEY]
