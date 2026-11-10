"""Command-line tool: read a floor plan file and print the chair report.

Run ``python -m chair_counter PLAN`` (or ``chair-counter PLAN`` after
installing). The report goes to standard output. ``--output DIR`` also saves it
to ``DIR/<plan>_report.txt``, and ``--animation`` adds an animated
``DIR/<plan>_search.html``, where ``<plan>`` is the plan's file name without
``.txt``. Different plans can therefore share one output folder.
"""

import argparse
import io
from collections.abc import Sequence
from pathlib import Path

from .floor_plan import count_chairs, format_report

DESCRIPTION = (
    "Count the chairs in an ASCII floor plan, "
    "for the whole apartment and for each named room."
)

EPILOG = r"""floor plan format (UTF-8 text file):
  walls       + - | / \
  chairs      W wooden, P plastic, S sofa, C china (one character per chair)
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

  To also save output/rooms_report.txt, and an animation of the search in
  output/rooms_search.html:
    %(prog)s rooms.txt --output output --animation
"""

REPORT_SUFFIX = "_report.txt"
ANIMATION_SUFFIX = "_search.html"


def output_files(plan: Path, folder: Path) -> tuple[Path, Path]:
    """Return the report and animation paths for a plan in an output folder.

    The plan's file name without its extension comes first, so
    ``inputs/rooms.txt`` gives ``rooms_report.txt`` and ``rooms_search.html``.
    """
    return folder / f"{plan.stem}{REPORT_SUFFIX}", folder / f"{plan.stem}{ANIMATION_SUFFIX}"


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """Create the argument parser, including the format guide shown by ``--help``.

    Args:
        prog: Program name for usage and help text. ``None`` lets argparse use
            the script name, which suits the installed ``chair-counter`` command.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("plan", type=Path, help="path to the floor plan text file")
    parser.add_argument(
        "--output",
        type=Path,
        metavar="DIR",
        help=f"also save the report to DIR/<plan>{REPORT_SUFFIX}, creating DIR if needed",
    )
    parser.add_argument(
        "--animation",
        action="store_true",
        help=f"with --output, also write an animation of the search to DIR/<plan>{ANIMATION_SUFFIX}",
    )
    return parser


def main(argv: Sequence[str] | None = None, prog: str | None = None) -> None:
    """Read a plan, print its report and save the requested files.

    Errors such as a missing file or an invalid plan are reported by argparse
    as a one-line message, and the process exits with code 2.

    Args:
        argv: Command-line arguments without the program name. ``None`` reads
            them from ``sys.argv``. Tests pass a list.
        prog: Program name shown in usage and help text.
    """
    parser = build_parser(prog)
    args = parser.parse_args(argv)
    if args.animation and args.output is None:
        parser.error("--animation needs --output DIR to know where to write the page")

    try:
        # utf-8-sig also accepts files that start with a byte order mark (BOM).
        plan = args.plan.read_text(encoding="utf-8-sig")
        report = count_chairs(plan)
    except (OSError, ValueError) as error:  # ValueError includes bad encodings.
        parser.error(str(error))

    text = format_report(report)
    print(text)

    if args.output is None:
        return
    report_path, animation_path = output_files(args.plan, args.output)
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
        if args.animation:
            # Imported here so the plain report never loads the visualisers.
            from .plotly_html import house_name, write_html

            houses = [(house_name(args.plan), plan)]
            write_html(houses, animation_path, io.StringIO())
    except OSError as error:
        parser.error(str(error))
