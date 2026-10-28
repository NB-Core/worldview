"""Per-metric scoring: percentile rank against history + label.

These functions are pure — they take a pandas Series and return primitives /
dataclasses. No I/O, no DB access. That makes them trivial to unit test.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..models import Metric, MetricScore

# Boundaries for the 5-bucket label.
_BUCKETS = [
    (10.0, "Extreme Low"),
    (25.0, "Low"),
    (75.0, "Normal"),
    (90.0, "High"),
    (100.01, "Extreme High"),  # 100.01 sentinel so 100.0 still hits "Extreme High"
]


def percentile_rank(history: pd.Series, value: float) -> float:
    """Return the percentile (0..100) of `value` against `history`.

    Uses the "less than" convention so a value at the historical max returns 100.
    Empty / NaN-only histories return NaN.
    """
    if history is None or len(history) == 0:
        return float("nan")
    arr = history.dropna().to_numpy(dtype=float)
    if arr.size == 0:
        return float("nan")
    return float((arr < value).sum() / arr.size * 100.0)


def label_from_pct(pct: float) -> str:
    """Map a 0..100 percentile to a regime label."""
    if pct is None or np.isnan(pct):
        return "Unknown"
    for upper, label in _BUCKETS:
        if pct < upper:
            return label
    return "Extreme High"


def score_metric(
    metric: Metric,
    history: pd.Series,
    asof: date | None = None,
    *,
    evaluation_date: date | None = None,
) -> MetricScore | None:
    """Score the most recent value of `history` against the rest of it.

    Args:
        metric: registry entry; used for id, polarity, and flag thresholds.
        history: full date-indexed series including the latest observation.
        asof: explicit observation date; defaults to history's last index.

    Returns:
        `MetricScore` or `None` if history is empty.
    """
    s = history.sort_index().dropna()
    if s.empty:
        return None
    if evaluation_date is not None:
        s = s.loc[s.index <= pd.Timestamp(evaluation_date)]
    s = s[np.isfinite(s)]
    if len(s) <= metric.min_history:
        return None

    last_idx = s.index[-1]
    last_val = float(s.iloc[-1])
    if evaluation_date is not None and (evaluation_date - pd.Timestamp(last_idx).date()).days > max_age_days(metric):
        return None
    pct = percentile_rank(s.iloc[:-1], last_val)

    flagged_high = (
        metric.flag_high_pct is not None
        and not np.isnan(pct)
        and pct >= metric.flag_high_pct
    )
    flagged_low = (
        metric.flag_low_pct is not None
        and not np.isnan(pct)
        and pct <= metric.flag_low_pct
    )

    return MetricScore(
        metric_id=metric.id,
        asof=asof or pd.Timestamp(last_idx).date(),
        value=last_val,
        percentile=pct,
        label=label_from_pct(pct),
        flagged_high=flagged_high,
        flagged_low=flagged_low,
    )


def max_age_days(metric: Metric) -> int:
    """Operational expiry tolerances in calendar days, not release-date estimates."""
    return metric.max_age_days if metric.max_age_days is not None else {
        "daily": 7, "weekly": 21, "monthly": 75, "quarterly": 200,
    }[metric.cadence.value]
