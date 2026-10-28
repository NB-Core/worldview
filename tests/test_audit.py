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
    db = Database(tmp_path / 'cap.db')
    db.init_schema()
    metrics = {m.id: m for m in load_metrics()}
    for mid in ('us_equity_market_cap', 'us_gdp'):
        db.upsert_metric(metrics[mid])
    assert _us_market_cap_div_gdp(db, date(2024, 1, 1)).empty
    idx = pd.to_datetime(['2024-01-01'])
    db.upsert_observations('us_equity_market_cap', pd.Series([50_000_000.], index=idx))
    db.upsert_observations('us_gdp', pd.Series([25_000.], index=idx))
    assert _us_market_cap_div_gdp(db, date(2024, 1, 1)).iloc[0] == 200


def test_recorded_history_uses_only_recorded_snapshots(tmp_path):
    from worldview.analysis.history import historical_overall_score
    from worldview.store import Database
    db = Database(tmp_path / 'recorded.db')
    db.init_schema()
    db.save_score_snapshot({'overall': {'valuation':20, 'sentiment':30, 'macro_risk':40}})
    result = historical_overall_score(db, {}, {}, {'valuation':.4, 'sentiment':.3, 'macro_risk':.3})
    assert result.iloc[-1].worldview_score == 71
