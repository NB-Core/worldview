# Worldview

Local dashboard that snapshots the state of the global economy and markets — valuation, sentiment, macro, geopolitical, energy, credit, and breadth. Designed to answer "where are we now?" and "where have we been?" with a 2×2 valuation/sentiment quadrant per business field.

See [`CLAUDE.md`](./CLAUDE.md) for the full design brief.

## Quick start

```bash
# 1. Set up
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # then fill in FRED_API_KEY

# 2. Initialize the local SQLite store
python -m worldview.cli init-db

# 3. Pull a first snapshot (priority metrics only — fast)
python -m worldview.cli snapshot --cadence daily

# 4. Open the dashboard
uvicorn worldview.webapp.main:app --reload --port 8000
# → http://127.0.0.1:8000
```

## Layout

```
.
├── CLAUDE.md                  # design brief
├── README.md
├── pyproject.toml
├── .env.example               # API keys go here (copy to .env)
├── config/
│   ├── metrics.yaml           # one row per metric: id, source, polarity, weights
│   ├── fields.yaml            # field → metrics rollup
│   └── capex_overrides.yaml   # manual hyperscaler-capex corrections
├── worldview/                 # the package
│   ├── cli.py                 # `python -m worldview.cli ...`
│   ├── config.py              # YAML + .env loader
│   ├── models.py              # Metric, Observation dataclasses
│   ├── store/                 # SQLite layer
│   │   ├── db.py
│   │   └── schema.sql
│   ├── fetchers/              # one module per data source
│   │   ├── base.py
│   │   ├── fred.py
│   │   ├── yfinance_fetcher.py
│   │   └── registry.py
│   ├── analysis/              # percentile/score/composite logic
│   │   ├── scoring.py
│   │   └── composite.py
│   └── webapp/                # FastAPI + Jinja2 + Plotly.js
│       ├── main.py
│       ├── templates/
│       └── static/
├── scripts/
│   └── run_snapshot.py        # convenience wrapper around `cli snapshot`
└── tests/
    ├── test_config.py
    ├── test_db.py
    ├── test_scoring.py
    └── test_fetchers.py
```

## Conventions

- **Python 3.11+**, type-hinted throughout. `from __future__ import annotations` everywhere.
- **No heavy frameworks**. Plain dataclasses, stdlib `sqlite3`, FastAPI for the web layer.
- **Side-effects at the edges**: fetchers do I/O, store writes the DB, analysis is pure-functional over pandas Series. Everything testable.
- **Idempotent writes**: every fetcher upserts on `(metric_id, date)`. Re-running is safe.
- **HTTP retries** via `tenacity` with exponential backoff.
- **Tests**: `pytest`. Network calls are mocked via `responses`. Real-network tests are marked `@pytest.mark.integration` and skipped by default.

```bash
pytest                          # unit tests only
pytest -m integration           # actually hits FRED + yfinance
ruff check . && mypy worldview  # lint + types
```

## Adding a new metric

1. Add a row to `config/metrics.yaml` (id, source, source_ref, polarity, etc.).
2. If the source is already wired (FRED, yfinance), nothing else to do — `cli snapshot` will pick it up.
3. If it's a new source, add a fetcher in `worldview/fetchers/`, register it in `registry.py`.
4. (Optional) attach to a field in `config/fields.yaml` so it rolls up into the 2×2.

## Refresh cadence

- `--cadence daily`   → prices, VIX/VVIX/MOVE, F&G, yields, credit spreads.
- `--cadence weekly`  → AAII, NAAIM, jobless claims, rig count.
- `--cadence monthly` → CPI, PCE, ISM, GPR, EPU, Shiller CAPE.
- `--cadence all`     → everything; safe but slow.

The store is idempotent so re-runs only insert new dates.
