"""Unit tests for src/utils/local_time.py — tz-aware display times.

Pure Python by design, so it runs headless. The critical regression
here is the Windows crash: format_local_dt() must never use the GNU
'%-d' strftime extension (Windows raises ValueError on it).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.utils.local_time import (
    city_now,
    format_local_dt,
    horizon_times,
    tz_display_name,
)


def test_city_now_returns_aware_datetime():
    now = city_now("Asia/Karachi")
    assert now is not None
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 5 * 3600  # PKT, UTC+5


def test_city_now_none_for_missing_or_bad_tz():
    assert city_now(None) is None
    assert city_now("Not/AZone") is None


def test_horizon_times_are_absolute_elapsed_hours():
    times = horizon_times("Asia/Karachi")
    assert times is not None
    assert [label for label, _ in times] == ["Current", "+24h", "+48h", "+72h"]
    _, now = times[0]
    for (label, ts) in times[1:]:
        delta = ts - now
        assert delta == timedelta(hours=int(label.strip("+h")))
        assert ts.tzinfo is not None


def test_horizon_times_none_for_bad_tz():
    assert horizon_times(None) is None


def test_format_local_dt_round_trip():
    ts = datetime(2026, 8, 12, 10, 30, tzinfo=ZoneInfo("Asia/Karachi"))
    assert format_local_dt(ts) == "Aug 12, 2026 — 10:30 AM"


def test_format_local_dt_no_leading_zero_in_hour():
    # 09:05 must render as "9:05 AM" — and must NOT crash on Windows
    # (the old '%-d' bug would raise ValueError there).
    ts = datetime(2026, 8, 12, 9, 5, tzinfo=ZoneInfo("Asia/Karachi"))
    assert format_local_dt(ts) == "Aug 12, 2026 — 9:05 AM"


def test_format_local_dt_none():
    assert format_local_dt(None) is None


def test_format_local_dt_midnight_and_noon():
    midnight = datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("UTC"))
    noon = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert format_local_dt(midnight).endswith("12:00 AM")
    assert format_local_dt(noon).endswith("12:00 PM")


def test_tz_display_name_contains_offset():
    name = tz_display_name("Asia/Karachi")
    assert name == "Asia/Karachi · UTC+5"


def test_tz_display_name_falls_back_to_bare_name():
    assert tz_display_name(None) is None
    assert tz_display_name("Not/AZone") == "Not/AZone"
