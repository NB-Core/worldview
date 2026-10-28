from datetime import date

import pandas as pd
import pytest

from worldview.analysis.composite import _oriented_pct, field_scores
from worldview.config import load_fields, load_metrics
from worldview.models import MetricScore


@pytest.mark.parametrize('mid', ['hy_oas_us', 'ig_oas_us', 'hy_minus_ig_oas', 'eu_hy_oas'])
def test_credit_spread_direction_depends_on_block(mid):
    metric = {m.id: m for m in load_metrics()}[mid]
    assert _oriented_pct(metric, 90, 'sentiment') == 10
    assert _oriented_pct(metric, 90, 'macro_risk') == 90


def test_usd_chf_direction():
    metric = {m.id: m for m in load_metrics()}['chf_usd']
    assert metric.source_ref == 'CHF=X'
    assert _oriented_pct(metric, 10, 'sentiment') == 10


def test_fundamental_direction():
    metrics = {m.id: m for m in load_metrics()}
    assert _oriented_pct(metrics['shiller_cape_us'], 90, 'valuation') == 90
    assert _oriented_pct(metrics['sp500_div_yield'], 90, 'valuation') == 10


def test_historical_credit_direction(tmp_path):
    from worldview.analysis.history import historical_overall_score
    from worldview.models import FieldDef
    from worldview.store import Database
    db = Database(tmp_path / 'test.db')
    db.init_schema()
    m = {m.id: m for m in load_metrics()}['hy_oas_us']
    db.upsert_metric(m)
    db.upsert_observations(m.id, pd.Series(range(101), index=pd.date_range('2024-01-01', periods=101)))
    fields = {'overall': FieldDef('overall', 'Overall', [], [m.id], [m.id])}
    df = historical_overall_score(db, {m.id: m}, fields, {})
    assert df.iloc[-1].sentiment == 0
    assert df.iloc[-1].macro_risk == 100
