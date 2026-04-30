#!/usr/bin/env python3
"""Convenience wrapper: `python scripts/run_snapshot.py --cadence daily`.

Identical to `python -m worldview.cli snapshot ...`. Exists because the
project brief in CLAUDE.md mentions this script by name.
"""

from __future__ import annotations

import sys

from worldview.cli import main

if __name__ == "__main__":
    # Re-route argv so this script's flags map to the `snapshot` subcommand.
    argv = ["snapshot", *sys.argv[1:]]
    sys.exit(main(argv))
