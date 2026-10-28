"""Shared contribution and quality metadata for the dashboard and snapshots."""

from __future__ import annotations

from .composite import _oriented_pct, _weighted_blend, effective_valuation, regime

BLOCKS = ("valuation", "sentiment", "macro_risk", "price_momentum", "concentration")


def field_details(definition, score, metrics, scores):
    blocks = {}
    for block in BLOCKS:
        ids = getattr(definition, block)
        used = [mid for mid in ids if mid in scores and mid in metrics and metrics[mid].weight > 0]
        total = sum(max(metrics[mid].weight, 0) for mid in ids if mid in metrics)
        available = sum(metrics[mid].weight for mid in used)
        blocks[block] = {
            "score": _weighted_blend(ids, metrics, scores, block),
            "coverage": available / total if total else None,
            "warning": "no_data"
            if not used
            else ("low_coverage" if available < total or len(used) < 2 else None),
            "contributors": [
                {
                    "id": mid,
                    "as_of": scores[mid].asof.isoformat(),
                    "percentile": scores[mid].percentile,
                    "oriented_percentile": _oriented_pct(
                        metrics[mid], scores[mid].percentile, block
                    ),
                    "normalized_weight": metrics[mid].weight / available,
                    "contribution": _oriented_pct(metrics[mid], scores[mid].percentile, block)
                    * metrics[mid].weight
                    / available,
                }
                for mid in used
            ],
        }
    proxy_val, is_proxy = effective_valuation(score.valuation, blocks["price_momentum"]["score"])
    axis_scores = {"valuation": proxy_val, "sentiment": blocks["sentiment"]["score"]}
    return {
        "regime": regime(proxy_val, score.sentiment),
        "valuation_is_proxy": is_proxy,
        "valuation_display": proxy_val,
        "distance_to_50": {
            b: None if axis_scores[b] is None else axis_scores[b] - 50
            for b in ("valuation", "sentiment")
        },
        "distance_to_transition": {
            b: None
            if axis_scores[b] is None
            else min(abs(axis_scores[b] - 45), abs(axis_scores[b] - 55))
            for b in ("valuation", "sentiment")
        },
        "blocks": blocks,
    }
