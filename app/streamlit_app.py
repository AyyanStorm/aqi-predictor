"""
streamlit_app.py — Day 17: Streamlit dashboard skeleton.

The first working page of the serving layer. It wires the Day 16
inference pipeline into a web UI: pick a city -> load the production
model from the registry -> show current AQI + the 3-day forecast.

Day 17 scope (roadmap): Streamlit FUNDAMENTALS — layout, widgets,
caching, session state. Day 18 added the three-tier location picker
(geo.py + components/location_picker.py): browser GPS → IP → manual
search, with reverse geocoding to a display name.

Deliberately NOT in this file yet:
    - Plotly charts, AQI colour bands,       (Day 19: aqi_utils.py,
      health messages, alerts, leaderboard    components/charts.py)
    - SHAP explanations + talking SHAP       (Day 20)

The Streamlit ideas this page demonstrates:
    1. LAYOUT        — st.set_page_config + sidebar + columns, so the
                       page reads as a dashboard, not a script.
    2. WIDGETS       — location picker (3 tiers), text_input (model
                       name), button (refresh) -> reruns read state.
    3. CACHING       — @st.cache_data on the prediction call: Open-Meteo
                       is hit once per city per TTL, not on every widget
                       interaction. The button clears the cache to force
                       a fresh forecast.
    4. SESSION STATE — the location dict + city survive reruns in
                       st.session_state, so widget changes don't reset
                       the page.

Error handling: the local registry may have no production model (data/
is gitignored; models live on the trainer's machine). The page shows a
friendly error instead of crashing — the same path a fresh Render
deploy would hit before its first training run.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# `streamlit run app/streamlit_app.py` puts app/ on sys.path, not the
# project root — so `import src` (and `import app.components`) would fail
# with "No module named". Prepend the repo root explicitly (parents[1] of
# this file) so the app works no matter where it's launched from (local
# dev, Render, etc.).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.inference.predict import predict
from src.utils.logger import get_logger
from app.components.location_picker import location_picker
from app.components.forecast_cards import render_forecast_cards
from app.components.charts import plot_trend, plot_forecast
from app.components.leaderboard import render_leaderboard
from app.components.explanation import (
    render_explanations,
    fetch_city_events,
    add_event_shapes,
)
from app.components.accuracy import (
    get_user_id,
    maybe_save_prediction,
    render_accuracy,
)

logger = get_logger(__name__)

# --- Dynamic country for the heading (Day 23 UI polish) ---
# The "— <country>" suffix follows the SELECTED location, never hardcoded:
# quick-pick → Pakistan · search → geocode country · GPS/IP → reverse/
# IP country. On the very first load session state is empty, so the tab
# title starts country-less; the visible heading below always resolves
# against the live location (the sidebar sets it before the main column).
from src.utils.geo import short_country

_location = st.session_state.get("location")
_page_country = short_country(_location.get("country")) if _location else None
st.set_page_config(
    page_title=("AQI Predictor"
                + (f" — {_page_country}" if _page_country else "")),
    page_icon="🌫️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Cache the inference call for 30 minutes. The Open-Meteo client already
# caches HTTP responses for 1h; this layer stops build_features + model
# loading from re-running on every widget interaction.
@st.cache_data(ttl=1800, show_spinner="Fetching live AQI data…")
def get_forecast(city, lat, lon, model_name):
    """Cached wrapper around the Day 16 inference pipeline."""
    return predict(lat, lon, city=city, name=model_name)


# ---------------------------------------------------------------
# Sidebar — the dashboard's control panel
# ---------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Settings")

    # Day 18: three-tier location picker (browser GPS -> IP -> search).
    # Returns {"name", "lat", "lon", "source"}, persisted in session state.
    loc = location_picker()
    city, lat, lon = loc["name"], loc["lat"], loc["lon"]

    model_name = st.text_input(
        "Model (optional)",
        value="",
        placeholder="default = production",
        help="Registry model family, e.g. 'lgbm'. Empty uses the "
             "current production model.",
    )

    if st.button("🔄 Refresh forecast", use_container_width=True):
        get_forecast.clear()
        st.rerun()

    st.caption(
        "Forecast: +24h / +48h / +72h · **US EPA AQI scale** · "
        "source: Open-Meteo (CAMS model)"
    )

# ---------------------------------------------------------------
# Main column — the forecast itself
# ---------------------------------------------------------------
# Heading is dynamic: the country suffix follows the selected location
# (e.g. Karachi → "— Pakistan", Dubai → "— UAE", London → "— UK").
# short_country() maps long official names to compact labels.
_country = short_country(loc.get("country"))
st.title("🌫️ AQI Predictor" + (f" — {_country}" if _country else ""))
st.caption(
    f"Live air quality forecast for **{city}** · "
    "city-agnostic model trained on 10 Pakistani cities · "
    f"lat {lat}, lon {lon} · source: {loc['source']}"
)

try:
    result = get_forecast(
        city,
        lat,
        lon,
        model_name or None,  # "" -> production model
    )
except (SystemExit, RuntimeError, KeyError) as e:
    st.error(f"Could not load the forecast: {e}")
    st.info(
        "No production model found in the registry. Train and promote one "
        "with:  `python -m src.training.train --model lgbm --register`"
    )
    st.stop()
else:
    # Only reachable when the forecast loaded — everything below needs
    # `result`, so it lives in the else branch (st.stop() halts in real
    # runs, but this keeps bare/edge executions from falling through).

    # --- Row 1: colour-coded forecast cards (EPA bands + health message) ---
    # loc carries the resolved IANA timezone -> each card shows its local
    # date/time, ticking live via the fragment inside render_forecast_cards.
    render_forecast_cards(result, loc)

    # --- AQI tracking + accuracy (Day 24): automatic, per-browser. ---
    # Save this prediction (idempotent) and render the Prediction-vs-Actual
    # section + Your Average Accuracy. Everything is defensive — a tracking
    # failure must never break the forecast UI.
    try:
        _user_id = get_user_id()
        maybe_save_prediction(_user_id, loc, result)
        render_accuracy(_user_id, loc)
    except Exception as e:
        logger.warning(f"AQI tracking section skipped: {e}")

    # --- Row 2: trend chart (observed history + forecast points) ---
    st.divider()
    st.subheader("📈 AQI trend")
    try:
        trend_fig = plot_trend(lat, lon, city, result)
        # Day 20: smog-season event annotations (episodes + spikes) on
        # the trend chart, from events.py detectors.
        try:
            events = fetch_city_events(
                lat, lon, city,
                start=pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=10),
                end=pd.Timestamp.now(tz="UTC"),
            )
            add_event_shapes(trend_fig, events)
            if not events.empty:
                st.caption(
                    f"🗓️ {len(events)} event(s) detected on this window "
                    "(red bands = smog episodes, ★ = AQI spikes)"
                )
        except Exception as e:
            logger.warning(f"Event annotations skipped: {e}")
        st.plotly_chart(
            trend_fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )
    except Exception as e:  # history fetch hiccup shouldn't kill the page
        st.warning(f"Trend chart unavailable: {e}")

    # --- Row 2b: SHAP explainability + talking SHAP (Day 20) ---
    st.divider()
    render_explanations(result)

    # --- Row 3: the three horizon cards as a compact chart ---
    st.plotly_chart(
        plot_forecast(result),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    with st.expander("📍 Where do these numbers come from?"):
        st.markdown(
            """
            - **Data:** Open-Meteo (free, no key) — hourly AQI + pollutants for
              the last 10 days, forecast weather for the next 4 days.
            - **Scale:** **US EPA AQI** (0–500). Other apps may show China AQI,
              UK DAQI or Pakistan's scale — the same air gives different
              numbers on different scales.
            - **Source:** Open-Meteo's AQI is the **CAMS global atmospheric
              model** — an estimate averaged over a ~10 km grid cell, not a
              physical ground station. Apps like IQAir/AccuWeather usually
              show readings from nearby stations, so small differences (5–20
              points) are expected even on the same scale.
            - **Timing:** the "Current AQI" is the last observed **hourly**
              value; many apps show a 12–24h nowcast instead, which lags
              spikes.
            - **Why this is fine:** the model was *trained* on the same
              Open-Meteo/CAMS source, so training and live inference are
              consistent — that is what makes the +24h/+48h/+72h forecast
              reliable, which is the actual goal.
            - **Features:** the SAME `build_features()` used in training
              (lags, rolling windows, change rate, cyclical time, future
              weather) — no training-serving skew by construction.
            - **Model:** the registry's production version, fed only the exact
              columns it was trained on.
            - **Output:** current observed AQI + predicted AQI at +24h/+48h/+72h.
            """
        )

    # --- Row 4: live 10-city leaderboard (worst air right now) ---
    st.divider()
    try:
        render_leaderboard()
    except Exception as e:
        st.warning(f"Leaderboard unavailable: {e}")
