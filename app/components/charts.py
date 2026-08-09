"""
charts.py — Day 19: Plotly visualisations for the dashboard.

Two charts:

  plot_trend()   — the AQI story: observed hourly AQI over the live
                   window (last ~10 days), a marker where "now" is,
                   and the +24h/+48h/+72h forecast points stitched on
                   at their real timestamps. The colour of every trace
                   follows the EPA band of the value it shows, and the
                   band background is shaded so "which band are we in?"
                   is answerable at a glance.

  plot_forecast() — the three horizon cards as a compact bar/point
                    chart with the same band colours (used in the main
                    forecast section).

Both are pure functions: take data, return a plotly Figure. No
Streamlit calls here — the app decides where to render them.
"""

import pandas as pd
import plotly.graph_objects as go

from src.inference.predict import fetch_live_frame
from src.utils.aqi_utils import AQI_BANDS, aqi_color
from src.utils.logger import get_logger

logger = get_logger(__name__)

_BAND_BG = "rgba(128, 128, 128, 0.06)"  # neutral grid background


def _band_rects(y_max):
    """
    Translucent horizontal stripes for each EPA band, so the chart
    background itself answers "what band is this AQI in?".
    """
    shapes = []
    for lo, hi, label, color, _msg in AQI_BANDS:
        if lo > y_max:
            break
        shapes.append(
            go.layout.Shape(
                type="rect",
                xref="paper", x0=0, x1=1,
                yref="y", y0=lo, y1=min(hi, y_max),
                fillcolor=color,
                opacity=0.10,
                line_width=0,
                layer="below",
            )
        )
    return shapes


def plot_trend(lat, lon, city, result):
    """
    Observed AQI history + forecast markers.

    Parameters
    ----------
    lat, lon : float
        Location the forecast was made for.
    city : str
        Display label (also the 'city' column in the live frame).
    result : dict
        The dict returned by src.inference.predict.predict() — needs
        'current_aqi', 'forecast' ({'24':..,'48':..,'72':..}) and
        'fetched_at' (ISO timestamp).
    """
    df, now_ts = fetch_live_frame(lat, lon, city=city)

    observed = df["us_aqi"].dropna()
    fig = go.Figure()

    # Observed series, coloured per-band via a scatter with marker colors.
    fig.add_trace(
        go.Scatter(
            x=observed.index,
            y=observed.values,
            mode="lines",
            name="Observed AQI",
            line=dict(color="#1f77b4", width=1.5),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>AQI %{y}<extra>Observed</extra>",
        )
    )

    # Forecast points at their true timestamps (fetched_at + horizon).
    fetched_at = pd.Timestamp(result["fetched_at"]).tz_convert("UTC")
    fc_x, fc_y, fc_colors = [], [], []
    for h in ("24", "48", "72"):
        aqi = result["forecast"][h]
        fc_x.append(fetched_at + pd.Timedelta(hours=int(h)))
        fc_y.append(aqi)
        fc_colors.append(aqi_color(aqi))

    fig.add_trace(
        go.Scatter(
            x=fc_x,
            y=fc_y,
            mode="markers+text",
            name="Forecast",
            text=[f"+{h}h" for h in ("24", "48", "72")],
            textposition="top center",
            marker=dict(size=13, color=fc_colors, symbol="diamond",
                        line=dict(color="black", width=1)),
            hovertemplate="%{x|%Y-%m-%d %H:%M}<br>AQI %{y}<extra>Forecast</extra>",
        )
    )

    # "Now" reference line.
    fig.add_vline(x=now_ts.timestamp() * 1000, line_dash="dot",
                  line_color="gray", annotation_text=" now ",
                  annotation_position="top left")

    y_max = max(observed.max(), max(fc_y), 50) + 20
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=1.12, x=0),
        yaxis_title="US AQI",
        xaxis_title=None,
        shapes=_band_rects(y_max),
        hovermode="x unified",
    )
    fig.update_yaxes(range=[0, y_max])
    return fig


def plot_forecast(result):
    """
    The three horizons as a compact colour-coded bar chart.

    Used in the main forecast section so the +24/48/72 cards have a
    visual companion with the same EPA band colours.
    """
    horizons = ("24", "48", "72")
    values = [result["forecast"][h] for h in horizons]
    colors = [aqi_color(v) for v in values]

    fig = go.Figure(
        go.Bar(
            x=[f"+{h}h" for h in horizons],
            y=values,
            marker_color=colors,
            text=values,
            textposition="outside",
            hovertemplate="%{x} forecast<br>AQI %{y}<extra></extra>",
        )
    )
    y_max = max(values + [50]) + 20
    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="US AQI",
        xaxis_title=None,
        showlegend=False,
        shapes=_band_rects(y_max),
    )
    fig.update_yaxes(range=[0, y_max])
    return fig
