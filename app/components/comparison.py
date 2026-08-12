"""
comparison.py — Multi-City Historical vs Predicted AQI Comparison.

grill-me decisions (all confirmed by AYYAN):
  - Historical source: LIVE Open-Meteo fetch (cached 1h) — any city worldwide.
  - Predictions: LIVE predict() per city (cached 30 min) — always fresh.
  - Window: last 15 days historical + 72h predicted.
  - Max 6 cities per comparison (readable, snappy first run).
  - X-axis: UTC shared timeline; hover shows each city's LOCAL date/time.

Design (matches the existing dark AQI Predictor language):
  - st.multiselect with a 6-city cap + an "add any city" geocode search.
  - One line per city: SOLID = historical, DASHED = predicted (markers at
    current/+24/+48/+72). Colors auto-assigned, stable within a comparison.
  - Legend keeps city names (not color-only) — accessibility.
  - Loading spinner, "select at least one city" empty state, per-city
    fetch failures degrade to warnings without killing the comparison.
  - Everything defensive: a failure here never breaks the forecast UI.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from zoneinfo import ZoneInfo

from src.config import AIR_QUALITY_URL, CITIES
from src.data_ingestion.open_meteo_client import fetch_air_quality
from src.inference.predict import predict
from src.utils.geo import geocode, resolve_timezone
from src.utils.logger import get_logger

logger = get_logger(__name__)

MAX_CITIES = 6
HISTORY_DAYS = 15  # grill-me Q3: last 15 days + 72h

# Distinct colours readable on the dark #0e1117 background; assigned in
# selection order so the mapping stays stable within a comparison.
PALETTE = [
    "#4fc3f7",  # light blue
    "#ffb74d",  # amber
    "#81c784",  # green
    "#f06292",  # pink
    "#ba68c8",  # purple
    "#ff8a65",  # orange
]

EXTRA_KEY = "cmp_extra_cities"


# ---------------------------------------------------------------
# Data (both sources live + cached, per grill-me Q1/Q2)
# ---------------------------------------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_predict(city, lat, lon):
    """predict() wrapped in st.cache_data — same pattern as the dashboard."""
    return predict(lat, lon, city=city)


def _history_df(lat, lon):
    """Last HISTORY_DAYS of observed hourly us_aqi (UTC), cached 1h by the
    Open-Meteo client session. Returns DataFrame or None on failure."""
    try:
        end = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        start = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=HISTORY_DAYS)
                 ).strftime("%Y-%m-%d")
        df = fetch_air_quality(lat, lon, start, end, AIR_QUALITY_URL)
        if df is None or df.empty or "us_aqi" not in df.columns:
            return None
        out = pd.DataFrame({
            "time": pd.to_datetime(df["date"]),
            "aqi": pd.to_numeric(df["us_aqi"], errors="coerce"),
        }).dropna(subset=["aqi"])
        return out if not out.empty else None
    except Exception as e:
        logger.warning(f"history fetch failed for ({lat}, {lon}): {e}")
        return None


def _prediction_df(result, tz_name):
    """Predicted points (current/+24/+48/+72) as a DataFrame (UTC)."""
    base = pd.Timestamp(result["fetched_at"]).floor("h")
    rows = [{"time": base, "aqi": int(result["current_aqi"]),
             "label": "Current"}]
    for h in (24, 48, 72):
        rows.append({"time": base + pd.Timedelta(hours=h),
                     "aqi": int(result["forecast"][str(h)]),
                     "label": f"+{h}h"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------
# City option handling (10 quick-pick + any geocoded city)
# ---------------------------------------------------------------
def _city_options():
    """[(label, lat, lon, tz)] — the 10 training cities + user-added ones."""
    options = [{"label": name, "lat": c["lat"], "lon": c["lon"],
                "timezone": None}
               for name, c in CITIES.items()]
    for extra in st.session_state.get(EXTRA_KEY, []):
        options.append(extra)
    return options


def _add_city(query):
    """Geocode a query and append the top match to the user's city list."""
    if not query or not query.strip():
        return False
    try:
        results = geocode(query.strip(), count=1)
    except Exception as e:
        logger.warning(f"geocode failed for '{query}': {e}")
        return False
    if not results:
        return False
    r = results[0]
    label = f"{r['name']}, {r.get('country', '')}".strip(", ")
    tz = r.get("timezone") or resolve_timezone(r["latitude"], r["longitude"])
    extras = st.session_state.setdefault(EXTRA_KEY, [])
    if all(e["label"] != label for e in extras):
        extras.append({"label": label, "lat": r["latitude"],
                       "lon": r["longitude"], "timezone": tz})
    return True


def _resolve(selected, options):
    """Map selected labels back to their {label, lat, lon, timezone} dicts."""
    by_label = {o["label"]: o for o in options}
    return [by_label[label] for label in selected if label in by_label]


# ---------------------------------------------------------------
# Chart
# ---------------------------------------------------------------
def _comparison_chart(city_data, failures):
    """
    city_data: list of dicts {label, tz_name, hist_df, pred_df, color}
    Returns a Plotly figure: solid historical + dashed predicted per city.
    """
    fig = go.Figure()

    for c in city_data:
        label, color = c["label"], c["color"]
        # Historical — solid line.
        if c["hist_df"] is not None and not c["hist_df"].empty:
            fig.add_trace(go.Scatter(
                x=c["hist_df"]["time"], y=c["hist_df"]["aqi"],
                mode="lines",
                name=label,
                legendgroup=label,
                line=dict(color=color, width=1.8),
                customdata=c["hist_df"]["time"].dt.strftime("%Y-%m-%d %H:%M UTC"),
                hovertemplate=(
                    "<b>%{legendtext}</b> · Historical<br>"
                    "AQI %{y:.0f}<br>"
                    "UTC %{customdata}<br>"
                    "Local <extra></extra>"
                ),
            ))
        # Predicted — dashed line with markers at current/+24/+48/+72.
        if c["pred_df"] is not None and not c["pred_df"].empty:
            fig.add_trace(go.Scatter(
                x=c["pred_df"]["time"], y=c["pred_df"]["aqi"],
                mode="lines+markers",
                name=label,
                legendgroup=label,
                showlegend=False,
                line=dict(color=color, width=2.2, dash="dash"),
                marker=dict(size=7, color=color, symbol="circle-open"),
                customdata=c["pred_df"]["time"].dt.strftime("%Y-%m-%d %H:%M UTC"),
                hovertemplate=(
                    "<b>%{legendtext}</b> · Predicted<br>"
                    "AQI %{y:.0f}<br>"
                    "UTC %{customdata}<br>"
                    "Local <extra></extra>"
                ),
            ))

    # Now marker: where history ends and prediction begins.
    if city_data:
        base = min(c["pred_df"]["time"].min() for c in city_data
                   if c["pred_df"] is not None and not c["pred_df"].empty)
        fig.add_vline(x=base, line_dash="dot", line_color="#8b93a1",
                      annotation_text=" predictions begin →",
                      annotation_position="top right",
                      annotation_font=dict(size=11, color="#8b93a1"))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        font=dict(color="#e6e6e6"),
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=12)),
        xaxis=dict(title="Time (UTC) · hover shows each city's local time",
                   gridcolor="#262b36"),
        yaxis=dict(title="AQI (US EPA)", gridcolor="#262b36"),
        hovermode="x unified",
    )
    if failures:
        fig.add_annotation(
            text="⚠️ " + " · ".join(failures),
            xref="paper", yref="paper", x=0, y=1.12,
            showarrow=False, font=dict(size=11, color="#ffb74d"),
        )
    return fig


# ---------------------------------------------------------------
# Main render
# ---------------------------------------------------------------
def render_comparison():
    """The 'Multi-City Historical vs Predicted AQI' section."""
    st.divider()
    st.subheader("🌍 Multi-City Historical vs Predicted AQI")

    options = _city_options()
    labels = [o["label"] for o in options]
    default_idx = 0 if labels else None

    # ---- Selection controls ----
    c_sel, c_add = st.columns([3, 1])
    with c_sel:
        selected = st.multiselect(
            "Select cities to compare (max 6)",
            options=labels,
            default=[labels[default_idx]] if default_idx is not None else [],
            max_selections=MAX_CITIES,
            help="Pick 2–6 cities. Solid line = historical AQI, "
                 "dashed = predicted (+24/+48/+72h).",
        )
    with c_add:
        q = st.text_input("Add any city", placeholder="e.g. Dubai, Tokyo…",
                          key="cmp_query")
        if st.button("➕ Add", use_container_width=True) and _add_city(q):
            st.rerun()

    st.caption(
        f"Selected: **{len(selected)}/{MAX_CITIES}** — "
        + (", ".join(f"`{s}`" for s in selected) if selected else "none yet")
    )

    # ---- Empty state ----
    if len(selected) < 2:
        st.info(
            "Select **at least two cities** and press **Start Comparing** to "
            "see historical (solid) and predicted (dashed) AQI side by side."
        )
        return

    # ---- Start comparing ----
    if not st.button("🚀 Start Comparing", type="primary",
                     use_container_width=True):
        st.caption("Press **Start Comparing** to build the graph.")
        return

    with st.spinner("Fetching history + generating predictions… "
                    "(first run per city takes a few seconds)"):
        city_data, failures = [], []
        resolved = _resolve(selected, options)
        for i, city in enumerate(resolved):
            color = PALETTE[i % len(PALETTE)]
            tz_name = city.get("timezone") or resolve_timezone(
                city["lat"], city["lon"], name=city["label"].split(",")[0])
            hist = _history_df(city["lat"], city["lon"])
            if hist is None:
                failures.append(f"{city['label']} (history unavailable)")
            try:
                result = _cached_predict(
                    city["label"].split(",")[0], city["lat"], city["lon"])
                pred = _prediction_df(result, tz_name)
            except Exception as e:
                logger.warning(f"predict failed for {city['label']}: {e}")
                failures.append(f"{city['label']} (prediction failed)")
                continue
            city_data.append({
                "label": city["label"], "tz_name": tz_name,
                "hist_df": hist, "pred_df": pred, "color": color,
            })

    if not city_data:
        st.error("Comparison failed for all selected cities. "
                 "Check the warnings above and try different cities.")
        return

    fig = _comparison_chart(city_data, failures)
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
    st.caption(
        "Solid = **historical** (observed) · dashed = **predicted** "
        "(+24/+48/+72h) · shared UTC timeline; hover a point for that "
        "city's **local** date/time."
    )
    if failures:
        st.warning("Some data was unavailable: " + "; ".join(failures))
