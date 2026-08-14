"""
location_picker.py — Day 18: three-tier geolocation widget for the sidebar.

The roadmap's location detection, in one component:

  Tier 1  Browser geolocation   — streamlit-js-eval calls the JS
                                  Geolocation API. Precise, but requires
                                  user permission and HTTPS.
  Tier 2  IP-based              — ipapi.co (fallback: ipwho.is, ip-api.com),
                                  resolved with the USER's IP (from request
                                  headers or a browser-side fetch) — never the
                                  server's datacenter IP (that was the bug where
                                  every user got "Columbus, Ohio": Render's
                                  US-East DC).
  Tier 3  Manual search         — text box → Open-Meteo Geocoding API.
                                  Always works; this is what a reviewer
                                  will actually use.

Everything resolves to a location dict that lives in st.session_state:

    {"name": "Karachi", "lat": 24.8608, "lon": 67.0104,
     "source": "browser", "country": "Pakistan"}

    source ∈ {"browser", "ip", "search", "quick-pick"} — shown in the UI
    so it's obvious WHICH tier won, and lets us debug silently.
    country is the display country of the resolved location (e.g.
    "Pakistan", "United Arab Emirates") — the dashboard heading uses it
    so the title stays in sync with the selected city. It may be None
    when a source can't determine it (rare coordinate fallbacks).

The 10 training cities stay available as a quick-pick dropdown (the
Day 17 default), so the widget never takes a capability away.
"""

import streamlit as st
from streamlit_js_eval import get_geolocation, streamlit_js_eval

from src.config import CITIES
from src.utils.geo import geocode, locate_by_ip, resolve_timezone, reverse_geocode
from src.utils.logger import get_logger

logger = get_logger(__name__)

LOCATION_KEY = "location"

# Client-side IP lookup, executed in the USER's browser. A server-side
# lookup (locate_by_ip without an IP) resolves the RENDER SERVER's IP —
# a US datacenter (Columbus, Ohio) — which is why every user saw the
# same wrong location. Running the fetch in the browser resolves the
# user's real IP. The component awaits promises, so an async IIFE works.
_IP_BROWSER_JS = r"""
(async () => {
  const providers = ['https://ipapi.co/json/', 'https://ipwho.is/'];
  for (const url of providers) {
    try {
      const r = await fetch(url);
      const d = await r.json();
      if (d && d.latitude !== undefined && d.longitude !== undefined) {
        return {
          city: d.city || null,
          latitude: d.latitude,
          longitude: d.longitude,
          country_name: d.country_name || d.country || null,
        };
      }
    } catch (e) { /* try next provider */ }
  }
  return null;
})()
"""


def _label(result):
    """One-line label for a geocoding result: 'Name, Region, Country'."""
    parts = [result.get("name"), result.get("admin1"), result.get("country")]
    return ", ".join(p for p in parts if p)


def _default_location():
    return {
        "name": "Karachi",
        "lat": CITIES["Karachi"]["lat"],
        "lon": CITIES["Karachi"]["lon"],
        "source": "quick-pick",
        "country": "Pakistan",
        # IANA timezone, resolved dynamically (never hardcoded) — the
        # quick-pick cities never hit geocoding, so we resolve by
        # lat/lon via Open-Meteo (timezone=auto), cached 1h.
        "timezone": resolve_timezone(
            CITIES["Karachi"]["lat"], CITIES["Karachi"]["lon"], name="Karachi"
        ),
    }


def _client_ip_from_headers():
    """The user's real IP from request headers (Render sets
    X-Forwarded-For on the proxied request). None when unavailable."""
    try:
        headers = st.context.headers
        fwd = headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
        real = headers.get("X-Real-IP")
        if real:
            return real.strip()
    except Exception as e:
        logger.warning(f"Could not read client IP from headers: {e}")
    return None


def _locate_by_ip_browser():
    """IP lookup executed in the user's browser (async component).

    The first call mounts the component and returns None; the value is
    delivered on a later rerun, so callers retry on the next run."""
    try:
        return streamlit_js_eval(js_expressions=_IP_BROWSER_JS, key="ip_browser")
    except Exception as e:
        logger.warning(f"Browser IP lookup failed: {e}")
        return None


def _apply_quick_pick():
    """on_change callback: quick-pick dropdown changed."""
    city = st.session_state["geo_quick"]
    lat, lon = CITIES[city]["lat"], CITIES[city]["lon"]
    st.session_state[LOCATION_KEY] = {
        "name": city,
        "lat": lat,
        "lon": lon,
        "source": "quick-pick",
        "country": "Pakistan",  # the 10 training cities are all Pakistani
        "timezone": resolve_timezone(lat, lon, name=city),
    }


def _apply_search_match():
    """on_change callback: user picked a geocoding search match."""
    results = st.session_state.get("geo_results", [])
    choice = st.session_state["geo_match"]
    labels = [_label(r) for r in results]
    r = results[labels.index(choice)]
    st.session_state[LOCATION_KEY] = {
        "name": _label(r),
        "lat": r["latitude"],
        "lon": r["longitude"],
        "source": "search",
        "country": r.get("country"),  # Open-Meteo geocoding returns it
        # Open-Meteo geocoding already provides the IANA timezone for
        # the match — take it straight from the result (no extra call).
        "timezone": r.get("timezone"),
    }
    logger.info(f"Location set by search: {_label(r)}")


def location_picker():
    """
    Render the three-tier location widget; return the active location.

    Returns
    -------
    dict
        {"name", "lat", "lon", "source"} — persisted across reruns in
        st.session_state["location"].
    """
    st.session_state.setdefault(LOCATION_KEY, _default_location())
    loc = st.session_state[LOCATION_KEY]

    st.subheader("📍 Location")

    # ---- Tier 1 (+ Tier 2 fallback): automatic detection ----
    if st.button("🎯 Use my location", use_container_width=True):
        st.session_state["loc_detect"] = True
        get_geolocation()          # mount GPS component (permission prompt)
        st.rerun()

    if st.session_state.get("loc_detect"):
        attempts = st.session_state.get("loc_attempts", 0)
        with st.spinner("Detecting location…"):
            # Tier 1: browser GPS — the component caches its async result,
            # so once the user allows permission this returns coords.
            geo = get_geolocation()
            if geo and geo.get("coords"):
                lat = geo["coords"]["latitude"]
                lon = geo["coords"]["longitude"]
                name = reverse_geocode(lat, lon) or f"{lat:.2f}, {lon:.2f}"
                st.session_state[LOCATION_KEY] = {
                    "name": name, "lat": lat, "lon": lon, "source": "browser",
                    # reverse_geocode returns "City, Region, Country" — the
                    # country is the last comma-separated part.
                    "country": _country_from_name(name),
                    # Browser GPS gives coordinates only — resolve the
                    # IANA timezone from lat/lon (timezone=auto, cached).
                    "timezone": resolve_timezone(lat, lon),
                }
                logger.info(f"Location set by browser geolocation: {name}")
                st.session_state.pop("loc_detect", None)
            else:
                # Tier 2: IP lookup using the USER's IP (from request
                # headers), never the server's datacenter IP.
                ip = locate_by_ip(client_ip=_client_ip_from_headers())
                if not ip or not ip.get("latitude"):
                    ip = _locate_by_ip_browser()   # async; retried below
                if ip and ip.get("latitude"):
                    lat, lon = ip["latitude"], ip["longitude"]
                    name = (reverse_geocode(lat, lon)
                            or ip.get("city")
                            or f"{lat:.2f}, {lon:.2f}")
                    st.session_state[LOCATION_KEY] = {
                        "name": name, "lat": lat, "lon": lon, "source": "ip",
                        "country": ip.get("country_name"),
                        "timezone": resolve_timezone(lat, lon),
                    }
                    logger.info(f"Location set by IP: {name}")
                    st.session_state.pop("loc_detect", None)
                elif attempts >= 2:
                    st.session_state.pop("loc_detect", None)
                    st.warning(
                        "Couldn't detect your location automatically — "
                        "use the search box below."
                    )
                else:
                    # Browser-side IP fetch still resolving — try again.
                    st.session_state["loc_attempts"] = attempts + 1
                    st.rerun()
        st.session_state.pop("loc_attempts", None)
        st.rerun()

    st.caption(
        "Browser GPS needs permission + HTTPS. If it fails we fall back "
        "to your IP (city-level), then to manual search."
    )

    # ---- Tier 3: manual search (always available) ----
    query = st.text_input(
        "Search any city",
        key="geo_query",
        placeholder="e.g. Sialkot, Dubai, London",
        help="Open-Meteo Geocoding API — free, no key, worldwide.",
    )
    if query.strip():
        results = geocode(query.strip())
        st.session_state["geo_results"] = results
        if results:
            labels = [_label(r) for r in results]
            # index=None + placeholder on purpose: with a pre-selected
            # first match (index=0), Streamlit's on_change never fires —
            # the widget's value doesn't CHANGE, so the callback is
            # skipped and the picked city never gets applied. Forcing an
            # explicit pick guarantees a change event -> _apply_search_match.
            st.selectbox(
                "Matches",
                labels,
                index=None,
                placeholder="Select a match…",
                key="geo_match",
                on_change=_apply_search_match,
            )
        else:
            st.caption("No matches — try another spelling.")

    # ---- Quick pick: the 10 training cities (Day 17 default) ----
    city_names = list(CITIES)
    default_idx = city_names.index(loc["name"]) if loc["name"] in city_names else 0
    st.selectbox(
        "Or pick a Pakistan city",
        city_names,
        index=default_idx,
        key="geo_quick",
        on_change=_apply_quick_pick,
    )

    st.caption(f"Active: **{loc['name']}** · source: `{loc['source']}`")
    return st.session_state[LOCATION_KEY]


def _country_from_name(name):
    """Last comma-separated part of a reverse-geocoded display name.

    reverse_geocode() returns "City, Region, Country" — the country is
    the final part. Coordinate fallbacks like "24.86, 67.01" have no
    country; return None so callers can omit it gracefully.
    """
    if not name or "," not in name:
        return None
    parts = [p.strip() for p in name.split(",") if p.strip()]
    last = parts[-1] if parts else None
    # Coordinates ("24.86") aren't a country; anything with a digit is.
    return last if last and not any(ch.isdigit() for ch in last) else None
