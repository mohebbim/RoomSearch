"""Show the chair counter's search step by step in the terminal.

Run ``python -m chair_counter.visualize PLAN``. Add ``--html FILE`` to write an
animated web page instead (see ``plotly_html.py``).

This module has no counting logic of its own. It runs the real search from
``floor_plan.py`` (``_parse_plan``, ``_find_areas`` and ``_add_area``) and passes
``Visualiser.trace`` as the search's ``trace`` hook. Each event the search
reports becomes one numbered step with a plain-English explanation, such as
"Look below line 3, col 5: line 4, col 5 is a wall '-', blocked."

How the pieces fit together:

- ``Visualiser`` turns events into steps and keeps the state needed to draw
  them: the stack, which area owns each cell, and the report so far. Every
  few steps it calls ``show_frame``, which draws the grid in the terminal.
  ``plotly_html.FrameRecorder`` overrides ``show_frame`` to record frames.
- ``run`` sets up a ``Visualiser`` for one plan and drives the search.
- ``main`` handles the command line.
"""

import argparse
import os
import shutil
import sys
import time
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

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

# Terminal colours are ANSI escape codes: "48;5;N" sets the background to colour
# N of the 256-colour palette, "38;5;N" sets the text colour, 97 is bright white
# text, 30 is black text, and 1 is bold.
AREA_COLOURS = (24, 28, 94, 54, 30, 58, 89, 23, 130, 60)
"""Background colours for enclosed areas, used in turn."""

STATE_STYLES = {
    "outside": "48;5;236",
    "problem": "48;5;52",
    "expanding": "48;5;201;97",
    "stack": "48;5;37;30",
    "look-scan": "48;5;220;30",
    "look-added": "48;5;34;97",
    "look-wall": "48;5;160;97",
    "look-visited": "48;5;25;97",
    "look-record": "48;5;214;30",
    "scan-path": "48;5;229;30",
}
"""Terminal style for each cell state from ``Visualiser.cell_state``."""

WALL_STYLE = "38;5;245"
"""Grey text for walls the search is not looking at."""

COLOUR_LEGEND = (
    "\x1b[48;5;201;97m expanding \x1b[0m \x1b[48;5;37;30m on stack \x1b[0m "
    "\x1b[48;5;34;97m pushed \x1b[0m \x1b[48;5;160;97m wall \x1b[0m "
    "\x1b[48;5;25;97m already reached \x1b[0m \x1b[48;5;214;30m recorded \x1b[0m "
    "\x1b[48;5;220;30m new area \x1b[0m \x1b[48;5;229;30m scan path \x1b[0m"
)
PLAIN_LEGEND = "Legend: * expanding, o on the stack, . reached in this area"

DIRECTIONS = {(-1, 0): "above", (1, 0): "below", (0, -1): "left of", (0, 1): "right of"}
"""Words for the four neighbour offsets, in the order ``_walk_area`` checks them."""

STACK_SHOWN = 6
"""How many stack entries the status lines list before saying "and N more"."""

RECENT_STEPS = 6
"""How many recent steps the animated terminal view lists under the grid."""


def counts_text(chairs: Counter[str]) -> str:
    """Format chair counts in report order, including zeros: ``W: 1, P: 0, S: 0, C: 2``."""
    return ", ".join(f"{chair}: {chairs[chair]}" for chair in CHAIR_TYPES)


def _upper_first(text: str) -> str:
    """Capitalise the first letter only, so room names keep their own case."""
    return text[:1].upper() + text[1:]


@dataclass
class ShownArea:
    """An area found by the search, plus what the display needs to know about it.

    Attributes:
        number: Order in which the scan found the area. 0 is the outside.
        area: The ``Area`` object the search is filling. It is updated live, so
            its cells, chairs and labels grow while the area is being filled.
        start: The cell where the scan started this area.
        problem: The error ``_add_area`` raised for this area, if any.
    """

    number: int
    area: Area
    start: Position
    problem: str | None = None

    @property
    def outside(self) -> bool:
        """Whether this is the outside of the building, using ``Area.is_exterior``."""
        # Before the first cell is recorded, ask the same question of the start cell.
        area = self.area if self.area.cells else Area([self.start], Counter(), [])
        return area.is_exterior

    @property
    def name(self) -> str:
        """A short name for step text, such as "the outside" or "area 2 (kitchen)"."""
        if self.outside:
            return "the outside"
        label = f" ({', '.join(self.area.names)})" if self.area.names else ""
        return f"area {self.number}{label}"

    def summary(self) -> str:
        """Describe the finished area in one line, including any problem."""
        area = self.area
        if self.outside:
            text = f"outside the walls: {len(area.cells)} cells, not counted"
            if area.names:
                text += f", labels found: {', '.join(area.names)}"
            if area.chairs:
                text += f", chairs found: {counts_text(area.chairs)}"
        else:
            label = f" ({', '.join(area.names)})" if area.names else " (no label)"
            text = f"area {self.number}{label}: {len(area.cells)} cells, {counts_text(area.chairs)}"
        if self.problem:
            text += f"  <-- {self.problem}"
        return text


class Visualiser:
    """Turn the search's trace events into numbered steps and show frames.

    The search calls ``trace`` for every event (see ``floor_plan.Trace``), and
    the driver calls ``area_finished`` after each area and ``finish`` at the end.
    Each of these produces one step through ``_step``. A step updates the text
    and the highlighted cells; every ``every`` steps, and after every finished
    area, ``show_frame`` draws the current state.

    Frames have two parts:

    - The grid, where ``cell_state`` decides how each cell looks: the cell being
      looked at, the cell being expanded, cells on the stack, filled areas,
      walls and untouched floor.
    - The status lines from ``status_lines``: the current step, the top of the
      stack, the area being filled, and the report so far.

    Subclasses can override ``show_frame`` to send frames elsewhere, as
    ``plotly_html.FrameRecorder`` does.

    Attributes:
        report: The report built by calling ``_add_area`` on each finished area,
            exactly as ``count_chairs`` does.
        shown: Every area found so far, in scan order.
        current: The area being filled, or ``None`` once the scan has finished.
        first_error: The first rule violation, which is the error
            ``count_chairs`` would raise. ``None`` if the plan is valid.
        label_text: The label characters ``_parse_plan`` removed from the grid,
            by position, so frames can still show room names.
    """

    def __init__(
        self,
        plan: str,
        grid: list[str],
        out: TextIO,
        *,
        colour: bool = False,
        animate: bool = False,
        delay: float = 0.0,
        every: int | None = None,
        step: bool = False,
        log: bool = True,
    ) -> None:
        """Prepare to visualise one plan.

        Args:
            plan: The plan text, used to show room labels in the grid.
            grid: The padded grid from ``_parse_plan``.
            out: Where to write steps and frames.
            colour: Draw the grid with terminal colours.
            animate: Redraw each frame in place instead of printing frames one
                after another.
            delay: Seconds to wait after each animated frame.
            every: Draw a frame every this many steps. ``None`` draws frames
                only when an area is finished.
            step: Pause for the Enter key after every frame.
            log: Print every step as a line of text. Ignored when animating,
                because the animated frame lists the recent steps instead.
        """
        self.grid = grid
        self.height, self.width = len(grid), len(grid[0])
        self.out = out
        self.colour = colour
        self.animate = animate
        self.delay = delay
        self.every = every
        self.pausing = step
        self.log = log and not animate
        self.label_text: dict[Position, str] = {}
        for row, line in enumerate(plan.splitlines(), start=1):
            for column, char in enumerate(line, start=1):
                if char != " " and grid[row][column] == " ":
                    self.label_text[row, column] = char

        # Search state, updated by the trace events.
        self.report = ChairReport(total=Counter(), rooms={})
        self.shown: list[ShownArea] = []
        self.owner: dict[Position, ShownArea] = {}  # Area of every popped cell.
        self.current: ShownArea | None = None
        self.stack: list[Position] = []
        self.first_error: str | None = None
        self.skipped: Counter[str] = Counter()  # Scan cells passed since the last step,
        self.skipped_cells: list[Position] = []  # by kind and by position.

        # Step and frame state.
        self.step_number = 0
        self.step_text = ""
        self.next_frame = 1  # Always draw the first step.
        self.recent: deque[str] = deque(maxlen=RECENT_STEPS)
        self.focus: Position | None = None  # The cell the current step looks at.
        self.focus_style = ""  # How that look turned out, e.g. "wall" or "added".
        self.source: Position | None = None  # The cell being expanded.
        self.scan_path: set[Position] = set()  # Cells the scan just walked past.
        self.closed = False
        if animate:
            self.out.write("\x1b[2J\x1b[?25l")  # Clear the screen and hide the cursor.

    # Search events ----------------------------------------------------------

    def trace(self, event: str, position: Position, **details: Any) -> None:
        """Receive one event from the search and turn it into a step.

        This is the ``trace`` function passed to ``_find_areas``. Scan events for
        walls and visited cells are only collected here; they are reported
        together with the next step, which shows them as the scan path, so the
        log is not flooded with them. The start of a new area always gets a
        frame, so it is never skipped.

        Args:
            event: ``"scan"``, ``"visit"``, ``"check"``, ``"label"`` or ``"chair"``.
            position: The cell the event is about.
            **details: Extra data for the event, described in ``floor_plan.Trace``.
        """
        if event == "scan":
            if details["result"] != "new area":
                self.skipped[details["result"]] += 1
                self.skipped_cells.append(position)
                return
            self.current = ShownArea(len(self.shown), details["area"], position)
            self.shown.append(self.current)
            self.stack = [position]
            passed, path = self._scan_passed()
            self._step(
                f"{passed}{self._where(position)} is open and in no area "
                f"yet, so start {self.current.name} here and push it onto the stack.",
                focus=position,
                style="scan",
                scan_path=path,
                force=True,
            )
        elif event == "visit":
            self.stack = details["stack"]  # The live stack, so frames stay current.
            self.owner[position] = self.current
            self._step(
                f"Pop {self._where(position)} from the stack into {self.current.name}, "
                "then check its four neighbours.",
                source=position,
            )
        elif event == "check":
            self._check_step(position, details["source"], details["result"])
        elif event == "label":
            self._step(
                f"The label ({details['name']}) starts at {self._where(position)}, "
                f"so record that name for {self.current.name}.",
                focus=position,
                style="record",
            )
        elif event == "chair":
            self._step(
                f"{self._where(position)} holds chair {details['chair']}. "
                f"{_upper_first(self.current.name)} now has "
                f"{counts_text(details['area'].chairs)}.",
                focus=position,
                style="record",
            )

    def area_finished(self, area: Area) -> None:
        """Add a finished area to the report, as ``count_chairs`` does, and explain it.

        ``count_chairs`` stops at the first rule violation. The visualiser marks
        the area as a problem and carries on, so the rest of the plan can still
        be seen. ``first_error`` keeps the error ``count_chairs`` would raise.

        Args:
            area: The area ``_find_areas`` has just yielded.
        """
        shown = self.current
        done = f"The stack is empty, so {shown.name} is complete with {len(area.cells)} cells."
        try:
            _add_area(self.report, area)
        except ValueError as error:
            shown.problem = str(error)
            if self.first_error is None:
                self.first_error = str(error)
            text = f"{done} _add_area rejects it: {error}"
        else:
            if shown.outside:
                text = f"{done} It is the outside of the building, so nothing is counted."
            elif area.names:
                text = (
                    f"{done} _add_area records room {area.names[0]!r} with "
                    f"{counts_text(area.chairs)} and adds them to the total."
                )
            else:
                text = (
                    f"{done} It has no label, so _add_area adds its chairs "
                    f"({counts_text(area.chairs)}) to the total only."
                )
        self._step(text, force=True)

    def finish(self) -> None:
        """Add the last step, after the scan has passed the final cell."""
        self.current = None
        passed, path = self._scan_passed()
        self._step(
            f"{passed}The scan has reached the end of the grid, "
            "so every open cell belongs to an area.",
            scan_path=path,
            force=True,
        )

    def close(self) -> None:
        """Restore the terminal cursor after an animation. Safe to call twice."""
        if self.animate and not self.closed:
            self.out.write("\x1b[?25h\n")
            self.out.flush()
        self.closed = True

    # Step text --------------------------------------------------------------

    def _check_step(self, position: Position, source: Position, result: str) -> None:
        """Explain the check of one neighbour, e.g. "Look below …: … is a wall '-', blocked."

        Args:
            position: The neighbour that was checked.
            source: The cell being expanded.
            result: ``"off grid"``, ``"visited"``, ``"wall"`` or ``"added"``.
        """
        offset = (position[0] - source[0], position[1] - source[1])
        look = f"Look {DIRECTIONS[offset]} {self._where(source)}: "
        where = self._where(position)
        if result == "off grid":
            self._step(look + "that is beyond the edge of the grid, skip.", source=source)
            return
        if result == "visited":
            text = f"{where} was already reached, skip."
        elif result == "wall":
            text = f"{where} is a wall {self.grid[position[0]][position[1]]!r}, blocked."
        else:
            text = f"{where} is {self.describe(position)}, so mark it reached and push it."
        self._step(look + text, focus=position, style=result, source=source)

    def _scan_passed(self) -> tuple[str, list[Position]]:
        """Summarise and reset the scan cells skipped since the last step.

        Returns:
            A sentence such as "The scan moves past 12 cells (5 walls, 7 already
            in an area). ", or an empty string if nothing was skipped, and the
            skipped cells, to be shown as the scan path.
        """
        path, self.skipped_cells = self.skipped_cells, []
        if not self.skipped:
            return "", path
        walls, visited = self.skipped["wall"], self.skipped["visited"]
        self.skipped.clear()
        text = (
            f"The scan moves past {walls + visited} cells "
            f"({walls} walls, {visited} already in an area). "
        )
        return text, path

    def _is_border(self, position: Position) -> bool:
        """Whether a cell is in the blank border that ``_parse_plan`` adds."""
        row, column = position
        return row in (0, self.height - 1) or column in (0, self.width - 1)

    def _where(self, position: Position) -> str:
        """Name a cell as it appears in the plan file, e.g. "line 3, col 5".

        Grid row r is line r of the file and grid column c is column c, because
        of the one-cell border. Border cells are not in the file, so they are
        named by grid position instead, e.g. "border cell (0, 4)".
        """
        row, column = position
        if self._is_border(position):
            return f"border cell ({row}, {column})"
        return f"line {row}, col {column}"

    def describe(self, position: Position) -> str:
        """Say what a cell holds: a wall, a chair, label text, border or floor."""
        char = self.grid[position[0]][position[1]]
        if position in self.label_text:
            return f"label text {self.label_text[position]!r}, which counts as floor"
        if char in WALLS:
            return f"wall {char!r}"
        if char in CHAIR_TYPES:
            return f"chair {char!r}"
        if self._is_border(position):
            return "blank border"
        return "floor"

    # Frames -----------------------------------------------------------------

    def _step(
        self,
        text: str,
        focus: Position | None = None,
        style: str = "",
        source: Position | None = None,
        scan_path: Sequence[Position] = (),
        force: bool = False,
    ) -> None:
        """Record one step and draw a frame if one is due.

        Args:
            text: The explanation of the step.
            focus: The cell this step looks at, if any.
            style: How the look turned out, which sets the focus cell's colour:
                ``"scan"``, ``"added"``, ``"wall"``, ``"visited"`` or ``"record"``.
            source: The cell being expanded, if any.
            scan_path: Cells the scan walked past to reach this step.
            force: Draw a frame even if one is not due, e.g. when an area
                starts or is done.
        """
        self.step_number += 1
        self.step_text = text
        self.recent.append(f"{self.step_number:>6}  {text}")
        if self.log:
            self.out.write(f"{self.step_number:>6}  {text}\n")
        self.focus, self.focus_style, self.source = focus, style, source
        self.scan_path = set(scan_path)
        due = self.every is not None and self.step_number >= self.next_frame
        if due or force:
            if self.every is not None:
                self.next_frame = self.step_number + self.every
            self.show_frame(long_pause=force)

    def show_frame(self, long_pause: bool) -> None:
        """Draw the grid and status lines in the terminal, then wait or pause.

        Args:
            long_pause: Hold this frame longer when animating, used when an area
                is finished so it can be seen.
        """
        text = "\n".join(
            [COLOUR_LEGEND if self.colour else PLAIN_LEGEND, "", self._draw_grid(), ""]
            + self.status_lines()
            + (["", "Recent steps:", *list(self.recent)[:-1]] if self.animate else [])
        )
        if self.animate:
            # Move the cursor home and clear what is left of the previous frame.
            self.out.write("\x1b[H" + text + "\x1b[J")
            self.out.flush()
        else:
            self.out.write("\n" + text + "\n\n")
        if self.pausing:
            self._prompt()
        elif self.animate:
            time.sleep(self.delay * (15 if long_pause else 1))

    def _prompt(self) -> None:
        """Wait for the user in ``--step`` mode and act on their answer.

        Enter shows the next frame, a number jumps that many steps ahead, ``c``
        stops pausing and ``q`` quits (raised as ``KeyboardInterrupt``).
        """
        self.out.write(
            "\nEnter: next | a number: jump that many steps | c: run to the end | q: quit > "
        )
        self.out.flush()
        answer = input().strip().lower()
        if answer == "q":
            raise KeyboardInterrupt
        if answer == "c":
            self.pausing = False
        elif answer.isdigit() and int(answer) > 0:
            self.next_frame = self.step_number + int(answer)

    def status_lines(self) -> list[str]:
        """Describe the current state in a few lines of text.

        Returns:
            The step number and area, the step's explanation (unless it was
            already printed as a log line), the top of the stack, the current
            area's cells, chairs and labels so far, and the report so far.
        """
        where = self.current.name if self.current else "scanning"
        lines = [f"Step {self.step_number} | {where}"]
        if self.animate or not self.log:
            lines.append(self.step_text)
        top = [self._where(cell) for cell in reversed(self.stack[-STACK_SHOWN:])]
        more = f" and {len(self.stack) - STACK_SHOWN} more" if len(self.stack) > STACK_SHOWN else ""
        lines.append(
            f"Stack ({len(self.stack)}, next pop first): {'; '.join(top) or 'empty'}{more}"
        )
        if self.current is not None:
            area = self.current.area
            lines.append(
                f"{_upper_first(self.current.name)} so far: {len(area.cells)} cells, "
                f"{counts_text(area.chairs)}, labels: {', '.join(area.names) or 'none'}"
            )
        rooms = ", ".join(self.report.rooms) or "none yet"
        lines.append(f"Report so far: total {counts_text(self.report.total)} | rooms: {rooms}")
        return lines

    def cell_state(
        self, position: Position, stack_cells: set[Position]
    ) -> tuple[str, ShownArea | None]:
        """Decide how a cell should look in the current frame.

        The first matching state wins, so the cell being looked at always stands
        out, even if it is also on the stack or in an area.

        Args:
            position: The cell to classify.
            stack_cells: The cells currently on the stack, as a set.

        Returns:
            The state and the area that owns the cell, if any. The states are
            ``"look-<style>"`` (the cell this step looks at), ``"expanding"``,
            ``"stack"``, ``"scan-path"`` (walked past by the scan to reach this
            step), ``"problem"`` (in a rejected area), ``"outside"``, ``"area"``
            (in an enclosed area), ``"wall"`` and ``"floor"``.
        """
        shown = self.owner.get(position)
        if position == self.focus:
            return f"look-{self.focus_style}", shown
        if position == self.source:
            return "expanding", shown
        if position in stack_cells:
            return "stack", shown
        if position in self.scan_path:
            return "scan-path", shown
        if shown is not None:
            if shown.problem:
                return "problem", shown
            return ("outside" if shown.outside else "area"), shown
        if self.grid[position[0]][position[1]] in WALLS:
            return "wall", None
        return "floor", None

    def _draw_grid(self) -> str:
        """Draw the grid as text, coloured or marked with ``*``, ``o`` and ``.``."""
        stack_cells = set(self.stack)
        rows = []
        for row, line in enumerate(self.grid):
            parts = []
            for column, cell in enumerate(line):
                position = (row, column)
                char = self.label_text.get(position, cell)
                state, shown = self.cell_state(position, stack_cells)
                if self.colour:
                    parts.append(self._coloured(position, char, cell, state, shown))
                else:
                    parts.append(self._plain(char, state, shown))
            rows.append("".join(parts))
        return "\n".join(rows)

    def _coloured(
        self, position: Position, char: str, cell: str, state: str, shown: ShownArea | None
    ) -> str:
        """Wrap one cell's character in the terminal colours for its state."""
        if state == "floor":
            return char
        if state == "wall":
            return f"\x1b[{WALL_STYLE}m{char}\x1b[0m"
        if state == "area":
            style = f"48;5;{AREA_COLOURS[(shown.number - 1) % len(AREA_COLOURS)]}"
        else:
            style = STATE_STYLES[state]
        if cell in CHAIR_TYPES or position in self.label_text:
            style += ";1"  # Bold, so chairs and names stay readable on colour.
        return f"\x1b[{style}m{char}\x1b[0m"

    def _plain(self, char: str, state: str, shown: ShownArea | None) -> str:
        """Mark one blank cell without colour: ``*`` expanding, ``o`` stack, ``.`` reached."""
        if char != " ":
            return char
        if state == "expanding":
            return "*"
        if state == "stack":
            return "o"
        if shown is not None and shown is self.current:
            return "."
        return char


# Running a plan -------------------------------------------------------------


def estimate_steps(grid: list[str]) -> int:
    """Estimate the number of steps: roughly one pop and four checks per open cell."""
    return 5 * sum(cell not in WALLS for line in grid for cell in line)


def trace_plan(
    visualiser: Visualiser, grid: list[str], labels: dict[Position, str]
) -> None:
    """Run the search on a parsed plan and send every event to the visualiser.

    This follows ``count_chairs``: find each area, then add it to the report.
    """
    for area in _find_areas(grid, labels, visualiser.trace):
        visualiser.area_finished(area)
    visualiser.finish()


def write_result(visualiser: Visualiser, out: TextIO) -> int:
    """Print a summary of every area, then the report or the error.

    Returns:
        A process exit code: 0 for a valid plan, 1 if it was rejected.
    """
    out.write("\nAreas found:\n")
    for shown in visualiser.shown:
        out.write(f"  {shown.summary()}\n")
    if visualiser.first_error is not None:
        out.write(f"\ncount_chairs rejects this plan: {visualiser.first_error}\n")
        return 1
    out.write("\nReport:\n" + format_report(visualiser.report) + "\n")
    return 0


def run(
    plan: str,
    out: TextIO,
    *,
    colour: bool,
    animate: bool,
    delay: float = 0.03,
    every: int | None = None,
    step: bool = False,
) -> int:
    """Show the search for one plan in the terminal.

    Args:
        plan: The floor plan text.
        out: Where to write the steps, frames and result.
        colour: Draw the grid with terminal colours.
        animate: Redraw frames in place. Turned off automatically when the
            frame is taller than the terminal, since it would scroll.
        delay: Seconds per animated frame.
        every: Draw a frame every this many steps. If ``None``: every step with
            ``step``, a pace that suits the plan size when animating, and
            otherwise only when an area is finished.
        step: Pause for the Enter key after every frame.

    Returns:
        A process exit code: 0 for a valid plan, 1 if it was rejected.

    Raises:
        ValueError: If the plan cannot be parsed at all.
    """
    grid, labels = _parse_plan(plan)
    if animate and len(grid) + 18 > shutil.get_terminal_size().lines:
        animate = False
    if every is None and step:
        every = 1
    elif every is None and animate:
        every = max(1, estimate_steps(grid) // 600)  # About 600 frames in total.

    visualiser = Visualiser(
        plan, grid, out, colour=colour, animate=animate, delay=delay, every=every, step=step
    )
    try:
        trace_plan(visualiser, grid, labels)
    finally:
        visualiser.close()
    return write_result(visualiser, out)


# Command line ---------------------------------------------------------------


def collect_plans(paths: Sequence[Path]) -> list[Path]:
    """Expand folders into the ``.txt`` plan files they contain.

    Args:
        paths: Plan files and folders, as given on the command line.

    Returns:
        The plan files, in the order given. A folder's files are sorted by name.

    Raises:
        ValueError: If a folder contains no ``.txt`` files.
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
    return plans


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for ``python -m chair_counter.visualize``."""
    parser = argparse.ArgumentParser(
        prog="python -m chair_counter.visualize",
        description="Watch the chair counter's search step by step on a floor plan.",
    )
    parser.add_argument(
        "plans",
        type=Path,
        nargs="+",
        metavar="plan",
        help="a floor plan file; with --html, several files or a folder of .txt plans",
    )
    parser.add_argument(
        "--step",
        action="store_true",
        help="pause after every frame; Enter continues, a number jumps ahead",
    )
    parser.add_argument(
        "--every",
        type=int,
        metavar="N",
        help="draw a frame every N steps (default: 1 with --step, otherwise automatic)",
    )
    parser.add_argument(
        "--delay", type=float, default=0.03, help="seconds per animated frame (default 0.03)"
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="no colour or animation; print every step as a line of text",
    )
    parser.add_argument(
        "--html",
        type=Path,
        metavar="FILE",
        help=(
            "write an animated web page to FILE instead; "
            "with several plans, the page has a drop-down to pick the house"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Parse the command line, then show the search or write the web page.

    Exits with code 0 for valid plans, 1 if a plan is rejected, 2 for bad
    arguments or unreadable files, and 130 if interrupted.

    Args:
        argv: Command-line arguments without the program name. ``None`` reads
            them from ``sys.argv``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.every is not None and args.every < 1:
        parser.error("--every must be at least 1")

    try:
        paths = collect_plans(args.plans)
        plans = [path.read_text(encoding="utf-8-sig") for path in paths]
    except (OSError, ValueError) as error:
        parser.error(str(error))

    if args.html is not None:
        from .plotly_html import house_name, write_html

        houses = [(house_name(path), plan) for path, plan in zip(paths, plans)]
        try:
            code = write_html(houses, args.html, sys.stdout, every=args.every)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        raise SystemExit(code)

    if len(plans) > 1:
        parser.error("the terminal view shows one plan; use --html for several")

    fancy = not args.plain and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if fancy and os.name == "nt":
        os.system("")  # Makes older Windows consoles process ANSI escape codes.

    try:
        code = run(
            plans[0],
            sys.stdout,
            colour=fancy,
            animate=fancy,
            delay=args.delay,
            every=args.every,
            step=args.step,
        )
    except ValueError as error:  # The plan could not be parsed at all.
        parser.error(str(error))
    except (KeyboardInterrupt, EOFError):
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
