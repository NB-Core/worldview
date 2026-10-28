"""Shared contribution and quality metadata for the dashboard and snapshots."""

from __future__ import annotations

from .composite import _oriented_pct, _weighted_blend, regime

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
    return {
        "regime": regime(score.valuation, score.sentiment),
        "distance_to_50": {
            b: None if blocks[b]["score"] is None else blocks[b]["score"] - 50
            for b in ("valuation", "sentiment")
        },
        "distance_to_transition": {
            b: None
            if blocks[b]["score"] is None
            else min(abs(blocks[b]["score"] - 45), abs(blocks[b]["score"] - 55))
            for b in ("valuation", "sentiment")
        },
        "blocks": blocks,
    }
