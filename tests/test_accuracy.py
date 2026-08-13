"""Unit tests for src/tracking/accuracy.py — the accuracy formulas.

The headline number is the MAPE-based score the user sees in the
dashboard ("Your Average Accuracy"). The formulas here must match the
grill-me decisions: max(0, 100 - |p-a|/max(a,1)*100), a ±15 AQI
tolerance hit-rate, and EPA category-match as supporting stats.
"""

import pandas as pd
import pytest

from src.tracking.accuracy import (
    actual_at,
    evaluate_horizon,
    evaluate_record,
    summarize,
)


def test_perfect_prediction_scores_100():
    r = evaluate_horizon(pred=50, actual=50)
    assert r["accuracy_mape"] == 100.0
    assert r["within_tolerance"] is True
    assert r["category_match"] is True


def test_small_error_scores_high():
    # |75-60|/60 = 25% error -> score 75; within ±15 -> hit.
    r = evaluate_horizon(pred=75, actual=60)
    assert r["accuracy_mape"] == pytest.approx(75.0)
    assert r["within_tolerance"] is True
    # 75 and 60 are BOTH Moderate -> category matches.
    assert r["category_match"] is True


def test_within_tolerance_counts_as_hit():
    r = evaluate_horizon(pred=70, actual=60)
    assert r["within_tolerance"] is True
    # accuracy is rounded to 2dp by the module; compare with abs tol.
    assert r["accuracy_mape"] == pytest.approx(
        round(100 - (10 / 60) * 100, 2), abs=0.01
    )


def test_beyond_tolerance_is_miss():
    r = evaluate_horizon(pred=90, actual=60)
    assert r["within_tolerance"] is False
    assert r["accuracy_mape"] == pytest.approx(100 - (30 / 60) * 100)


def test_category_mismatch_detected():
    # 110 = Unhealthy for Sensitive Groups vs 60 = Moderate.
    r = evaluate_horizon(pred=110, actual=60)
    assert r["category_match"] is False
    assert r["within_tolerance"] is False


def test_score_floor_is_zero():
    # 200% error would be -100; must clamp to 0.
    r = evaluate_horizon(pred=90, actual=30)
    assert r["accuracy_mape"] == 0.0
    assert r["within_tolerance"] is False


def test_division_by_zero_guard():
    # actual=0 (impossible in practice) must not crash: max(a,1) guard.
    r = evaluate_horizon(pred=10, actual=0)
    assert r["accuracy_mape"] == 0.0
    # |10 - 0| <= 15 -> within tolerance (0 AQI is a valid edge value).
    assert r["within_tolerance"] is True


def test_missing_actual_returns_none():
    assert evaluate_horizon(pred=50, actual=None) is None
    assert evaluate_horizon(pred=50, actual=float("nan")) is None


def test_actual_at_finds_exact_hour():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=48, freq="h", tz="UTC"),
            "us_aqi": range(48),
        }
    )
    ts = df["date"].iloc[10]
    assert actual_at(df, ts) == 10.0


def test_actual_at_returns_none_when_missing():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC"),
            "us_aqi": range(10),
        }
    )
    assert actual_at(df, pd.Timestamp("2026-01-05", tz="UTC")) is None
    assert actual_at(pd.DataFrame(), pd.Timestamp("2026-01-01", tz="UTC")) is None


def test_evaluate_record_and_summarize():
    base = pd.Timestamp("2026-01-01", tz="UTC")
    record = {
        "user_id": "u1",
        "city": "Karachi",
        "base_ts": base,
        "pred_24": 50,
        "pred_48": 60,
        "pred_72": 70,
    }
    # Observed actuals: exact matches at +24h (01-02 00:00), +48h
    # (01-03 00:00), +72h (01-04 00:00); garbage elsewhere.
    idx = pd.date_range("2026-01-02", periods=73, freq="h", tz="UTC")
    vals = [0] * 73
    vals[0] = 50   # +24h
    vals[24] = 60  # +48h
    vals[48] = 70  # +72h
    actuals = pd.DataFrame({"date": idx, "us_aqi": vals})

    results, ts = evaluate_record(record, actuals)
    assert len(results) == 3  # one row per horizon
    assert {r["horizon"] for r in results} == {24, 48, 72}
    assert ts == {24: idx[0], 48: idx[24], 72: idx[48]}

    summary = summarize(results)
    assert summary["n_horizons"] == 3
    assert summary["avg_accuracy"] == 100.0  # perfect predictions
    assert summary["hit_rate"] == 100.0
    assert summary["category_rate"] == 100.0
    assert summary["n_correct"] == 3


def test_summarize_none_for_empty():
    assert summarize([]) is None


def test_summarize_averages_across_rows():
    rows = [
        {"accuracy_mape": 100.0, "within_tolerance": True, "category_match": True},
        {"accuracy_mape": 50.0, "within_tolerance": False, "category_match": False},
    ]
    summary = summarize(rows)
    assert summary["n_horizons"] == 2
    assert summary["avg_accuracy"] == 75.0
    assert summary["hit_rate"] == 50.0
    assert summary["category_rate"] == 50.0
    assert summary["n_correct"] == 1
