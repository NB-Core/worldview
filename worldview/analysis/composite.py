"""Field-level rollups: Valuation / Sentiment / Macro-Risk + the Worldview Score.

Each block is a weighted blend of metric percentiles, oriented so that:

    Valuation Score :  0 = cheap,    100 = expensive
    Sentiment Score:  0 = fearful,  100 = euphoric
    Macro Risk     :  0 = healthy,  100 = stressed

Polarity flips happen here — see `_oriented_pct`. A metric with
`polarity=expensive` contributes its raw percentile to Valuation; a
`polarity=cheap` metric contributes `100 - percentile`. Same idea for the
other two blocks.

The 2×2 quadrant per field falls out of (Valuation, Sentiment).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from ..models import FieldDef, Metric, MetricScore, Polarity

# Polarity → which block it belongs in, and which sign it carries there.
# A "+1" means raw percentile; "-1" means 100 - percentile.
_POLARITY_ORIENTATION: dict[Polarity, tuple[str, int]] = {
    Polarity.EXPENSIVE: ("valuation", +1),
    Polarity.CHEAP:     ("valuation", -1),
    Polarity.GREEDY:    ("sentiment", +1),
    Polarity.FEARFUL:   ("sentiment", -1),
    Polarity.STRESSED:  ("macro_risk", +1),
    Polarity.HEALTHY:   ("macro_risk", -1),
    Polarity.WEAK:      ("macro_risk", +1),  # weak breadth → stressed
}


def _oriented_pct(metric: Metric, pct: float, block: str | None = None) -> float:
    """Flip percentile if the metric's polarity is the inverse of its block."""
    _, sign = _POLARITY_ORIENTATION[metric.polarity]
    if block in {"price_momentum", "concentration"}:
        sign = 1
    sign = metric.score_directions.get(block, sign) if block is not None else sign
    return pct if sign == +1 else (100.0 - pct)


@dataclass(frozen=True, slots=True)
class FieldScore:
    """The three sub-scores + quadrant label for one field."""

    field_id: str
    label: str
    valuation: float | None    # None = no metrics in this block for this field
    sentiment: float | None
    macro_risk: float | None
    quadrant: str              # BUY / CAUTION / TRAP / BUBBLE / N/A
    contributing: dict[str, list[str]]  # block → list[metric_id]


def _weighted_blend(
    metric_ids: list[str],
    metrics_by_id: dict[str, Metric],
    scores_by_id: dict[str, MetricScore],
    block: str | None = None,
) -> float | None:
    """Weighted average of *oriented* percentiles. None if nothing contributes."""
    pairs: list[tuple[float, float]] = []
    for mid in metric_ids:
        metric = metrics_by_id.get(mid)
        score = scores_by_id.get(mid)
        if metric is None or score is None:
            continue
        if not isfinite(score.percentile):
            continue
        pairs.append((_oriented_pct(metric, score.percentile, block), max(metric.weight, 0.0)))

    if not pairs:
        return None
    weights = sum(w for _, w in pairs)
    if weights <= 0:
        return None
    return sum(v * w for v, w in pairs) / weights


def _quadrant(val: float | None, sent: float | None) -> str:
    """Map (Valuation, Sentiment) into one of BUY / CAUTION / TRAP / BUBBLE."""
    if val is None or sent is None:
        return "N/A"
    cheap = val <= 50.0
    fearful = sent <= 50.0
    if cheap and fearful:
        return "BUY"
    if cheap and not fearful:
        return "CAUTION"     # Oliver's "running hot but cheap" warning
    if not cheap and fearful:
        return "TRAP"
    return "BUBBLE"


def regime(val: float | None, sent: float | None) -> str:
    """Descriptive regime with an inclusive neutral band; quadrant remains legacy."""
    if val is None or sent is None:
        return "N/A"
    if 45 <= val <= 55 or 45 <= sent <= 55:
        return "TRANSITION"
    return _quadrant(val, sent)


def field_scores(
    fields: dict[str, FieldDef],
    metrics_by_id: dict[str, Metric],
    scores_by_id: dict[str, MetricScore],
) -> dict[str, FieldScore]:
    """Compute per-field scores for every defined field.

    Args:
        fields: registry from fields.yaml.
        metrics_by_id: lookup so we can read polarity + weight.
        scores_by_id: latest `MetricScore` for each metric.
    """
    out: dict[str, FieldScore] = {}
    for fid, fdef in fields.items():
        val  = _weighted_blend(fdef.valuation,  metrics_by_id, scores_by_id, "valuation")
        sent = _weighted_blend(fdef.sentiment,  metrics_by_id, scores_by_id, "sentiment")
        risk = _weighted_blend(fdef.macro_risk, metrics_by_id, scores_by_id, "macro_risk")
        out[fid] = FieldScore(
            field_id=fid,
            label=fdef.label,
            valuation=val,
            sentiment=sent,
            macro_risk=risk,
            quadrant=_quadrant(val, sent),
            contributing={
                "valuation":  [mid for mid in fdef.valuation if mid in scores_by_id],
                "sentiment":  [mid for mid in fdef.sentiment if mid in scores_by_id],
                "macro_risk": [mid for mid in fdef.macro_risk if mid in scores_by_id],
            },
        )
    return out


def _sentiment_term(sentiment: float, mode: str) -> float:
    """Convert a sentiment percentile (0=fearful, 100=greedy) into a 0..100
    contribution to the Worldview Score.

    Modes
    -----
    penalize_greed (DEFAULT, Buffett-aligned):
        100 - sentiment. Fear (low sentiment) helps the score; neutral is
        medium; greed kills it. The "things are breaking" caveat at extreme
        fear is independently captured by the macro_risk block, so we
        don't double-count it here.

    penalize_extremes (legacy):
        100 - 2*|sentiment - 50|. Rewards neutral sentiment, penalizes both
        ends. Reasonable for a "central tendency" view but punishes the
        historical buying opportunities (March 2009, March 2020, late 2022)
        that famously printed extreme fear with low valuations.
    """
    if mode == "penalize_extremes":
        return 100.0 - 2.0 * abs(sentiment - 50.0)
    # default
    return 100.0 - sentiment


def worldview_score(
    overall: FieldScore,
    weights: dict[str, float],
    sentiment_mode: str = "penalize_greed",
) -> float | None:
    """The single headline number on top of the dashboard.

    Higher = better entry conditions. By default this uses the
    Buffett-aligned `penalize_greed` sentiment formulation: fear helps,
    greed hurts, and macro_risk independently flags broken regimes. Pass
    `sentiment_mode="penalize_extremes"` to recover the original
    central-tendency formula.
    """
    if overall.valuation is None or overall.sentiment is None or overall.macro_risk is None:
        return None
    val_term  = (100.0 - overall.valuation)  * weights.get("valuation", 0.4)
    sent_term = _sentiment_term(overall.sentiment, sentiment_mode) * weights.get("sentiment", 0.3)
    risk_term = (100.0 - overall.macro_risk) * weights.get("macro_risk", 0.3)
    return val_term + sent_term + risk_term
