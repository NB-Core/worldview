"""Maps `Metric.source` strings to a `Fetcher` instance.

Centralized so `run_snapshot.py` and tests can swap implementations cleanly.
Sources that aren't wired yet (csv, scrape, ucdp, eia, eurostat) raise
`UnsupportedSource` — Milestone 0/1 only ships fred + yfinance.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..config import Settings
from ..models import Metric
from ..store import Database
from .aaii import AAIIFetcher
from .base import Fetcher, FetchError
from .cnn_fng import CNNFearGreedFetcher
from .derived import DerivedFetcher
from .fred import FREDFetcher
from .gpr_iacoviello import GPRDailyFetcher
from .ishares import ISharesFetcher
from .multpl import MultplFetcher
from .naaim import NAAIMFetcher
from .yfinance_fetcher import YFinanceFetcher


class UnsupportedSource(FetchError):  # noqa: N818 -- public compatibility
    """The metric's `source` has no fetcher wired up yet."""


class FetcherRegistry:
    """Holds one fetcher per source string. Lazy — fetchers are built on first access.

    Usage:
        reg = FetcherRegistry()
        reg.register("fred", FREDFetcher(api_key="..."))
        series = reg.fetch(metric, start=date(2008, 1, 1))
    """

    def __init__(self) -> None:
        self._by_source: dict[str, Fetcher] = {}

    def register(self, source: str, fetcher: Fetcher) -> None:
        self._by_source[source] = fetcher

    def get(self, source: str) -> Fetcher:
        if source not in self._by_source:
            raise UnsupportedSource(
                f"no fetcher registered for source={source!r}. "
                f"Known: {sorted(self._by_source)}"
            )
        return self._by_source[source]

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        return self.get(metric.source).fetch(metric, start)


def default_registry(settings: Settings, db: Database | None = None) -> FetcherRegistry:
    """Build the registry shipped with M2: yfinance + FRED + CNN F&G + GPR + multpl + derived.

    FRED is registered only if `FRED_API_KEY` is present — otherwise FRED
    metrics get a clearer error message at fetch time. The derived fetcher
    needs a `Database` reference so it can read inputs from the local store.
    """
    reg = FetcherRegistry()
    reg.register("yfinance", YFinanceFetcher())
    reg.register("cnn_fng", CNNFearGreedFetcher())
    reg.register("gpr_iacoviello", GPRDailyFetcher())
    reg.register("multpl", MultplFetcher())
    reg.register("aaii", AAIIFetcher())
    reg.register("naaim", NAAIMFetcher())
    reg.register("ishares", ISharesFetcher())
    if settings.fred_api_key:
        reg.register("fred", FREDFetcher(api_key=settings.fred_api_key))
    if db is not None:
        reg.register("derived", DerivedFetcher(db))
    return reg
