"""Fetcher tests. Network is fully mocked — no live HTTP from unit tests.

Live integration smoke tests are gated behind `pytest -m integration`.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from worldview.fetchers import FetchError, FetcherRegistry
from worldview.fetchers.fred import FREDFetcher
from worldview.fetchers.yfinance_fetcher import YFinanceFetcher
from worldview.models import Cadence, Category, Metric, Polarity


def _metric(source: str, ref: str) -> Metric:
    return Metric(
        id="test",
        category=Category.MACRO,
        field="overall",
        source=source,
        source_ref=ref,
        polarity=Polarity.STRESSED,
        cadence=Cadence.DAILY,
    )


# ── FRED ──────────────────────────────────────────────────────────────────────

class _FakeFred:
    """In-memory stand-in for `fredapi.Fred`."""

    def __init__(self, series: pd.Series | None = None, raise_with: Exception | None = None):
        self._series = series
        self._raise = raise_with
        self.calls: list[tuple[str, str]] = []

    def get_series(self, series_id: str, observation_start: str):
        self.calls.append((series_id, observation_start))
        if self._raise:
            raise self._raise
        return self._series


def test_fred_fetcher_returns_clean_series():
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    fake = _FakeFred(pd.Series([1.0, np.nan, 3.0], index=idx))
    fetcher = FREDFetcher(client=fake)
    result = fetcher.fetch(_metric("fred", "DGS10"), date(2024, 1, 1))
    assert list(result.values) == [1.0, 3.0]
    assert fake.calls == [("DGS10", "2024-01-01")]


def test_fred_fetcher_returns_empty_when_source_returns_nothing():
    fake = _FakeFred(pd.Series([], dtype=float))
    fetcher = FREDFetcher(client=fake)
    result = fetcher.fetch(_metric("fred", "X"), date(2024, 1, 1))
    assert result.empty


def test_fred_fetcher_translates_exceptions_to_fetcherror():
    fake = _FakeFred(raise_with=RuntimeError("boom"))
    fetcher = FREDFetcher(client=fake)
    with pytest.raises(FetchError):
        fetcher.fetch(_metric("fred", "X"), date(2024, 1, 1))


def test_fred_fetcher_requires_api_key_or_client():
    with pytest.raises(FetchError):
        FREDFetcher(api_key=None)


# ── yfinance ──────────────────────────────────────────────────────────────────

class _FakeTicker:
    def __init__(self, df: pd.DataFrame, *, raise_with: Exception | None = None):
        self._df = df
        self._raise = raise_with

    def history(self, **_kwargs):
        if self._raise:
            raise self._raise
        return self._df


def _factory(df: pd.DataFrame, *, raise_with: Exception | None = None):
    return lambda _ticker: _FakeTicker(df, raise_with=raise_with)


def test_yfinance_fetcher_extracts_close():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    df = pd.DataFrame({"Open": [1, 2, 3], "Close": [10.0, 11.0, 12.0]}, index=idx)
    fetcher = YFinanceFetcher(ticker_factory=_factory(df))
    result = fetcher.fetch(_metric("yfinance", "^VIX"), date(2024, 1, 1))
    assert list(result.values) == [10.0, 11.0, 12.0]
    assert result.index.is_monotonic_increasing


def test_yfinance_fetcher_drops_nan_close():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    df = pd.DataFrame({"Close": [10.0, np.nan]}, index=idx)
    fetcher = YFinanceFetcher(ticker_factory=_factory(df))
    result = fetcher.fetch(_metric("yfinance", "X"), date(2024, 1, 1))
    assert list(result.values) == [10.0]


def test_yfinance_history_raises_on_empty_so_retry_can_fire():
    """Yahoo's "rate-limited → empty DataFrame" symptom must surface as an
    exception inside `_history` so tenacity's retry actually fires. We call
    the underlying function directly via `__wrapped__` to bypass retry timing.
    """
    from worldview.fetchers.yfinance_fetcher import _EmptyYahooResponse

    fetcher = YFinanceFetcher(ticker_factory=_factory(pd.DataFrame()))
    # `__wrapped__` on a tenacity-decorated function returns the bare function.
    inner = fetcher._history.__wrapped__
    with pytest.raises(_EmptyYahooResponse, match="rate-limited"):
        inner(fetcher, "ANYTHING", date(2024, 1, 1))


def test_yfinance_fetcher_translates_exception():
    fetcher = YFinanceFetcher(
        ticker_factory=_factory(pd.DataFrame(), raise_with=RuntimeError("network"))
    )
    with pytest.raises(FetchError):
        fetcher.fetch(_metric("yfinance", "X"), date(2024, 1, 1))


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_dispatches_by_source():
    reg = FetcherRegistry()

    idx = pd.to_datetime(["2024-01-02"])
    yf_fetcher = YFinanceFetcher(
        ticker_factory=_factory(pd.DataFrame({"Close": [42.0]}, index=idx))
    )
    fred_fetcher = FREDFetcher(client=_FakeFred(pd.Series([1.5], index=idx)))

    reg.register("yfinance", yf_fetcher)
    reg.register("fred", fred_fetcher)

    yf_result = reg.fetch(_metric("yfinance", "X"), date(2024, 1, 1))
    fred_result = reg.fetch(_metric("fred", "X"), date(2024, 1, 1))

    assert yf_result.iloc[0] == 42.0
    assert fred_result.iloc[0] == 1.5


def test_registry_unsupported_source_raises():
    reg = FetcherRegistry()
    with pytest.raises(FetchError):
        reg.fetch(_metric("scrape", "X"), date(2024, 1, 1))


# ── Integration smoke tests — run only with `pytest -m integration` ──────────

@pytest.mark.integration
def test_fred_live_smoke():
    """Real FRED call. Requires FRED_API_KEY in the environment."""
    import os
    key = os.getenv("FRED_API_KEY")
    if not key:
        pytest.skip("FRED_API_KEY not set")
    fetcher = FREDFetcher(api_key=key)
    s = fetcher.fetch(_metric("fred", "DGS10"), date(2024, 1, 1))
    assert not s.empty


@pytest.mark.integration
def test_yfinance_live_smoke():
    """Real yfinance call. May fail intermittently — that's why it's gated."""
    fetcher = YFinanceFetcher()
    s = fetcher.fetch(_metric("yfinance", "^VIX"), date(2024, 1, 1))
    assert not s.empty
