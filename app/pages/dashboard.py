"""
dashboard.py — the Dashboard page: forecast cards, health insight,
trend chart, SHAP explanations, horizon chart.

Everything that used to live in the single-page main column, minus the
sections that moved to their own pages (Compare / Tracking / Analytics).
The page reads the shared location from session_state (set by the
navbar's location dialog) — no sidebar, no hardcoded country.
"""

import logging

import pandas as pd
import streamlit as st

from app.forecast_service import get_forecast
from app.components.explanation import (
    render_explanations,
    fetch_city_events,
    add_event_shapes,
)
from app.components.forecast_cards import render_forecast_cards
from app.components.charts import plot_trend, plot_forecast
from app.components.accuracy import get_user_id, maybe_save_prediction
from src.utils.geo import short_country
from src.utils.logger import get_logger, log_event

logger = get_logger(__name__)


def _header(loc, model_name):
    """Glass page header: product, location context, supporting info."""
    country = short_country(loc.get("country"))
    title = "AQI Predictor" + (f" — {country}" if country else "")
    st.markdown(
        f'<div class="aqi-page-title"><span class="aqi-gradient-text">'
        f"{title}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="aqi-sub">📍 {loc.get("name", "Unknown")} · '
        f"live air quality forecast</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="aqi-context">Lat {loc.get("lat")}, '
        f'Lon {loc.get("lon")} · source: {loc.get("source")} · '
        f'model: {model_name or "production"} · '
        f"US EPA AQI · Open-Meteo (CAMS)</div>",
        unsafe_allow_html=True,
    )


def render_dashboard():
    """The Dashboard page body (called by the st.navigation router)."""
    loc = st.session_state.get("location", {})
    model_name = st.session_state.get("model_name", "")

    _header(loc, model_name)

    city = loc.get("name")
    lat, lon = loc.get("lat"), loc.get("lon")

    if not city or lat is None or lon is None:
        st.info("Pick a city from the navbar to see its forecast.")
        return

    try:
        result = get_forecast(city, lat, lon, model_name or None)
        log_event(
            logger, "forecast_loaded", city=city, lat=lat, lon=lon,
            source=loc.get("source"), model=model_name or "production",
        )
    except (SystemExit, RuntimeError, KeyError) as e:
        log_event(
            logger, "forecast_failed", city=city, lat=lat, lon=lon,
            error=str(e), level=logging.ERROR,
        )
        st.error(f"Could not load the forecast: {e}")
        st.info(
            "No production model found in the registry. Train and promote "
            "one with:  `python -m src.training.train --model lgbm "
            "--register`"
        )
        return

    # Row 1: colour-coded forecast cards (glass, EPA bands + local time).
    render_forecast_cards(result, loc)

    # Automatic per-browser prediction tracking (unchanged behaviour).
    _user_id = get_user_id()
    try:
        maybe_save_prediction(_user_id, loc, result)
    except Exception as e:
        logger.warning(f"AQI tracking save skipped: {e}")

    # Row 2: trend chart (observed history + forecast points) in glass.
    st.markdown('<div class="aqi-section">', unsafe_allow_html=True)
    st.subheader("📈 AQI trend")
    try:
        trend_fig = plot_trend(lat, lon, city, result)
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
        with st.container(border=True):
            st.plotly_chart(
                trend_fig, use_container_width=True,
                config={"displayModeBar": False},
            )
    except Exception as e:  # history fetch hiccup shouldn't kill the page
        st.warning(f"Trend chart unavailable: {e}")
    st.markdown("</div>", unsafe_allow_html=True)

    # Row 3: SHAP explainability (glass containers).
    st.divider()
    render_explanations(result)

    # Row 4: horizon cards as a compact glass chart.
    with st.container(border=True):
        st.plotly_chart(
            plot_forecast(result),
            use_container_width=True,
            config={"displayModeBar": False},
        )

    with st.expander("📍 Where do these numbers come from?"):
        st.markdown(
            """
            - **Data:** Open-Meteo (free, no key) — hourly AQI + pollutants
              for the last 10 days, forecast weather for the next 4 days.
            - **Scale:** **US EPA AQI** (0–500). Other apps may show China
              AQI, UK DAQI or Pakistan's scale — the same air gives
              different numbers on different scales.
            - **Source:** Open-Meteo's AQI is the **CAMS global atmospheric
              model** — an estimate averaged over a ~10 km grid cell, not a
              physical ground station.
            - **Timing:** the "Current AQI" is the last observed **hourly**
              value; many apps show a 12–24h nowcast instead, which lags
              spikes.
            - **Model:** the registry's production version, fed only the
              exact columns it was trained on.
            - **Output:** current observed AQI + predicted AQI at
              +24h/+48h/+72h.
            """
        )
