"""YAML loading + validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from worldview.config import load_fields, load_metrics, load_score_weights
from worldview.models import Cadence, Category, Polarity


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_load_metrics_basic(tmp_path):
    p = _write(tmp_path, "metrics.yaml", """
metrics:
  - id: vix
    category: sentiment
    field: overall
    source: yfinance
    source_ref: "^VIX"
    polarity: fearful
    cadence: daily
    flag_high_pct: 90
    flag_low_pct: 10
    weight: 1.5
    notes: implied vol
""")
    metrics = load_metrics(p)
    assert len(metrics) == 1
    m = metrics[0]
    assert m.id == "vix"
    assert m.category == Category.SENTIMENT
    assert m.polarity == Polarity.FEARFUL
    assert m.cadence == Cadence.DAILY
    assert m.flag_high_pct == 90
    assert m.weight == 1.5


def test_load_metrics_rejects_unknown_enum(tmp_path):
    p = _write(tmp_path, "metrics.yaml", """
metrics:
  - id: vix
    category: not_a_category
    field: overall
    source: yfinance
    source_ref: "^VIX"
    polarity: fearful
    cadence: daily
""")
    with pytest.raises(ValueError):
        load_metrics(p)


def test_load_metrics_rejects_missing_field(tmp_path):
    p = _write(tmp_path, "metrics.yaml", """
metrics:
  - id: vix
    source: yfinance
""")
    with pytest.raises(ValueError, match="missing required key"):
        load_metrics(p)


def test_load_metrics_detects_duplicate_id(tmp_path):
    p = _write(tmp_path, "metrics.yaml", """
metrics:
  - id: vix
    category: sentiment
    field: overall
    source: yfinance
    source_ref: "^VIX"
    polarity: fearful
    cadence: daily
  - id: vix
    category: sentiment
    field: overall
    source: yfinance
    source_ref: "^VIX2"
    polarity: fearful
    cadence: daily
""")
    with pytest.raises(ValueError, match="duplicate"):
        load_metrics(p)


def test_load_fields(tmp_path):
    p = _write(tmp_path, "fields.yaml", """
fields:
  overall:
    label: "Overall market"
    valuation: [cape]
    sentiment: [vix]
    macro_risk: []
worldview_score_weights:
  valuation: 0.5
  sentiment: 0.3
  macro_risk: 0.2
""")
    fields = load_fields(p)
    assert "overall" in fields
    assert fields["overall"].valuation == ["cape"]
    assert fields["overall"].sentiment == ["vix"]
    assert fields["overall"].macro_risk == []

    weights = load_score_weights(p)
    assert weights == {"valuation": 0.5, "sentiment": 0.3, "macro_risk": 0.2}


def test_load_score_weights_defaults(tmp_path):
    p = _write(tmp_path, "fields.yaml", "fields: {}\n")
    weights = load_score_weights(p)
    assert weights == {"valuation": 0.4, "sentiment": 0.3, "macro_risk": 0.3}


def test_shipped_config_files_load_cleanly():
    """The metrics.yaml / fields.yaml in ./config must always parse."""
    metrics = load_metrics()
    assert len(metrics) >= 5
    fields = load_fields()
    assert "overall" in fields

    # every metric_id referenced in fields.yaml must exist in metrics.yaml
    known = {m.id for m in metrics}
    for fdef in fields.values():
        for mid in (*fdef.valuation, *fdef.sentiment, *fdef.macro_risk):
            assert mid in known, f"fields.yaml references unknown metric: {mid}"
