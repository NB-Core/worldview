"""yfinance fetcher.

Used for equities, ETFs, futures, FX, and indices. yfinance is free and
key-less but the upstream Yahoo API is famously flaky — we retry with
exponential backoff and fall back to an empty Series on persistent failure
rather than crashing the whole snapshot.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Metric
from .base import Fetcher, FetchError


class YFinanceFetcher(Fetcher):
    """Pulls daily closes from Yahoo Finance via the `yfinance` library."""

    source_name = "yfinance"

    def __init__(self, ticker_factory: object | None = None) -> None:
        """Args:
        ticker_factory: callable returning a yfinance.Ticker-like object.
            Injected for tests; defaults to `yfinance.Ticker`.
        """
        if ticker_factory is None:
            import yfinance as yf

            ticker_factory = yf.Ticker
        self._ticker_factory = ticker_factory

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, ValueError)),
        reraise=True,
    )
    def _history(self, source_ref: str, start: date) -> pd.DataFrame:
        ticker = self._ticker_factory(source_ref)  # type: ignore[misc]
        return ticker.history(start=start.isoformat(), auto_adjust=False)

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        try:
            df = self._history(metric.source_ref, start)
        except Exception as e:  # noqa: BLE001
            raise FetchError(
                f"yfinance fetch failed for {metric.source_ref}: {e}"
            ) from e

        if df is None or df.empty or "Close" not in df.columns:
            return pd.Series(dtype=float, name=metric.id)

        s = df["Close"].dropna().astype(float)
        # yfinance returns tz-aware timestamps — strip to plain dates for storage.
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        s.name = metric.id
        return s.sort_index()
