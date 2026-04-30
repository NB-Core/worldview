"""NAAIM Exposure Index, weekly.

The National Association of Active Investment Managers polls its members
every Wednesday for their *current* equity exposure, ranging from -200%
(leveraged short) through 0% (flat) to +200% (leveraged long). The mean
of those answers is the NAAIM Number — what we track here.

NAAIM publishes the data as a downloadable XLSX whose URL drifts (the
WordPress upload directory contains the year-month of the *first* upload,
not the current month). Hard-coding the URL breaks every year. So we
scrape the index page for the live `.xlsx` link instead.

If `metric.source_ref` is non-empty it's used as the URL override.
"""

from __future__ import annotations

import re
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
from ._excel import first_present, read_excel_any
from .base import Fetcher, FetchError

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_DATE_COLS = ("Date", "Reported Date", "date")
# NAAIM's headline column has shifted naming; try several.
_VALUE_COLS = (
    "NAAIM Number Mean", "Mean", "Average", "NAAIM Number",
)


INDEX_PAGE = "https://www.naaim.org/programs/naaim-exposure-index/"

# Captures any ".../wp-content/uploads/YYYY/MM/<filename>.xlsx" link in the
# rendered HTML. The first one on the page is reliably the data file.
_XLSX_LINK = re.compile(
    r'href=["\'](https?://[^"\']+wp-content/uploads/\d{4}/\d{2}/[^"\']+\.xlsx)["\']',
    re.IGNORECASE,
)


class NAAIMFetcher(Fetcher):
    """NAAIM Exposure Index — mean of member positioning, percent."""

    source_name = "naaim"

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_s: float = 30.0,
        index_page: str = INDEX_PAGE,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout_s
        self._index_page = index_page

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _http_get(self, url: str) -> requests.Response:
        resp = self._session.get(url, headers=_HEADERS, timeout=self._timeout)
        resp.raise_for_status()
        return resp

    def _resolve_xlsx_url(self) -> str:
        """Scrape the index page for the live .xlsx link."""
        try:
            page = self._http_get(self._index_page).text
        except requests.RequestException as e:
            raise FetchError(
                f"NAAIM index page {self._index_page} unreachable ({e}). "
                "Set the metric's `source_ref:` in metrics.yaml to the current "
                "xlsx URL — find it under 'Exposure Index' on naaim.org."
            ) from e
        match = _XLSX_LINK.search(page)
        if match is None:
            raise FetchError(
                f"NAAIM page at {self._index_page} contained no .xlsx link. "
                "The site layout has changed — set `source_ref:` in "
                "metrics.yaml to the current xlsx URL."
            )
        return match.group(1)

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        try:
            url = metric.source_ref or self._resolve_xlsx_url()
            blob = self._http_get(url).content
        except FetchError:
            raise
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"NAAIM fetch failed: {e}") from e

        df = read_excel_any(blob, source=metric.source_ref or self._index_page)
        df = _promote_naaim_header(df)

        date_col = first_present(df.columns, _DATE_COLS)
        value_col = first_present(df.columns, _VALUE_COLS)
        if date_col is None or value_col is None:
            raise FetchError(
                f"NAAIM payload missing expected columns. Got {list(df.columns)!r}"
            )

        s = (
            df[[date_col, value_col]]
            .dropna()
            .assign(_d=lambda x: pd.to_datetime(x[date_col], errors="coerce"))
            .dropna(subset=["_d"])
            .set_index("_d")[value_col]
        )
        s = pd.to_numeric(s, errors="coerce").dropna().astype(float).sort_index()
        s.name = metric.id
        s.index = s.index.normalize()
        return s[s.index.date >= start]


def _promote_naaim_header(df: pd.DataFrame) -> pd.DataFrame:
    """Tolerate a few preamble rows before the actual header line."""
    if any(c in df.columns for c in (*_DATE_COLS, *_VALUE_COLS)):
        return df
    for offset in range(1, 6):
        if offset >= len(df):
            break
        candidate = df.iloc[offset].astype(str).tolist()
        if any(c in candidate for c in (*_DATE_COLS, *_VALUE_COLS)):
            new = df.iloc[offset + 1:].copy()
            new.columns = candidate
            return new.reset_index(drop=True)
    return df
