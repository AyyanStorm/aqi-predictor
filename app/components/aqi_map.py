"""
aqi_map.py — Interactive Global AQI Map component (deck.gl / pydeck).

grill-me decisions, all confirmed:
  - Global map, all countries, heatmap coloring (IQAir-style reference).
  - Engine: pydeck via its documented API (pdk.Layer("ScatterplotLayer",
    ...), pdk.Layer("HeatmapLayer", ...)) — installed, no reinstall.
  - Heat layer: self-computed from Open-Meteo grid (map_service) rendered
    as a deck.gl HeatmapLayer with the app's US EPA band colors.
  - Markers: top-15-per-country cities, colored by AQI band, pickable.
  - Refresh: 30-min cache TTL + manual Refresh + "updated X ago".
  - Two-way sync: clicking a marker selects that city app-wide
    (session_state["location"], source="map"); selecting a city anywhere
    re-centers/highlights the map.
  - Glassmorphism: dark CARTO basemap + glass legend + glass info card,
    Orbitron typography from app/theme.py.

Selection flow (Streamlit 1.61): st.pydeck_chart(on_select="rerun",
selection_mode="single-object") returns a selection state whose
.selection holds the clicked row; we map it back to the marker's city.
"""

import pandas as pd
import pydeck as pdk
import streamlit as st

from app.map_service import (
    fetch_heat_grid,
    fetch_markers,
    map_updated_at,
    clear_map_cache,
)
from app.theme import glass_card
from src.utils.aqi_utils import AQI_BANDS, aqi_category, aqi_color
from src.utils.geo import resolve_timezone, short_country
from src.utils.logger import get_logger

logger = get_logger(__name__)

LOCATION_KEY = "location"
SELECTION_KEY = "aqi_map_selection"


# ------------------------------------------------------------------
# Color helpers (EPA hex -> deck.gl rgba)
# ------------------------------------------------------------------
def _hex_to_rgb(hex_color, alpha=255):
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alpha]


def _band_rgba(aqi):
    """EPA band color as [r, g, b, a] for the given AQI value."""
    return _hex_to_rgb(aqi_color(aqi), alpha=230)


def _heat_color_range():
    """deck.gl colorRange: the six EPA band colors (green..maroon)."""
    return [_hex_to_rgb(band[3], alpha=220) for band in AQI_BANDS]


def _prepare_markers(df):
    """Add deck.gl-friendly columns (position + fill color) to markers."""
    if df is None or df.empty:
        return df
    out = df.copy()
    out["aqi"] = pd.to_numeric(out["aqi"], errors="coerce")
    out = out.dropna(subset=["aqi"])
    out["fill_color"] = out["aqi"].apply(_band_rgba)
    return out


def _prepare_grid(df):
    """HeatmapLayer input: position + weight (AQI)."""
    if df is None or df.empty:
        return df
    out = df.copy()
    out["aqi"] = pd.to_numeric(out["aqi"], errors="coerce")
    return out.dropna(subset=["aqi"])


# ------------------------------------------------------------------
# Deck construction
# ------------------------------------------------------------------
def _initial_view(loc):
    """Center the map on the selected city when known, else world view."""
    if loc and loc.get("lat") is not None and loc.get("lon") is not None:
        return pdk.ViewState(
            latitude=loc["lat"], longitude=loc["lon"],
            zoom=4.5, pitch=0, bearing=0,
        )
    return pdk.ViewState(latitude=25.0, longitude=15.0, zoom=1.6,
                         pitch=0, bearing=0)


def build_deck(grid_df, markers_df, loc):
    """The full pydeck Deck: heat layer + markers + dark basemap."""
    layers = []

    # Heat layer: AQI on the global grid, weight = AQI value.
    heat_data = _prepare_grid(grid_df)
    if heat_data is not None and not heat_data.empty:
        layers.append(pdk.Layer(
            "HeatmapLayer",
            data=heat_data,
            get_position="[lon, lat]",
            get_weight="aqi",
            radius_pixels=42,
            intensity=1.0,
            threshold=0.03,
            color_range=_heat_color_range(),
            opacity=0.55,
        ))

    # Marker layer: top-15-per-country cities, colored by band, pickable.
    marker_data = _prepare_markers(markers_df)
    if marker_data is not None and not marker_data.empty:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            data=marker_data,
            get_position="[lon, lat]",
            get_fill_color="fill_color",
            get_radius="population_radius",
            radius_min_pixels=3.5,
            radius_max_pixels=14,
            pickable=True,
            auto_highlight=True,
            stroked=True,
            get_line_color=[255, 255, 255, 120],
            line_width_min_pixels=0.8,
            tooltip={
                "html": "<b>{name}</b><br/>{country}<br/>"
                        "AQI <b>{aqi}</b> · {category}",
                "style": {
                    "backgroundColor": "rgba(10,14,24,0.92)",
                    "border": "1px solid rgba(255,255,255,0.18)",
                    "borderRadius": "10px",
                    "color": "#EEF2FA",
                    "fontFamily": "Orbitron, Inter, sans-serif",
                },
            },
        ))

    return pdk.Deck(
        layers=layers,
        initial_view_state=_initial_view(loc),
        map_style=pdk.map_styles.CARTO_DARK,
        tooltip={"text": "{name}"},
    )


# ------------------------------------------------------------------
# Selection -> selected city (two-way sync)
# ------------------------------------------------------------------
def _apply_map_selection(selection, markers_df):
    """
    Turn a pydeck click into the app-wide selected location.

    Streamlit delivers the clicked row's data in selection; we rebuild a
    location dict exactly like the picker does (source="map") so the
    navbar, Dashboard, Top-10 etc. all follow.
    """
    if selection is None:
        return False
    try:
        if hasattr(selection, "selection"):
            rows = selection.selection
        else:
            rows = selection
        if rows is None:
            return False
        if isinstance(rows, pd.DataFrame):
            if rows.empty:
                return False
            row = rows.iloc[0]
        else:
            row = rows
        name = row.get("name") or row.get("city")
        lat = row.get("lat") or row.get("latitude")
        lon = row.get("lon") or row.get("longitude")
        country = row.get("country")
        if not name or lat is None or lon is None:
            return False
        st.session_state[LOCATION_KEY] = {
            "name": str(name),
            "lat": float(lat),
            "lon": float(lon),
            "source": "map",
            "country": country,
            "timezone": resolve_timezone(float(lat), float(lon), name=str(name)),
        }
        logger.info(f"Location set by map click: {name} ({country})")
        return True
    except Exception as e:
        logger.warning(f"map selection failed: {e}")
        return False


# ------------------------------------------------------------------
# Legend + info card
# ------------------------------------------------------------------
def _legend_html():
    """Glass EPA legend (matches aqi_utils bands exactly)."""
    items = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;'
        f'font-family:var(--font-display);font-size:0.78rem;'
        f'letter-spacing:0.04em;text-transform:uppercase;color:var(--muted);">'
        f'<span style="width:14px;height:14px;border-radius:50%;'
        f'background:{band[3]};box-shadow:0 0 10px {band[3]}66;"></span>'
        f"{band[2]}</div>"
        for band in AQI_BANDS
    )
    return f"""
    <div style="display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;
         background:var(--glass);border:1px solid var(--border);
         border-radius:14px;padding:10px 16px;backdrop-filter:blur(12px);">
      <div style="font-family:var(--font-display);font-size:0.8rem;
           letter-spacing:0.14em;color:var(--text);text-transform:uppercase;">
        AQI&nbsp;·&nbsp;US&nbsp;EPA</div>
      {items}
    </div>
    """


def _selected_city_card(loc):
    """Glass info card for the currently selected city (real data)."""
    if not loc or not loc.get("name"):
        return
    st.markdown(
        '<div style="font-family:var(--font-display);letter-spacing:0.1em;'
        'text-transform:uppercase;color:var(--muted);font-size:0.8rem;'
        'margin-bottom:6px;">Selected location</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='font-family:var(--font-display);font-weight:700;"
        f"font-size:1.05rem;letter-spacing:0.04em;'>"
        f"{loc.get('name')}"
        f"{' · ' + short_country(loc.get('country')) if loc.get('country') else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"source: `{loc.get('source')}` · lat {loc.get('lat')}, "
               f"lon {loc.get('lon')}")


def _status_html(aqi):
    """Small glass row: AQI value + band + category for the card."""
    if aqi is None:
        return ""
    color = aqi_color(aqi)
    return f"""
    <div style="display:flex;align-items:center;gap:14px;margin-top:10px;">
      <div style="font-family:var(--font-display);font-size:2.4rem;
           font-weight:800;color:{color};
           text-shadow:0 0 26px {color}55;">{int(aqi)}</div>
      <div style="font-family:var(--font-display);font-size:0.85rem;
           letter-spacing:0.08em;text-transform:uppercase;color:var(--muted);">
        {aqi_category(aqi)}<br/>
        <span style="color:{color};">Current AQI</span>
      </div>
    </div>
    """


# ------------------------------------------------------------------
# Main render
# ------------------------------------------------------------------
def render_aqi_map():
    """The Interactive Global AQI Map section (Map page body)."""
    loc = st.session_state.get("location", {})

    # ---- Data (cached: heat grid 6h, markers 30 min) — fetch markers
    # first and render them even if the heat layer is partial, so a
    # rate-limited grid never hides the interactive map. ----
    try:
        markers_df = fetch_markers()
    except Exception as e:
        logger.error(f"map marker fetch failed: {e}")
        st.error("Could not fetch global AQI data right now. "
                 "Please try again in a minute.")
        return

    grid_df = None
    try:
        grid_df = fetch_heat_grid()
    except Exception as e:
        logger.warning(f"heat grid unavailable (markers still shown): {e}")

    # ---- Controls row: refresh + updated-at ----
    c_refresh, c_updated = st.columns([1, 4])
    with c_refresh:
        if st.button("🔄 Refresh map", key="map_refresh",
                     use_container_width=True):
            clear_map_cache()
            st.rerun()
    with c_updated:
        updated = map_updated_at()
        if updated:
            st.caption(f"🕐 Updated {updated[11:16]} UTC · auto-refreshes "
                       "every 30 min")

    # ---- Legend (above the map, always visible) ----
    st.markdown(_legend_html(), unsafe_allow_html=True)

    if markers_df is None or markers_df.empty:
        st.info("No AQI data available yet — try the refresh button.")
        return

    # Marker radius by population (log scale, clamped).
    markers_df = markers_df.copy()
    pop = pd.to_numeric(markers_df.get("population"), errors="coerce").fillna(100_000)
    markers_df["population_radius"] = 4 + 10 * (
        (pop.clip(50_000, 20_000_000).apply(lambda x: x ** 0.25))
        / (20_000_000 ** 0.25)
    )

    # ---- Two-way sync: click -> select city ----
    deck = build_deck(grid_df, markers_df, loc)
    selection = st.pydeck_chart(
        deck,
        use_container_width=True,
        height=560,
        selection_mode="single-object",
        on_select="rerun",
        key="aqi_map",
    )
    _apply_map_selection(selection, markers_df)

    # ---- Selected-city info card (real data from markers) ----
    st.divider()
    _selected_city_card(loc)
    if loc and loc.get("name"):
        row = markers_df[markers_df["name"] == loc.get("name")]
        if not row.empty:
            r = row.iloc[0]
            st.markdown(_status_html(r["aqi"]), unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                pm = r.get("pm2_5")
                st.markdown(glass_card("PM2.5", f"{pm:.1f}" if pm is not None
                                       else "—", "µg/m³", "#06B6D4"),
                            unsafe_allow_html=True)
            with c2:
                pm10 = r.get("pm10")
                st.markdown(glass_card("PM10", f"{pm10:.1f}" if pm10 is not None
                                       else "—", "µg/m³", "#3B82F6"),
                            unsafe_allow_html=True)
        else:
            st.caption("Click any city marker on the map to select it — "
                       "the whole dashboard follows.")
    else:
        st.caption("Click any city marker on the map to select it — "
                   "the whole dashboard follows.")
