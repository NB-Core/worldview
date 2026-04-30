"""Flag detection: which metrics are currently sitting in extreme territory.

A flag is a `(metric_id, side, percentile, value, date)` tuple. It's stored
in the `flags` SQLite table so we can later answer "GPR has been > 90th pct
for 47 days".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..models import MetricScore


@dataclass(frozen=True, slots=True)
class Flag:
    metric_id: str
    side: str       # "high" | "low"
    pct: float
    value: float
    on: date


def compute_flags(scores: list[MetricScore]) -> list[Flag]:
    """Translate `MetricScore.flagged_*` flags into `Flag` records ready for the DB."""
    out: list[Flag] = []
    for s in scores:
        if s.flagged_high:
            out.append(Flag(s.metric_id, "high", s.percentile, s.value, s.asof))
        if s.flagged_low:
            out.append(Flag(s.metric_id, "low", s.percentile, s.value, s.asof))
    return out
