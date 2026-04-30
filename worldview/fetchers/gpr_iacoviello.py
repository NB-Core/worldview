"""Geopolitical Risk Index (Caldara & Iacoviello), daily.

Source:
    https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls

Distributed with a `.xls` extension; sometimes truly legacy BIFF, sometimes
xlsx-renamed-to-xls. We delegate the engine-juggling to `_excel.read_excel_any`.

The first sheet contains columns roughly like:

    DATE | GPRD | GPRD_THREATS | GPRD_ACT | GPRD_MA7 | GPRD_MA30

We extract `DATE` and `GPRD` (the headline daily index). The fetcher is
column-name driven, so light schema drift on the source doesn't break us.
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
from ._excel import first_present, read_excel_any
from .base import Fetcher, FetchError

GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"

_VALUE_COL_CANDIDATES = ("GPRD", "GPR_D", "gprd")
_DATE_COL_CANDIDATES = ("DATE", "date", "Date", "month")


class GPRDailyFetcher(Fetcher):
    """Daily Geopolitical Risk Index from matteoiacoviello.com.

    `Metric.source_ref` is treated as the URL when set, falling back to
    `GPR_URL`.  This makes mocking trivial without monkey-patching the module.
    """

    source_name = "gpr_iacoviello"

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._session = session or requests.Session()
        self._timeout = timeout_s

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _download(self, url: str) -> bytes:
        resp = self._session.get(url, timeout=self._timeout)
        resp.raise_for_status()
        return resp.content

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        url = metric.source_ref or GPR_URL
        try:
            blob = self._download(url)
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"GPR fetch failed for {url}: {e}") from e

        df = read_excel_any(blob, source=url)

        date_col = first_present(df.columns, _DATE_COL_CANDIDATES)
        value_col = first_present(df.columns, _VALUE_COL_CANDIDATES)
        if date_col is None or value_col is None:
            raise FetchError(
                f"GPR payload missing expected columns. Got {list(df.columns)!r}"
            )

        s = (
            df[[date_col, value_col]]
            .dropna()
            .assign(_d=lambda x: pd.to_datetime(x[date_col], errors="coerce"))
            .dropna(subset=["_d"])
            .set_index("_d")[value_col]
            .astype(float)
            .sort_index()
        )
        s.name = metric.id
        s.index = s.index.normalize()
        return s[s.index.date >= start]


