"""Read a floor plan file and print the chair report."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from .floor_plan import count_chairs, format_report


def main(argv: Sequence[str] | None = None) -> None:
    """Read a UTF-8 floor plan and write the report to standard output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="path to the floor plan text file")
    args = parser.parse_args(argv)

    try:
        plan = args.plan.read_text(encoding="utf-8-sig")
        report = count_chairs(plan)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(format_report(report))
