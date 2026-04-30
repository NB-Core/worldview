# Worldview — Project Brief

## Goal
Build a snapshot view of the global economic + market state that combines valuation, sentiment, macro, geopolitical, energy, credit, and breadth signals — so that at any point in time we can answer:

1. **Where are we now?** (overheated / fair / fearful / dislocated)
2. **Where have we been?** (percentile / z-score vs history since 2008)
3. **Which fields are buyable, which are bubbles, which are traps?** — by separately scoring **valuation** and **sentiment** for each field (AI, construction, finance, energy, defensives, etc.)

This is **state identification**, not trend prediction. The output should let Oliver form a thesis like *"AI sector: valuation 95th pct, sentiment 92nd pct → bubble quadrant; Energy: valuation 45th pct, sentiment 30th pct, GPR 90th pct → buyable with geopolitical tailwind"*.

---

## Investment philosophy this serves
Oliver wants to buy quality cheaply (Buffett-style) **but** also wants to be warned away from things that are *cheap on fundamentals yet running hot in sentiment* (the classic "value trap reversed" — fundamentally fine, but late in the crowd's enthusiasm cycle). So the system must always answer two separate questions:

- **Is it expensive?** → valuation block (CAPE, fwd P/E, P/B, ERP, Buffett indicator, FCF yield)
- **Is it crowded?** → sentiment/positioning block (VIX, F&G, AAII, NAAIM, MOVE, put/call, momentum, breadth)

These produce a 2×2 action map per field:

| | Sentiment LOW (fearful) | Sentiment HIGH (greedy) |
|---|---|---|
| **Valuation LOW (cheap)** | **BUY** — Buffett zone | **CAUTION** — cheap but late; momentum pile-on, "lift off the ground" |
| **Valuation HIGH (expensive)** | **TRAP** — no enthusiasm, risk grinding lower | **BUBBLE** — get out / hedge |

The headline call per field is the quadrant + the strongest single flag (e.g., "BUY, but HY OAS 90th pct says credit is breaking — wait").

---

## Decisions (locked)
- **History start: 2008-01-01.** Captures GFC, Eurozone crisis, 2015–16 oil bust, 2020 COVID, 2022 inflation/bond rout, 2024–26 AI boom. ~18 years is enough percentile depth without dragging in dot-com era data that has different microstructure.
- **Geographies: US + EU.** EU = Eurozone + UK aggregate, not country-by-country. Skip China / EM for v1.
- **Storage: local SQLite** at `worldview/store/worldview.db`. One row per `(metric_id, date, value)`. Parquet exports for ad-hoc analysis.
- **Dashboard: local FastAPI app** (single `uvicorn` command), Jinja2 templates, Plotly.js for charts. No login, binds to localhost only. Re-fetches happen via a separate `run_snapshot.py` (or a manual "Refresh" button hitting an internal endpoint). This is heavier than static HTML but lighter than Dash/Streamlit, and it keeps fetch and render decoupled.
- **Alerts: yes, threshold flags.** Each metric has optional `flag_high` / `flag_low` percentile thresholds in YAML (default 90/10). Flagged metrics surface in a top "Flags right now" banner on the dashboard. Optional: write flag history to a `flags` table so we can see "GPR has been > 90th pct for 47 days".
- **Composite scoring: yes, our own.** No black-box copy of CNN F&G. We define and document the weights ourselves (see § Scoring).

---

## Metric framework

Every metric is stored as: `metric_id, date, value, source, transform, category, sub_field, flag_high_pct, flag_low_pct, weight`.

Each metric is normalized to a 0–100 percentile vs. its **own** post-2008 history (rolling 10y window for things that drift, full-window for stable ones — flagged per metric in YAML).

### 1. Valuation block — *"How expensive is the market?"*
| Metric | What it tells us | Source | Cadence |
|---|---|---|---|
| Buffett Indicator (Wilshire 5000 / GDP) | Aggregate equity valuation vs. economy | FRED `WILL5000PRFC` + `GDP` | Daily / Q |
| Shiller CAPE (US) | Long-horizon S&P valuation | shillerdata.com / Yale CSV | Monthly |
| EU Buffett analog (Stoxx 600 mcap / Eurozone GDP) | EU aggregate valuation; replaces EU CAPE in v1 | yfinance `^STOXX` × shares + Eurostat `naidq_10_gdp` | Quarterly |
| S&P 500 forward P/E | Current Wall St expectations | multpl.com (scrape), yardeni | Weekly |
| S&P 500 trailing P/E | Lagging valuation | multpl.com | Weekly |
| S&P 500 P/B | Asset-side valuation | multpl.com | Monthly |
| S&P 500 dividend yield − 10Y | Equity risk premium proxy | FRED `DGS10` + multpl.com | Daily |
| Stoxx 600 forward P/E | EU valuation | yardeni / yfinance derived | Weekly |
| Top-10 share of S&P 500 mkt cap | Concentration / Mag-7 risk | slickcharts.com (scrape) | Weekly |
| Nvidia % of MSCI World | Oliver's specific concentration flag | iShares URTH holdings CSV | Weekly |
| Equal-weight vs cap-weight S&P (RSP/SPY) | Breadth-of-rally proxy | yfinance | Daily |

### 2. Sentiment / positioning block — *"How crowded is the trade?"*
| Metric | Source | Cadence |
|---|---|---|
| VIX (30-day implied vol) | yfinance `^VIX` / FRED `VIXCLS` | Daily |
| VVIX (vol of vol) | yfinance `^VVIX` | Daily |
| VIX term structure (VIX/VIX3M) | yfinance | Daily |
| MOVE Index (bond vol) | yfinance `^MOVE` | Daily |
| CNN Fear & Greed | `production.dataviz.cnn.io/index/fearandgreed/graphdata` | Daily |
| AAII Bull/Bear spread | aaii.com weekly CSV | Weekly |
| NAAIM Exposure Index | naaim.org weekly CSV | Weekly |
| CBOE Put/Call ratio | CBOE CSV | Daily |
| High-Yield OAS (US) | FRED `BAMLH0A0HYM2` | Daily |
| Investment-Grade OAS (US) | FRED `BAMLC0A0CM` | Daily |
| EU HY OAS | FRED `BAMLHE00EHYIOAS` | Daily |
| EU IG OAS | FRED `BAMLEMHYHYLCRPIOAS` (or ICE EU IG) | Daily |
| S&P 500 % above 200d MA | scrape stockcharts `$SPXA200R` | Daily |
| 52-week new highs − new lows (NYSE) | barchart scrape | Daily |
| ETF flow proxy (SPY / QQQ AUM Δ) | yfinance shares outstanding | Weekly |
| BTC-USD price | speculative pulse | yfinance `BTC-USD` | Daily |
| BTC 30d realized volatility | crypto risk-on/off | derived from `BTC-USD` | Daily |
| ARKK price (innovation-fund proxy) | retail-speculation pulse | yfinance `ARKK` | Daily |
| MSTR price (BTC-leverage proxy) | extreme-greed proxy | yfinance `MSTR` | Daily |

### 3. Macro block — *"What's the economy actually doing?"*
US (FRED unless noted):

| Metric | Series |
|---|---|
| 10Y Treasury yield | `DGS10` |
| 2s10s curve | `T10Y2Y` |
| 3M-10Y curve | `T10Y3M` |
| 10Y real yield (TIPS) | `DFII10` |
| 5y5y inflation breakeven | `T5YIFR` |
| CPI / Core CPI YoY | `CPIAUCSL`, `CPILFESL` |
| Core PCE YoY | `PCEPILFE` |
| Unemployment rate | `UNRATE` |
| Initial jobless claims | `ICSA` |
| ISM Manufacturing PMI | ISM (scrape) |
| ISM Services PMI | ISM (scrape) |
| Conference Board LEI | FRED `USSLIND` proxy |
| U-Mich consumer sentiment | `UMCSENT` |
| Retail sales YoY | `RSAFS` |
| Industrial production | `INDPRO` |
| M2 YoY | `M2SL` |
| DXY | yfinance `DX-Y.NYB` / FRED `DTWEXBGS` |

EU:

| Metric | Source |
|---|---|
| Eurozone HICP YoY | FRED `CP0000EZ19M086NEST` |
| Eurozone Core HICP YoY | Eurostat `prc_hicp_manr` |
| Germany 10Y Bund yield | FRED `IRLTLT01DEM156N` |
| Italy 10Y - Germany 10Y spread | FRED `IRLTLT01ITM156N` − `IRLTLT01DEM156N` |
| Eurozone unemployment | FRED `LRHUTTTTEZM156S` |
| Eurozone Composite PMI | tradingeconomics scrape (or Markit headline) |
| ECB deposit rate | FRED `ECBDFR` |
| EUR/USD | yfinance `EURUSD=X` |
| ZEW Indicator (DE) | tradingeconomics scrape |
| Ifo Business Climate (DE) | FRED `BSCICP02DEM460S` |

### 4. Geopolitical block — *"How dangerous is the world?"*
| Metric | Source |
|---|---|
| Geopolitical Risk Index (Caldara/Iacoviello GPR) | matteoiacoviello.com daily CSV |
| Economic Policy Uncertainty (US, EU) | policyuncertainty.com CSVs |
| World Uncertainty Index | worlduncertaintyindex.com CSV |
| Trade Policy Uncertainty | policyuncertainty.com CSV |
| Active armed conflicts count | UCDP API (`ucdp.uu.se`) |
| Conflict fatalities (rolling 30d) | UCDP API |
| Brent crude (proxy for war premium) | yfinance `BZ=F` |
| Hormuz / Red Sea shipping risk proxy | Baltic Dirty Tanker Index — tradingeconomics |

### 5. Energy / commodities block — *"Inflation + scarcity signals"*
| Metric | Source |
|---|---|
| Brent | yfinance `BZ=F` |
| WTI | yfinance `CL=F` / FRED `DCOILWTICO` |
| Henry Hub natgas | FRED `DHHNGSP` |
| TTF European gas | yfinance `TTF=F` (fallback: ICE scrape) |
| Gold | yfinance `GC=F` / FRED `GOLDAMGBD228NLBM` |
| Silver | yfinance `SI=F` |
| Copper | yfinance `HG=F` |
| Uranium proxy | yfinance `URA` ETF |
| Bloomberg Commodity Index | yfinance `^BCOM` (or DBC) |
| Baltic Dry Index | tradingeconomics scrape |
| Gold/Copper ratio | derived (recession signal) |
| Gold/Oil ratio | derived (energy stress signal) |

### 6. Field dashboards (per-sector valuation + sentiment)
For each field we score valuation and sentiment **independently** so the 2×2 quadrant works at the field level too.

**AI / Semis** — SOX `^SOX`, SMH ETF, NVDA / AMD / TSM / ASML fwd P/E, hyperscaler capex (auto-fetched quarterly: sum of MSFT + GOOGL + AMZN + META + ORCL `Capital Expenditure` from yfinance `Ticker.quarterly_cashflow`; YAML override field per ticker per quarter for corrections), XLK/XLU ratio (power-demand proxy), AI-fund flows (yfinance ETF AUM).

**Building & Construction** — NAHB HMI (FRED `MSACSR` proxy), housing starts `HOUST`, permits `PERMIT`, 30Y mortgage `MORTGAGE30US`, lumber `LB=F`, ITB / XHB ETFs. EU side: Eurostat construction production index, Stoxx Europe 600 Construction.

**Finance / Banks** — KBW Bank Index `^BKX`, XLF, KRE (regionals), 10Y-3M (NIM proxy), HY OAS, IG OAS, SLOOS lending standards `DRTSCILM`. EU: EUFN ETF, Italy-Bund spread, Stoxx 600 Banks.

**Energy** — XLE, XOP, OIH, Baker Hughes rig count CSV, EIA crude inventories, refinery margins (3-2-1 crack — derived).

**Defense** — ITA ETF, LMT/RTX/NOC/HII fwd P/E. EU: Rheinmetall, BAE, Leonardo, Saab; EUAD ETF.

**Defensives / Safe-haven** — XLP, XLU, XLV, gold, TLT (long Treasuries), CHF=X, JPY=X. (BTC is *not* treated as a safe haven here — it lives in the sentiment block as a speculative-pulse indicator.)

### 7. Breadth / internals block
| Metric | Source |
|---|---|
| % S&P 500 above 200d MA | stockcharts `$SPXA200R` scrape |
| NYSE A/D line | yfinance `^ADD` |
| New 52w highs − lows | barchart scrape |
| RSP/SPY ratio | derived |
| SPX vs SPXEW Y/Y delta | derived |

---

## Scoring — the "Worldview Score"

For each metric:
1. Pull full series since 2008-01-01.
2. Compute its current **percentile** vs. its history. (Some metrics use a rolling 10y window where the regime drifts — flagged in YAML.)
3. Map percentile → label: `0–10 Extreme Low / 10–25 Low / 25–75 Normal / 75–90 High / 90–100 Extreme High`.
4. Optionally flip sign — for VIX, "high" = fearful = bullish contrarian; for forward P/E, "high" = expensive = bearish. Each metric's YAML row says which direction is "bullish for risk assets".

For each **field** (AI, construction, etc.), compute three sub-scores:
- **Valuation Score** (0–100): weighted percentile blend of the field's valuation metrics. 100 = most expensive.
- **Sentiment Score** (0–100): weighted blend of the field's sentiment/positioning metrics. 100 = most euphoric/crowded.
- **Macro/Risk Score** (0–100): weighted blend of credit spreads + GPR + real yields relevant to the field. 100 = most stressed.

Then the **Action Quadrant** for the field is determined by (Valuation, Sentiment):
- **BUY** (val ≤ 50, sent ≤ 50)
- **CAUTION** (val ≤ 50, sent ≥ 50) — Oliver's "running hot but cheap" warning
- **TRAP** (val ≥ 50, sent ≤ 50)
- **BUBBLE** (val ≥ 50, sent ≥ 50)

Macro/Risk overlays as a colored border: green (safe regime) → red (broken regime). A BUY in a red regime is downgraded to "WAIT".

A single overall **Worldview Score** is exposed too, mostly for the top of the dashboard:
`Worldview Score = w1·(100 − Valuation) + w2·(50 − |Sentiment − 50|) + w3·(100 − Macro/Risk)`
…where the middle term penalizes both euphoria *and* panic (we want neutral-to-fearful, not extreme-fearful, since extreme-fearful often means something is breaking).

Default weights: 0.4 / 0.3 / 0.3. All weights live in YAML and are tunable.

---

## Free data plumbing

**Tier 1 — APIs with stable free access (preferred):**
- **FRED** via `fredapi`. Free key. Backbone — most macro + credit spreads + commodities.
- **yfinance** — equities, ETFs, futures, FX, indices. No key. Cache aggressively (it's flaky).
- **Stooq** via `pandas-datareader` — yfinance backup.
- **EIA** — energy inventories. Free key.
- **UCDP** — armed conflicts REST. No key.
- **Eurostat** — JSON-stat REST. No key.
- **ECB SDW** — REST. No key.

**Tier 2 — Free CSV downloads (scheduled fetch):**
- Shiller CAPE (US): `econ.yale.edu/~shiller/data/ie_data.xls`
- GPR Index: `matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls`
- EPU (US, EU): `policyuncertainty.com/media/All_Country_Data.csv`
- AAII sentiment: `aaii.com/files/surveys/sentiment.xls`
- NAAIM: `naaim.org/programs/naaim-exposure-index/`
- Baker Hughes rig count weekly CSV
- iShares ETF holdings: daily CSV (IVV, URTH, EUFN, ITA, EUAD)

**Tier 3 — Light scraping:**
- CNN Fear & Greed JSON endpoint
- multpl.com (Shiller PE, dividend yield, etc.)
- slickcharts.com (S&P 500 weights)
- stockcharts.com `$SPXA200R` (breadth)
- tradingeconomics (PMI, Baltic indices)
- ISM headline scrape

**Tier 4 — Skip for v1:** Bloomberg, Refinitiv, paid Trading Economics, paid AAII.

---

## Architecture

```
worldview/
  config/
    metrics.yaml          # one row per metric: id, source, transform, category, field, weight, flag thresholds
    fields.yaml           # field → metric_id list + weights
    sources.yaml          # API keys, cache TTLs, retry policy
  fetchers/
    base.py               # Fetcher ABC: fetch(metric) -> DataFrame[date, value]
    fred.py
    yfinance_fetcher.py
    csv_sources.py        # Shiller, GPR, AAII, EPU, NAAIM, Baker Hughes
    scrapers.py           # CNN F&G, slickcharts, multpl, stockcharts
    ucdp.py
    eia.py
    eurostat.py
    ecb.py
  store/
    db.py                 # SQLite engine, schema, upserts
    schema.sql            # metrics, observations, flags, runs
    worldview.db          # the database itself
  analysis/
    scoring.py            # percentile/z-score, label mapping, direction flip
    fields.py             # field-level Valuation/Sentiment/Macro composites
    flags.py              # threshold detection, flag history
    composite.py          # the Worldview Score
  webapp/
    main.py               # FastAPI app
    templates/
      snapshot.html       # current state, percentile bars, quadrants per field
      history.html        # state through time, regime markers
      metric.html         # drill-down per metric
    static/
      app.js              # plotly charts, refresh button
      styles.css
  run_snapshot.py         # CLI: refresh everything (or by category/field)
  README.md
```

### Database schema (sketch)
```sql
CREATE TABLE metrics (
  id            TEXT PRIMARY KEY,    -- e.g. "vix", "buffett_indicator"
  category      TEXT NOT NULL,       -- valuation / sentiment / macro / geo / energy / breadth
  field         TEXT,                -- ai / construction / finance / energy / defense / defensive / overall
  source        TEXT NOT NULL,
  source_ref    TEXT NOT NULL,       -- ticker, FRED series, URL
  direction     TEXT NOT NULL,       -- "bullish_high" or "bullish_low"
  cadence       TEXT NOT NULL,       -- daily / weekly / monthly / quarterly
  flag_high_pct REAL,                -- e.g. 90
  flag_low_pct  REAL,                -- e.g. 10
  weight        REAL NOT NULL DEFAULT 1.0,
  notes         TEXT
);

CREATE TABLE observations (
  metric_id  TEXT NOT NULL REFERENCES metrics(id),
  date       DATE NOT NULL,
  value      REAL NOT NULL,
  PRIMARY KEY (metric_id, date)
);

CREATE TABLE flags (
  metric_id  TEXT NOT NULL,
  date       DATE NOT NULL,
  side       TEXT NOT NULL,          -- "high" or "low"
  pct        REAL NOT NULL,
  value      REAL NOT NULL,
  PRIMARY KEY (metric_id, date, side)
);

CREATE TABLE runs (
  run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at DATETIME NOT NULL,
  finished_at DATETIME,
  status     TEXT NOT NULL,          -- ok / partial / failed
  log        TEXT
);
```

### Refresh cadence
- **Daily** (run via `python run_snapshot.py --daily`): prices, VIX/VVIX/MOVE, F&G, yields, credit spreads, GPR daily.
- **Weekly**: AAII, NAAIM, jobless claims, rig count, holdings CSVs, multpl scrapes.
- **Monthly**: CPI, PCE, ISM, EPU, GPR monthly, Shiller CAPE.
- **Quarterly**: GDP (for Buffett denominator), SLOOS, Buffett full update.
- **Idempotent**: every fetcher upserts on `(metric_id, date)`. Re-runs are safe.

### Web app
- **FastAPI** + **Jinja2** + **Plotly.js** (CDN). Single `uvicorn webapp.main:app --reload` to run.
- Routes:
  - `/` — Snapshot. Top banner: flagged metrics. Then a grid of field cards (AI / Construction / Finance / Energy / Defense / Defensives / Overall), each showing the 2×2 quadrant position + Valuation/Sentiment/Macro bars + a 3-month sparkline.
  - `/history` — Time series of the field scores + regime shading.
  - `/metric/{id}` — Single-metric drill-down: full history, percentile band, flag history.
  - `/api/snapshot.json` — JSON for the dashboard's frontend.
  - `/api/refresh` — kicks `run_snapshot.py` (debounced).
- Bind to `127.0.0.1` only. No auth needed.

---

## Implementation roadmap

**Milestone 0 — Skeleton (½ day)**
- Repo layout, `pyproject.toml`, `.env` for FRED/EIA keys.
- SQLite schema + `db.py` with upsert.
- `metrics.yaml` with the ~10 priority metrics: VIX, ^GSPC, ^STOXX, DGS10, T10Y2Y, BAMLH0A0HYM2, GPR daily, Brent, Gold, Buffett.

**Milestone 1 — Vertical slice (1 day)**
- FRED + yfinance fetchers with retry/cache.
- `run_snapshot.py --daily` populates DB end-to-end.
- `analysis/scoring.py` produces percentiles and labels.
- A bare-bones snapshot HTML rendered via FastAPI showing the 10 metrics with percentile bars.

**Milestone 2 — Full metric set + fields (1–2 days)**
- All Tier 1+2+3 sources wired.
- `fields.yaml` with weights; `analysis/fields.py` produces per-field Valuation/Sentiment/Macro.
- Snapshot shows the 2×2 quadrant per field.

**Milestone 3 — Flags + history (½ day)**
- Threshold flagging + `flags` table.
- `/history` route with regime shading.
- Banner on snapshot page.

**Milestone 4 — Polish (open-ended)**
- Drill-down pages, export to PNG/PDF, Worldview Score tuning, manual capex inputs (hyperscaler), email/Slack flag digest if Oliver wants it later.

---

## Resolved decisions (final)
1. **EU CAPE**: skipped for v1. We use a Buffett analog instead — Stoxx 600 aggregate market cap / Eurozone GDP — plus Stoxx 600 forward P/E. If we ever need true CAPE we'll compute from Stoxx 600 trailing earnings.
2. **Hyperscaler capex**: auto-fetched. `yfinance` `Ticker.quarterly_cashflow` exposes `Capital Expenditure` for each of MSFT / GOOGL / AMZN / META / ORCL. We sum them per quarter and store the total as `hyperscaler_capex_quarterly`. Caveats: yfinance lags the actual 10-Q by 2–5 days, and Amazon's capex includes finance leases (slight overstatement). Each ticker × quarter has an optional YAML override (`config/capex_overrides.yaml`) for corrections — Oliver edits, no uploader needed.
3. **Bitcoin**: included in the sentiment / positioning block as a *speculative-pulse* indicator alongside ARKK and MSTR. Not treated as a safe haven.
4. **Refresh**: manual via `python run_snapshot.py [--daily|--weekly|--monthly|--all]`. No scheduler in v1.

## Implementation notes carried into Milestone 0
- `config/capex_overrides.yaml` schema: `{ticker: {quarter_end_date: capex_usd}}` — values here win over yfinance.
- BTC realized vol = stdev of daily log returns × √365, 30d window. Computed in `analysis/derived.py`, not stored as a raw observation.
- EU Buffett analog: numerator from yfinance `^STOXX` × Stoxx 600 total shares (we'll need a small static reference or scrape STOXX's site for the divisor); denominator from Eurostat `naidq_10_gdp` quarterly.
