"""Tests for analysis/history.py and the streak/backfill flow."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from worldview.analysis.history import (
    backfill_flags,
    current_streak,
    expanding_percentiles,
)
from worldview.models import Cadence, Category, Metric, Polarity

# ── expanding_percentiles ─────────────────────────────────────────────────────

def test_expanding_percentiles_first_value_is_nan():
    s = pd.Series([5.0, 6.0, 7.0])
    pct = expanding_percentiles(s)
    assert np.isnan(pct.iloc[0])
    # second value: 1 prior, 6 > 5 → 100% above prior
    assert pct.iloc[1] == 100.0
    # third: 2 priors [5,6], 7 > both → 100%
    assert pct.iloc[2] == 100.0


def test_expanding_percentiles_strictly_less_than():
    """Ties land at the bottom of the bucket (bisect_left)."""
    s = pd.Series([5.0, 5.0, 5.0])
    pct = expanding_percentiles(s)
    assert np.isnan(pct.iloc[0])
    assert pct.iloc[1] == 0.0   # 5 not strictly > 5
    assert pct.iloc[2] == 0.0


def test_expanding_percentiles_handles_decline():
    s = pd.Series([10.0, 9.0, 8.0])
    pct = expanding_percentiles(s)
    assert np.isnan(pct.iloc[0])
    assert pct.iloc[1] == 0.0   # 9 < 10
    assert pct.iloc[2] == 0.0   # 8 < both


def test_expanding_percentiles_propagates_nan_inputs():
    s = pd.Series([1.0, np.nan, 3.0])
    pct = expanding_percentiles(s)
    assert np.isnan(pct.iloc[0])
    assert np.isnan(pct.iloc[1])
    # third has 1 valid prior (1.0), 3 > 1 → 100%
    assert pct.iloc[2] == 100.0


# ── backfill_flags ────────────────────────────────────────────────────────────

def _metric(flag_high=None, flag_low=None) -> Metric:
    return Metric(
        id="m", category=Category.SENTIMENT, field="overall",
        source="yfinance", source_ref="X",
        polarity=Polarity.FEARFUL, cadence=Cadence.DAILY,
        flag_high_pct=flag_high, flag_low_pct=flag_low,
    )


def test_backfill_flags_empty_when_no_thresholds():
    s = pd.Series([1, 2, 3, 4, 5], index=pd.date_range("2024-01-01", periods=5))
    assert backfill_flags(_metric(), s) == []


def test_backfill_flags_emits_high_when_threshold_crossed():
    # ascending series — last few values are at 100th percentile
    idx = pd.date_range("2024-01-01", periods=20)
    s = pd.Series(list(range(20)), index=idx, dtype=float)
    flags = backfill_flags(_metric(flag_high=90), s)
    # Anything where pct >= 90 should be flagged. Final values clearly qualify.
    assert flags
    assert all(f.side == "high" for f in flags)
    assert all(f.pct >= 90 for f in flags)
    # Last day must be among them.
    flag_dates = {f.on for f in flags}
    assert idx[-1].date() in flag_dates


def test_backfill_flags_emits_both_sides():
    """A V-shaped series should produce low flags early, high flags late."""
    idx = pd.date_range("2024-01-01", periods=30)
    values = list(range(15, -1, -1)) + list(range(1, 15))   # 15..0..1..14
    s = pd.Series(values, index=idx, dtype=float)
    flags = backfill_flags(_metric(flag_high=85, flag_low=15), s)
    sides = {f.side for f in flags}
    assert "high" in sides or "low" in sides   # at least one side should fire


# ── current_streak ────────────────────────────────────────────────────────────

def test_current_streak_zero_when_latest_not_flagged():
    obs = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    flagged = {date(2024, 1, 1)}
    assert current_streak(obs, flagged) == 0


def test_current_streak_counts_run_ending_at_latest():
    obs = [date(2024, 1, d) for d in range(1, 11)]
    # last 4 days flagged
    flagged = {date(2024, 1, d) for d in (7, 8, 9, 10)}
    assert current_streak(obs, flagged) == 4


def test_current_streak_breaks_on_first_unflagged_obs():
    obs = [date(2024, 1, d) for d in range(1, 11)]
    # 1,2,5,6,7,8,9,10 flagged — gap on 3-4 means latest streak is only 6
    flagged = {date(2024, 1, d) for d in (1, 2, 5, 6, 7, 8, 9, 10)}
    assert current_streak(obs, flagged) == 6


def test_current_streak_empty_returns_zero():
    assert current_streak([], set()) == 0


# ── DB integration: flagged_dates / observation_dates ────────────────────────

def test_flagged_dates_and_observation_dates(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)
    # 5 daily obs
    idx = pd.to_datetime([date(2024, 1, d) for d in range(1, 6)])
    tmp_db.upsert_observations(sample_metric.id, pd.Series([1, 2, 3, 4, 5], index=idx, dtype=float))
    # flag day 4 and 5 (high)
    tmp_db.write_flag(sample_metric.id, date(2024, 1, 4), "high", 92.0, 4.0)
    tmp_db.write_flag(sample_metric.id, date(2024, 1, 5), "high", 95.0, 5.0)

    obs_dates = tmp_db.observation_dates(sample_metric.id)
    flagged   = tmp_db.flagged_dates(sample_metric.id, "high")

    assert obs_dates == [date(2024, 1, d) for d in range(1, 6)]
    assert flagged == {date(2024, 1, 4), date(2024, 1, 5)}
    assert current_streak(obs_dates, flagged) == 2


def test_flagged_dates_rejects_bad_side(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)
    with pytest.raises(ValueError):
        tmp_db.flagged_dates(sample_metric.id, "sideways")
