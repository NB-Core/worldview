"""Config loading: YAML metric/field registry + .env API keys.

This module is the *only* place YAML/env files are read. Everything else
takes already-parsed `Metric` / `FieldDef` objects. That keeps fetchers and
analysis decoupled from on-disk format and makes them trivial to test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .models import Cadence, Category, FieldDef, Metric, Polarity

# ── Paths ─────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """Return the directory containing metrics.yaml / fields.yaml.

    Honors `WORLDVIEW_CONFIG_DIR` if set, else `<project>/config`.
    """
    override = os.getenv("WORLDVIEW_CONFIG_DIR")
    return Path(override) if override else PROJECT_ROOT / "config"


def db_path() -> Path:
    """Return the SQLite DB path. Honors `WORLDVIEW_DB_PATH`."""
    override = os.getenv("WORLDVIEW_DB_PATH")
    if override:
        return Path(override)
    return PROJECT_ROOT / "worldview" / "store" / "worldview.db"


# ── Settings ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved runtime settings."""

    fred_api_key: str | None
    eia_api_key: str | None
    db_path: Path
    config_dir: Path


def load_settings(env_file: Path | None = None) -> Settings:
    """Load settings from `.env` (if present) + environment.

    Args:
        env_file: optional override path to a .env file (used by tests).
    """
    if env_file is not None:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(PROJECT_ROOT / ".env", override=False)

    return Settings(
        fred_api_key=os.getenv("FRED_API_KEY") or None,
        eia_api_key=os.getenv("EIA_API_KEY") or None,
        db_path=db_path(),
        config_dir=config_dir(),
    )


# ── Metric registry ───────────────────────────────────────────────────────────


def _parse_directions(raw: dict) -> dict[str, int]:
    if any(k not in {"valuation", "sentiment", "macro_risk", "price_momentum"}
           or type(v) is not int or v not in {-1, 1} for k, v in raw.items()):
        raise ValueError("score_directions requires block: +1 or -1")
    return dict(raw)


def _parse_metric(row: dict) -> Metric:
    """Parse one YAML row into a `Metric`. Raises `ValueError` on bad input."""
    try:
        return Metric(
            id=row["id"],
            category=Category(row["category"]),
            field=row.get("field", "overall"),
            source=row["source"],
            source_ref=row["source_ref"],
            polarity=Polarity(row["polarity"]),
            cadence=Cadence(row["cadence"]),
            weight=float(row.get("weight", 1.0)),
            flag_high_pct=row.get("flag_high_pct"),
            flag_low_pct=row.get("flag_low_pct"),
            score_directions=_parse_directions(row.get("score_directions", {})),
            notes=row.get("notes", "") or "",
        )
    except KeyError as e:
        raise ValueError(f"metric row missing required key {e!s}: {row!r}") from e


def load_metrics(path: Path | None = None) -> list[Metric]:
    """Load and validate the metric registry.

    Args:
        path: explicit path to metrics.yaml; defaults to `config_dir()/metrics.yaml`.

    Returns:
        List of Metric objects. Order matches the YAML file.
    """
    p = path or config_dir() / "metrics.yaml"
    raw = yaml.safe_load(p.read_text())
    rows = raw.get("metrics", []) if raw else []
    metrics = [_parse_metric(row) for row in rows]
    _check_unique_ids(metrics)
    return metrics


def _check_unique_ids(metrics: list[Metric]) -> None:
    seen: set[str] = set()
    for m in metrics:
        if m.id in seen:
            raise ValueError(f"duplicate metric id: {m.id!r}")
        seen.add(m.id)


def load_fields(path: Path | None = None) -> dict[str, FieldDef]:
    """Load field rollups from `fields.yaml`."""
    p = path or config_dir() / "fields.yaml"
    raw = yaml.safe_load(p.read_text())
    rows = (raw or {}).get("fields", {})
    out: dict[str, FieldDef] = {}
    for fid, fdef in rows.items():
        out[fid] = FieldDef(
            id=fid,
            label=fdef.get("label", fid),
            valuation=list(fdef.get("valuation") or []),
            sentiment=list(fdef.get("sentiment") or []),
            macro_risk=list(fdef.get("macro_risk") or []),
        )
    return out


def load_score_weights(path: Path | None = None) -> dict[str, float]:
    """Load the Worldview Score weights (valuation/sentiment/macro_risk)."""
    p = path or config_dir() / "fields.yaml"
    raw = yaml.safe_load(p.read_text()) or {}
    weights = raw.get("worldview_score_weights") or {}
    # sane defaults if missing
    return {
        "valuation": float(weights.get("valuation", 0.4)),
        "sentiment": float(weights.get("sentiment", 0.3)),
        "macro_risk": float(weights.get("macro_risk", 0.3)),
    }


def load_sentiment_mode(path: Path | None = None) -> str:
    """Load `worldview_sentiment_mode` from fields.yaml.

    Returns "penalize_greed" or "penalize_extremes". Anything else falls
    back to the default to keep the dashboard from crashing on a typo.
    """
    p = path or config_dir() / "fields.yaml"
    raw = yaml.safe_load(p.read_text()) or {}
    mode = raw.get("worldview_sentiment_mode", "penalize_greed")
    return mode if mode in ("penalize_greed", "penalize_extremes") else "penalize_greed"


@lru_cache(maxsize=1)
def cached_metrics() -> list[Metric]:
    """Cached `load_metrics()` for hot paths (e.g. webapp)."""
    return load_metrics()
