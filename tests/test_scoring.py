"""Scoring + composite logic. Pure unit tests, no I/O."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from worldview.analysis.composite import _quadrant, field_scores, worldview_score
from worldview.analysis.flags import compute_flags
from worldview.analysis.scoring import label_from_pct, percentile_rank, score_metric
from worldview.models import (
    Cadence,
    Category,
    FieldDef,
    Metric,
    MetricScore,
    Polarity,
)

# ── percentile_rank ───────────────────────────────────────────────────────────

def test_percentile_rank_basic():
    s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    assert percentile_rank(s, 5.5) == 50.0
    assert percentile_rank(s, 0) == 0.0
    assert percentile_rank(s, 11) == 100.0


def test_percentile_rank_handles_empty_history():
    assert np.isnan(percentile_rank(pd.Series([], dtype=float), 1.0))


def test_percentile_rank_drops_nans():
    s = pd.Series([1.0, np.nan, 2.0, np.nan, 3.0])
    assert percentile_rank(s, 2.5) == pytest.approx(2 / 3 * 100)


# ── label_from_pct ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "pct,expected",
    [
        (0.0,  "Extreme Low"),
        (5.0,  "Extreme Low"),
        (10.0, "Low"),
        (24.9, "Low"),
        (25.0, "Normal"),
        (74.9, "Normal"),
        (75.0, "High"),
        (89.9, "High"),
        (90.0, "Extreme High"),
        (100.0, "Extreme High"),
    ],
)
def test_label_from_pct(pct, expected):
    assert label_from_pct(pct) == expected


def test_label_from_pct_unknown_for_nan():
    assert label_from_pct(float("nan")) == "Unknown"


# ── score_metric ──────────────────────────────────────────────────────────────

def _metric(**overrides) -> Metric:
    base = dict(
        id="m1",
        category=Category.SENTIMENT,
        field="overall",
        source="yfinance",
        source_ref="^M1",
        polarity=Polarity.FEARFUL,
        cadence=Cadence.DAILY,
        weight=1.0,
        flag_high_pct=90.0,
        flag_low_pct=10.0,
    )
    base.update(overrides)
    return Metric(**base)


def test_score_metric_returns_none_for_empty():
    assert score_metric(_metric(), pd.Series([], dtype=float)) is None


def test_score_metric_picks_latest_value_against_prior_history():
    # 99 values of 0..98; last value of 99 → 100th percentile against history
    idx = pd.to_datetime(pd.date_range("2024-01-01", periods=100, freq="D"))
    series = pd.Series(list(range(100)), index=idx, dtype=float)
    score = score_metric(_metric(), series)
    assert score is not None
    assert score.value == 99.0
    assert score.percentile == 100.0
    assert score.label == "Extreme High"
    assert score.flagged_high
    assert not score.flagged_low


def test_score_metric_flags_low_extreme():
    # ramp 99..0 — last value = 0 = below all history
    idx = pd.to_datetime(pd.date_range("2024-01-01", periods=100, freq="D"))
    series = pd.Series(list(range(99, -1, -1)), index=idx, dtype=float)
    score = score_metric(_metric(), series)
    assert score is not None
    assert score.percentile == 0.0
    assert score.flagged_low
    assert not score.flagged_high


# ── compute_flags ─────────────────────────────────────────────────────────────

def test_compute_flags_extracts_only_flagged():
    scores = [
        MetricScore("a", date(2024, 1, 1), 1.0, 95.0, "Extreme High",
                    flagged_high=True, flagged_low=False),
        MetricScore("b", date(2024, 1, 1), 2.0, 50.0, "Normal"),
        MetricScore("c", date(2024, 1, 1), 3.0, 5.0,  "Extreme Low",
                    flagged_high=False, flagged_low=True),
    ]
    flags = compute_flags(scores)
    assert {(f.metric_id, f.side) for f in flags} == {("a", "high"), ("c", "low")}


# ── quadrant ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "val,sent,expected",
    [
        (10, 10, "BUY"),
        (10, 90, "CAUTION"),
        (90, 10, "TRAP"),
        (90, 90, "BUBBLE"),
        (50, 50, "BUY"),       # boundary — both <= 50
        (None, 50, "N/A"),
        (50, None, "N/A"),
    ],
)
def test_quadrant(val, sent, expected):
    assert _quadrant(val, sent) == expected


# ── field_scores ──────────────────────────────────────────────────────────────

def test_field_scores_flips_polarity_correctly():
    """A `fearful` metric at pct=80 should yield sentiment_score = 20 (un-fearful)."""
    metric = _metric(id="vix", polarity=Polarity.FEARFUL)
    scores = {
        "vix": MetricScore(
            "vix", date(2024, 1, 1), 30.0, 80.0, "High",
        )
    }
    fields = {
        "overall": FieldDef("overall", "Overall", [], ["vix"], []),
    }
    out = field_scores(fields, {"vix": metric}, scores)
    assert out["overall"].sentiment == pytest.approx(20.0)
    assert out["overall"].valuation is None
    assert out["overall"].quadrant == "N/A"


def test_field_scores_does_not_flip_when_polarity_matches_block():
    """An `expensive` metric at pct=80 contributes 80 to valuation."""
    metric = _metric(id="cape", polarity=Polarity.EXPENSIVE)
    scores = {"cape": MetricScore("cape", date(2024, 1, 1), 35.0, 80.0, "High")}
    fields = {"overall": FieldDef("overall", "Overall", ["cape"], [], [])}
    out = field_scores(fields, {"cape": metric}, scores)
    assert out["overall"].valuation == pytest.approx(80.0)


def test_field_scores_weighted_blend():
    m1 = _metric(id="m1", polarity=Polarity.EXPENSIVE, weight=1.0)
    m2 = _metric(id="m2", polarity=Polarity.EXPENSIVE, weight=3.0)
    scores = {
        "m1": MetricScore("m1", date(2024, 1, 1), 1.0, 20.0, "Low"),
        "m2": MetricScore("m2", date(2024, 1, 1), 1.0, 80.0, "High"),
    }
    fields = {"overall": FieldDef("overall", "Overall", ["m1", "m2"], [], [])}
    out = field_scores(fields, {"m1": m1, "m2": m2}, scores)
    # weighted: (1*20 + 3*80) / 4 = 65
    assert out["overall"].valuation == pytest.approx(65.0)


def test_field_scores_skips_missing_metrics():
    fields = {"overall": FieldDef("overall", "Overall", ["does_not_exist"], [], [])}
    out = field_scores(fields, {}, {})
    assert out["overall"].valuation is None


# ── worldview_score ───────────────────────────────────────────────────────────

def test_worldview_score_max_when_cheap_fearful_healthy():
    """Default 'penalize_greed' mode: cheap + fearful + healthy = best score."""
    from worldview.analysis.composite import FieldScore

    fs = FieldScore("overall", "Overall", valuation=0.0, sentiment=0.0,
                    macro_risk=0.0, quadrant="BUY", contributing={})
    score = worldview_score(fs, {"valuation": 0.4, "sentiment": 0.3, "macro_risk": 0.3})
    # all three terms contribute their max of 100: 100*(0.4+0.3+0.3) = 100
    assert score == pytest.approx(100.0)


def test_worldview_score_default_rewards_fear_monotonically():
    """Buffett-aligned default: fear should help the score, greed should hurt."""
    from worldview.analysis.composite import FieldScore

    base_kwargs = dict(field_id="overall", label="Overall",
                       valuation=50.0, macro_risk=50.0, quadrant="BUY", contributing={})
    weights = {"valuation": 0.4, "sentiment": 0.3, "macro_risk": 0.3}

    s_fear    = worldview_score(FieldScore(sentiment=0.0, **base_kwargs),   weights)
    s_neutral = worldview_score(FieldScore(sentiment=50.0, **base_kwargs),  weights)
    s_greed   = worldview_score(FieldScore(sentiment=100.0, **base_kwargs), weights)

    # fear ≥ neutral ≥ greed (monotonic in default mode)
    assert s_fear > s_neutral > s_greed


def test_worldview_score_legacy_mode_still_available():
    """Pass mode='penalize_extremes' to recover the symmetric formulation."""
    from worldview.analysis.composite import FieldScore

    base_kwargs = dict(field_id="overall", label="Overall",
                       valuation=50.0, macro_risk=50.0, quadrant="BUY", contributing={})
    weights = {"valuation": 0.4, "sentiment": 0.3, "macro_risk": 0.3}

    s_greedy = worldview_score(
        FieldScore(sentiment=100.0, **base_kwargs), weights, "penalize_extremes",
    )
    s_panic = worldview_score(
        FieldScore(sentiment=0.0, **base_kwargs), weights, "penalize_extremes",
    )
    s_neutral = worldview_score(
        FieldScore(sentiment=50.0, **base_kwargs), weights, "penalize_extremes",
    )

    assert s_neutral > s_greedy
    assert s_neutral > s_panic
    assert s_greedy == pytest.approx(s_panic)


def test_worldview_score_none_when_block_missing():
    from worldview.analysis.composite import FieldScore
    fs = FieldScore("overall", "Overall", valuation=None, sentiment=50.0,
                    macro_risk=10.0, quadrant="N/A", contributing={})
    assert worldview_score(fs, {"valuation": 0.4, "sentiment": 0.3, "macro_risk": 0.3}) is None
