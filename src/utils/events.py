"""
events.py — pollution event detection on historical AQI (unique feature #2).

The 4-year backfill is a flat table of numbers. This module turns it into
a STORY: for every city it finds the moments that mattered, so the
dashboard (Day 19+) can annotate trend charts with them and the report
can quote real events instead of abstract statistics.

Two detector types, both derived ONLY from the hourly `us_aqi` column
(no extra data, no targets — so it runs straight on a Feature Store
frame or a raw ingestion frame):

    episode  — sustained unhealthy air: the daily mean stays at or above
               the US EPA "Unhealthy" level (150) for N+ consecutive
               days. In Pakistan's smog window (Oct–Feb) these are the
               winter smog episodes that blanket the Punjab belt.
    spike    — a sharp, short peak: hourly AQI crosses "Very Unhealthy"
               (200) AND climbed at least MIN_SPIKE_RISE points within
               the previous 24h — crop-burning and fireworks events.

Output: one tidy DataFrame (city, event_type, start, end, peak_aqi,
duration_h, smog_season) that the dashboard filters by city and the
report aggregates per city.

The US EPA thresholds live in config.py — the same constants the
dashboard's colour bands and health messages will use on Day 19
(single source of truth, roadmap structural rule 1).
"""

import numpy as np
import pandas as pd

from src.config import AQI_UNHEALTHY, AQI_VERY_UNHEALTHY
from src.utils.logger import get_logger

logger = get_logger(__name__)

MIN_EPISODE_DAYS = 2     # at least 2 consecutive days of unhealthy air
MIN_SPIKE_RISE = 100     # AQI points climbed within the spike window
SPIKE_WINDOW_H = 24      # how fast the spike must happen
SMOG_SEASON_MONTHS = {10, 11, 12, 1, 2}  # Oct–Feb: Pakistan's smog window

_EVENT_COLUMNS = [
    "city", "event_type", "start", "end", "peak_aqi", "duration_h", "smog_season",
]


# =========================================================
# 1. EPISODE DETECTION (sustained unhealthy air)
# =========================================================

def detect_episodes(city_series, min_days=MIN_EPISODE_DAYS, threshold=AQI_UNHEALTHY):
    """
    Find runs of consecutive days whose mean AQI >= threshold.

    Parameters
    ----------
    city_series : pd.Series
        Hourly us_aqi for ONE city, DatetimeIndex, ascending.
    min_days : int
        Minimum run length (in days) to count as an episode.
    threshold : float
        Daily-mean AQI level that defines "unhealthy air".

    Returns
    -------
    list[dict] : one dict per episode with start/end (timestamps),
        peak daily mean, duration in days.
    """
    daily = city_series.resample("D").mean().dropna()
    unhealthy = daily >= threshold

    episodes = []
    run_start = None
    for day, is_unhealthy in unhealthy.items():
        if is_unhealthy and run_start is None:
            run_start = day
        elif not is_unhealthy and run_start is not None:
            run_end = day - pd.Timedelta(days=1)
            if (run_end - run_start).days + 1 >= min_days:
                window = daily.loc[run_start:run_end]
                episodes.append({
                    "start": run_start,
                    "end": run_end,
                    "peak_aqi": float(window.max()),
                    "duration_h": int(len(window) * 24),
                })
            run_start = None
    # flush a run that reaches the end of the series
    if run_start is not None:
        window = daily.loc[run_start:]
        if (window.index[-1] - run_start).days + 1 >= min_days:
            episodes.append({
                "start": run_start,
                "end": window.index[-1],
                "peak_aqi": float(window.max()),
                "duration_h": int(len(window) * 24),
            })
    return episodes


# =========================================================
# 2. SPIKE DETECTION (sharp short peaks)
# =========================================================

def detect_spikes(city_series, min_rise=MIN_SPIKE_RISE,
                  threshold=AQI_VERY_UNHEALTHY, window_h=SPIKE_WINDOW_H):
    """
    Find short, sharp peaks: AQI >= threshold AND it rose >= min_rise
    points within the previous `window_h` hours (a 24h window captures
    crop-burning and fireworks events; a slow seasonal climb does NOT
    qualify — it is an episode, not a spike).

    Parameters
    ----------
    city_series : pd.Series
        Hourly us_aqi for ONE city, DatetimeIndex, ascending.
    min_rise : float
        Minimum rise (in AQI points) within the window.
    threshold : float
        Absolute AQI level the peak must reach.
    window_h : int
        Look-back window for the rise.

    Returns
    -------
    list[dict] : one dict per spike event.
    """
    series = city_series.dropna()
    if len(series) < window_h:
        return []

    # rolling min over the window ENDING at each hour (backward-looking —
    # never peeks at the future, consistent with the project's leakage rule)
    rolling_min = series.rolling(window_h, min_periods=1).min()
    spike_mask = (series >= threshold) & (series - rolling_min >= min_rise)

    # cluster consecutive spike hours into single events
    spikes = []
    in_run = False
    for ts, is_spike in spike_mask.items():
        if is_spike and not in_run:
            run_start = ts
            in_run = True
        elif not is_spike and in_run:
            window = series.loc[run_start:ts - pd.Timedelta(hours=1)]
            spikes.append({
                "start": run_start,
                "end": ts - pd.Timedelta(hours=1),
                "peak_aqi": float(window.max()),
                "duration_h": int(len(window)),
            })
            in_run = False
    if in_run:
        window = series.loc[run_start:]
        spikes.append({
            "start": run_start,
            "end": window.index[-1],
            "peak_aqi": float(window.max()),
            "duration_h": int(len(window)),
        })
    return spikes


# =========================================================
# 3. COMBINED PER-CITY DETECTION
# =========================================================

def detect_events(df, cities=None):
    """
    Run both detectors over every city in the frame.

    Parameters
    ----------
    df : pd.DataFrame
        Must have a DatetimeIndex, a 'city' column and a 'us_aqi' column
        (same contract as build_features.py).
    cities : list[str] | None
        Restrict detection to these cities. None = all cities in df.

    Returns
    -------
    pd.DataFrame : one row per event with columns
        city, event_type, start, end, peak_aqi, duration_h, smog_season.
        Sorted by (city, start). Empty DataFrame if nothing is detected.
    """
    required = {"city", "us_aqi"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"df must have columns {required}; missing: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("df.index must be a DatetimeIndex (hourly, ascending)")

    if cities is None:
        cities = df["city"].unique()

    rows = []
    for city in cities:
        series = df.loc[df["city"] == city, "us_aqi"].sort_index()
        for ev in detect_episodes(series):
            rows.append({
                "city": city,
                "event_type": "episode",
                "start": ev["start"],
                "end": ev["end"],
                "peak_aqi": ev["peak_aqi"],
                "duration_h": ev["duration_h"],
                "smog_season": ev["start"].month in SMOG_SEASON_MONTHS,
            })
        for ev in detect_spikes(series):
            rows.append({
                "city": city,
                "event_type": "spike",
                "start": ev["start"],
                "end": ev["end"],
                "peak_aqi": ev["peak_aqi"],
                "duration_h": ev["duration_h"],
                "smog_season": ev["start"].month in SMOG_SEASON_MONTHS,
            })

    events = pd.DataFrame(rows, columns=_EVENT_COLUMNS)
    if not events.empty:
        events = events.sort_values(["city", "start"]).reset_index(drop=True)
    logger.info(f"Detected {len(events)} events across {len(cities)} cities")
    return events


def event_summary(events):
    """
    Per-city roll-up for the report/dashboard: count of episodes and
    spikes, plus the worst peak AQI seen. Takes detect_events() output.
    Sorted by worst_peak_aqi DESCENDING so the most polluted city leads
    (the dashboard's "worst city right now" leaderboard uses the same
    ordering idea on Day 19).
    """
    if events.empty:
        return pd.DataFrame(
            columns=["city", "n_episodes", "n_spikes", "worst_peak_aqi"]
        )
    summary = (
        events.groupby("city")
        .agg(
            n_episodes=("event_type", lambda s: (s == "episode").sum()),
            n_spikes=("event_type", lambda s: (s == "spike").sum()),
            worst_peak_aqi=("peak_aqi", "max"),
        )
        .reset_index()
        .sort_values("worst_peak_aqi", ascending=False)
        .reset_index(drop=True)
    )
    return summary


def worst_city(events):
    """
    Return the city with the single worst peak AQI across all events
    (ties broken by total event count). Returns (city, worst_peak_aqi)
    or (None, None) when there are no events.
    """
    if events.empty:
        return None, None
    summary = event_summary(events)
    top = summary.iloc[0]
    return top["city"], float(top["worst_peak_aqi"])


# =========================================================
# 4. CLI — demo on synthetic data with INJECTED events
# =========================================================

def _demo_data(n_days=400, cities=None):
    """
    Synthetic hourly AQI with two KNOWN injected events per city, so the
    detectors can be eyeballed (and tested) without real data:
        - a 5-day smog episode in JANUARY (daily mean ~180 > 150, so the
          smog_season flag must come out True)
        - a 12-hour spike in late October (peak 260 > 200, rise > 100 in 24h)
    """
    if cities is None:
        cities = ["Karachi", "Lahore"]
    rng = np.random.default_rng(0)
    idx = pd.date_range("2023-01-01", periods=n_days * 24, freq="h")

    frames = []
    for city in cities:
        t = np.arange(len(idx))
        base = 80 + 30 * np.sin(2 * np.pi * t / (24 * 7)) + t / len(t) * 40
        aqi = base + rng.normal(0, 10, len(idx))

        # inject smog episode: days 20-24 = Jan 21-25, inside smog season
        ep_start, ep_days = 20 * 24, 5
        aqi[ep_start:ep_start + ep_days * 24] = 180 + rng.normal(0, 5, ep_days * 24)
        # inject spike: 12 hours on day 300 (Oct 28, crop-burning season)
        sp_start = 300 * 24
        aqi[sp_start:sp_start + 12] = 260 + rng.normal(0, 3, 12)

        frames.append(pd.DataFrame({"city": city, "us_aqi": np.clip(aqi, 10, 400)},
                                   index=idx))
    return pd.concat(frames).sort_index()


def main():
    """Smoke test: run detection on synthetic data with injected events,
    across ALL configured cities, and report the worst city."""
    from src.config import CITIES

    df = _demo_data(cities=list(CITIES.keys()))
    events = detect_events(df)
    print(events.to_string(index=False))
    print("\nPer-city summary (worst peak first):")
    print(event_summary(events).to_string(index=False))
    city, peak = worst_city(events)
    print(f"\nWorst city by peak AQI: {city} ({peak:.1f})")


if __name__ == "__main__":
    main()
