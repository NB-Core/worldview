"""Core dataclasses used across the project.

Kept intentionally small. No business logic here — just typed value objects
that travel between fetchers, the store, and the analysis layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from enum import Enum


class Category(str, Enum):  # noqa: UP042 -- preserve Enum string representation
    """Top-level metric bucket."""

    VALUATION = "valuation"
    SENTIMENT = "sentiment"
    MACRO = "macro"
    GEO = "geo"
    ENERGY = "energy"
    BREADTH = "breadth"


class Cadence(str, Enum):  # noqa: UP042 -- preserve Enum string representation
    """How often the underlying source publishes new data."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class Polarity(str, Enum):  # noqa: UP042 -- preserve Enum string representation
    """What it means when this metric prints HIGH.

    Used by the composite layer to flip percentiles where needed:
    e.g. high VIX = fearful → contributes negatively to a "greedy" sentiment
    score; high CAPE = expensive → contributes positively to a "valuation"
    score that we *want* to be high when things are pricey.
    """

    EXPENSIVE = "expensive"
    CHEAP = "cheap"
    GREEDY = "greedy"
    FEARFUL = "fearful"
    STRESSED = "stressed"
    HEALTHY = "healthy"
    WEAK = "weak"


@dataclass(frozen=True, slots=True)
class Metric:
    """Static description of a single time-series we track."""

    id: str
    category: Category
    field: str
    source: str
    source_ref: str
    polarity: Polarity
    cadence: Cadence
    weight: float = 1.0
    flag_high_pct: float | None = None
    flag_low_pct: float | None = None
    notes: str = ""
    min_history: int = 20
    max_age_days: int | None = None
    score_directions: dict[str, int] = dc_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Observation:
    """A single (metric, date, value) datapoint."""

    metric_id: str
    date: date
    value: float


@dataclass(frozen=True, slots=True)
class FieldDef:
    """Roll-up definition for a business field (AI, energy, …)."""

    id: str
    label: str
    valuation: list[str] = dc_field(default_factory=list)
    sentiment: list[str] = dc_field(default_factory=list)
    macro_risk: list[str] = dc_field(default_factory=list)
    price_momentum: list[str] = dc_field(default_factory=list)
    concentration: list[str] = dc_field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MetricScore:
    """Result of scoring one metric against its history."""

    metric_id: str
    asof: date
    value: float
    percentile: float          # 0..100 vs history
    label: str                 # "Extreme Low" … "Extreme High"
    flagged_high: bool = False
    flagged_low: bool = False
