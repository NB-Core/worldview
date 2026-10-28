"""Historical analysis: expanding-percentile time series + flag backfill.

Two related jobs live here:

1. `expanding_percentiles(series)` — for each row i, returns the percentile
   rank of `series[i]` against `series[:i]`. Vectorized via bisect, O(n log n)
   per metric.

2. `backfill_flags(metric, series)` — uses the percentiles above plus the
   metric's `flag_high_pct` / `flag_low_pct` to produce a list of `Flag`
   records covering every historical day the metric crossed its threshold.
   Persisting these to the `flags` table is what enables the "GPR > 90th
   pct for 47 days" streak counter on the dashboard.

Pure functions over pandas Series — no I/O.
"""

from __future__ import annotations

import bisect
from datetime import date

import pandas as pd

from ..analysis.flags import Flag
from ..models import Metric


def expanding_percentiles(series: pd.Series) -> pd.Series:
    """For each row, percentile of value against rows BEFORE it (strict <).

    The first observation is `NaN` (no prior). Equal values land at the
    percentile of the first occurrence — `bisect_left` keeps it stable.
    """
    out: list[float] = []
    sorted_prior: list[float] = []
    for v in series.to_numpy(dtype=float, na_value=float("nan")):
        if pd.isna(v):
            out.append(float("nan"))
            continue
        n = len(sorted_prior)
        if n == 0:
            out.append(float("nan"))
        else:
            pos = bisect.bisect_left(sorted_prior, v)
            out.append(pos / n * 100.0)
        bisect.insort(sorted_prior, v)
    return pd.Series(out, index=series.index, dtype=float)


def backfill_flags(metric: Metric, series: pd.Series) -> list[Flag]:
    """Walk the full history and emit a Flag for every threshold crossing.

    Idempotent: callers should upsert the rows; the (metric_id, date, side)
    primary key on the flags table prevents duplicates across re-runs.
    """
    if series.empty or (
        metric.flag_high_pct is None and metric.flag_low_pct is None
    ):
        return []

    pcts = expanding_percentiles(series)
    flags: list[Flag] = []
    for ts, val in series.items():
        pct = pcts.loc[ts]
        if pd.isna(pct):
            continue
        d = pd.Timestamp(ts).date()
        if metric.flag_high_pct is not None and pct >= metric.flag_high_pct:
            flags.append(Flag(metric.id, "high", float(pct), float(val), d))
        if metric.flag_low_pct is not None and pct <= metric.flag_low_pct:
            flags.append(Flag(metric.id, "low", float(pct), float(val), d))
    return flags


def current_streak(observation_dates: list[date], flagged_dates: set[date]) -> int:
    """How many consecutive observations, ending at the most recent, were flagged.

    Args:
        observation_dates: every date for which we have a value, ascending.
        flagged_dates: the subset that were flagged on a given side.

    Returns:
        Number of consecutive flagged observations ending at the latest one.
        0 if the latest observation isn't flagged.
    """
    streak = 0
    for d in reversed(observation_dates):
        if d in flagged_dates:
            streak += 1
        else:
            break
    return streak


def historical_overall_score(
    db,
    metrics_by_id: dict[str, Metric],
    fields,
    weights: dict[str, float],
    sentiment_mode: str = "penalize_greed",
    *,
    verified_only: bool = True,
) -> pd.DataFrame:
    """Compute the overall field's Valuation/Sentiment/MacroRisk + Worldview Score
    over time.

    Returns a DataFrame indexed by date with columns:
        valuation, sentiment, macro_risk, worldview_score

    Implementation: per-metric expanding percentiles → polarity-flip → blend.
    Joined on date intersection of inputs (dates where all relevant metrics
    have an observation; missing days drop out cleanly).
    """

    if verified_only:
        import json
        with db.connect() as conn:
            rows = conn.execute("SELECT captured_at, payload FROM score_snapshots WHERE model_version='v2' ORDER BY captured_at").fetchall()
        if rows:
            from .composite import FieldScore, worldview_score
            records = []
            for row in rows:
                values = json.loads(row[1]).get("overall", {})
                fs = FieldScore("overall", "Overall", values.get("valuation"), values.get("sentiment"), values.get("macro_risk"), "N/A", {})
                records.append({"date": pd.Timestamp(row[0][:10]), "valuation": fs.valuation,
                                "sentiment": fs.sentiment, "macro_risk": fs.macro_risk,
                                "worldview_score": worldview_score(fs, weights, sentiment_mode)})
            return pd.DataFrame(records).set_index("date").groupby(level=0).last()

    overall = fields.get("overall")
    if overall is None:
        return pd.DataFrame(
            columns=["valuation", "sentiment", "macro_risk", "worldview_score"]
        )

    def _block_series(metric_ids: list[str], block: str) -> pd.Series:
        """Weighted-average expanding percentile (polarity-oriented) for a block."""
        ids = [mid for mid in metric_ids if mid in metrics_by_id]
        if not ids:
            return pd.Series(dtype=float)

        oriented: list[pd.Series] = []
        weights_seq: list[float] = []
        for mid in ids:
            metric = metrics_by_id[mid]
            # Legacy store has no release timestamps or revision vintages.
            # Daily traded prices are the only supported observation-date inputs.
            if verified_only and (metric.source != "yfinance" or metric.cadence.value != "daily"):
                continue
            obs = db.get_observations(mid).sort_index()
            if obs.empty:
                continue
            obs = obs.loc[obs.index <= pd.Timestamp(date.today())]
            if obs.empty:
                continue
            pct = expanding_percentiles(obs)
            pct.iloc[:metric.min_history] = float("nan")
            metric = metrics_by_id[mid]
            sign = metric.score_directions.get(block)
            if sign is None:
                from .composite import _POLARITY_ORIENTATION
                sign = _POLARITY_ORIENTATION[metric.polarity][1]
            if sign == -1:
                pct = 100.0 - pct
            pct.name = mid
            oriented.append(pct)
            weights_seq.append(max(metric.weight, 0.0))

        if not oriented:
            return pd.Series(dtype=float)

        wide = pd.concat(oriented, axis=1)
        # Forward-fill so a metric reported only weekly still contributes
        # on intervening daily rows.
        from .scoring import max_age_days
        wide = wide.sort_index()
        for mid in wide.columns:
            dates = pd.Series(wide.index, index=wide.index).where(wide[mid].notna()).ffill()
            wide[mid] = wide[mid].ffill().where((wide.index.to_series() - dates).dt.days <= max_age_days(metrics_by_id[mid]))
        wide = wide.dropna(how="all")
        w = pd.Series(weights_seq, index=[s.name for s in oriented])
        # weighted mean per row, ignoring NaN cells
        numerator = (wide * w).sum(axis=1, min_count=1)
        denominator = wide.notna().mul(w, axis=1).sum(axis=1)
        return (numerator / denominator).dropna()

    val = _block_series(overall.valuation, "valuation")
    sent = _block_series(overall.sentiment, "sentiment")
    risk = _block_series(overall.macro_risk, "macro_risk")

    out = pd.concat(
        {"valuation": val, "sentiment": sent, "macro_risk": risk}, axis=1
    )
    if sentiment_mode == "penalize_extremes":
        sent_term = 100.0 - 2.0 * (out["sentiment"] - 50.0).abs()
    else:  # penalize_greed (default)
        sent_term = 100.0 - out["sentiment"]
    out["worldview_score"] = (
        (100.0 - out["valuation"]) * weights.get("valuation", 0.4)
        + sent_term                * weights.get("sentiment", 0.3)
        + (100.0 - out["macro_risk"]) * weights.get("macro_risk", 0.3)
    )
    return out
