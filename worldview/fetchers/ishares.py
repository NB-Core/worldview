"""iShares ETF holdings — daily concentration metrics.

iShares publishes a daily CSV of every ETF's full holdings, no auth needed.
The IVV (S&P 500) file gives us cap-weighted index weights one could not
easily get elsewhere for free; we slice it into concentration aggregates:

    top_5_share   — sum of the top 5 weights
    top_10_share  — sum of the top 10 weights
    mag7_share    — sum of NVDA, MSFT, GOOGL+GOOG, AMZN, META, AAPL, TSLA
    nvda_share    — single-name Nvidia weight

`Metric.source_ref` is the recipe name above. Because iShares only exposes
the *current* day's holdings (no history endpoint), we store one
observation per snapshot date. Percentile depth builds over weeks of runs.

The IVV holdings CSV URL has been stable for years:
    https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/
        1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund

The CSV has a multi-line preamble (fund name, as-of date, NAV, …) before
the actual header row. We locate the header by scanning for a row that
starts with `Ticker,`.
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pandas as pd
import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Metric
from .base import Fetcher, FetchError

IVV_URL = (
    "https://www.ishares.com/us/products/239726/"
    "ishares-core-sp-500-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IVV_holdings&dataType=fund"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*;q=0.8",
}

MAG7 = ("NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AAPL", "TSLA")


def _top_n(n: int):
    def _f(weights: dict[str, float]) -> float:
        return sum(sorted(weights.values(), reverse=True)[:n])
    return _f


def _mag7(weights: dict[str, float]) -> float:
    # GOOGL + GOOG counted separately by iShares; sum both.
    return sum(weights.get(t, 0.0) for t in MAG7)


def _single(ticker: str):
    def _f(weights: dict[str, float]) -> float:
        return weights.get(ticker, 0.0)
    return _f


ISHARES_RECIPES = {
    "top_5_share":  _top_n(5),
    "top_10_share": _top_n(10),
    "mag7_share":   _mag7,
    "nvda_share":   _single("NVDA"),
}


class ISharesFetcher(Fetcher):
    """Pulls iShares IVV (S&P 500) holdings and computes concentration aggregates."""

    source_name = "ishares"

    def __init__(
        self,
        session: requests.Session | None = None,
        url: str = IVV_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self._session = session or requests.Session()
        self._url = url
        self._timeout = timeout_s

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _download(self) -> str:
        resp = self._session.get(self._url, headers=_HEADERS, timeout=self._timeout)
        resp.raise_for_status()
        return resp.text

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        recipe = ISHARES_RECIPES.get(metric.source_ref)
        if recipe is None:
            raise FetchError(
                f"unknown ishares recipe {metric.source_ref!r}. "
                f"Known: {sorted(ISHARES_RECIPES)}"
            )
        try:
            text = self._download()
            weights = parse_ishares_holdings(text)
        except FetchError:
            raise
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"iShares fetch failed: {e}") from e

        if not weights:
            return pd.Series(dtype=float, name=metric.id)

        value = float(recipe(weights))
        today = pd.Timestamp(date.today())
        s = pd.Series([value], index=[today], dtype=float, name=metric.id)
        return s[s.index.date >= start]


def parse_ishares_holdings(text: str) -> dict[str, float]:
    """Extract {ticker: weight_percent} from an iShares holdings CSV.

    The file has a 9-12 line preamble (Fund Name, NAV, As Of, etc.) before
    the actual header row. We locate the header by scanning for a line that
    starts with `Ticker,`. Cash / FX / non-equity rows are skipped.
    """
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or line.startswith('"Ticker"'):
            header_idx = i
            break
    if header_idx is None:
        raise FetchError("iShares CSV: no `Ticker,` header row found")

    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body))

    # Column names vary slightly; locate the weight column.
    weight_col = _pick_column(list(reader.fieldnames or []), (
        "Weight (%)", "Weight(%)", "Weight", "% of Net Assets",
    ))
    ticker_col = "Ticker"
    if weight_col is None:
        raise FetchError(
            f"iShares CSV: no recognizable weight column. Got {reader.fieldnames!r}"
        )

    out: dict[str, float] = {}
    for row in reader:
        ticker = (row.get(ticker_col) or "").strip().upper()
        if not ticker or not _looks_like_equity_ticker(ticker):
            continue
        # Filter out non-equity rows (cash, FX, futures collateral). iShares
        # tags these in the `Asset Class` column.
        asset_class = (row.get("Asset Class") or "").strip().lower()
        if asset_class and asset_class != "equity":
            continue
        weight = _parse_percent(row.get(weight_col, ""))
        if weight is None or weight <= 0:
            continue
        out[ticker] = weight
    return out


def _pick_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in fieldnames:
            return c
    return None


def _looks_like_equity_ticker(s: str) -> bool:
    """Filter out cash/FX/non-equity rows.

    iShares CSVs include lines like `USD,US DOLLAR,...` for cash holdings.
    Equity tickers are short, alphabetic (with allowed `.` / `-`).
    """
    if len(s) > 6:
        return False
    return all(c.isalpha() or c in (".", "-") for c in s)


def _parse_percent(text: str) -> float | None:
    if not text:
        return None
    cleaned = text.replace("%", "").replace(",", "").strip().strip('"')
    if cleaned == "" or cleaned == "-":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
