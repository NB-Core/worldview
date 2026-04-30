"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from worldview.models import Cadence, Category, Metric, Polarity
from worldview.store import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """A fresh, schema-applied SQLite database in a tmp dir."""
    db = Database(tmp_path / "test.db")
    db.init_schema()
    return db


@pytest.fixture
def sample_metric() -> Metric:
    return Metric(
        id="vix",
        category=Category.SENTIMENT,
        field="overall",
        source="yfinance",
        source_ref="^VIX",
        polarity=Polarity.FEARFUL,
        cadence=Cadence.DAILY,
        weight=1.0,
        flag_high_pct=90.0,
        flag_low_pct=10.0,
        notes="implied vol",
    )


@pytest.fixture
def sample_series() -> pd.Series:
    """100 daily values: a steady ramp from 10 → 30."""
    start = date(2020, 1, 1)
    idx = pd.to_datetime([start + timedelta(days=i) for i in range(100)])
    values = [10.0 + i * 0.2 for i in range(100)]
    return pd.Series(values, index=idx, name="vix")
