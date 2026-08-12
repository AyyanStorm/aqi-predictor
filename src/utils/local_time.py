"""
local_time.py — timezone-aware local time for the dashboard.

Pure Python (no Streamlit import) so it can be unit-tested headlessly
and reused by the FastAPI endpoint later. Everything derives from an
IANA timezone name resolved per-city by geo.resolve_timezone() —
nothing here is hardcoded to any city or country.

Horizon semantics (deliberate): +24h/+48h/+72h are ABSOLUTE elapsed
hours from the city's current local time — i.e. now + exactly
24/48/72 real hours, then converted back to the city's zone. That is
the literal reading of "the local date/time when 24 hours from now are
completed". Around DST transitions (e.g. London in March) the wall
clock shifts by an hour even though the elapsed time is exact; zoneinfo
handles that arithmetic correctly.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Display order of the timeline periods: current + the three horizons.
# Shared with forecast_cards.py so the cards and the times can never
# disagree about which horizon is which.
PERIODS = [("Current", 0), ("+24h", 24), ("+48h", 48), ("+72h", 72)]


def city_now(tz_name):
    """
    Current local datetime for an IANA timezone name.

    Parameters
    ----------
    tz_name : str | None
        IANA timezone, e.g. "Asia/Dubai".

    Returns
    -------
    datetime | None
        Timezone-aware `now` in that zone, or None when the tz is
        missing/unrecognised (callers fall back to hiding the times).
    """
    if not tz_name:
        return None
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception as e:  # bad tz name, missing tzdata, etc.
        logger.warning(f"city_now: bad timezone '{tz_name}': {e}")
        return None


def horizon_times(tz_name):
    """
    The four timeline timestamps (current + 24/48/72h) in one zone.

    Returns
    -------
    list[(label, datetime)] | None
        [(label, aware_dt), ...] in display order, or None when the
        timezone can't be resolved. The datetimes are ABSOLUTE elapsed
        hours from now (DST-correct via zoneinfo).
    """
    now = city_now(tz_name)
    if now is None:
        return None
    return [(label, now + timedelta(hours=h)) for label, h in PERIODS]


def format_local_dt(ts):
    """
    Compact human date+time: "Aug 12, 2026 — 10:30 AM".

    12-hour clock (matching the existing dashboard copy) with a
    zero-padded-free hour: 09:30 shows as "9:30 AM".
    """
    if ts is None:
        return None
    date_part = ts.strftime("%b %-d, %Y")
    time_part = ts.strftime("%I:%M %p").lstrip("0")
    return f"{date_part} — {time_part}"


def tz_display_name(tz_name, ts=None):
    """
    Short human label for a timezone: "Asia/Dubai · UTC+4".

    The offset is computed from the actual zone at that moment (zoneinfo
    knows about DST), never hardcoded. Falls back to the bare name if
    the zone is invalid.
    """
    if not tz_name:
        return None
    ts = ts or city_now(tz_name)
    if ts is None:
        return tz_name
    off = ts.utcoffset()
    total_min = int(off.total_seconds()) // 60
    sign = "+" if total_min >= 0 else "-"
    total_min = abs(total_min)
    h, m = divmod(total_min, 60)
    offset = f"UTC{sign}{h}" + (f":{m:02d}" if m else "")
    return f"{tz_name} · {offset}"
