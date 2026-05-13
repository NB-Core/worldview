"""yfinance fetcher.

Used for equities, ETFs, futures, FX, and indices. yfinance is free and
key-less but the upstream Yahoo API is famously flaky — we retry with
exponential backoff and fall back to an empty Series on persistent failure
rather than crashing the whole snapshot.

Critically, when Yahoo rate-limits a chatty session it returns an *empty
DataFrame* (and yfinance prints "$<TICKER>: possibly delisted; no price
data found") rather than raising. We translate that into an exception
inside the retry loop so retries actually fire on rate-limits.
"""

from __future__ import annotations

import random
import time
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


class _EmptyYahooResponse(ConnectionError):
    """Treated as transient — yfinance hands us an empty frame on rate-limit."""


class YFinanceFetcher(Fetcher):
    """Pulls daily closes from Yahoo Finance via the `yfinance` library."""

    source_name = "yfinance"

    # Small inter-call delay (seconds) to stop Yahoo rate-limiting a burst
    # of ~40 sequential yfinance calls during one snapshot. Randomized so we
    # don't synchronize requests on every snapshot.
    _CALL_JITTER_MIN = 0.10
    _CALL_JITTER_MAX = 0.30

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
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, ValueError)),
        reraise=True,
    )
    def _history(self, source_ref: str, start: date) -> pd.DataFrame:
        ticker = self._ticker_factory(source_ref)  # type: ignore[misc]
        df = ticker.history(start=start.isoformat(), auto_adjust=False)
        # yfinance returns an empty DataFrame (with no exception) when Yahoo
        # rate-limits the session. Raise so tenacity actually retries.
        if df is None or df.empty:
            raise _EmptyYahooResponse(
                f"yfinance returned empty data for {source_ref!r} — "
                "likely rate-limited; will retry."
            )
        return df

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        try:
            df = self._history(metric.source_ref, start)
        except _EmptyYahooResponse:
            # Retries exhausted — likely genuinely delisted or sustained
            # rate-limit. Return empty so the snapshot continues; the
            # metric just won't get a fresh observation this run.
            return pd.Series(dtype=float, name=metric.id)
        except Exception as e:  # noqa: BLE001
            raise FetchError(
                f"yfinance fetch failed for {metric.source_ref}: {e}"
            ) from e
        finally:
            # Jitter regardless of success/failure so the next yfinance call
            # in this snapshot doesn't pile straight onto Yahoo.
            time.sleep(random.uniform(self._CALL_JITTER_MIN, self._CALL_JITTER_MAX))

        if "Close" not in df.columns:
            return pd.Series(dtype=float, name=metric.id)

        s = df["Close"].dropna().astype(float)
        # yfinance returns tz-aware timestamps — strip to plain dates for storage.
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        s.name = metric.id
        return s.sort_index()
