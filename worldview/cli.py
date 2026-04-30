"""Command-line entry point: `python -m worldview.cli ...`.

Subcommands:
    init-db     create the SQLite store + tables, then exit.
    snapshot    fetch + persist + score. Prints a summary to stdout.
    list        list metrics in the registry.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_metrics, load_settings
from .snapshot import run_snapshot
from .store import Database


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )


def cmd_init_db(_args: argparse.Namespace) -> int:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init_schema()
    print(f"DB initialized at {settings.db_path}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    result = run_snapshot(cadence=args.cadence, only=args.only)
    print(f"\nFetched {result.fetched} rows. Failures: {result.failed or 'none'}")
    if result.skipped:
        print(f"Skipped (fetcher not yet wired): {', '.join(result.skipped)}")

    if result.worldview is not None:
        print(f"\nWorldview Score: {result.worldview:>5.1f}")

    if result.fields:
        print("\nField rollups:")
        for fid, fs in result.fields.items():
            v = "—" if fs.valuation is None else f"{fs.valuation:>5.1f}"
            s = "—" if fs.sentiment is None else f"{fs.sentiment:>5.1f}"
            r = "—" if fs.macro_risk is None else f"{fs.macro_risk:>5.1f}"
            print(f"  {fid:<13}  val={v}  sent={s}  risk={r}  → {fs.quadrant}")

    if result.scores:
        print("\nMetrics:")
        for mid, sc in sorted(result.scores.items()):
            flag = " ⚑" if (sc.flagged_high or sc.flagged_low) else ""
            print(
                f"  {mid:<22}  asof {sc.asof}  "
                f"val={sc.value:>10.2f}  pct={sc.percentile:>5.1f}  "
                f"{sc.label}{flag}"
            )

    return 0 if not result.failed else 1


def cmd_list(_args: argparse.Namespace) -> int:
    for m in load_metrics():
        print(
            f"{m.id:<22}  {m.category.value:<10}  {m.field:<13}  "
            f"{m.source:<10}  {m.source_ref}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worldview",
        description="Local snapshot of the global economy + markets.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="create the SQLite schema")
    p_init.set_defaults(func=cmd_init_db)

    p_snap = sub.add_parser("snapshot", help="refresh + score")
    p_snap.add_argument(
        "--cadence",
        choices=["daily", "weekly", "monthly", "quarterly", "all"],
        default="daily",
    )
    p_snap.add_argument(
        "--only",
        nargs="*",
        help="restrict to specific metric ids (debugging)",
    )
    p_snap.set_defaults(func=cmd_snapshot)

    p_list = sub.add_parser("list", help="list metrics in the registry")
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
