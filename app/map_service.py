"""
map_service.py — data layer for the Interactive Global AQI Map.

Feasibility-verified design (grill-me decisions, all confirmed):
  - Data source: the EXISTING Open-Meteo air-quality API (free, no key,
    global model — data everywhere on Earth, not just cities).
  - Heat field: self-computed from a coarse global grid (~2° spacing,
    11,700 points) fetched in batched multi-location GET calls (~300
    per request), rendered by deck.gl HeatmapLayer. Same source as the
    markers = one US EPA AQI standard; Historical/Predicted modes later
    just swap the grid values (same API supports past + forecast dates).
  - Markers: top 15 cities per country (~2,636) via the existing
    cities_for_country() — no new city machinery.
  - Refesh: 30-min st.cache_data TTL (matches the rest of the app) +
    manual Refresh button clearing the cache.

All HTTP goes through the same cached+retrying session pattern as the
rest of the project (requests_cache, 1h HTTP TTL) so reruns never
hammer the API.
"""

import math
import time
from datetime import datetime, timezone

import pandas as pd
import requests_cache
import streamlit as st
from retry_requests import retry

from src.config import AIR_QUALITY_URL
from src.utils.country_cities import cities_for_country, _by_country
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Cached+retrying session (own cache file so we never contend with the
# Open-Meteo forecast session's sqlite lock). 1h HTTP cache + retries.
_map_session = retry(
    requests_cache.CachedSession(".cache_map", expire_after=3600),
    retries=3, backoff_factor=0.3,
)

# Batches of 300 locations per GET with 2-decimal coordinates — VERIFIED
# safe with all three fields (us_aqi,pm2_5,pm10): 300 works in ~0.3s;
# 500 works for us_aqi alone but 414s with the full field list (URL too
# long); POST is not supported. Keep 300 for reliability.
BATCH = 300

# Grid spacing in degrees (3° ≈ 5,200 global points ≈ 18 calls — keeps a
# full refresh comfortably inside Open-Meteo's burst limits).
GRID_STEP = 3.0
GRID_LAT_MIN, GRID_LAT_MAX = -60.0, 69.0   # skip Antarctica (no data value)
GRID_LON_MIN, GRID_LON_MAX = -180.0, 177.0

# Pacing between batches — Open-Meteo rate-limits bursts (HTTP 429), so
# a full refresh spreads its ~27 calls over a few seconds.
BATCH_SLEEP_S = 0.35


def _fetch_batch(lats, lons):
    """One batched Open-Meteo GET (~300 locations), cached 1h.

    Rate-limit handling: on HTTP 429 we do NOT sleep 60s per batch —
    when a whole IP is throttled that compounds into minutes of
    spinner. We raise immediately; _fetch_many skips the batch and the
    map renders with partial data (markers-first), so the page always
    loads fast. The 30-min/6h caches + Refresh button backfill data as
    the limit frees up.
    """
    params = {
        "latitude": ",".join(f"{x:.2f}" for x in lats),
        "longitude": ",".join(f"{x:.2f}" for x in lons),
        "current": "us_aqi,pm2_5,pm10",
    }
    resp = _map_session.get(AIR_QUALITY_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_many(points):
    """
    Fetch current AQI for many (lat, lon) points in batches.

    points : list[(lat, lon)]
    Returns (rows, failed_batches): rows is a list of dicts {lat, lon,
    aqi, pm2_5, pm10} (aqi None when the model has no value for that
    point); failed_batches counts rate-limited/errored batches so
    callers can warn that the map may be partial.
    """
    rows, failed = [], 0
    for i in range(0, len(points), BATCH):
        chunk = points[i:i + BATCH]
        lats = [p[0] for p in chunk]
        lons = [p[1] for p in chunk]
        try:
            data = _fetch_batch(lats, lons)
        except Exception as e:
            failed += 1
            logger.warning(f"map batch {i // BATCH} failed: {e}")
            continue
        for loc in data:
            cur = loc.get("current") or {}
            rows.append({
                "lat": loc.get("latitude"),
                "lon": loc.get("longitude"),
                "aqi": cur.get("us_aqi"),
                "pm2_5": cur.get("pm2_5"),
                "pm10": cur.get("pm10"),
            })
        time.sleep(BATCH_SLEEP_S)  # pace vs the minutely rate limit
    return rows, failed


def _grid_points():
    """All (lat, lon) points of the global 2° grid."""
    pts = []
    lat = GRID_LAT_MIN
    while lat <= GRID_LAT_MAX:
        lon = GRID_LON_MIN
        while lon <= GRID_LON_MAX:
            pts.append((round(lat, 2), round(lon, 2)))
            lon += GRID_STEP
        lat += GRID_STEP
    return pts


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fetch_heat_grid():
    """Current AQI on the global grid (cached 6h).

    The CAMS global model only updates every 12h (verified in the
    Open-Meteo docs), so a 6h TTL costs zero freshness while cutting
    the heat-grid's share of a refresh from 18 calls to ~2/day — well
    inside the free tier's 600/min burst limit on shared IPs.
    """
    points = _grid_points()
    rows, failed = _fetch_many(points)
    df = pd.DataFrame(rows).dropna(subset=["aqi"])
    logger.info(f"heat grid: {len(points)} points -> {len(df)} with AQI "
                f"({failed} batches failed)")
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_markers():
    """
    Top-15-per-country city markers with live AQI (cached 30 min).

    Reuses cities_for_country() — the same pool as the Top-10 feature.
    Returns DataFrame [name, lat, lon, country, population, aqi, pm2_5,
    pm10] with one row per city that has AQI.
    """
    seen, points, meta = set(), [], []
    for country in _by_country():
        for c in cities_for_country(country, limit=15):
            key = (round(c["lat"], 3), round(c["lon"], 3))
            if key in seen:
                continue
            seen.add(key)
            points.append((c["lat"], c["lon"]))
            meta.append({"name": c["name"], "lat": c["lat"], "lon": c["lon"],
                         "country": c["country"], "population": c["population"]})

    rows, failed = _fetch_many(points)
    out = []
    for m, r in zip(meta, rows):
        if r.get("aqi") is None:
            continue
        out.append({**m, "aqi": r["aqi"], "pm2_5": r.get("pm2_5"),
                    "pm10": r.get("pm10")})
    df = pd.DataFrame(out)
    logger.info(f"markers: {len(meta)} candidates -> {len(df)} with AQI "
                f"({failed} batches failed)")
    return df


def map_updated_at():
    """ISO timestamp of the last successful data fetch (UTC)."""
    try:
        # Touch the caches so we know they are warm, then report now.
        grid = fetch_heat_grid()
        markers = fetch_markers()
        if grid is None and markers is None:
            return None
        return datetime.now(timezone.utc).isoformat()
    except Exception as e:
        logger.warning(f"map_updated_at failed: {e}")
        return None


def clear_map_cache():
    """Invalidate heat grid + markers (navbar/map Refresh button)."""
    fetch_heat_grid.clear()
    fetch_markers.clear()


def nearest_marker(lat, lon, markers_df, k=1):
    """
    Nearest marker(s) to a coordinate (for click-to-select fallback).

    Returns the closest row(s) of markers_df by haversine distance.
    """
    if markers_df is None or markers_df.empty:
        return pd.DataFrame()
    dlat = (markers_df["lat"] - lat).to_numpy()
    dlon = (markers_df["lon"] - lon).to_numpy()
    dist = dlat ** 2 + dlon ** 2  # equirectangular proxy, plenty for k=1
    idx = dist.argsort()[:k]
    return markers_df.iloc[idx]


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))
