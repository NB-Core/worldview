"""End-to-end snapshot pipeline test with mocked fetchers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from worldview.fetchers import FetcherRegistry
from worldview.fetchers.base import Fetcher
from worldview.models import Metric
from worldview.snapshot import run_snapshot
from worldview.store import Database


class _CannedFetcher(Fetcher):
    """Returns a configurable Series no matter what is asked of it."""

    source_name = "canned"

    def __init__(self, series: pd.Series):
        self._series = series

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        s = self._series.copy()
        s.name = metric.id
        return s


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch):
    """Point both the DB and the config at a tmp dir so the test can't see the user's data."""
    db_path = tmp_path / "wv.db"
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()

    (cfg_dir / "metrics.yaml").write_text(
        """
metrics:
  - id: cape
    category: valuation
    field: overall
    source: canned
    source_ref: TEST_CAPE
    polarity: expensive
    cadence: daily
    flag_high_pct: 90
    flag_low_pct: 10
  - id: vix
    category: sentiment
    field: overall
    source: canned
    source_ref: TEST_VIX
    polarity: fearful
    cadence: daily
    flag_high_pct: 90
    flag_low_pct: 10
"""
    )
    (cfg_dir / "fields.yaml").write_text(
        """
fields:
  overall:
    label: "Overall"
    valuation: [cape]
    sentiment: [vix]
    macro_risk: []
worldview_score_weights:
  valuation: 0.5
  sentiment: 0.3
  macro_risk: 0.2
"""
    )

    monkeypatch.setenv("WORLDVIEW_DB_PATH", str(db_path))
    monkeypatch.setenv("WORLDVIEW_CONFIG_DIR", str(cfg_dir))

    # `cached_metrics` may have been hit by other tests in this session; clear it.
    from worldview import config as cfg
    cfg.cached_metrics.cache_clear()

    return db_path, cfg_dir


def _ramp(name: str, last_value: float | None = None) -> pd.Series:
    idx = pd.to_datetime(pd.date_range(end=date.today(), periods=100, freq="D"))
    values = [float(i) for i in range(100)]
    if last_value is not None:
        values[-1] = last_value
    return pd.Series(values, index=idx, name=name)


def test_run_snapshot_end_to_end(isolated_env):
    """Snapshot runs cleanly, persists, scores, and returns sane values."""
    db_path, _ = isolated_env

    registry = FetcherRegistry()
    registry.register("canned", _CannedFetcher(_ramp("x")))

    result = run_snapshot(cadence="daily", db=Database(db_path), registry=registry)

    assert result.fetched > 0
    assert "cape" in result.scores
    assert "vix" in result.scores

    # Latest value of a 0..99 ramp = 99 → 100th percentile of 0..98
    assert result.scores["cape"].percentile == 100.0
    assert result.scores["cape"].flagged_high

    overall = result.fields["overall"]
    # cape (expensive) at 100 → valuation 100; vix (fearful) at 100 → sentiment 0
    assert overall.valuation == pytest.approx(100.0)
    assert overall.sentiment == pytest.approx(0.0)
    assert overall.quadrant == "TRAP"
    # worldview_score = 0*0.5 + (100 - 2*|0-50|)*0.3 + ... but macro_risk is None → score is None
    # Our composite returns None when any block is missing — that's the contract.
    assert result.worldview is None


def test_run_snapshot_persists_to_db_and_writes_flags(isolated_env):
    db_path, _ = isolated_env
    registry = FetcherRegistry()
    registry.register("canned", _CannedFetcher(_ramp("x")))

    run_snapshot(cadence="daily", db=Database(db_path), registry=registry)

    db = Database(db_path)
    assert db.latest_value("cape") is not None
    assert db.latest_value("vix") is not None

    flags = db.latest_flags()
    flagged_ids = {f["metric_id"] for f in flags}
    assert "cape" in flagged_ids  # high
    assert "vix" in flagged_ids   # also high (90+) on this ramp


def test_run_snapshot_handles_partial_failure(isolated_env, monkeypatch):
    """If a single fetch raises, others still complete and the run is 'partial'."""
    db_path, _ = isolated_env

    class _PartiallyBroken(Fetcher):
        source_name = "canned"
        calls = 0

        def fetch(self, metric, start):
            type(self).calls += 1
            if metric.id == "vix":
                from worldview.fetchers.base import FetchError
                raise FetchError("simulated network failure")
            return _ramp(metric.id)

    registry = FetcherRegistry()
    registry.register("canned", _PartiallyBroken())

    result = run_snapshot(cadence="daily", db=Database(db_path), registry=registry)
    assert "vix" in result.failed
    assert "cape" in result.scores
    # vix had no data this run, so it's missing from scores
    assert "vix" not in result.scores


def test_run_snapshot_only_filter(isolated_env):
    db_path, _ = isolated_env
    registry = FetcherRegistry()
    registry.register("canned", _CannedFetcher(_ramp("x")))

    result = run_snapshot(
        cadence="daily",
        only=["cape"],
        db=Database(db_path),
        registry=registry,
    )
    # Only "cape" was fetched, but the post-fetch scoring re-reads the DB and
    # both metrics get scored if they happen to have data — vix won't here.
    assert "cape" in result.scores
    assert "vix" not in result.scores


def test_run_snapshot_skips_unwired_source_without_failing(tmp_path, monkeypatch):
    """Metrics with a `source:` that has no fetcher should land in `skipped`, not `failed`."""
    db_path = tmp_path / "wv.db"
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "metrics.yaml").write_text(
        """
metrics:
  - id: cape
    category: valuation
    field: overall
    source: canned
    source_ref: TEST_CAPE
    polarity: expensive
    cadence: daily
  - id: gpr_daily
    category: geo
    field: overall
    source: csv
    source_ref: "https://example.test/gpr.csv"
    polarity: stressed
    cadence: daily
"""
    )
    (cfg_dir / "fields.yaml").write_text(
        "fields:\n  overall:\n    label: Overall\n    valuation: [cape]\n    sentiment: []\n    macro_risk: []\n"
    )
    monkeypatch.setenv("WORLDVIEW_DB_PATH", str(db_path))
    monkeypatch.setenv("WORLDVIEW_CONFIG_DIR", str(cfg_dir))
    from worldview import config as cfg
    cfg.cached_metrics.cache_clear()

    registry = FetcherRegistry()
    registry.register("canned", _CannedFetcher(_ramp("x")))
    # NOTE: deliberately do NOT register "csv".

    result = run_snapshot(cadence="daily", db=Database(db_path), registry=registry)

    assert "gpr_daily" in result.skipped
    assert "gpr_daily" not in result.failed
    assert "cape" in result.scores                    # the wired metric still runs cleanly
    assert result.fetched > 0
