"""
geo.py — Day 18: three-tier geolocation + geocoding search.

The dashboard needs to know WHERE the user is, with graceful degradation:

  Tier 1  Browser geolocation  — JS Geolocation API via streamlit-js-eval.
                                Precise, but needs permission + HTTPS.
  Tier 2  IP-based lookup      — ipapi.co (free, no key); falls back to
                                ipwho.is then ip-api.com if rate-limited.
  Tier 3  Manual search        — Open-Meteo Geocoding API: type a city,
                                pick a match. Always works.

Plus reverse geocoding (lat/lon -> display name) via Nominatim
(OpenStreetMap) — free, no key, just requires a real User-Agent.

This module is deliberately pure Python (no Streamlit import) so it can
be unit-tested headlessly and reused by the FastAPI endpoint on Day 19.
The Streamlit plumbing (buttons, session state) lives in
app/components/location_picker.py.
"""

import requests_cache
from retry_requests import retry

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Same cached+retrying session pattern as open_meteo_client.py (Day 1):
# geo lookups are slow HTTP calls; caching stops widget reruns from
# hammering the APIs, retries smooth over transient failures.
# Separate cache file (.cache_geo) so we never contend with the
# Open-Meteo session for the same sqlite lock.
_geo_session = requests_cache.CachedSession(".cache_geo", expire_after=3600)
_geo_session = retry(_geo_session, retries=3, backoff_factor=0.3)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

# IP providers in priority order. ipapi.co is the roadmap pick; ipwho.is
# and ip-api.com are free no-key fallbacks for when it rate-limits us
# (it does, from datacenter IPs — this is exactly why the fallbacks exist).
IP_API_URLS = [
    "https://ipapi.co/json/",      # Tier 2 primary (roadmap)
    "https://ipwho.is/",           # fallback 1
    "http://ip-api.com/json/",     # fallback 2 (free tier is http-only)
]

# Nominatim requires a real User-Agent identifying the app (their usage
# policy bans generic/browser-like agents). We never send an API key.
_HEADERS = {
    "User-Agent": "aqi-predictor/1.0 (10Pearls internship project; "
                  "https://github.com/AyyanStorm/aqi-predictor)",
}


# Compact labels for countries whose official geocoding name is long.
# Used in the dashboard heading ("AQI Predictor — UK" instead of
# "— United Kingdom"). Unmapped countries keep their full name.
COUNTRY_SHORT = {
    "United Arab Emirates": "UAE",
    "United Kingdom": "UK",
    "United States": "USA",
    "United States of America": "USA",
}


def short_country(country):
    """Short display label for a country name (None stays None)."""
    if not country:
        return None
    return COUNTRY_SHORT.get(country, country)


def geocode(query, count=5):
    """
    Search Open-Meteo's geocoding API for a place name.

    Parameters
    ----------
    query : str
        Free-text place name, e.g. "Sialkot", "Dubai", "London".
    count : int
        Max results to return.

    Returns
    -------
    list of dict
        Each result carries name, latitude, longitude, country,
        admin1 (state/province), country_code, ... as returned by the
        API. Empty list when nothing matches.
    """
    params = {"name": query, "count": count, "language": "en", "format": "json"}
    resp = _geo_session.get(GEOCODING_URL, params=params, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    logger.info(f"geocode('{query}') -> {len(results)} matches")
    return results


def reverse_geocode(lat, lon):
    """
    Reverse-geocode coordinates to a short display name.

    Uses Nominatim (OpenStreetMap) — free, no key. Returns something
    like "Karachi, Sindh, Pakistan".

    Returns None on failure (offline, blocked, no address found) so
    callers can fall back to showing the raw coordinates.
    """
    params = {
        "lat": lat, "lon": lon,
        "format": "jsonv2", "accept-language": "en",
    }
    resp = _geo_session.get(REVERSE_URL, params=params, headers=_HEADERS, timeout=10)
    if resp.status_code != 200:
        logger.warning(f"reverse_geocode({lat}, {lon}) -> HTTP {resp.status_code}")
        return None
    addr = resp.json().get("address", {})
    parts = [
        addr.get("city") or addr.get("town") or addr.get("village"),
        addr.get("state") or addr.get("region"),
        addr.get("country"),
    ]
    parts = [p for p in parts if p]
    name = ", ".join(parts) if parts else None
    logger.info(f"reverse_geocode({lat}, {lon}) -> {name}")
    return name


def locate_by_ip():
    """
    IP-based location, trying each provider in order.

    Returns
    -------
    dict | None
        {"city", "latitude", "longitude", "country_name"} from the first
        provider that answers, or None if all fail.
    """
    for url in IP_API_URLS:
        try:
            resp = _geo_session.get(url, timeout=10)
            data = resp.json()

            if "ipapi.co" in url:
                if data.get("error") or "latitude" not in data:
                    logger.warning(f"ipapi.co refused: {data.get('reason')}")
                    continue
                return {
                    "city": data.get("city"),
                    "latitude": data["latitude"],
                    "longitude": data["longitude"],
                    "country_name": data.get("country_name"),
                }

            if "ipwho.is" in url:
                if not data.get("success"):
                    logger.warning("ipwho.is refused")
                    continue
                return {
                    "city": data.get("city"),
                    "latitude": data["latitude"],
                    "longitude": data["longitude"],
                    "country_name": data.get("country"),
                }

            # ip-api.com
            if data.get("status") != "success":
                logger.warning("ip-api.com refused")
                continue
            return {
                "city": data.get("city"),
                "latitude": data["lat"],
                "longitude": data["lon"],
                "country_name": data.get("country"),
            }

        except Exception as e:  # network error, bad JSON, timeout
            logger.warning(f"IP lookup failed via {url}: {e}")
            continue

    logger.error("All IP geolocation providers failed")
    return None
