"""AAII Investor Sentiment Survey, weekly.

The American Association of Individual Investors publishes a weekly poll of
its members:

    bullish %  +  neutral %  +  bearish %  =  100

The headline reading we track is the **bull-bear spread** (bullish minus
bearish). Extreme positive readings have historically marked retail-greed
peaks; extreme negative readings have marked retail-capitulation troughs.

Source (free, no auth, intermittent UA blocks):
    https://www.aaii.com/files/surveys/sentiment.xls

`Metric.source_ref` is treated as a URL override; an empty value falls
back to the canonical URL above. The file format has shifted across the
years — we parse by column name, not column position.
"""

from __future__ import annotations

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
from ._excel import first_present, is_excel_blob, read_excel_any
from .base import Fetcher, FetchError

AAII_URL = "https://www.aaii.com/files/surveys/sentiment.xls"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

_DATE_COLS = (
    "Reported Date", "Date", "reported_date",
    "Date Reported", "Reported",
)
_BULL_COLS = ("Bullish", "Bull", "bullish")
_BEAR_COLS = ("Bearish", "Bear", "bearish")
_SPREAD_COLS = (
    "Bull-Bear Spread", "Bull-Bear",
)  # spread can sometimes already be a column


class AAIIFetcher(Fetcher):
    """Returns the AAII Bull-Bear spread time series.

    Spread is computed from raw `bullish - bearish` columns. If the source
    file already exposes a spread column under a known name we use it
    directly.
    """

    source_name = "aaii"

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout_s

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _download(self, url: str) -> bytes:
        resp = self._session.get(url, headers=_HEADERS, timeout=self._timeout)
        resp.raise_for_status()
        # AAII intermittently serves HTML (rate-limit / maintenance pages)
        # with a 200 OK in place of the XLS. Detect it via magic bytes and
        # raise to trigger a retry rather than confuse the Excel parser.
        if not is_excel_blob(resp.content):
            raise requests.RequestException(
                "AAII returned non-Excel body (likely a rate-limit or "
                "maintenance HTML page). Will retry."
            )
        return resp.content

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        url = metric.source_ref or AAII_URL
        try:
            blob = self._download(url)
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"AAII fetch failed for {url}: {e}") from e

        df = read_excel_any(blob, source=url)
        # Header may not be on row 0 — AAII files usually have a few title
        # rows before the actual table. Re-detect if needed.
        df = _normalize_aaii_frame(df)

        date_col = first_present(df.columns, _DATE_COLS)
        if date_col is None:
            raise FetchError(
                f"AAII payload missing a recognizable date column. Got {list(df.columns)!r}"
            )

        # `format='mixed'` silences the dateutil-fallback warning while still
        # tolerating AAII's occasional format drift (M/D/YY ↔ YYYY-MM-DD).
        df["_d"] = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
        df = df.dropna(subset=["_d"]).set_index("_d").sort_index()

        spread = _spread_from(df)
        if spread is None:
            raise FetchError(
                "AAII payload missing bullish/bearish columns "
                f"(got {list(df.columns)!r})"
            )

        spread.name = metric.id
        return spread[spread.index.date >= start]


def _normalize_aaii_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Find the row that has both a date-like header AND a bull/bear column.

    AAII xls ships with a multi-row header — the "headline" row (Reported,
    Sentiment Survey, …) is what pandas picks as df.columns by default, but
    the actual machine-readable column names live on the row below. We need
    *both* a date column AND at least one bull/bear column to consider a
    row as "the real header"; otherwise we keep scanning.
    """
    def _has_both(names: list[str]) -> bool:
        names_set = {str(n) for n in names}
        has_date = any(c in names_set for c in _DATE_COLS)
        has_val  = any(c in names_set for c in (*_BULL_COLS, *_BEAR_COLS, *_SPREAD_COLS))
        return has_date and has_val

    # Already correctly-headed?
    if _has_both(list(df.columns)):
        return df

    # Search the first ~10 rows for a header line.
    for offset in range(0, min(10, len(df))):
        candidate = df.iloc[offset].astype(str).tolist()
        if _has_both(candidate):
            new = df.iloc[offset + 1:].copy()
            new.columns = candidate
            return new.reset_index(drop=True)
    return df


def _spread_from(df: pd.DataFrame) -> pd.Series | None:
    """Either pluck a pre-computed spread column or build it from bull-bear."""
    spread_col = first_present(df.columns, _SPREAD_COLS)
    if spread_col is not None:
        return _coerce_pct(df[spread_col]).dropna()

    bull_col = first_present(df.columns, _BULL_COLS)
    bear_col = first_present(df.columns, _BEAR_COLS)
    if bull_col is None or bear_col is None:
        return None

    bull = _coerce_pct(df[bull_col])
    bear = _coerce_pct(df[bear_col])
    return (bull - bear).dropna()


def _coerce_pct(s: pd.Series) -> pd.Series:
    """Parse a column that may be 0..1 (fractions) or 0..100 (percent strings)."""
    if s.dtype == object:
        s = s.astype(str).str.replace("%", "").str.strip()
    s = pd.to_numeric(s, errors="coerce")
    # If the values are mostly < 1.0, multiply to put them on a 0..100 scale.
    if s.dropna().abs().median() <= 1.0:
        s = s * 100.0
    return s
