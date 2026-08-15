"""
leaderboard.py — dynamic Top-10 cities for the selected country.

The unique feature: one glance tells you which of the biggest cities in
the SELECTED city's country has the dirtiest air RIGHT NOW, sorted
worst-first, colour-coded by EPA band. Uses observed current AQI (no
model needed — this is a real-time ranking, not a forecast), fetched
through the same cached Open-Meteo client as everything else.

Dynamic by country (grill-me decisions, all confirmed):
  - City list comes from a static global dataset (simplemaps World
    Cities Basic, built by src/utils/build_world_cities.py) filtered by
    the selected city's country — no Pakistan hardcoding, works
    worldwide.
  - Candidate pool: top 15 cities by population for that country (the
    AQI-fetch budget); ranked worst-first by live AQI; top 10 shown
    (or fewer when a country has fewer valid cities / failed fetches).
  - Section heading follows the country: "Top 10 Cities in {Country}".
  - The old full structure is kept: heading, "worst right now" callout,
    bar chart, medal list.

The fetch is wrapped in st.cache_data (TTL 30 min) so the per-city API
calls happen at most once per half hour per user, not on every rerun.
"""

import pandas as pd
import streamlit as st

from src.config import AIR_QUALITY_URL
from src.data_ingestion.open_meteo_client import fetch_air_quality
from src.utils.aqi_utils import aqi_category, aqi_color
from src.utils.country_cities import cities_for_country
from src.utils.geo import short_country
from src.utils.logger import get_logger

logger = get_logger(__name__)

# How many candidate cities we fetch live AQI for per country (grill-me
# Q2: top 15 by population). Caps Open-Meteo calls per selection while
# leaving a buffer so a couple of failed fetches don't drop below 10.
CANDIDATE_POOL = 15
TOP_N = 10


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


def _fetch_ranked(country):
    """
    Fetch live AQI for the candidate pool, rank worst-first, cap at 10.

    Returns (rows, failures) where rows is [(city, aqi), ...] sorted by
    AQI descending (existing ranking logic: worst air right now first)
    and failures is the number of candidates with no AQI (fetch error or
    missing data). Never fabricates values — cities without AQI are
    simply skipped.
    """
    candidates = cities_for_country(country, limit=CANDIDATE_POOL)
    rows, failures = [], 0
    for city in candidates:
        try:
            aqi = _current_aqi(city["name"], city["lat"], city["lon"])
        except Exception as e:
            logger.warning(f"Leaderboard AQI fetch failed for {city['name']}: {e}")
            aqi = None
        if aqi is not None:
            rows.append((city["name"], aqi))
        else:
            failures += 1

    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:TOP_N], failures


def render_leaderboard(country):
    """
    Render the live Top-10 cities section for the selected city's country.

    country : str | None
        The country of the selected location (loc["country"]). None when
        the picker couldn't determine one (rare coordinate fallbacks) —
        we show a hint instead of crashing.
    """
    label = short_country(country) or country or "your country"
    st.subheader(f"🏁 Top 10 Cities in {label}")

    if not country:
        st.info(
            "Select a city to see the Top 10 ranking for its country "
            "(search any city, e.g. New York, London, Dubai, Tokyo)."
        )
        return

    candidates = cities_for_country(country, limit=CANDIDATE_POOL)
    if not candidates:
        st.info(
            f"No city data available for **{label}** yet — the dataset "
            "covers 244 countries, but if yours isn't among them we "
            "can't build a ranking. Try another city."
        )
        return

    rows, failures = _fetch_ranked(country)

    if not rows:
        st.warning(
            f"Could not fetch live AQI for any city in **{label}** "
            "right now. Please try again in a few minutes."
        )
        return

    worst_city, worst_aqi = rows[0]

    st.markdown(
        f"### 🌫️ Worst right now: **{worst_city}** — AQI **{worst_aqi}** "
        f"({aqi_category(worst_aqi)})"
    )

    # Bar chart: AQI per city, colour = EPA band.
    # Plotly (not st.bar_chart): st.bar_chart's `color` expects one color
    # per COLUMN, not per row, so per-city EPA colours crash it with a
    # StreamlitColorLengthError. Plotly marker_color is per-bar and plays
    # nicely with the rest of the dashboard's charts.
    import plotly.graph_objects as go

    chart = go.Figure(
        go.Bar(
            x=[c for c, _ in rows],
            y=[a for _, a in rows],
            marker_color=[aqi_color(a) for _, a in rows],
            text=[a for _, a in rows],
            textposition="outside",
            hovertemplate="%{x}<br>AQI %{y}<extra></extra>",
        )
    )
    chart.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Current AQI",
        xaxis_title=None,
        showlegend=False,
    )
    st.plotly_chart(chart, use_container_width=True,
                    config={"displayModeBar": False})

    # Text ranking with badges.
    for rank, (city, aqi) in enumerate(rows, start=1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")
        st.markdown(
            f"{medal} **{city}** — AQI **{aqi}** "
            f"<span style='color:{aqi_color(aqi)}'>●</span> "
            f"{aqi_category(aqi)}",
            unsafe_allow_html=True,
        )

    # Transparency: when the pool was bigger than what we show, or some
    # cities had no data, say so — never silently imply a full top-10.
    notes = []
    if len(rows) < TOP_N:
        notes.append(f"{len(rows)} of the top {TOP_N} shown")
    if failures:
        notes.append(f"AQI unavailable for {failures} candidate city/cities")
    if notes:
        st.caption("ℹ️ " + " · ".join(notes) + " — no data was invented.")
    st.caption("Cities: simplemaps.com (CC-BY 4.0) · AQI: Open-Meteo live, cached 30 min")
