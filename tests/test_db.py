"""SQLite store: schema init, upserts, idempotency."""

from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import pytest

from worldview.models import Metric


def test_init_schema_is_idempotent(tmp_db):
    # Calling twice mustn't fail.
    tmp_db.init_schema()
    tmp_db.init_schema()


def test_upsert_metric_roundtrip(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)
    loaded = tmp_db.get_metric(sample_metric.id)
    assert loaded == sample_metric


def test_upsert_metric_updates_existing_row(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)

    edited = Metric(
        id=sample_metric.id,
        category=sample_metric.category,
        field=sample_metric.field,
        source=sample_metric.source,
        source_ref=sample_metric.source_ref,
        polarity=sample_metric.polarity,
        cadence=sample_metric.cadence,
        weight=2.5,                # changed
        flag_high_pct=95.0,        # changed
        flag_low_pct=sample_metric.flag_low_pct,
        notes="updated notes",     # changed
    )
    tmp_db.upsert_metric(edited)

    loaded = tmp_db.get_metric(sample_metric.id)
    assert loaded is not None
    assert loaded.weight == 2.5
    assert loaded.flag_high_pct == 95.0
    assert loaded.notes == "updated notes"

    # Still only one row.
    assert len(tmp_db.list_metrics()) == 1


def test_upsert_observations_idempotent(tmp_db, sample_metric, sample_series):
    tmp_db.upsert_metric(sample_metric)
    n1 = tmp_db.upsert_observations(sample_metric.id, sample_series)
    n2 = tmp_db.upsert_observations(sample_metric.id, sample_series)
    assert n1 == len(sample_series)
    assert n2 == len(sample_series)  # writes happen, but rows don't duplicate

    loaded = tmp_db.get_observations(sample_metric.id)
    assert len(loaded) == len(sample_series)


def test_upsert_observations_skips_nan_and_inf(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)
    s = pd.Series(
        [1.0, float("nan"), 3.0, float("inf"), 5.0],
        index=pd.to_datetime(
            ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04", "2020-01-05"]
        ),
    )
    n = tmp_db.upsert_observations(sample_metric.id, s)
    assert n == 3  # nan + inf dropped

    loaded = tmp_db.get_observations(sample_metric.id)
    assert list(loaded.values) == [1.0, 3.0, 5.0]


def test_get_observations_since(tmp_db, sample_metric, sample_series):
    tmp_db.upsert_metric(sample_metric)
    tmp_db.upsert_observations(sample_metric.id, sample_series)

    cutoff = date(2020, 2, 1)
    s = tmp_db.get_observations(sample_metric.id, since=cutoff)
    assert s.index.min().date() >= cutoff


def test_latest_value(tmp_db, sample_metric, sample_series):
    tmp_db.upsert_metric(sample_metric)
    tmp_db.upsert_observations(sample_metric.id, sample_series)

    latest = tmp_db.latest_value(sample_metric.id)
    assert latest is not None
    d, v = latest
    assert d == sample_series.index[-1].date()
    assert v == pytest.approx(float(sample_series.iloc[-1]))


def test_observation_requires_existing_metric(tmp_db, sample_series):
    # foreign-key violation if the metric isn't registered first
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.upsert_observations("nonexistent", sample_series)


def test_flags_table_roundtrip(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)
    tmp_db.write_flag(sample_metric.id, date(2024, 1, 5), "high", 92.5, 38.1)
    tmp_db.write_flag(sample_metric.id, date(2024, 1, 6), "high", 94.0, 39.5)
    flags = tmp_db.latest_flags()
    assert len(flags) == 1
    assert flags[0]["pct"] == 94.0
    assert flags[0]["date"] == "2024-01-06"


def test_flags_rejects_bad_side(tmp_db, sample_metric):
    tmp_db.upsert_metric(sample_metric)
    with pytest.raises(ValueError):
        tmp_db.write_flag(sample_metric.id, date(2024, 1, 5), "sideways", 50.0, 1.0)


def test_run_lifecycle(tmp_db):
    rid = tmp_db.start_run()
    assert rid > 0
    tmp_db.finish_run(rid, "ok", "everything fine")
    with tmp_db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (rid,)).fetchone()
    assert row["status"] == "ok"
    assert row["finished_at"] is not None


def test_run_finish_rejects_bad_status(tmp_db):
    rid = tmp_db.start_run()
    with pytest.raises(ValueError):
        tmp_db.finish_run(rid, "not-a-status")
