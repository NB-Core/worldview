"""Smoke tests for the FastAPI dashboard.

Catches regressions like Starlette signature changes that wouldn't be caught
by the unit tests alone (the / route only blew up at request time, not at
import).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    """Boot the app against an empty tmp DB so it can't see real user data."""
    db_path = tmp_path / "wv.db"
    monkeypatch.setenv("WORLDVIEW_DB_PATH", str(db_path))
    # Make sure we read whatever metrics.yaml the project ships with — fine, it's read-only.
    from worldview import config as cfg
    cfg.cached_metrics.cache_clear()

    from worldview.webapp.main import app
    return TestClient(app)


def test_snapshot_route_returns_html_200(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Worldview" in r.text


def test_snapshot_json_returns_payload(client):
    r = client.get("/api/snapshot.json")
    assert r.status_code == 200
    body = r.json()
    # An empty DB still returns a well-formed payload.
    assert "fields" in body
    assert "metrics" in body
    assert "flags" in body
    assert isinstance(body["metrics"], list)


def test_unknown_metric_route_404s(client):
    r = client.get("/metric/does_not_exist_anywhere")
    assert r.status_code == 404


def test_unknown_metric_json_404s(client):
    r = client.get("/api/metric/does_not_exist_anywhere.json")
    assert r.status_code == 404


def test_history_route_returns_html_200(client):
    r = client.get("/history")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Worldview Score" in r.text


def test_history_json_empty_db_returns_well_formed_payload(client):
    r = client.get("/api/history.json")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "dates", "valuation", "sentiment", "macro_risk", "worldview_score"
    }
    # Empty DB → empty arrays.
    assert body["dates"] == []
    assert body["worldview_score"] == []


def test_prices_json_returns_only_known_metrics(client):
    """Empty DB → empty `series` array. Unknown ids silently dropped."""
    r = client.get("/api/prices.json?ids=sp500_close,nasdaq_close,not_a_real_id")
    assert r.status_code == 200
    body = r.json()
    assert "series" in body
    assert isinstance(body["series"], list)
    # Empty DB so even known ids have no observations.
    assert body["series"] == []


def test_prices_json_with_seeded_observations(client, tmp_path, monkeypatch):
    """Seed a known metric and confirm /api/prices.json returns its values."""
    import pandas as pd

    from worldview.config import load_metrics
    from worldview.store import Database

    db = Database(tmp_path / "wv.db")
    db.init_schema()
    sp500 = next(m for m in load_metrics() if m.id == "sp500_close")
    db.upsert_metric(sp500)
    db.upsert_observations(
        "sp500_close",
        pd.Series(
            [4500.0, 4520.0, 4480.0],
            index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        ),
    )

    r = client.get("/api/prices.json?ids=sp500_close")
    assert r.status_code == 200
    series = r.json()["series"]
    assert len(series) == 1
    s = series[0]
    assert s["id"] == "sp500_close"
    assert "S&P 500" in s["label"]
    assert s["values"] == [4500.0, 4520.0, 4480.0]


def test_snapshot_payload_includes_field_contributors(client):
    body = client.get("/api/snapshot.json").json()
    assert "field_contributors" in body
    contribs = body["field_contributors"]
    # every field in fields.yaml should be present as a key
    assert "overall" in contribs
    assert set(contribs["overall"].keys()) == {"valuation", "sentiment", "macro_risk"}
