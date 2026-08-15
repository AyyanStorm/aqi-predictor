"""
forecast_cards.py — Day 19: colour-coded forecast cards.

Renders the current + +24h/+48h/+72h forecasts as cards whose border
and badge follow the US EPA band colour of the value, with the band
label and EPA health message underneath. The "current" card also flags
hazardous air (AQI >= 151) with a clear alert.

Day 24 addition: each card carries a footer showing that period's
LOCAL date/time in the selected city's timezone (e.g. "Current" ->
the city's current local time, "+24h" -> the exact local time 24
hours from now). The card row runs inside an st.fragment(run_every=30)
so the times tick live — recomputed inside the fragment body on every
beat (never captured as stale args). When the timezone can't be
resolved the cards render exactly as before, minus the footers.

Pure Streamlit rendering — all AQI-band logic lives in
src/utils/aqi_utils.py and all time math in src/utils/local_time.py so
the FastAPI endpoint and the dashboard can never disagree.
"""

import streamlit as st

from src.utils.aqi_utils import (
    aqi_category,
    aqi_color,
    health_message,
    is_hazardous,
)
from src.utils.local_time import format_local_dt, horizon_times, tz_display_name
from app.theme import glass_card


def _card_html(title, aqi, subtitle, accent, time_str=None):
    """One forecast card as a premium glass card (app/theme.py CSS)."""
    return glass_card(title, aqi, subtitle, accent, time_str=time_str)


@st.fragment(run_every=30)
def _cards_fragment(current, forecast, tz_name):
    """The four AQI cards, re-run every 30s so the local times tick.

    IMPORTANT: only `tz_name` is passed in — the timestamps are
    recomputed inside the body on every beat. If we passed a datetime
    in, the fragment would re-render the same frozen value forever.
    """
    times = horizon_times(tz_name)  # [(label, aware_dt)] or None

    col_cur, col_24, col_48, col_72 = st.columns(4)

    with col_cur:
        st.markdown(
            _card_html(
                "Current AQI",
                current,
                aqi_category(current),
                aqi_color(current),
                time_str=format_local_dt(times[0][1]) if times else None,
            ),
            unsafe_allow_html=True,
        )

    for col, h in ((col_24, 24), (col_48, 48), (col_72, 72)):
        aqi = forecast[str(h)]
        with col:
            st.markdown(
                _card_html(
                    f"+{h}h forecast",
                    aqi,
                    aqi_category(aqi),
                    aqi_color(aqi),
                    time_str=format_local_dt(times[h // 24][1]) if times else None,
                ),
                unsafe_allow_html=True,
            )


def render_forecast_cards(result, loc=None):
    """
    Render the four AQI cards (current + 3 horizons) with band colours
    and, when the timezone is known, the local time for each period.

    Parameters
    ----------
    result : dict
        The dict returned by src.inference.predict.predict().
    loc : dict | None
        The active location dict (name/lat/lon/timezone...). Falls back
        to st.session_state["location"] when omitted.
    """
    if loc is None:
        loc = st.session_state.get("location", {})

    current = result["current_aqi"]
    forecast = result["forecast"]
    tz_name = loc.get("timezone")

    _cards_fragment(current, forecast, tz_name)

    # Health message under the cards (for the worst value shown).
    worst = max([current] + list(forecast.values()))
    if is_hazardous(worst):
        st.error(
            f"⚠️ **Hazardous air (AQI {worst})** — {health_message(worst)}"
        )
    else:
        st.info(f"💡 {health_message(worst)}")

    # One-line provenance row + timezone context (static per city).
    m = result["model"]
    st.caption(
        f"Model **{m['name']}_v{m['version']}** · walk-forward RMSE "
        f"{m['mean_rmse']:.1f} · fetched {result['fetched_at'][11:16]} UTC"
    )
    if tz_name:
        label = tz_display_name(tz_name)
        st.caption(f"🕐 Times in **{loc.get('name', '')}** local time — {label}")
    else:
        st.caption("🕐 Local times unavailable — timezone lookup failed for this location.")
