-- Worldview SQLite schema.
-- All writes are idempotent: re-running a fetch only inserts new (metric_id, date) rows.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS metrics (
    id            TEXT PRIMARY KEY,
    category      TEXT NOT NULL,
    field         TEXT NOT NULL,
    source        TEXT NOT NULL,
    source_ref    TEXT NOT NULL,
    polarity      TEXT NOT NULL,
    cadence       TEXT NOT NULL,
    weight        REAL NOT NULL DEFAULT 1.0,
    flag_high_pct REAL,
    flag_low_pct  REAL,
    notes         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS observations (
    metric_id TEXT NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,        -- ISO YYYY-MM-DD
    value     REAL NOT NULL,
    PRIMARY KEY (metric_id, date)
);

CREATE INDEX IF NOT EXISTS idx_obs_date ON observations(date);

CREATE TABLE IF NOT EXISTS flags (
    metric_id TEXT NOT NULL REFERENCES metrics(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,
    side      TEXT NOT NULL CHECK (side IN ('high', 'low')),
    pct       REAL NOT NULL,
    value     REAL NOT NULL,
    PRIMARY KEY (metric_id, date, side)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('running', 'ok', 'partial', 'failed')),
    log         TEXT NOT NULL DEFAULT ''
);

-- Append-only model snapshots. Observation history is untouched.
CREATE TABLE IF NOT EXISTS score_snapshots (
    captured_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (captured_at, model_version)
);
