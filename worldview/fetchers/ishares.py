"""S&P 500 concentration metrics from a free ETF holdings file.

We need cap-weighted S&P 500 index weights — not easily had for free —
to compute concentration aggregates:

    top_5_share   — sum of the top 5 weights
    top_10_share  — sum of the top 10 weights
    mag7_share    — sum of NVDA, MSFT, GOOGL+GOOG, AMZN, META, AAPL, TSLA
    nvda_share    — single-name Nvidia weight

`Metric.source_ref` is the recipe name above. The holdings file only
exposes the *current* day (no history endpoint), so we store one
observation per snapshot date; percentile depth builds over weeks of runs.

Two interchangeable sources, both tracking the S&P 500:

  1. **Primary — iShares IVV CSV.** Stable URL for years, but the endpoint
     now sits behind Akamai Bot Manager: on blocked requests it returns
     HTTP 200 with `Content-Type: text/csv` yet a 10 MB *HTML* product page
     in the body. We detect that and fail fast (see `_looks_like_html`).
  2. **Fallback — State Street SPDR SPY XLSX.** Same index, not bot-walled.
     Header sits a few rows down (Name | Ticker | … | Weight | …); we locate
     it by scanning for a row containing both "Ticker" and "Weight".

Both yield a `{ticker: weight_percent}` dict that the recipes consume
identically, so a fallback is transparent to the caller.
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
from ._excel import is_excel_blob
from .base import Fetcher, FetchError

IVV_URL = (
    "https://www.ishares.com/us/products/239726/"
    "ishares-core-sp-500-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IVV_holdings&dataType=fund"
)

# State Street SPDR S&P 500 ETF (SPY) daily holdings — same index as IVV,
# served as a small .xlsx and (unlike iShares) not behind a bot wall.
SSGA_SPY_URL = (
    "https://www.ssga.com/us/en/intermediary/etfs/library-content/"
    "products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8",
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
        ssga_url: str = SSGA_SPY_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self._session = session or requests.Session()
        self._url = url
        self._ssga_url = ssga_url
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
        text = resp.text
        # Akamai Bot Manager serves the HTML product page (with a misleading
        # text/csv content-type) when it blocks the request. Fail fast — a
        # retry won't clear the block, and the SSGA fallback is waiting.
        if "Ticker," not in text and _looks_like_html(text):
            raise FetchError(
                "iShares IVV returned an HTML page instead of the holdings CSV "
                "(Akamai bot protection / rate-limit)."
            )
        return text

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _download_ssga(self) -> bytes:
        resp = self._session.get(self._ssga_url, headers=_HEADERS, timeout=self._timeout)
        resp.raise_for_status()
        # Same HTML-block defence as iShares, but here we can use magic bytes
        # since the payload is a binary .xlsx.
        if not is_excel_blob(resp.content):
            raise FetchError(
                "SSGA SPY returned a non-Excel body (likely an HTML block or "
                "maintenance page)."
            )
        return resp.content

    def _load_weights(self) -> dict[str, float]:
        """Get S&P 500 weights, trying iShares IVV then the SSGA SPY fallback."""
        try:
            return parse_ishares_holdings(self._download())
        except Exception as ivv_err:  # noqa: BLE001
            try:
                return parse_ssga_spy_holdings(self._download_ssga())
            except Exception as ssga_err:  # noqa: BLE001
                raise FetchError(
                    f"iShares IVV unavailable ({ivv_err}); "
                    f"SSGA SPY fallback also failed ({ssga_err})."
                ) from ssga_err

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        recipe = ISHARES_RECIPES.get(metric.source_ref)
        if recipe is None:
            raise FetchError(
                f"unknown ishares recipe {metric.source_ref!r}. "
                f"Known: {sorted(ISHARES_RECIPES)}"
            )

        weights = self._load_weights()
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
    weight_col = _pick_column(reader.fieldnames or [], (
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


def parse_ssga_spy_holdings(blob: bytes) -> dict[str, float]:
    """Extract {ticker: weight_percent} from a State Street SPDR SPY .xlsx.

    The SSGA file has a short metadata preamble (Fund Name, Ticker Symbol,
    "Holdings: As of …") before the real header row, which carries the
    columns `Name | Ticker | Identifier | SEDOL | Weight | Sector | …`. We
    locate that row by looking for one that holds both "Ticker" and
    "Weight", then read tickers and (already-percent) weights below it.
    Non-equity / placeholder rows are filtered the same way as the iShares
    parser.
    """
    if not is_excel_blob(blob):
        raise FetchError(
            "SSGA SPY payload was not an Excel file (likely an HTML block page)."
        )

    df = pd.read_excel(io.BytesIO(blob), engine="openpyxl", header=None)

    header_idx = None
    for i in range(min(15, len(df))):
        cells = {str(v).strip() for v in df.iloc[i].tolist()}
        if "Ticker" in cells and "Weight" in cells:
            header_idx = i
            break
    if header_idx is None:
        raise FetchError(
            "SSGA SPY: no 'Ticker'/'Weight' header row found in the holdings file."
        )

    header = [str(v).strip() for v in df.iloc[header_idx].tolist()]
    body = df.iloc[header_idx + 1:].copy()
    body.columns = header

    out: dict[str, float] = {}
    for _, row in body.iterrows():
        ticker = str(row.get("Ticker", "")).strip().upper()
        if ticker in ("", "NAN", "-") or not _looks_like_equity_ticker(ticker):
            continue
        weight = _parse_percent(str(row.get("Weight", "")))
        if weight is None or weight <= 0:
            continue
        out[ticker] = weight
    return out


def _looks_like_html(text: str) -> bool:
    """True if `text` opens with an HTML document (a bot-block / error page)."""
    head = text[:512].lstrip().lower()
    return (
        head.startswith("<!doctype")
        or head.startswith("<html")
        or "<head" in head
    )


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
