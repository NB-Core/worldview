"""Tests for Milestone-2 fetchers: CNN F&G, GPR daily, multpl, derived ratios."""

from __future__ import annotations

import io
from datetime import date

import openpyxl
import pandas as pd
import pytest
import responses

from worldview.fetchers import FetchError
from worldview.fetchers.cnn_fng import ENDPOINT as CNN_ENDPOINT
from worldview.fetchers.cnn_fng import CNNFearGreedFetcher
from worldview.fetchers.derived import RECIPES, DerivedFetcher
from worldview.fetchers.gpr_iacoviello import GPR_URL, GPRDailyFetcher
from worldview.fetchers.multpl import BASE_URL as MULTPL_BASE
from worldview.fetchers.multpl import MultplFetcher
from worldview.models import Cadence, Category, Metric, Polarity


def _metric(source: str, ref: str, mid: str = "test") -> Metric:
    return Metric(
        id=mid,
        category=Category.SENTIMENT,
        field="overall",
        source=source,
        source_ref=ref,
        polarity=Polarity.GREEDY,
        cadence=Cadence.DAILY,
    )


# ── CNN Fear & Greed ──────────────────────────────────────────────────────────

@responses.activate
def test_cnn_fng_parses_historical_payload():
    payload = {
        "fear_and_greed": {"score": 35.4, "rating": "fear"},
        "fear_and_greed_historical": {
            "data": [
                {"x": 1704067200000, "y": 33.7, "rating": "fear"},     # 2024-01-01
                {"x": 1704153600000, "y": 31.0, "rating": "fear"},     # 2024-01-02
                {"x": 1704240000000, "y": 29.5, "rating": "fear"},     # 2024-01-03
            ]
        },
    }
    responses.add(responses.GET, CNN_ENDPOINT, json=payload, status=200)

    fetcher = CNNFearGreedFetcher()
    s = fetcher.fetch(_metric("cnn_fng", "default"), date(2024, 1, 1))

    assert list(s.values) == [33.7, 31.0, 29.5]
    assert s.index[0] == pd.Timestamp("2024-01-01")
    assert s.name == "test"


@responses.activate
def test_cnn_fng_filters_by_start_date():
    payload = {
        "fear_and_greed_historical": {
            "data": [
                {"x": 1672531200000, "y": 60.0},   # 2023-01-01 (excluded)
                {"x": 1704067200000, "y": 33.7},   # 2024-01-01 (kept)
            ]
        },
    }
    responses.add(responses.GET, CNN_ENDPOINT, json=payload, status=200)
    s = CNNFearGreedFetcher().fetch(_metric("cnn_fng", "x"), date(2024, 1, 1))
    assert len(s) == 1
    assert s.iloc[0] == 33.7


@responses.activate
def test_cnn_fng_translates_http_error():
    responses.add(responses.GET, CNN_ENDPOINT, status=503)
    with pytest.raises(FetchError):
        CNNFearGreedFetcher().fetch(_metric("cnn_fng", "x"), date(2024, 1, 1))


@responses.activate
def test_cnn_fng_handles_missing_keys():
    responses.add(responses.GET, CNN_ENDPOINT, json={"unexpected": "shape"}, status=200)
    with pytest.raises(FetchError, match="missing expected keys"):
        CNNFearGreedFetcher().fetch(_metric("cnn_fng", "x"), date(2024, 1, 1))


# ── GPR (Iacoviello) ─────────────────────────────────────────────────────────

def _make_gpr_xlsx(rows: list[tuple[str, float]]) -> bytes:
    """Build an in-memory xlsx mimicking the Iacoviello GPR daily layout."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DATE", "GPRD", "GPRD_THREATS", "GPRD_ACT"])
    for d, v in rows:
        ws.append([d, v, v - 1, v - 2])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@responses.activate
def test_gpr_parses_excel_and_extracts_gprd_column():
    blob = _make_gpr_xlsx(
        [("2024-01-01", 110.0), ("2024-01-02", 130.5), ("2024-01-03", 99.0)]
    )
    responses.add(responses.GET, GPR_URL, body=blob, status=200,
                  content_type="application/octet-stream")

    s = GPRDailyFetcher().fetch(_metric("gpr_iacoviello", ""), date(2024, 1, 1))
    assert list(s.values) == [110.0, 130.5, 99.0]
    assert s.index[1] == pd.Timestamp("2024-01-02")


@responses.activate
def test_gpr_raises_on_missing_columns():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["wrong_col_a", "wrong_col_b"])
    ws.append(["x", "y"])
    out = io.BytesIO()
    wb.save(out)

    responses.add(responses.GET, GPR_URL, body=out.getvalue(), status=200)
    with pytest.raises(FetchError, match="missing expected columns"):
        GPRDailyFetcher().fetch(_metric("gpr_iacoviello", ""), date(2024, 1, 1))


@responses.activate
def test_gpr_translates_http_error():
    responses.add(responses.GET, GPR_URL, status=500)
    with pytest.raises(FetchError):
        GPRDailyFetcher().fetch(_metric("gpr_iacoviello", ""), date(2024, 1, 1))


# ── multpl ────────────────────────────────────────────────────────────────────

_MULTPL_HTML = """
<html><body>
  <table id="datatable">
    <thead><tr><th>Date</th><th>Value</th></tr></thead>
    <tbody>
      <tr><td>Aug 1, 2024</td><td>28.45</td></tr>
      <tr><td>Jul 1, 2024</td><td>27.10</td></tr>
      <tr><td>Jun 1, 2024</td><td>26.80</td></tr>
      <tr><td>—</td><td>—</td></tr>
      <tr><td>May 1, 2024</td><td>26.05x</td></tr>
    </tbody>
  </table>
</body></html>
"""


@responses.activate
def test_multpl_parses_history_table():
    # The fetcher rewrites bare slugs to /<slug>/table/by-month — that's
    # the URL the test must mock.
    url = f"{MULTPL_BASE}/s-p-500-pe-ratio/table/by-month"
    responses.add(responses.GET, url, body=_MULTPL_HTML, status=200,
                  content_type="text/html")

    s = MultplFetcher().fetch(
        _metric("multpl", "s-p-500-pe-ratio"), date(2024, 1, 1)
    )
    # rows are: Aug→28.45, Jul→27.10, Jun→26.80, May→26.05 (the "x" suffix is stripped)
    assert sorted(s.values.tolist()) == [26.05, 26.8, 27.1, 28.45]
    assert s.index.is_monotonic_increasing


@responses.activate
def test_multpl_returns_empty_when_table_has_only_dashes():
    html = '<table id="datatable"><tr><td>—</td><td>—</td></tr></table>'
    url = f"{MULTPL_BASE}/foo/table/by-month"
    responses.add(responses.GET, url, body=html, status=200)
    s = MultplFetcher().fetch(_metric("multpl", "foo"), date(2024, 1, 1))
    assert s.empty


@responses.activate
def test_multpl_translates_http_error():
    url = f"{MULTPL_BASE}/foo/table/by-month"
    responses.add(responses.GET, url, status=404)
    with pytest.raises(FetchError):
        MultplFetcher().fetch(_metric("multpl", "foo"), date(2024, 1, 1))


@responses.activate
def test_multpl_respects_explicit_table_path():
    """If source_ref already contains /table, fetcher should NOT double-append."""
    url = f"{MULTPL_BASE}/foo/table"
    responses.add(responses.GET, url, body=_MULTPL_HTML, status=200)
    s = MultplFetcher().fetch(_metric("multpl", "foo/table"), date(2024, 1, 1))
    assert not s.empty


# ── DerivedFetcher ────────────────────────────────────────────────────────────

def test_derived_ratio_computes_from_db(tmp_db, sample_metric):
    """Construct two raw series in the DB, then derive their ratio."""
    # Build two metrics: numerator "xlk" and denominator "xlu".
    from worldview.models import Cadence, Category, Metric, Polarity

    xlk = Metric(id="xlk", category=Category.SENTIMENT, field="ai",
                 source="yfinance", source_ref="XLK", polarity=Polarity.GREEDY,
                 cadence=Cadence.DAILY)
    xlu = Metric(id="xlu", category=Category.SENTIMENT, field="defensive",
                 source="yfinance", source_ref="XLU", polarity=Polarity.GREEDY,
                 cadence=Cadence.DAILY)
    tmp_db.upsert_metric(xlk)
    tmp_db.upsert_metric(xlu)

    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    tmp_db.upsert_observations("xlk", pd.Series([200.0, 220.0, 240.0], index=idx))
    tmp_db.upsert_observations("xlu", pd.Series([100.0, 100.0, 120.0], index=idx))

    # The recipe lookup is by source_ref:
    derived = DerivedFetcher(tmp_db)
    metric = Metric(id="xlk_xlu_ratio", category=Category.SENTIMENT, field="ai",
                    source="derived", source_ref="xlk_div_xlu",
                    polarity=Polarity.GREEDY, cadence=Cadence.DAILY)
    s = derived.fetch(metric, date(2024, 1, 1))

    assert list(s.values) == pytest.approx([2.0, 2.2, 2.0])


def test_derived_unknown_recipe_raises(tmp_db):
    derived = DerivedFetcher(tmp_db)
    bad = _metric("derived", "not_a_real_recipe", mid="bogus")
    with pytest.raises(FetchError, match="unknown derived recipe"):
        derived.fetch(bad, date(2024, 1, 1))


def test_recipes_registered():
    """Sanity: every metric in metrics.yaml using source=derived has a recipe."""
    from worldview.config import load_metrics
    derived_metrics = [m for m in load_metrics() if m.source == "derived"]
    assert derived_metrics, "expected at least one derived metric in metrics.yaml"
    for m in derived_metrics:
        assert m.source_ref in RECIPES, (
            f"{m.id} → recipe {m.source_ref!r} not in RECIPES"
        )
