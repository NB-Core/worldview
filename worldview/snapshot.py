"""End-to-end snapshot pipeline: fetch → store → score → flag.

This is the function the CLI calls and the webapp's `/api/refresh` endpoint
will call. Kept in one place so we have a single, testable entry point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from .analysis.composite import FieldScore, field_scores, worldview_score
from .analysis.history import backfill_flags
from .analysis.scoring import score_metric
from .config import (
    load_fields,
    load_metrics,
    load_score_weights,
    load_sentiment_mode,
    load_settings,
)
from .fetchers import FetcherRegistry, FetchError, default_registry
from .fetchers.registry import UnsupportedSource
from .models import Cadence, Metric, MetricScore
from .store import Database

log = logging.getLogger(__name__)

HISTORY_START = date(2008, 1, 1)


# Cadence flag → which cadences run.
_CADENCE_GROUPS: dict[str, set[Cadence]] = {
    "daily":     {Cadence.DAILY},
    "weekly":    {Cadence.DAILY, Cadence.WEEKLY},
    "monthly":   {Cadence.DAILY, Cadence.WEEKLY, Cadence.MONTHLY},
    "quarterly": {Cadence.DAILY, Cadence.WEEKLY, Cadence.MONTHLY, Cadence.QUARTERLY},
    "all":       set(Cadence),
}


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    fetched: int                      # number of observation rows written this run
    failed: list[str]                 # metric_ids whose fetch raised a real FetchError
    skipped: list[str]                # metric_ids whose source has no fetcher wired up yet
    scores: dict[str, MetricScore]
    fields: dict[str, FieldScore]
    worldview: float | None


def run_snapshot(
    cadence: str = "daily",
    only: list[str] | None = None,
    db: Database | None = None,
    registry: FetcherRegistry | None = None,
) -> SnapshotResult:
    """Refresh data, persist to SQLite, and compute scores.

    Args:
        cadence: which cadence bucket to refresh ("daily" | "weekly" | …).
                 A higher cadence implies all lower ones below it.
        only: optional list of metric ids to restrict to (for debugging).
        db: optional injected Database (tests).
        registry: optional injected FetcherRegistry (tests).

    Returns:
        `SnapshotResult` with per-metric scores, field rollups, and the
        Worldview Score.
    """
    settings = load_settings()
    db = db or Database(settings.db_path)
    db.init_schema()

    metrics = load_metrics()
    if only:
        wanted = set(only)
        metrics = [m for m in metrics if m.id in wanted]

    db.upsert_metrics(metrics)

    if cadence not in _CADENCE_GROUPS:
        raise ValueError(
            f"unknown cadence {cadence!r}. Pick from {sorted(_CADENCE_GROUPS)}"
        )
    keep = _CADENCE_GROUPS[cadence]
    metrics_to_run = [m for m in metrics if m.cadence in keep]

    registry = registry or default_registry(settings, db=db)

    run_id = db.start_run()
    failed: list[str] = []
    skipped: list[str] = []
    fetched = 0

    # Two-pass: raw fetchers first, derived fetchers second so derived recipes
    # see freshly-upserted inputs in the DB.
    raw     = [m for m in metrics_to_run if m.source != "derived"]
    derived = [m for m in metrics_to_run if m.source == "derived"]

    for m in (*raw, *derived):
        try:
            series = registry.fetch(m, HISTORY_START)
        except UnsupportedSource:
            # Expected for metrics whose fetcher isn't built yet.
            log.info("skipping %s: source=%r not yet wired", m.id, m.source)
            skipped.append(m.id)
            continue
        except FetchError as e:
            log.warning("fetch failed for %s: %s", m.id, e)
            failed.append(m.id)
            continue

        n = db.upsert_observations(m.id, series)
        fetched += n
        log.info("upserted %d rows for %s", n, m.id)

    # Score everything we have history for, regardless of whether we just refreshed it.
    all_metrics = load_metrics()
    metrics_by_id = {m.id: m for m in all_metrics}
    scores: dict[str, MetricScore] = {}
    for m in all_metrics:
        history = db.get_observations(m.id)
        if history.empty:
            continue
        s = score_metric(m, history, evaluation_date=date.today())
        if s is not None:
            scores[m.id] = s

    # Backfill flag history so the dashboard can show "X has been flagged for
    # N consecutive observations". Idempotent thanks to the table's
    # (metric_id, date, side) PK.
    for m in all_metrics:
        if m.flag_high_pct is None and m.flag_low_pct is None:
            continue
        history = db.get_observations(m.id)
        if history.empty:
            continue
        for flag in backfill_flags(m, history):
            db.write_flag(flag.metric_id, flag.on, flag.side, flag.pct, flag.value)

    fields_def = load_fields()
    fscores = field_scores(fields_def, metrics_by_id, scores)
    weights = load_score_weights()
    mode = load_sentiment_mode()
    overall = fscores.get("overall")
    wv = worldview_score(overall, weights, mode) if overall is not None else None

    from .analysis.composite import regime
    db.save_score_snapshot({fid: {
        "valuation": fs.valuation, "sentiment": fs.sentiment,
        "macro_risk": fs.macro_risk, "regime": regime(fs.valuation, fs.sentiment),
    } for fid, fs in fscores.items()})

    # `skipped` doesn't count as failure — it's expected during M0/M1.
    status = "ok" if not failed else ("partial" if fetched > 0 else "failed")
    db.finish_run(
        run_id,
        status=status,
        log=(
            f"fetched={fetched} "
            f"failed={','.join(failed) or '-'} "
            f"skipped={','.join(skipped) or '-'}"
        ),
    )

    return SnapshotResult(
        fetched=fetched,
        failed=failed,
        skipped=skipped,
        scores=scores,
        fields=fscores,
        worldview=wv,
    )


def _metric_summary(m: Metric, score: MetricScore | None) -> str:
    if score is None:
        return f"{m.id:<24}  no data"
    flag = "  ⚑" if (score.flagged_high or score.flagged_low) else ""
    return (
        f"{m.id:<24}  asof {score.asof}  "
        f"value={score.value:>10.2f}  pct={score.percentile:>5.1f}  "
        f"{score.label}{flag}"
    )
