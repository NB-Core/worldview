"""FRED (St. Louis Fed) fetcher.

Most macro / credit-spread / yield series live here. Free API key required;
get one at https://fred.stlouisfed.org/docs/api/api_key.html.

The library `fredapi` returns a pandas Series indexed by Timestamp — exactly
what `Fetcher.fetch` expects, so the adapter is mostly a thin wrapper plus
retry policy.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Metric
from .base import Fetcher, FetchError

# fredapi converts every HTTP failure into ValueError. We want to retry
# transient server-side errors (5xx, gateway timeouts, "Service Unavailable")
# but fail fast on deterministic 4xx like "The series does not exist" —
# retrying won't bring a deleted series back.
_TRANSIENT_FRAGMENTS = (
    "Internal Server Error",
    "Service Unavailable",
    "Bad Gateway",
    "Gateway Timeout",
    "Request Timeout",
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, ValueError):
        msg = str(exc)
        return any(frag in msg for frag in _TRANSIENT_FRAGMENTS)
    return False


class FREDFetcher(Fetcher):
    """Wraps `fredapi.Fred`. Inject the client for testability."""

    source_name = "fred"

    def __init__(self, api_key: str | None = None, client: object | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            if not api_key:
                raise FetchError(
                    "FRED_API_KEY missing — set it in .env or pass api_key= explicitly."
                )
            # Imported lazily so tests that inject a fake client don't need fredapi.
            from fredapi import Fred  # type: ignore[import-untyped]

            self._client = Fred(api_key=api_key)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _get_series(self, series_id: str, start: date) -> pd.Series:
        return self._client.get_series(  # type: ignore[attr-defined]
            series_id,
            observation_start=start.isoformat(),
        )

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        try:
            raw = self._get_series(metric.source_ref, start)
        except Exception as e:  # noqa: BLE001 — translate to our hierarchy
            raise FetchError(f"FRED fetch failed for {metric.source_ref}: {e}") from e

        if raw is None or len(raw) == 0:
            return pd.Series(dtype=float, name=metric.id)

        s = pd.Series(raw, dtype=float).dropna()
        s.index = pd.to_datetime(s.index)
        s.name = metric.id
        return s.sort_index()
