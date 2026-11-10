"""Command-line tool: read floor plan files and print their chair reports.

Run ``python -m chair_counter PLAN`` (or ``chair-counter PLAN`` after
installing). The report goes to standard output, in the exact format the old
system reads. A folder stands for every ``.txt`` plan in it. ``--approach``
picks the counting method (see ``APPROACHES``); both give the same report.

Everything else is optional and goes into the folder given by ``--output DIR``:

- ``DIR/<plan>_report.txt``: the report of each plan.
- With ``--animation``: a web page that animates the search, step by step,
  for both approaches, opening on the one ``--approach`` chose.
  One plan gives ``DIR/<plan>_search.html``; several give ``DIR/search.html``,
  with a drop-down to pick the house. ``--every N`` records one frame every
  ``N`` steps instead of every step, for a smaller page.

``<plan>`` is the plan's file name without ``.txt``, so several plans can share
one output folder.
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from .floor_plan import count_chairs, format_report
from .room_seeded import count_chairs_room_seeded

APPROACHES = {
    "connected-areas": count_chairs,
    "room-seeded": count_chairs_room_seeded,
}
"""The counting functions ``--approach`` can choose. Both give the same report.

- ``connected-areas`` (default): find every connected area, then name each one.
- ``room-seeded``: flood-fill from each room label; see ``room_seeded.py``.
"""
DEFAULT_APPROACH = "connected-areas"

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

more examples:
  %(prog)s --approach room-seeded rooms.txt
      count by flood-filling from each room name instead; same report
  %(prog)s rooms.txt --output output
      also save output/rooms_report.txt
  %(prog)s rooms.txt --output output --animation
      also save an animation of the search as output/rooms_search.html
  %(prog)s inputs --output output --animation
      every plan in inputs/: one report each, and output/search.html
      with a drop-down to pick the house
"""

REPORT_SUFFIX = "_report.txt"
ANIMATION_SUFFIX = "_search.html"
COMBINED_ANIMATION = "search.html"


def collect_plans(paths: Sequence[Path]) -> list[Path]:
    """Expand folders into the ``.txt`` plan files they contain.

    Args:
        paths: Plan files and folders, as given on the command line.

    Returns:
        The plan files, in the order given. A folder's files are sorted by name.

    Raises:
        ValueError: If a folder contains no ``.txt`` files, or two plans have
            the same file name, so their output files would overwrite each other.
    """
    plans = []
    for path in paths:
        if path.is_dir():
            found = sorted(path.glob("*.txt"))
            if not found:
                raise ValueError(f"No .txt floor plans in folder {path}.")
            plans.extend(found)
        else:
            plans.append(path)

    stems = [plan.stem for plan in plans]
    for stem in stems:
        if stems.count(stem) > 1:
            raise ValueError(f"Two plans are named {stem!r}; their output files would clash.")
    return plans


def report_file(plan: Path, folder: Path) -> Path:
    """Return where a plan's report is saved, e.g. ``inputs/rooms.txt`` -> ``folder/rooms_report.txt``."""
    return folder / f"{plan.stem}{REPORT_SUFFIX}"


def animation_file(plans: Sequence[Path], folder: Path) -> Path:
    """Return where the animation is saved: ``<plan>_search.html``, or ``search.html`` for several plans."""
    if len(plans) == 1:
        return folder / f"{plans[0].stem}{ANIMATION_SUFFIX}"
    return folder / COMBINED_ANIMATION


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
    parser.add_argument(
        "plans",
        type=Path,
        nargs="+",
        metavar="plan",
        help="a floor plan text file, or a folder of .txt plans; several may be given",
    )
    parser.add_argument(
        "--approach",
        choices=APPROACHES,
        default=DEFAULT_APPROACH,
        help=(
            "how to count: connected-areas finds every enclosed area first, "
            "room-seeded fills outwards from each room name "
            f"(default: {DEFAULT_APPROACH}; both give the same report)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="DIR",
        help=f"also save each report to DIR/<plan>{REPORT_SUFFIX}, creating DIR if needed",
    )
    parser.add_argument(
        "--animation",
        action="store_true",
        help=(
            f"with --output, also write a web page that animates the search of both "
            f"approaches, opening on --approach: "
            f"DIR/<plan>{ANIMATION_SUFFIX}, or DIR/{COMBINED_ANIMATION} for several plans"
        ),
    )
    parser.add_argument(
        "--every",
        type=int,
        metavar="N",
        help="with --animation, record one frame every N steps (default: every step)",
    )
    return parser


def main(argv: Sequence[str] | None = None, prog: str | None = None) -> None:
    """Read the plans, print their reports and save the requested files.

    Every plan is read and counted before anything is printed or saved, so an
    invalid plan leaves no partial output. Errors such as a missing file or an
    invalid plan are reported by argparse as a one-line message, and the
    process exits with code 2.

    Args:
        argv: Command-line arguments without the program name. ``None`` reads
            them from ``sys.argv``. Tests pass a list.
        prog: Program name shown in usage and help text.
    """
    parser = build_parser(prog)
    args = parser.parse_args(argv)
    if args.animation and args.output is None:
        parser.error("--animation needs --output DIR to know where to write the page")
    if args.every is not None and not args.animation:
        parser.error("--every only applies with --animation")
    if args.every is not None and args.every < 1:
        parser.error("--every must be at least 1")
    count = APPROACHES[args.approach]

    try:
        paths = collect_plans(args.plans)
    except ValueError as error:
        parser.error(str(error))

    results = []  # (path, plan text, report text) for each plan.
    for path in paths:
        try:
            # utf-8-sig also accepts files that start with a byte order mark (BOM).
            plan = path.read_text(encoding="utf-8-sig")
            text = format_report(count(plan))
        except OSError as error:  # The message already names the file.
            parser.error(str(error))
        except ValueError as error:  # An invalid plan, or not UTF-8 text.
            parser.error(f"{path}: {error}")
        results.append((path, plan, text))

    for index, (path, _, text) in enumerate(results):
        if len(results) > 1:  # Head each report with its file; one plan prints the report only.
            if index:
                print()
            print(f"== {path}")
        print(text)

    if args.output is None:
        return
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        for path, _, text in results:
            report_file(path, args.output).write_text(text + "\n", encoding="utf-8")
        if args.animation:
            # Imported here so a plain report never loads the animation code.
            from .plotly_html import house_name, write_html

            houses = [(house_name(path), plan) for path, plan, _ in results]
            # Record every approach, the chosen one first, so the page opens on it
            # and its drop-down can switch to the others.
            order = [args.approach] + [key for key in APPROACHES if key != args.approach]
            write_html(houses, animation_file(paths, args.output), every=args.every, approaches=order)
    except OSError as error:
        parser.error(str(error))
