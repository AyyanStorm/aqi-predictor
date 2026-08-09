"""
explanation.py — Day 20: render SHAP explanations + smog-event
annotations in the dashboard.

Two jobs:

  render_explanations(result)
      "Why this forecast?" — talking SHAP sentences for +24/48/72h plus
      a horizontal contributor chart per horizon (features pushing AQI
      up in red, pulling it down in blue, using plain-English labels
      from explain.py). SHAP computation is cached per model version.

  add_event_shapes(fig, events)
      Overlays smog-season annotations on a trend chart: red shaded
      bands for EPISODES (sustained unhealthy air, Oct–Feb smog) and
      markers for SPIKES (sharp peaks), using events.py detectors.

Everything degrades gracefully: if no production model is registered
(the dashboard can't compute SHAP without it), the section explains
that instead of crashing — same philosophy as the rest of the app.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.utils.events import detect_events
from src.utils.explain import explain, talking_all
from src.utils.logger import get_logger

logger = get_logger(__name__)


@st.cache_data(ttl=1800, show_spinner="Explaining the forecast (SHAP)…")
def _cached_explain(result, model_name, model_version):
    """SHAP explanation, cached per model version + fetch time."""
    return explain(result)


def render_explanations(result):
    """
    Render talking SHAP + contributor charts for all three horizons.

    Parameters
    ----------
    result : dict
        Output of src.inference.predict.predict().
    """
    m = result["model"]
    try:
        explanation = _cached_explain(result, m["name"], m["version"])
    except (SystemExit, FileNotFoundError, KeyError) as e:
        st.info(
            f"🔍 Explanations unavailable: {e}\n\n"
            "SHAP needs the production model — once a model is trained "
            "and promoted, every forecast here comes with a plain-English "
            "explanation of *why*."
        )
        return

    st.subheader("🔍 Why this forecast? (SHAP)")
    sentences = talking_all(explanation)

    for h in ("24", "48", "72"):
        with st.container(border=True):
            st.markdown(f"**+{h}h forecast — {result['forecast'][h]} AQI**")
            st.markdown(f"💬 {sentences[h]}")
            _contributor_chart(explanation, h)


def _contributor_chart(explanation, horizon):
    """
    Horizontal bar chart of SHAP contributions for one horizon:
    red = pushes AQI up, blue = pulls it down. Top 8 by |SHAP|.
    """
    contribs = explanation["horizons"][horizon]["contributors"][:8]
    labels = explanation["labels"]

    names = [labels.get(f, f) for f, _ in contribs][::-1]
    values = [v for _, v in contribs][::-1]
    colors = ["#d62728" if v > 0 else "#1f77b4" for v in values]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=colors,
            hovertemplate="%{y}: %{x:+.2f} AQI<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="SHAP contribution to AQI (points)",
        yaxis_title=None,
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------
# Smog-season event annotations on the trend chart
# ---------------------------------------------------------------

def fetch_city_events(lat, lon, city, start, end):
    """
    Detect smog episodes + spikes for one city within a time window.

    Parameters
    ----------
    lat, lon : float
        City coordinates (anywhere Open-Meteo covers).
    city : str
        City label — also the 'city' column value in the live frame.
    start, end : pd.Timestamp
        Window (the trend chart's x-range).

    Returns
    -------
    pd.DataFrame : events (city, event_type, start, end, peak_aqi, ...)
        filtered to the window; empty if none.
    """
    from src.inference.predict import fetch_live_frame

    df, _ = fetch_live_frame(lat, lon, city=city)
    events = detect_events(df, cities=[city])
    if events.empty:
        return events
    mask = (
        (pd.to_datetime(events["end"]) >= start)
        & (pd.to_datetime(events["start"]) <= end)
    )
    return events[mask]


def add_event_shapes(fig, events):
    """
    Overlay smog-season event annotations on a plotly figure.

    - EPISODE -> translucent red band across the event's [start, end].
    - SPIKE   -> orange diamond marker at the peak.

    Mutates and returns the figure.
    """
    if events is None or events.empty:
        return fig

    for _, ev in events.iterrows():
        start = pd.to_datetime(ev["start"])
        end = pd.to_datetime(ev["end"])
        if ev["event_type"] == "episode":
            fig.add_vrect(
                x0=start, x1=end,
                fillcolor="red", opacity=0.15, line_width=0,
                annotation_text="smog episode",
                annotation_position="top left",
                annotation_font_size=11,
            )
        else:  # spike
            fig.add_trace(
                go.Scatter(
                    x=[end],
                    y=[ev["peak_aqi"]],
                    mode="markers",
                    marker=dict(symbol="star", size=14, color="#ff7f0e",
                                line=dict(color="black", width=1)),
                    name="AQI spike",
                    hovertemplate=(
                        f"Spike: peak {ev['peak_aqi']} AQI "
                        f"({ev['start'][:10]})<extra></extra>"
                    ),
                )
            )
    return fig
