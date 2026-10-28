"""Tests for AAII, NAAIM, and SlickCharts fetchers."""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pandas as pd
import pytest
import responses

from worldview.fetchers import FetchError
from worldview.fetchers.aaii import AAII_URL, AAIIFetcher
from worldview.fetchers.ishares import (
    ISHARES_RECIPES,
    IVV_URL,
    ISharesFetcher,
    parse_ishares_holdings,
)
from worldview.fetchers.naaim import INDEX_PAGE as NAAIM_INDEX_PAGE
from worldview.fetchers.naaim import NAAIMFetcher
from worldview.models import Cadence, Category, Metric, Polarity


def _metric(source: str, ref: str = "", mid: str = "test") -> Metric:
    return Metric(
        id=mid,
        category=Category.SENTIMENT,
        field="overall",
        source=source,
        source_ref=ref,
        polarity=Polarity.GREEDY,
        cadence=Cadence.WEEKLY,
    )


# ── AAII ─────────────────────────────────────────────────────────────────────

def _make_aaii_xlsx(rows: list[tuple[str, float, float]]) -> bytes:
    """Build a small xlsx mimicking AAII's weekly survey layout.

    Columns: Reported Date | Bullish | Bearish (we ignore Neutral here).
    Values in 0..100 percentage points.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    # AAII files often have a couple of title rows; emulate that.
    ws.append(["AAII Sentiment Survey", "", ""])
    ws.append(["", "", ""])
    ws.append(["Reported Date", "Bullish", "Bearish"])
    for d, bull, bear in rows:
        ws.append([d, bull, bear])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@responses.activate
def test_aaii_returns_bull_minus_bear_spread():
    blob = _make_aaii_xlsx([
        ("2024-01-04", 35.0, 30.0),   # spread = +5
        ("2024-01-11", 28.0, 40.0),   # spread = -12
        ("2024-01-18", 50.0, 25.0),   # spread = +25
    ])
    responses.add(responses.GET, AAII_URL, body=blob, status=200)
    s = AAIIFetcher().fetch(_metric("aaii"), date(2024, 1, 1))
    assert list(s.values) == [5.0, -12.0, 25.0]
    assert s.index[0] == pd.Timestamp("2024-01-04")


@responses.activate
def test_aaii_handles_fractional_input():
    """If columns ship 0..1 fractions, we promote to 0..100."""
    blob = _make_aaii_xlsx([("2024-01-04", 0.40, 0.20)])  # spread = 0.20 → 20%
    responses.add(responses.GET, AAII_URL, body=blob, status=200)
    s = AAIIFetcher().fetch(_metric("aaii"), date(2024, 1, 1))
    assert s.iloc[0] == pytest.approx(20.0)


@responses.activate
def test_aaii_raises_on_missing_columns():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Wrong", "Columns"])
    ws.append(["x", "y"])
    out = io.BytesIO()
    wb.save(out)
    responses.add(responses.GET, AAII_URL, body=out.getvalue(), status=200)
    with pytest.raises(FetchError):
        AAIIFetcher().fetch(_metric("aaii"), date(2024, 1, 1))


@responses.activate
def test_aaii_translates_http_error():
    responses.add(responses.GET, AAII_URL, status=503)
    with pytest.raises(FetchError):
        AAIIFetcher().fetch(_metric("aaii"), date(2024, 1, 1))


@responses.activate
def test_aaii_html_body_triggers_retry_then_clean_error():
    """200 OK with HTML body (rate-limit page) should retry and ultimately fail
    with a real FetchError, not a confusing 'Expected BOF record' parser crash."""
    # Same URL gets called multiple times; responses replays the registered
    # body for each call. After all retries the fetcher must still surface
    # FetchError with a clear cause — not a binascii / Excel parse error.
    responses.add(
        responses.GET, AAII_URL,
        body="<!DOCTYPE html><html><body>rate limited</body></html>",
        status=200, content_type="text/html",
    )
    with pytest.raises(FetchError):
        AAIIFetcher().fetch(_metric("aaii"), date(2024, 1, 1))


# ── NAAIM ────────────────────────────────────────────────────────────────────

def _make_naaim_xlsx(rows: list[tuple[str, float]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Date", "NAAIM Number Mean", "Bullish 8 wk Mov Avg"])
    for d, mean in rows:
        ws.append([d, mean, mean - 1])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@responses.activate
def test_naaim_extracts_mean_column():
    """Empty source_ref → fetcher scrapes the index page for the live .xlsx link."""
    xlsx_url = "https://www.naaim.org/wp-content/uploads/2024/03/naaim-exposure-index-data.xlsx"
    page_html = f'<html>... <a href="{xlsx_url}">Download Data</a> ...</html>'
    responses.add(responses.GET, NAAIM_INDEX_PAGE, body=page_html, status=200)
    blob = _make_naaim_xlsx([
        ("2024-01-03", 65.5),
        ("2024-01-10", 72.1),
        ("2024-01-17", 80.4),
    ])
    responses.add(responses.GET, xlsx_url, body=blob, status=200)
    s = NAAIMFetcher().fetch(_metric("naaim"), date(2024, 1, 1))
    assert list(s.values) == [65.5, 72.1, 80.4]


@responses.activate
def test_naaim_raises_when_index_page_has_no_xlsx_link():
    responses.add(responses.GET, NAAIM_INDEX_PAGE, body="<html>nothing here</html>", status=200)
    with pytest.raises(FetchError, match="contained no .xlsx link"):
        NAAIMFetcher().fetch(_metric("naaim"), date(2024, 1, 1))


@responses.activate
def test_naaim_uses_explicit_url_override():
    custom = "https://example.test/naaim.xlsx"
    blob = _make_naaim_xlsx([("2024-01-10", 55.0)])
    responses.add(responses.GET, custom, body=blob, status=200)
    s = NAAIMFetcher().fetch(_metric("naaim", custom), date(2024, 1, 1))
    assert list(s.values) == [55.0]


# ── iShares IVV ──────────────────────────────────────────────────────────────

# A realistic-shaped iShares IVV holdings CSV — multi-line preamble, then the
# Ticker,Name,...,Weight (%),... header, then rows. Includes a cash row to
# verify it gets filtered out.
_IVV_CSV = """\
Fund Holdings as of,"Apr 28, 2026"
Inception Date,"May 15, 2000"
Shares Outstanding,"926,500,000"
Stock,-,-

Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date
NVDA,NVIDIA CORP,Information Technology,Equity,"123,456,789","7.20","123,456,789","100","900.00",United States,NASDAQ,USD,1.00,USD,-
MSFT,MICROSOFT CORP,Information Technology,Equity,"100","6.10","100","100","410.00",United States,NASDAQ,USD,1.00,USD,-
AAPL,APPLE INC,Information Technology,Equity,"100","5.50","100","100","180.00",United States,NASDAQ,USD,1.00,USD,-
AMZN,AMAZON COM INC,Consumer Discretionary,Equity,"100","4.20","100","100","185.00",United States,NASDAQ,USD,1.00,USD,-
META,META PLATFORMS INC CLASS A,Communication,Equity,"100","2.50","100","100","500.00",United States,NASDAQ,USD,1.00,USD,-
GOOGL,ALPHABET INC CLASS A,Communication,Equity,"100","2.30","100","100","175.00",United States,NASDAQ,USD,1.00,USD,-
GOOG,ALPHABET INC CLASS C,Communication,Equity,"100","2.00","100","100","175.00",United States,NASDAQ,USD,1.00,USD,-
TSLA,TESLA INC,Consumer Discretionary,Equity,"100","1.80","100","100","180.00",United States,NASDAQ,USD,1.00,USD,-
BRK.B,BERKSHIRE HATHAWAY INC CLASS B,Financials,Equity,"100","1.50","100","100","440.00",United States,NYSE,USD,1.00,USD,-
JPM,JPMORGAN CHASE & CO,Financials,Equity,"100","1.40","100","100","200.00",United States,NYSE,USD,1.00,USD,-
LLY,ELI LILLY,Health Care,Equity,"100","1.30","100","100","800.00",United States,NYSE,USD,1.00,USD,-
USD,USD CASH,-,Cash,"5,000","0.05","5,000","5000","1.00",United States,-,USD,1.00,USD,-
"""


@responses.activate
def test_ishares_top_10_share():
    responses.add(responses.GET, IVV_URL, body=_IVV_CSV, status=200,
                  content_type="text/csv")
    s = ISharesFetcher().fetch(_metric("ishares", "top_10_share"), date(2008, 1, 1))
    # top 10 equity weights (cash filtered): 7.2+6.1+5.5+4.2+2.5+2.3+2.0+1.8+1.5+1.4 = 34.5
    assert s.iloc[0] == pytest.approx(34.5)
    assert len(s) == 1


@responses.activate
def test_ishares_top_5_share():
    responses.add(responses.GET, IVV_URL, body=_IVV_CSV, status=200)
    s = ISharesFetcher().fetch(_metric("ishares", "top_5_share"), date(2008, 1, 1))
    # NVDA(7.2) + MSFT(6.1) + AAPL(5.5) + AMZN(4.2) + META(2.5) = 25.5
    assert s.iloc[0] == pytest.approx(25.5)


@responses.activate
def test_ishares_mag7_share_includes_both_alphabet_classes():
    responses.add(responses.GET, IVV_URL, body=_IVV_CSV, status=200)
    s = ISharesFetcher().fetch(_metric("ishares", "mag7_share"), date(2008, 1, 1))
    # NVDA + MSFT + GOOGL + GOOG + AMZN + META + AAPL + TSLA = 7.2+6.1+2.3+2.0+4.2+2.5+5.5+1.8 = 31.6
    assert s.iloc[0] == pytest.approx(31.6)


@responses.activate
def test_ishares_nvda_share():
    responses.add(responses.GET, IVV_URL, body=_IVV_CSV, status=200)
    s = ISharesFetcher().fetch(_metric("ishares", "nvda_share"), date(2008, 1, 1))
    assert s.iloc[0] == pytest.approx(7.2)


def test_ishares_parser_filters_cash_rows():
    weights = parse_ishares_holdings(_IVV_CSV)
    assert "USD" not in weights, "cash row must be filtered"
    assert "NVDA" in weights
    assert weights["NVDA"] == pytest.approx(7.2)


@responses.activate
def test_ishares_unknown_recipe_raises():
    responses.add(responses.GET, IVV_URL, body=_IVV_CSV, status=200)
    with pytest.raises(FetchError, match="unknown ishares recipe"):
        ISharesFetcher().fetch(_metric("ishares", "not_a_real_recipe"), date(2008, 1, 1))


@responses.activate
def test_ishares_translates_http_error():
    responses.add(responses.GET, IVV_URL, status=403)
    with pytest.raises(FetchError):
        ISharesFetcher().fetch(_metric("ishares", "top_10_share"), date(2008, 1, 1))


@responses.activate
def test_ishares_raises_when_header_missing():
    bad_csv = "Fund Holdings as of,2026-04-28\n\nFoo,Bar,Baz\nNVDA,100,7.2\n"
    responses.add(responses.GET, IVV_URL, body=bad_csv, status=200)
    with pytest.raises(FetchError, match="no `Ticker,` header"):
        ISharesFetcher().fetch(_metric("ishares", "nvda_share"), date(2008, 1, 1))


def test_ishares_recipes_all_referenced_in_yaml():
    from worldview.config import load_metrics
    ish_metrics = [m for m in load_metrics() if m.source == "ishares"]
    assert ish_metrics, "expected at least one ishares metric in metrics.yaml"
    for m in ish_metrics:
        assert m.source_ref in ISHARES_RECIPES, (
            f"{m.id} references unknown recipe {m.source_ref!r}"
        )
