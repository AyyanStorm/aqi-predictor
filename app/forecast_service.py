"""
forecast_service.py — shared forecast loading for the multipage app.

The cached get_forecast() used to live in streamlit_app.py; with the
multipage redesign it moves here so both the Dashboard page (fetch) and
the navbar (refresh/clear) use the SAME cache — clearing from the navbar
must invalidate exactly what the dashboard reads.
"""

import streamlit as st

from src.inference.predict import predict


@st.cache_data(ttl=1800, show_spinner="Fetching live AQI data…")
def get_forecast(city, lat, lon, model_name):
    """Cached wrapper around the inference pipeline (30 min TTL)."""
    return predict(lat, lon, city=city, name=model_name)


def clear_forecast_cache():
    """Invalidate every cached forecast (navbar Refresh button)."""
    get_forecast.clear()
