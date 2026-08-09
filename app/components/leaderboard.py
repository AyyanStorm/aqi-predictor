"""
leaderboard.py — Day 19: live 10-city leaderboard ("worst city right now").

The unique feature: one glance tells you which of the 10 training
cities has the dirtiest air RIGHT NOW, sorted worst-first, colour-coded
by EPA band. Uses observed current AQI (no model needed — this is a
real-time ranking, not a forecast), fetched through the same cached
Open-Meteo client as everything else.

The fetch is wrapped in st.cache_data (TTL 30 min) so the 10 API calls
happen at most once per half hour per user, not on every rerun.
"""

import pandas as pd
import streamlit as st

from src.config import CITIES, AIR_QUALITY_URL
from src.data_ingestion.open_meteo_client import fetch_air_quality
from src.utils.aqi_utils import aqi_category, aqi_color
from src.utils.logger import get_logger

logger = get_logger(__name__)


@st.cache_data(ttl=1800, show_spinner=False)
def _current_aqi(city, lat, lon):
    """
    Last observed hourly AQI for one city (cached 30 min).

    Fetches the trailing 48h and takes the most recent observed row —
    far lighter than a full inference call, which is all the leaderboard
    needs (observed ranking, not forecasts).
    """
    now = pd.Timestamp.now(tz="UTC").floor("h")
    start = (now - pd.Timedelta(hours=48)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    df = fetch_air_quality(lat, lon, start, end, AIR_QUALITY_URL)
    observed = df["us_aqi"].dropna()
    if observed.empty:
        return None
    return int(round(float(observed.iloc[-1])))


def render_leaderboard():
    """
    Render the live leaderboard: all 10 cities, worst AQI first, with
    EPA colour badges and a "worst right now" callout.
    """
    st.subheader("🏁 Live 10-city leaderboard — worst air right now")

    rows = []
    for city, coords in CITIES.items():
        aqi = _current_aqi(city, coords["lat"], coords["lon"])
        if aqi is not None:
            rows.append((city, aqi))

    if not rows:
        st.info("Leaderboard unavailable — could not fetch live AQI for any city.")
        return

    rows.sort(key=lambda r: r[1], reverse=True)
    worst_city, worst_aqi = rows[0]

    st.markdown(
        f"### 🌫️ Worst right now: **{worst_city}** — AQI **{worst_aqi}** "
        f"({aqi_category(worst_aqi)})"
    )

    # Bar chart: AQI per city, colour = EPA band.
    chart_data = pd.DataFrame(rows, columns=["city", "aqi"]).set_index("city")
    st.bar_chart(
        chart_data,
        color=[aqi_color(a) for a in chart_data["aqi"]],
        height=320,
    )

    # Text ranking with badges.
    for rank, (city, aqi) in enumerate(rows, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        st.markdown(
            f"{medal} **{city}** — AQI **{aqi}** "
            f"<span style='color:{aqi_color(aqi)}'>●</span> "
            f"{aqi_category(aqi)}",
            unsafe_allow_html=True,
        )
