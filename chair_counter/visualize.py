"""Animate how count_chairs splits a floor plan into areas and counts chairs.

Run ``python -m chair_counter.visualize PLAN``. This is a learning and debugging
aid with no counting logic of its own. It calls the same steps as count_chairs
(_parse_plan, _find_areas, _add_area) and replays each area's cells in the order
the search reached them.
"""

import argparse
import os
import shutil
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .floor_plan import (
    CHAIR_TYPES,
    WALLS,
    Area,
    ChairReport,
    Position,
    _add_area,
    _find_areas,
    _parse_plan,
    format_report,
)

AREA_COLOURS = (24, 28, 94, 54, 30, 58, 89, 23, 130, 60)
OUTSIDE_COLOUR = 236
PROBLEM_COLOUR = 160
FRONTIER_STYLE = "48;5;220;38;5;16"
WALL_STYLE = "38;5;245"
HEADER = (
    "Scan the grid row by row. Each open cell not seen yet starts a new area,\n"
    "which spreads up, down, left and right until walls stop it."
)


@dataclass
class ShownArea:
    """An area from _find_areas plus what the display needs to know about it."""

    number: int
    area: Area
    problem: str | None = None

    def summary(self) -> str:
        """Describe the area in one line."""
        area = self.area
        chairs = ", ".join(f"{chair}: {area.chairs[chair]}" for chair in CHAIR_TYPES)
        if area.is_exterior:
            text = f"outside the walls: {len(area.cells)} cells, not counted"
            if area.names:
                text += f", labels found: {', '.join(area.names)}"
            if area.chairs:
                text += f", chairs found: {chairs}"
        else:
            label = f" ({', '.join(area.names)})" if area.names else " (no label)"
            text = f"area {self.number}{label}: {len(area.cells)} cells, {chairs}"
        if self.problem:
            text += f"  <-- {self.problem}"
        return text


class Canvas:
    """Draw the padded grid, colouring each cell by the area that owns it."""

    def __init__(self, plan: str, grid: list[str], colour: bool) -> None:
        self.grid = grid
        self.colour = colour
        self.owner: dict[Position, ShownArea] = {}
        # The parser blanks room labels out of the grid. Keep their text for display.
        self.label_text: dict[Position, str] = {}
        for row, line in enumerate(plan.splitlines(), start=1):
            for column, char in enumerate(line, start=1):
                if char != " " and grid[row][column] == " ":
                    self.label_text[row, column] = char

    def draw(self, current: ShownArea, frontier: set[Position]) -> str:
        """Return the grid as text, highlighting the cells reached most recently."""
        rows = []
        for row, line in enumerate(self.grid):
            parts = []
            for column, cell in enumerate(line):
                position = (row, column)
                char = self.label_text.get(position, cell)
                shown = self.owner.get(position)
                if self.colour:
                    parts.append(self._style(position, char, cell, shown, frontier))
                elif shown is current and char == " ":
                    parts.append(".")
                else:
                    parts.append(char)
            rows.append("".join(parts))
        return "\n".join(rows)

    def _style(
        self,
        position: Position,
        char: str,
        cell: str,
        shown: ShownArea | None,
        frontier: set[Position],
    ) -> str:
        if cell in WALLS:
            return f"\x1b[{WALL_STYLE}m{char}\x1b[0m"
        if position in frontier:
            style = FRONTIER_STYLE
        elif shown is None:
            return char
        elif shown.problem:
            style = f"48;5;{PROBLEM_COLOUR}"
        elif shown.area.is_exterior:
            style = f"48;5;{OUTSIDE_COLOUR}"
        else:
            style = f"48;5;{AREA_COLOURS[(shown.number - 1) % len(AREA_COLOURS)]}"
        if cell in CHAIR_TYPES or position in self.label_text:
            style += ";1;97"
        return f"\x1b[{style}m{char}\x1b[0m"


class Screen:
    """Write frames either in place (animated) or one after another."""

    def __init__(self, out: TextIO, animate: bool, delay: float) -> None:
        self.out = out
        self.animate = animate
        self.delay = delay
        if animate:
            self.out.write("\x1b[2J\x1b[?25l")

    def show(
        self,
        canvas: Canvas,
        shown: list[ShownArea],
        current: ShownArea,
        reached: int,
        frontier: set[Position] = frozenset(),
        pause: float = 0.0,
    ) -> None:
        if current.area.is_exterior:
            where = "outside, started in the blank border added around the plan"
        else:
            row, column = current.area.cells[0]
            where = f"area {current.number}, started at line {row}, column {column}"
        now = f"Now: {where}, {reached} cells so far"
        history = [item.summary() for item in shown if item is not current]
        if self.animate:
            spare = shutil.get_terminal_size().lines - len(canvas.grid) - 6
            history = history[-spare:] if spare > 0 else []
        text = "\n".join([HEADER, "", canvas.draw(current, frontier), "", now, *history])
        if self.animate:
            self.out.write("\x1b[H" + text + "\x1b[J")
            self.out.flush()
            time.sleep(pause or self.delay)
        else:
            self.out.write(text + "\n\n")

    def close(self) -> None:
        if self.animate:
            self.out.write("\x1b[?25h\n")
            self.out.flush()


def run(
    plan: str,
    out: TextIO,
    *,
    colour: bool,
    animate: bool,
    delay: float = 0.03,
    cells_per_frame: int | None = None,
    step: bool = False,
) -> int:
    """Visualise count_chairs on one plan and return a process exit code."""
    grid, labels = _parse_plan(plan)
    canvas = Canvas(plan, grid, colour)
    if animate and len(grid) + 8 > shutil.get_terminal_size().lines:
        animate = False  # The frame would scroll, so print frames one after another.
    open_cells = sum(cell not in WALLS for line in grid for cell in line)
    batch = cells_per_frame or max(1, open_cells // 300)
    screen = Screen(out, animate, delay)
    report = ChairReport(total=Counter(), rooms={})
    shown: list[ShownArea] = []
    first_error: str | None = None

    try:
        for number, area in enumerate(_find_areas(grid, labels)):
            current = ShownArea(number, area)
            shown.append(current)
            # Replay the fill in the order _walk_area reached the cells.
            for done in range(0, len(area.cells), batch):
                reached = area.cells[done:done + batch]
                for position in reached:
                    canvas.owner[position] = current
                if animate:
                    screen.show(canvas, shown, current, done + len(reached), set(reached))

            try:
                _add_area(report, area)
            except ValueError as error:
                # count_chairs would stop here. Keep going to show the rest of the plan.
                current.problem = str(error)
                if first_error is None:
                    first_error = str(error)

            screen.show(canvas, shown, current, len(area.cells), pause=delay * 15)
            if step:
                out.write("\nPress Enter for the next area...")
                out.flush()
                input()
    finally:
        screen.close()

    out.write("\nAreas found:\n")
    for item in shown:
        out.write(f"  {item.summary()}\n")

    if first_error is not None:
        out.write(f"\ncount_chairs rejects this plan: {first_error}\n")
        return 1
    out.write("\nReport:\n" + format_report(report) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Parse arguments, read the plan and run the visualisation."""
    parser = argparse.ArgumentParser(
        prog="python -m chair_counter.visualize",
        description="Watch how the chair counter finds each area of a floor plan.",
    )
    parser.add_argument("plan", type=Path, help="path to the floor plan text file")
    parser.add_argument(
        "--delay", type=float, default=0.03, help="seconds per frame (default 0.03)"
    )
    parser.add_argument(
        "--cells-per-frame",
        type=int,
        metavar="N",
        help="cells to fill between frames (default: about 300 frames in total)",
    )
    parser.add_argument(
        "--step", action="store_true", help="wait for Enter after each area"
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="no colour or animation; print one frame per area, marking it with dots",
    )
    args = parser.parse_args(argv)
    if args.cells_per_frame is not None and args.cells_per_frame < 1:
        parser.error("--cells-per-frame must be at least 1")

    try:
        plan = args.plan.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as error:
        parser.error(str(error))

    fancy = not args.plain and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if fancy and os.name == "nt":
        os.system("")  # Makes older Windows consoles process ANSI escape codes.

    try:
        code = run(
            plan,
            sys.stdout,
            colour=fancy,
            animate=fancy,
            delay=args.delay,
            cells_per_frame=args.cells_per_frame,
            step=args.step,
        )
    except ValueError as error:  # The plan could not be parsed at all.
        parser.error(str(error))
    except (KeyboardInterrupt, EOFError):
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
