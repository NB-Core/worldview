"""Explicit v1 comparison: original config, polarity and single-observation rule."""

from dataclasses import replace
from pathlib import Path

from ..config import load_fields
from ..models import MetricScore
from .composite import field_scores, worldview_score
from .scoring import score_metric


def legacy_scores(db, metrics, weights, mode):
    old_metrics = {
        mid: replace(m, score_directions={}, min_history=0) for mid, m in metrics.items()
    }
    scores = {}
    for mid, metric in old_metrics.items():
        history = db.get_observations(mid)
        if history.empty:
            continue
        if len(history) == 1:
            scores[mid] = MetricScore(
                mid, history.index[-1].date(), float(history.iloc[-1]), 50, "Normal"
            )
        else:
            scores[mid] = score_metric(metric, history)
    fields = field_scores(
        load_fields(Path(__file__).resolve().parents[2] / "config/fields_legacy.yaml"),
        old_metrics,
        scores,
    )
    return {
        "worldview_score": worldview_score(fields["overall"], weights, mode),
        "fields": {
            fid: {
                "valuation": f.valuation,
                "sentiment": f.sentiment,
                "macro_risk": f.macro_risk,
                "quadrant": f.quadrant,
            }
            for fid, f in fields.items()
        },
    }
