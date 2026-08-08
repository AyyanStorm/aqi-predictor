"""
streamlit_app.py — Day 17: Streamlit dashboard skeleton.

The first working page of the serving layer. It wires the Day 16
inference pipeline into a web UI: pick a city -> load the production
model from the registry -> show current AQI + the 3-day forecast.

Day 17 scope (roadmap): Streamlit FUNDAMENTALS — layout, widgets,
caching, session state. Deliberately NOT in this file yet:
    - geolocation / geocoding search        (Day 18: geo.py)
    - Plotly charts, AQI colour bands,       (Day 19: aqi_utils.py,
      health messages, alerts, leaderboard    components/charts.py)
    - SHAP explanations + talking SHAP       (Day 20)
The skeleton is structured so those slots in cleanly.

The three Streamlit ideas this page demonstrates:
    1. LAYOUT        — st.set_page_config + sidebar + columns, so the
                       page reads as a dashboard, not a script.
    2. WIDGETS       — selectbox (city), text_input (model name),
                       button (refresh) -> each rerun reads their state.
    3. CACHING       — @st.cache_data on the prediction call: Open-Meteo
                       is hit once per city per TTL, not on every widget
                       interaction. The button clears the cache to force
                       a fresh forecast.
    4. SESSION STATE — the chosen city survives reruns in
                       st.session_state, so sidebar changes don't reset
                       the page.

Error handling: the local registry may have no production model (data/
is gitignored; models live on the trainer's machine). The page shows a
friendly error instead of crashing — the same path a fresh Render
deploy would hit before its first training run.
"""

import sys
from pathlib import Path

import streamlit as st

# `streamlit run app/streamlit_app.py` puts app/ on sys.path, not the
# project root — so `import src` would fail with "No module named 'src'".
# Prepend the repo root explicitly (parents[1] of this file) so the app
# works no matter where it's launched from (local dev, Render, etc.).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import CITIES
from src.inference.predict import predict
from src.utils.logger import get_logger

logger = get_logger(__name__)

st.set_page_config(
    page_title="AQI Predictor — Pakistan",
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

    city_names = list(CITIES)
    # Session state: the chosen city survives every rerun.
    default_idx = city_names.index(
        st.session_state.get("city", "Karachi")
    ) if st.session_state.get("city") in city_names else 0
    city = st.selectbox(
        "City",
        city_names,
        index=default_idx,
        help="Model is city-agnostic (global) — any of these works.",
    )
    st.session_state["city"] = city

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

    st.caption("Forecast: +24h / +48h / +72h · US AQI")

# ---------------------------------------------------------------
# Main column — the forecast itself
# ---------------------------------------------------------------
st.title("🌫️ AQI Predictor — Pakistan")
st.caption(
    f"Live air quality forecast for **{city}** · "
    "city-agnostic model trained on 10 Pakistani cities · "
    f"lat {CITIES[city]['lat']}, lon {CITIES[city]['lon']}"
)

try:
    result = get_forecast(
        city,
        CITIES[city]["lat"],
        CITIES[city]["lon"],
        model_name or None,  # "" -> production model
    )
except (SystemExit, RuntimeError, KeyError) as e:
    st.error(f"Could not load the forecast: {e}")
    st.info(
        "No production model found in the registry. Train and promote one "
        "with:  `python -m src.training.train --model lgbm --register`"
    )
    st.stop()

current = result["current_aqi"]
forecast = result["forecast"]
model = result["model"]

# --- Row 1: current AQI + the three horizon cards ---
col_cur, col_24, col_48, col_72 = st.columns([1.2, 1, 1, 1])

with col_cur:
    st.metric("Current AQI", f"{current}", help="Last observed hourly AQI")

for col, h in ((col_24, 24), (col_48, 48), (col_72, 72)):
    with col:
        st.metric(f"+{h}h forecast", f"{forecast[str(h)]}",
                  help=f"Predicted AQI {h} hours from now")

# --- Row 2: model + data provenance ---
st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Model", f"{model['name']}_v{model['version']}")
m2.metric("Walk-forward RMSE", f"{model['mean_rmse']:.1f}")
m3.metric("Fetched at", f"{result['fetched_at'][11:16]} UTC")
m4.metric("City", city)

with st.expander("📍 Where do these numbers come from?"):
    st.markdown(
        """
        - **Data:** Open-Meteo (free, no key) — hourly AQI + pollutants for
          the last 10 days, forecast weather for the next 4 days.
        - **Features:** the SAME `build_features()` used in training
          (lags, rolling windows, change rate, cyclical time, future
          weather) — no training-serving skew by construction.
        - **Model:** the registry's production version, fed only the exact
          columns it was trained on.
        - **Output:** current observed AQI + predicted AQI at +24h/+48h/+72h.
        """
    )
