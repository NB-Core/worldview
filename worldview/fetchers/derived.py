"""Derived metrics — computed from already-stored observations.

A derived metric is a pandas series that's a function of one or more *raw*
metrics. Examples:

    xlk_xlu_ratio    = XLK / XLU              (AI power-demand proxy)
    gold_copper      = Gold / Copper          (recession signal)
    gold_oil         = Gold / Brent           (energy stress signal)
    italy_de_spread  = it_10y - de_10y        (Eurozone risk)

Derived metrics use `source: derived` in metrics.yaml and the `source_ref`
names a recipe registered below. The fetcher reads inputs from the SQLite
store rather than the network.

This keeps the run_snapshot pipeline two-pass: raw fetchers run first,
then derived fetchers — same code path, no special-casing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd

from ..models import Metric
from ..store import Database
from .base import Fetcher, FetchError

# A recipe takes a (db, start) and returns a pandas Series.
Recipe = Callable[[Database, date], pd.Series]


def _ratio(num_id: str, den_id: str) -> Recipe:
    """Return a recipe computing num/den from two stored series."""
    def _recipe(db: Database, start: date) -> pd.Series:
        n = db.get_observations(num_id, since=start)
        d = db.get_observations(den_id, since=start)
        if n.empty or d.empty:
            return pd.Series(dtype=float)
        # Align on common dates so we don't create artificial gaps.
        aligned = pd.concat([n.rename("n"), d.rename("d")], axis=1).dropna()
        return (aligned["n"] / aligned["d"]).rename(num_id + "_" + den_id)
    return _recipe


def _diff(left_id: str, right_id: str) -> Recipe:
    """Return a recipe computing left - right."""
    def _recipe(db: Database, start: date) -> pd.Series:
        a = db.get_observations(left_id, since=start)
        b = db.get_observations(right_id, since=start)
        if a.empty or b.empty:
            return pd.Series(dtype=float)
        aligned = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
        return (aligned["a"] - aligned["b"]).rename(left_id + "_minus_" + right_id)
    return _recipe


# Public registry. Keys are what shows up in `metric.source_ref`.
def _sp500_div_gdp(db: Database, start: date) -> pd.Series:
    """Legacy S&P index-level / nominal GDP proxy, NOT market-cap / GDP.

    The index divisor changes; historical ranks are not equivalent to a Buffett
    indicator. Retained solely for legacy comparisons; excluded from valuation.
    GDP observation dates are period dates, not verified release dates.
    """
    p = db.get_observations("sp500_close", since=start)
    g = db.get_observations("us_gdp", since=start)
    if p.empty or g.empty:
        return pd.Series(dtype=float)
    aligned = pd.concat({"p": p, "g": g}, axis=1).sort_index()
    aligned["g"] = aligned["g"].ffill()
    aligned = aligned.dropna()
    return (aligned["p"] / aligned["g"]).rename("buffett_indicator")


def _earnings_yield_minus_10y(db: Database, start: date) -> pd.Series:
    """Equity risk premium proxy: (1 / sp500_pe * 100) - us_10y.

    Positive = stocks yield more than risk-free rate. Negative = stocks
    pricing in expected returns below Treasuries — a warning historically
    associated with severe drawdowns. The Fed Model in its raw form.
    """
    pe = db.get_observations("sp500_pe", since=start)
    y10 = db.get_observations("us_10y", since=start)
    if pe.empty or y10.empty:
        return pd.Series(dtype=float)
    aligned = pd.concat({"pe": pe, "y10": y10}, axis=1).sort_index()
    aligned = aligned.ffill().dropna()
    return ((100.0 / aligned["pe"]) - aligned["y10"]).rename("equity_risk_premium")


def _hy_minus_ig(db: Database, start: date) -> pd.Series:
    """HY OAS minus IG OAS — credit dispersion.

    Widening means junk spreads are blowing out faster than IG; the credit
    market is discriminating against weaker balance sheets first. Often
    leads equity drawdowns.
    """
    return _diff("hy_oas_us", "ig_oas_us")(db, start)


def _us_market_cap_div_gdp(db: Database, start: date) -> pd.Series:
    """Quarterly public-equity cap (millions) / GDP SAAR (billions), percent.

    Join identical reference periods only. No interpolation, no index fallback,
    no assertion that reference dates are publication dates.
    """
    cap = db.get_observations("us_equity_market_cap", since=start)
    gdp = db.get_observations("us_gdp", since=start)
    if cap.empty or gdp.empty:
        return pd.Series(dtype=float)
    data = pd.concat({"cap": cap, "gdp": gdp}, axis=1).dropna()
    data = data[(data["gdp"] > 0) & (data["cap"] > 0)]
    return (data["cap"] / 1000.0 / data["gdp"] * 100.0).rename("us_market_cap_gdp")


RECIPES: dict[str, Recipe] = {
    "xlk_div_xlu":              _ratio("xlk", "xlu"),
    "gold_div_copper":          _ratio("gold", "copper"),
    "gold_div_brent":           _ratio("gold", "brent"),
    "italy_minus_bund":         _diff("it_10y", "de_10y"),
    "rsp_div_spy":              _ratio("rsp", "spy"),
    "us_market_cap_div_gdp": _us_market_cap_div_gdp,
    "sp500_div_gdp":            _sp500_div_gdp,
    "earnings_yield_minus_10y": _earnings_yield_minus_10y,
    "hy_minus_ig":              _hy_minus_ig,
}


class DerivedFetcher(Fetcher):
    """Computes one of the recipes above. Reads from the local DB."""

    source_name = "derived"

    def __init__(self, db: Database) -> None:
        self._db = db

    def fetch(self, metric: Metric, start: date) -> pd.Series:
        recipe = RECIPES.get(metric.source_ref)
        if recipe is None:
            raise FetchError(
                f"unknown derived recipe {metric.source_ref!r}. "
                f"Known: {sorted(RECIPES)}"
            )
        s = recipe(self._db, start)
        if s.empty:
            return pd.Series(dtype=float, name=metric.id)
        s.name = metric.id
        return s.sort_index()
