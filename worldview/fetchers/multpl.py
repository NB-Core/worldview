"""multpl.com scraper.

multpl publishes a long history of common S&P 500 valuation metrics as plain
HTML tables. We scrape the historical table off each page and return the
whole series.

Pages we use:
    /s-p-500-pe-ratio/         → trailing P/E
    /s-p-500-dividend-yield/   → dividend yield (%)
    /s-p-500-price-to-book/    → P/B ratio
    /shiller-pe/               → Shiller / cyclically-adjusted P/E

`Metric.source_ref` carries the page slug (without leading/trailing slashes
or domain) — e.g. "s-p-500-pe-ratio". The fetcher pre-pends the host.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Metric
from .base import Fetcher, FetchError

BASE_URL = "https://www.multpl.com"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

# Strip suffix characters: "%", "x", thousand separators, whitespace.
_NUMERIC_NOISE = re.compile(r"[,%\s]+")


class MultplFetcher(Fetcher):
    """Scrapes the historical-table on a multpl.com page."""

    source_name = "multpl"

    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        timeout_s: float = 15.0,
    ) -> None:
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _get_html(self, url: str) -> str:
        resp = self._session.get(
            url, headers=_DEFAULT_HEADERS, timeout=self._timeout
        )
        resp.raise_for_status()
        return resp.text

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        slug = metric.source_ref.strip("/").replace(self._base, "").strip("/")
        # multpl's main page only shows the *current* value; the historical
        # time-series table lives at /<slug>/table/by-month. We always go
        # there. If a slug already includes a trailing /table fragment we
        # respect it.
        if "/table" not in slug:
            slug = f"{slug}/table/by-month"
        url = f"{self._base}/{slug}"
        try:
            html = self._get_html(url)
            series = _parse_multpl_html(html)
        except Exception as e:  # noqa: BLE001
            raise FetchError(f"multpl fetch failed for {url}: {e}") from e

        if series.empty:
            return pd.Series(dtype=float, name=metric.id)

        series.name = metric.id
        return series[series.index.date >= start]


def _parse_multpl_html(html: str) -> pd.Series:
    """Locate the data table on a multpl page and return a date→value Series.

    Multpl pages have a `<table id="datatable">` with two columns: a textual
    date and a value (sometimes wrapped in `<span>` tags). We tolerate both
    shapes.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="datatable")
    if table is None:
        # fallback: any <table> with at least two text-only columns
        table = soup.find("table")
    if table is None:
        return pd.Series(dtype=float)

    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td"])
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(strip=True)
        value_text = cells[1].get_text(strip=True)
        d = _parse_date(date_text)
        v = _parse_number(value_text)
        if d is None or v is None:
            continue
        dates.append(d)
        values.append(v)

    if not dates:
        return pd.Series(dtype=float)

    s = pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _parse_date(text: str) -> pd.Timestamp | None:
    text = text.strip()
    if not text:
        return None
    try:
        return pd.to_datetime(text)
    except (ValueError, pd.errors.ParserError):
        return None


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    cleaned = _NUMERIC_NOISE.sub("", text)
    # Collapse trailing letters that multpl sometimes leaves: "21.4x" → "21.4".
    cleaned = re.sub(r"[a-zA-Z]+$", "", cleaned)
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
