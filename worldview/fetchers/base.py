"""Fetcher base class.

Every data source plugs in here. The contract is intentionally tiny:

    fetch(metric, start) -> pd.Series

Indexed by date, values are floats. Return an empty Series on a soft miss
(e.g. weekend / holiday with no new data); raise `FetchError` on a hard miss
that callers should surface as a failed run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from ..models import Metric


class FetchError(RuntimeError):
    """Raised when a fetcher cannot return any data for hard reasons.

    Soft misses (no new bars, market closed) should return an empty Series
    instead — they are not errors.
    """


class Fetcher(ABC):
    """Abstract base. Subclasses register a `source_name` matching `Metric.source`."""

    source_name: str = ""

    @abstractmethod
    def fetch(self, metric: Metric, start: date) -> pd.Series:
        """Pull observations for `metric` from `start` onward.

        Args:
            metric: registry entry describing what to fetch.
            start: earliest date to request, inclusive.

        Returns:
            Date-indexed Series of float values, sorted ascending.
            Index entries must be `pd.Timestamp` (date precision is fine).

        Raises:
            FetchError: on connection, auth, or schema problems.
        """
