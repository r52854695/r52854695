#!/usr/bin/env python3
"""Standalone SVG + SMIL validator for the generated assets.

    python tools/validate.py                     # every asset in output/
    python tools/validate.py output/hero-banner.svg

``python build.py`` runs the same checks automatically after each write; this
entry point exists for CI steps and for inspecting assets that were committed
by an earlier build.  Exits non-zero if any asset fails.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from config import OUTPUT_DIR  # noqa: E402 - path bootstrap must come first
from generator.validation import validate_file  # noqa: E402


def main(argv: Sequence[str]) -> int:
    """Validate the requested assets and return a process exit code."""
    targets = [Path(argument) for argument in argv] or sorted(OUTPUT_DIR.glob("*.svg"))
    if not targets:
        print(f"\n  no SVG assets found in {OUTPUT_DIR}; run `python build.py` first\n")
        return 1

    print("\n  svg + smil validation\n")
    reports = [validate_file(path) for path in targets]
    for report in reports:
        print(report.format_summary())
        if not report.ok:
            print(report.format_details())

    failures = [report for report in reports if not report.ok]
    checked = sum(report.animation_count for report in reports)
    print(
        f"\n  {len(reports) - len(failures)}/{len(reports)} assets valid · "
        f"{checked} animations checked\n"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
