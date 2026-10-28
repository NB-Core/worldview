"""Thin SQLite wrapper.

We deliberately avoid an ORM. The data model is two tables of (metric, date,
value) — sqlite3 stdlib handles it cleanly. Methods here are the *only* place
the project talks to the DB.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from ..models import Cadence, Category, Metric, Polarity

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """SQLite-backed metric/observation store.

    Usage:
        db = Database(Path("worldview.db"))
        db.init_schema()
        db.upsert_metric(metric)
        db.upsert_observations("vix", series)
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── Connection ────────────────────────────────────────────────────────

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection with sane defaults; commits on success."""
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Apply schema.sql. Idempotent."""
        sql = SCHEMA_PATH.read_text()
        with self.connect() as conn:
            conn.executescript(sql)

    # ── Metrics ───────────────────────────────────────────────────────────

    def upsert_metric(self, metric: Metric) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO metrics
                  (id, category, field, source, source_ref, polarity, cadence,
                   weight, flag_high_pct, flag_low_pct, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  category=excluded.category,
                  field=excluded.field,
                  source=excluded.source,
                  source_ref=excluded.source_ref,
                  polarity=excluded.polarity,
                  cadence=excluded.cadence,
                  weight=excluded.weight,
                  flag_high_pct=excluded.flag_high_pct,
                  flag_low_pct=excluded.flag_low_pct,
                  notes=excluded.notes
                """,
                (
                    metric.id,
                    metric.category.value,
                    metric.field,
                    metric.source,
                    metric.source_ref,
                    metric.polarity.value,
                    metric.cadence.value,
                    metric.weight,
                    metric.flag_high_pct,
                    metric.flag_low_pct,
                    metric.notes,
                ),
            )

    def upsert_metrics(self, metrics: Iterable[Metric]) -> None:
        for m in metrics:
            self.upsert_metric(m)

    def list_metrics(self) -> list[Metric]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM metrics ORDER BY id").fetchall()
        return [_row_to_metric(r) for r in rows]

    def get_metric(self, metric_id: str) -> Metric | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM metrics WHERE id = ?", (metric_id,)
            ).fetchone()
        return _row_to_metric(row) if row else None

    # ── Observations ──────────────────────────────────────────────────────

    def upsert_observations(self, metric_id: str, series: pd.Series) -> int:
        """Insert/replace (metric_id, date, value) rows.

        Args:
            metric_id: must exist in `metrics`.
            series: pandas Series indexed by date-like; non-finite values dropped.

        Returns:
            Number of rows written.
        """
        if series.empty:
            return 0

        clean = series.dropna()
        clean = clean[clean.apply(_is_finite)]
        if clean.empty:
            return 0

        rows = [
            (metric_id, _to_iso(idx), float(val))
            for idx, val in clean.items()
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO observations (metric_id, date, value)
                VALUES (?, ?, ?)
                ON CONFLICT(metric_id, date) DO UPDATE SET value=excluded.value
                """,
                rows,
            )
        return len(rows)

    def get_observations(
        self,
        metric_id: str,
        since: date | None = None,
    ) -> pd.Series:
        """Return all observations for a metric as a date-indexed Series."""
        sql = "SELECT date, value FROM observations WHERE metric_id = ?"
        params: list[object] = [metric_id]
        if since is not None:
            sql += " AND date >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY date"

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return pd.Series(dtype=float, name=metric_id)

        idx = pd.to_datetime([r["date"] for r in rows])
        vals = [r["value"] for r in rows]
        return pd.Series(vals, index=idx, name=metric_id, dtype=float)

    def latest_value(self, metric_id: str) -> tuple[date, float] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT date, value FROM observations
                WHERE metric_id = ?
                ORDER BY date DESC LIMIT 1
                """,
                (metric_id,),
            ).fetchone()
        if not row:
            return None
        return date.fromisoformat(row["date"]), float(row["value"])

    # ── Flags ─────────────────────────────────────────────────────────────

    def write_flag(
        self,
        metric_id: str,
        on: date,
        side: str,
        pct: float,
        value: float,
    ) -> None:
        if side not in ("high", "low"):
            raise ValueError(f"side must be 'high' or 'low', got {side!r}")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO flags (metric_id, date, side, pct, value)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(metric_id, date, side) DO UPDATE SET
                  pct=excluded.pct, value=excluded.value
                """,
                (metric_id, on.isoformat(), side, pct, value),
            )

    def flagged_dates(self, metric_id: str, side: str) -> set[date]:
        """Return the set of dates a metric was flagged on a given side."""
        if side not in ("high", "low"):
            raise ValueError(f"side must be 'high' or 'low', got {side!r}")
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT date FROM flags WHERE metric_id = ? AND side = ?",
                (metric_id, side),
            ).fetchall()
        return {date.fromisoformat(r["date"]) for r in rows}

    def observation_dates(self, metric_id: str) -> list[date]:
        """All observation dates for a metric, ascending."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT date FROM observations WHERE metric_id = ? ORDER BY date",
                (metric_id,),
            ).fetchall()
        return [date.fromisoformat(r["date"]) for r in rows]

    def latest_flags(self) -> list[dict]:
        """Most recent flag per (metric, side)."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT f.metric_id, f.date, f.side, f.pct, f.value
                FROM flags f
                JOIN (
                    SELECT metric_id, side, MAX(date) AS max_date
                    FROM flags GROUP BY metric_id, side
                ) latest
                ON f.metric_id = latest.metric_id
                   AND f.side = latest.side
                   AND f.date = latest.max_date
                ORDER BY f.metric_id
                """
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Runs ──────────────────────────────────────────────────────────────

    def start_run(self) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (_utcnow_iso(),),
            )
            return int(cur.lastrowid or 0)

    def finish_run(self, run_id: int, status: str, log: str = "") -> None:
        if status not in ("ok", "partial", "failed"):
            raise ValueError(f"bad status: {status!r}")
        with self.connect() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, status = ?, log = ? WHERE run_id = ?",
                (_utcnow_iso(), status, log, run_id),
            )

    def save_score_snapshot(self, payload: dict) -> None:
        import json
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO score_snapshots VALUES (?, ?, ?)",
                (_utcnow_iso(), "v2", json.dumps(payload, allow_nan=False)),
            )

    def score_changes(self, current: dict, today: date) -> dict:
        import json
        from datetime import timedelta
        result: dict[str, dict | None] = {}
        with self.connect() as conn:
            for days in (7, 14, 30):
                target = today - timedelta(days=days)
                row = conn.execute(
                    "SELECT captured_at, payload FROM score_snapshots WHERE model_version='v2' "
                    "AND substr(captured_at,1,10) <= ? ORDER BY captured_at DESC LIMIT 1",
                    (target.isoformat(),),
                ).fetchone()
                if row is None or (target - date.fromisoformat(row[0][:10])).days > 3:
                    result[str(days)] = None
                    continue
                old = json.loads(row[1])
                entry: dict = {'as_of': row[0], 'fields': {}}
                result[str(days)] = entry
                for fid, now in current.items():
                    before = old.get(fid, {})
                    delta = {b: None if now.get(b) is None or before.get(b) is None else now[b] - before[b]
                             for b in ('valuation', 'sentiment', 'macro_risk')}
                    moves = [abs(v) for v in delta.values() if v is not None]
                    entry['fields'][fid] = {
                        'delta': delta, 'previous_regime': before.get('regime'),
                        'regime': now.get('regime'),
                        'small_move': bool(moves) and max(moves) <= 2,
                    }
        return result


# ── helpers ───────────────────────────────────────────────────────────────────


def _row_to_metric(row: sqlite3.Row) -> Metric:
    return Metric(
        id=row["id"],
        category=Category(row["category"]),
        field=row["field"],
        source=row["source"],
        source_ref=row["source_ref"],
        polarity=Polarity(row["polarity"]),
        cadence=Cadence(row["cadence"]),
        weight=row["weight"],
        flag_high_pct=row["flag_high_pct"],
        flag_low_pct=row["flag_low_pct"],
        notes=row["notes"] or "",
    )


def _to_iso(value: object) -> str:
    """Coerce a pandas index value into ISO YYYY-MM-DD."""
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # pd.Timestamp or numpy datetime64
    return pd.Timestamp(value).date().isoformat()


def _is_finite(x: float) -> bool:
    import math
    return isinstance(x, (int, float)) and math.isfinite(float(x))


def _utcnow_iso() -> str:
    """ISO-formatted UTC timestamp at second precision; tz-aware (Python 3.11+)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()
