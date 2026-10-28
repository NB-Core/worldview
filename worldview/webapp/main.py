"""FastAPI app for the local Worldview dashboard.

Routes:
    GET  /                     — Snapshot HTML (server-rendered, hydrated by JS)
    GET  /metric/{id}          — Per-metric drilldown
    GET  /api/snapshot.json    — Snapshot data as JSON
    GET  /api/metric/{id}.json — Metric history as JSON
    POST /api/refresh          — Run a snapshot (cadence query param)

Bind to 127.0.0.1 only:
    uvicorn worldview.webapp.main:app --host 127.0.0.1 --port 8000 --reload
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..analysis.composite import field_scores, worldview_score
from ..analysis.history import current_streak, historical_overall_score
from ..analysis.legacy import legacy_scores
from ..analysis.scoring import score_metric
from ..analysis.transparency import field_details
from ..config import (
    load_fields,
    load_metrics,
    load_score_weights,
    load_sentiment_mode,
    load_settings,
)
from ..snapshot import run_snapshot
from ..store import Database

PKG_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(PKG_DIR / "templates"))

app = FastAPI(title="Worldview", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(PKG_DIR / "static")), name="static")


# ── helpers ───────────────────────────────────────────────────────────────────


def _build_payload() -> dict:
    """Compute the snapshot payload from whatever's already in the DB."""
    settings = load_settings()
    db = Database(settings.db_path)
    db.init_schema()

    metrics = load_metrics()
    metrics_by_id = {m.id: m for m in metrics}

    scores = {}
    quality = {}
    for m in metrics:
        history = db.get_observations(m.id)
        from ..analysis.scoring import max_age_days
        age = (date.today() - history.index[-1].date()).days if not history.empty else None
        quality[m.id] = {"as_of": history.index[-1].date().isoformat() if not history.empty else None,
                         "observations": len(history), "age_days": age,
                         "warning": "missing" if history.empty else (
                             "insufficient_history" if len(history) <= m.min_history else (
                                 "stale" if age is not None and age > max_age_days(m) else None))}
        s = score_metric(m, history, evaluation_date=date.today())
        if s is not None:
            scores[m.id] = s

    fdef = load_fields()
    fscores = field_scores(fdef, metrics_by_id, scores)
    weights = load_score_weights()
    mode = load_sentiment_mode()
    overall = fscores.get("overall")
    wv = worldview_score(overall, weights, mode) if overall else None

    details = {fid: field_details(fdef[fid], fs, metrics_by_id, scores) for fid, fs in fscores.items()}
    current = {fid: {"valuation": fs.valuation, "sentiment": fs.sentiment,
                     "macro_risk": fs.macro_risk, "regime": details[fid]["regime"]}
               for fid, fs in fscores.items()}
    return {
        "asof": max((s.asof for s in scores.values()), default=None),
        "worldview_score": wv,
        "model_version": "v2",
        "legacy_v1": legacy_scores(db, metrics_by_id, weights, mode),
        "quality": quality,
        "field_details": details,
        "changes": db.score_changes(current, date.today()),
        "sentiment_mode": mode,
        "fields": [
            {
                "id":         fs.field_id,
                "label":      fs.label,
                "valuation":  fs.valuation,
                "sentiment":  fs.sentiment,
                "macro_risk": fs.macro_risk,
                "quadrant":   fs.quadrant,
            }
            for fs in fscores.values()
        ],
        "field_contributors": {
            fid: {
                "valuation":  fs.contributing.get("valuation",  []),
                "sentiment":  fs.contributing.get("sentiment",  []),
                "macro_risk": fs.contributing.get("macro_risk", []),
            }
            for fid, fs in fscores.items()
        },
        "metrics": [
            {
                "id":         s.metric_id,
                "category":   metrics_by_id[s.metric_id].category.value,
                "field":      metrics_by_id[s.metric_id].field,
                "asof":       s.asof.isoformat(),
                "value":      s.value,
                "percentile": s.percentile,
                "label":      s.label,
                "flagged_high": s.flagged_high,
                "flagged_low":  s.flagged_low,
                "notes":      metrics_by_id[s.metric_id].notes,
            }
            for s in sorted(scores.values(), key=lambda x: x.metric_id)
        ],
        "flags": _flags_with_streak(db),
    }


def _flags_with_streak(db: Database) -> list[dict]:
    """Currently-active flags only, each with its consecutive-obs streak.

    `db.latest_flags()` returns the most-recent flag row per (metric, side)
    even if it's stale — i.e., the metric has since fallen back into normal
    territory. We filter to streak > 0 so the dashboard banner only shows
    things flagged on their LATEST observation. Sorted streak-desc so the
    most persistent flags surface first.
    """
    enriched: list[dict] = []
    for f in db.latest_flags():
        obs_dates = db.observation_dates(f["metric_id"])
        flagged = db.flagged_dates(f["metric_id"], f["side"])
        streak = current_streak(obs_dates, flagged)
        if streak == 0:
            continue
        enriched.append({**f, "streak": streak})
    enriched.sort(key=lambda x: x["streak"], reverse=True)
    return enriched


# ── routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def snapshot_page(request: Request) -> HTMLResponse:
    payload = _build_payload()
    # Starlette ≥0.29: request is the first positional arg.
    return TEMPLATES.TemplateResponse(
        request,
        "snapshot.html",
        {"payload": payload},
    )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "history.html", {})


@app.get("/api/history.json")
def history_json(legacy: bool = False) -> JSONResponse:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init_schema()
    metrics_by_id = {m.id: m for m in load_metrics()}
    fields = load_fields()
    weights = load_score_weights()

    df = historical_overall_score(db, metrics_by_id, fields, weights, load_sentiment_mode(), verified_only=not legacy)
    if df.empty:
        return JSONResponse({"dates": [], "valuation": [], "sentiment": [],
                             "macro_risk": [], "worldview_score": []})

    # Drop only rows where *every* block is empty — keep partial coverage so
    # the chart renders something useful before all metrics are seeded.
    df = df.dropna(how="all", subset=["valuation", "sentiment", "macro_risk"])
    return JSONResponse(
        {
            "provenance": "observation_date_unverified" if legacy else "daily_market_observations_only",
            "dates":           [d.date().isoformat() for d in df.index],
            "valuation":       [_safe(v) for v in df["valuation"]],
            "sentiment":       [_safe(v) for v in df["sentiment"]],
            "macro_risk":      [_safe(v) for v in df["macro_risk"]],
            "worldview_score": [_safe(v) for v in df["worldview_score"]],
        }
    )


def _safe(v) -> float | None:
    """JSON-safe scalar: None for NaN/Inf."""
    import math
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


@app.get("/api/prices.json")
def prices_json(ids: str = "") -> JSONResponse:
    """Raw value series for the requested metric ids.

    Used by /history to overlay benchmarks (S&P, Nasdaq, Stoxx) on top of
    the Worldview Score chart. `ids` is a comma-separated list.
    """
    settings = load_settings()
    db = Database(settings.db_path)
    db.init_schema()
    by_id = {m.id: m for m in load_metrics()}
    requested = [s.strip() for s in ids.split(",") if s.strip()]
    series_payload: list[dict] = []
    for mid in requested:
        if mid not in by_id:
            continue
        history = db.get_observations(mid)
        if history.empty:
            continue
        series_payload.append({
            "id":     mid,
            "label":  by_id[mid].notes or mid,
            "dates":  [d.date().isoformat() for d in history.index],
            "values": [_safe(v) for v in history.values],
        })
    return JSONResponse({"series": series_payload})


@app.get("/api/snapshot.json")
def snapshot_json() -> JSONResponse:
    payload = _build_payload()
    # date isn't JSON-serializable by default
    if isinstance(payload.get("asof"), date):
        payload["asof"] = payload["asof"].isoformat()
    return JSONResponse(payload)


@app.get("/metric/{metric_id}", response_class=HTMLResponse)
def metric_page(request: Request, metric_id: str) -> HTMLResponse:
    metrics = {m.id: m for m in load_metrics()}
    if metric_id not in metrics:
        raise HTTPException(status_code=404, detail=f"unknown metric {metric_id!r}")
    return TEMPLATES.TemplateResponse(
        request,
        "metric.html",
        {"metric": metrics[metric_id]},
    )


@app.get("/api/metric/{metric_id}.json")
def metric_json(metric_id: str) -> JSONResponse:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init_schema()  # safe on a fresh / never-seeded DB
    history = db.get_observations(metric_id)
    if history.empty:
        raise HTTPException(status_code=404, detail="no observations for that metric")
    return JSONResponse(
        {
            "metric_id": metric_id,
            "dates":  [d.date().isoformat() for d in history.index],
            "values": [float(v) for v in history.values],
        }
    )


@app.post("/api/refresh")
def refresh(cadence: str = "daily") -> JSONResponse:
    """Manual refresh trigger. POST so it's not accidentally re-run by browsers."""
    result = run_snapshot(cadence=cadence)
    return JSONResponse(
        {
            "fetched":         result.fetched,
            "failed":          result.failed,
            "worldview_score": result.worldview,
        }
    )
