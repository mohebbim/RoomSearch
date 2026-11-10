"""Read a floor plan file and print the chair report."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from .floor_plan import count_chairs, format_report

DESCRIPTION = (
    "Count the chairs in an ASCII floor plan, "
    "for the whole apartment and for each named room."
)

EPILOG = r"""floor plan format (UTF-8 text file):
  walls       + - | / \
  chairs      W P S C   (one character per chair)
  room names  in parentheses inside the room, e.g. (office)
  Use spaces for everything else. Rooms must be fully enclosed by walls.

example:
  rooms.txt:
    +-----------+
    | (office)  |
    |  W     C  |
    +-----------+

  command:
    %(prog)s rooms.txt

  output:
    total:
    W: 1, P: 0, S: 0, C: 1
    office:
    W: 1, P: 0, S: 0, C: 1
"""


def main(argv: Sequence[str] | None = None, prog: str | None = None) -> None:
    """Read a UTF-8 floor plan and write the report to standard output."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("plan", type=Path, help="path to the floor plan text file")
    args = parser.parse_args(argv)

    try:
        plan = args.plan.read_text(encoding="utf-8-sig")
        report = count_chairs(plan)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(format_report(report))
