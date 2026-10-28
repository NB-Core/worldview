from datetime import date

import pandas as pd
import pytest

from worldview.analysis.composite import _oriented_pct, field_scores
from worldview.config import load_fields, load_metrics
from worldview.models import MetricScore


@pytest.mark.parametrize("mid", ["hy_oas_us", "ig_oas_us", "hy_minus_ig_oas", "eu_hy_oas"])
def test_credit_spread_direction_depends_on_block(mid):
    metric = {m.id: m for m in load_metrics()}[mid]
    assert _oriented_pct(metric, 90, "sentiment") == 10
    assert _oriented_pct(metric, 90, "macro_risk") == 90


def test_usd_chf_direction():
    metric = {m.id: m for m in load_metrics()}["chf_usd"]
    assert metric.source_ref == "CHF=X"
    assert _oriented_pct(metric, 10, "sentiment") == 10


def test_fundamental_direction():
    metrics = {m.id: m for m in load_metrics()}
    assert _oriented_pct(metrics["shiller_cape_us"], 90, "valuation") == 90
    assert _oriented_pct(metrics["sp500_div_yield"], 90, "valuation") == 10


def test_historical_credit_direction(tmp_path):
    from worldview.analysis.history import historical_overall_score
    from worldview.models import FieldDef
    from worldview.store import Database

    db = Database(tmp_path / "test.db")
    db.init_schema()
    m = {m.id: m for m in load_metrics()}["hy_oas_us"]
    db.upsert_metric(m)
    db.upsert_observations(
        m.id, pd.Series(range(101), index=pd.date_range("2024-01-01", periods=101))
    )
    fields = {"overall": FieldDef("overall", "Overall", [], [m.id], [m.id])}
    df = historical_overall_score(db, {m.id: m}, fields, {}, verified_only=False)
    assert df.iloc[-1].sentiment == 0
    assert df.iloc[-1].macro_risk == 100


@pytest.mark.parametrize(
    "val,sent,label",
    [
        (80, 49.9, "TRANSITION"),
        (80, 50.1, "TRANSITION"),
        (45, 10, "TRANSITION"),
        (55, 90, "TRANSITION"),
        (10, 10, "BUY"),
        (10, 90, "CAUTION"),
        (90, 10, "TRAP"),
        (90, 90, "BUBBLE"),
        (None, 10, "N/A"),
    ],
)
def test_regime_neutral_band(val, sent, label):
    from worldview.analysis.composite import regime

    assert regime(val, sent) == label


@pytest.mark.parametrize(
    "val,price_momentum,expected_value,expected_proxy",
    [
        (80, 30, 80, False),   # real valuation present -> never touch the proxy
        (None, 30, 30, True),  # no real valuation -> fall back to price_momentum
        (None, None, None, False),  # neither available -> stays N/A, not a false proxy
        (0, 99, 0, False),     # 0 is a legit valuation value, not falsy-None
    ],
)
def test_effective_valuation_fallback(val, price_momentum, expected_value, expected_proxy):
    from worldview.analysis.composite import effective_valuation

    value, is_proxy = effective_valuation(val, price_momentum)
    assert value == expected_value
    assert is_proxy is expected_proxy


def test_field_details_regime_uses_price_momentum_proxy_when_valuation_missing():
    """AI/Construction/Finance/Energy/Defense/Defensive have no fundamental
    valuation metrics (config/fields.yaml) post-audit, so field_scores(...)
    valuation stays None. field_details() must not leave the dashboard's
    regime tag permanently N/A for those fields -- it should fall back to the
    field's price_momentum percentile, and must say so via valuation_is_proxy.
    """
    from worldview.analysis.transparency import field_details
    from worldview.models import FieldDef

    metrics = {m.id: m for m in load_metrics()}
    # No valuation metrics configured (mirrors the real ai/finance/... fields),
    # but sentiment and price_momentum both have data.
    definition = FieldDef(
        "test", "Test", valuation=[], sentiment=["vix"], macro_risk=[], price_momentum=["smh"]
    )
    scores = {
        "vix": MetricScore("vix", date.today(), 10, 20, "Low"),
        "smh": MetricScore("smh", date.today(), 200, 90, "High"),
    }
    score = field_scores({"test": definition}, metrics, scores)["test"]
    assert score.valuation is None  # the honest, unchanged value

    details = field_details(definition, score, metrics, scores)
    assert details["valuation_is_proxy"] is True
    assert details["valuation_display"] == pytest.approx(90)
    # vix is "fearful" polarity: raw pct 20 flips to oriented sentiment 80 (greedy).
    # proxy valuation=90 (expensive) + sentiment=80 (greedy) -> BUBBLE, not N/A.
    assert score.sentiment == pytest.approx(80)
    assert details["regime"] == "BUBBLE"


def test_field_details_no_proxy_when_real_valuation_present():
    from worldview.analysis.transparency import field_details
    from worldview.models import FieldDef

    metrics = {m.id: m for m in load_metrics()}
    definition = FieldDef(
        "test", "Test", valuation=["shiller_cape_us"], sentiment=["vix"], macro_risk=[],
        price_momentum=["smh"],
    )
    scores = {
        "shiller_cape_us": MetricScore("shiller_cape_us", date.today(), 30, 70, "High"),
        "vix": MetricScore("vix", date.today(), 10, 20, "Low"),
        "smh": MetricScore("smh", date.today(), 200, 10, "Low"),
    }
    score = field_scores({"test": definition}, metrics, scores)["test"]
    details = field_details(definition, score, metrics, scores)
    assert details["valuation_is_proxy"] is False
    assert details["valuation_display"] == pytest.approx(score.valuation)


def test_quality_insufficient_stale_and_future():
    from worldview.analysis.scoring import score_metric

    metric = {m.id: m for m in load_metrics()}["vix"]
    idx = pd.date_range("2024-01-01", periods=100)
    history = pd.Series(range(100), index=idx, dtype=float)
    assert score_metric(metric, history.iloc[:1]) is None
    assert score_metric(metric, history.iloc[:20]) is None
    assert score_metric(metric, history, evaluation_date=date(2025, 1, 1)) is None
    before = score_metric(metric, history.iloc[:31], evaluation_date=date(2024, 1, 31))
    after = score_metric(metric, history, evaluation_date=date(2024, 1, 31))
    assert before == after
    assert after.asof == date(2024, 1, 31)


def test_strict_history_excludes_unverified_macro(tmp_path):
    from worldview.analysis.history import historical_overall_score
    from worldview.models import FieldDef
    from worldview.store import Database

    db = Database(tmp_path / "db.sqlite")
    db.init_schema()
    metric = {m.id: m for m in load_metrics()}["hy_oas_us"]
    db.upsert_metric(metric)
    db.upsert_observations(
        metric.id, pd.Series(range(100), index=pd.date_range("2024-01-01", periods=100))
    )
    fields = {"overall": FieldDef("overall", "Overall", [], [], [metric.id])}
    assert (
        historical_overall_score(db, {metric.id: metric}, fields, {})["macro_risk"].dropna().empty
    )


def test_new_valuation_excludes_prices_and_false_buffett():
    fields = load_fields()
    assert fields["finance"].valuation == []
    assert "xlf" in fields["finance"].price_momentum
    assert "buffett_indicator" not in fields["overall"].valuation
    assert "nvda_sp500_share" in fields["ai"].concentration


def test_snapshot_changes_do_not_invent_history(tmp_path):
    from worldview.store import Database

    db = Database(tmp_path / "db.sqlite")
    db.init_schema()
    assert db.score_changes({}, date.today()) == {"7": None, "14": None, "30": None}
    db.save_score_snapshot({"overall": {"valuation": None}})
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM score_snapshots").fetchone()[0] == 1


def test_contributions_reconcile():
    from worldview.analysis.transparency import field_details
    from worldview.models import FieldDef

    metrics = {m.id: m for m in load_metrics()}
    definition = FieldDef("test", "Test", [], ["hy_oas_us", "vix"], [])
    scores = {mid: MetricScore(mid, date.today(), 10, 90, "High") for mid in definition.sentiment}
    score = field_scores({"test": definition}, metrics, scores)["test"]
    block = field_details(definition, score, metrics, scores)["blocks"]["sentiment"]
    assert sum(c["contribution"] for c in block["contributors"]) == pytest.approx(score.sentiment)
    assert block["coverage"] == 1


def test_real_market_cap_gdp_units_and_no_fallback(tmp_path):
    from worldview.fetchers.derived import _us_market_cap_div_gdp
    from worldview.store import Database

    db = Database(tmp_path / "cap.db")
    db.init_schema()
    metrics = {m.id: m for m in load_metrics()}
    for mid in ("us_equity_market_cap", "us_gdp"):
        db.upsert_metric(metrics[mid])
    assert _us_market_cap_div_gdp(db, date(2024, 1, 1)).empty
    idx = pd.to_datetime(["2024-01-01"])
    db.upsert_observations("us_equity_market_cap", pd.Series([50_000_000.0], index=idx))
    db.upsert_observations("us_gdp", pd.Series([25_000.0], index=idx))
    assert _us_market_cap_div_gdp(db, date(2024, 1, 1)).iloc[0] == 200


def test_recorded_history_uses_only_recorded_snapshots(tmp_path):
    from worldview.analysis.history import historical_overall_score
    from worldview.store import Database

    db = Database(tmp_path / "recorded.db")
    db.init_schema()
    db.save_score_snapshot({"overall": {"valuation": 20, "sentiment": 30, "macro_risk": 40}})
    result = historical_overall_score(
        db, {}, {}, {"valuation": 0.4, "sentiment": 0.3, "macro_risk": 0.3}
    )
    assert result.iloc[-1].worldview_score == 71


def test_seven_day_worldview_and_regime_change(tmp_path):
    import json
    from datetime import timedelta

    from worldview.store import Database

    db = Database(tmp_path / "changes.db")
    db.init_schema()
    old = {
        "_worldview_score": 30,
        "overall": {"valuation": 80, "sentiment": 56, "macro_risk": 40, "regime": "BUBBLE"},
    }
    stamp = (date.today() - timedelta(days=7)).isoformat() + "T12:00:00+00:00"
    with db.connect() as conn:
        conn.execute("INSERT INTO score_snapshots VALUES (?, ?, ?)", (stamp, "v2", json.dumps(old)))
    current = {
        "overall": {"valuation": 80, "sentiment": 54, "macro_risk": 40, "regime": "TRANSITION"}
    }
    changes = db.score_changes(current, date.today(), 31)
    assert changes["7"]["worldview_delta"] == 1
    assert changes["7"]["fields"]["overall"]["previous_regime"] == "BUBBLE"
    assert changes["7"]["fields"]["overall"]["small_move"] is True
    assert changes["14"] is None
