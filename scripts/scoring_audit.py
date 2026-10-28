"""Read-only score comparison on the bundled DB: python scripts/scoring_audit.py."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

from worldview.analysis.composite import field_scores, worldview_score
from worldview.analysis.legacy import legacy_scores
from worldview.analysis.scoring import score_metric
from worldview.config import load_fields, load_metrics, load_score_weights
from worldview.store import Database

metrics = {m.id: m for m in load_metrics()}
db = Database(Path("worldview/store/worldview.db"))
weights = load_score_weights()
legacy = legacy_scores(db, metrics, weights, "penalize_greed")
latest = max(db.latest_value(mid)[0] for mid in metrics if db.latest_value(mid))
out = {"database_as_of": str(latest), "legacy_v1": legacy}
for label, fields, when in [
    ("polarity_only", load_fields(Path("config/fields_legacy.yaml")), None),
    ("v2_at_database_date", load_fields(), latest),
    ("v2_today", load_fields(), date.today()),
]:
    scores = {}
    for mid, metric in metrics.items():
        if label == "polarity_only":
            metric = replace(metric, min_history=0)
        s = score_metric(metric, db.get_observations(mid), evaluation_date=when)
        if s is not None:
            scores[mid] = s
    fs = field_scores(fields, metrics, scores)
    out[label] = {
        "worldview_score": worldview_score(fs["overall"], weights),
        "fields": {
            fid: {b: getattr(f, b) for b in ("valuation", "sentiment", "macro_risk", "quadrant")}
            for fid, f in fs.items()
        },
    }
print(json.dumps(out, indent=2, allow_nan=False))
