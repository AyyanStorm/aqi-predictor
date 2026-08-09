"""
forecast_cards.py — Day 19: colour-coded forecast cards.

Renders the current + +24h/+48h/+72h forecasts as cards whose border
and badge follow the US EPA band colour of the value, with the band
label and EPA health message underneath. The "current" card also flags
hazardous air (AQI >= 151) with a clear alert.

Pure Streamlit rendering — all AQI-band logic lives in
src/utils/aqi_utils.py so the FastAPI endpoint and the dashboard can
never disagree about what a number means.
"""

import streamlit as st

from src.utils.aqi_utils import (
    aqi_category,
    aqi_color,
    health_message,
    is_hazardous,
)


def _card_html(title, aqi, subtitle, accent):
    """One forecast card as inline-styled HTML (Streamlit-safe subset)."""
    return f"""
    <div style="
        border: 2px solid {accent};
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 8px;
        background: #0e1117;">
      <div style="font-size: 0.85rem; color: #aaa;">{title}</div>
      <div style="font-size: 2.4rem; font-weight: 700; color: {accent};">
        {aqi}
      </div>
      <div style="font-size: 0.9rem; color: {accent}; font-weight: 600;">
        {subtitle}
      </div>
    </div>
    """


def render_forecast_cards(result):
    """
    Render the four AQI cards (current + 3 horizons) with band colours.

    Parameters
    ----------
    result : dict
        The dict returned by src.inference.predict.predict().
    """
    current = result["current_aqi"]
    forecast = result["forecast"]

    col_cur, col_24, col_48, col_72 = st.columns(4)

    with col_cur:
        st.markdown(
            _card_html(
                "Current AQI",
                current,
                aqi_category(current),
                aqi_color(current),
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
                ),
                unsafe_allow_html=True,
            )

    # Health message under the cards (for the worst value shown).
    worst = max([current] + list(forecast.values()))
    if is_hazardous(worst):
        st.error(
            f"⚠️ **Hazardous air (AQI {worst})** — {health_message(worst)}"
        )
    else:
        st.info(f"💡 {health_message(worst)}")

    # One-line provenance row.
    m = result["model"]
    st.caption(
        f"Model **{m['name']}_v{m['version']}** · walk-forward RMSE "
        f"{m['mean_rmse']:.1f} · fetched {result['fetched_at'][11:16]} UTC"
    )
