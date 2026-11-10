"""Write an animated web page of the chair counter's search, one frame per step.

The page is made by ``python -m chair_counter PLAN --output DIR --animation``.

This module has no counting logic of its own. It runs the real search from
``floor_plan.py`` (``_parse_plan``, ``_find_areas`` and ``_add_area``) and passes
``FrameRecorder.trace`` as the search's ``trace`` hook. Each event the search
reports becomes one numbered step with a plain-English explanation, such as
"Look below line 3, col 5: line 4, col 5 is a wall '-', blocked.", and one
frame of the animation.

How the pieces fit together:

- ``FrameRecorder`` turns the events into steps. It keeps what is needed to
  draw them (the stack, which area owns each cell, the report so far) and
  records the colour of every cell after each step.
- ``write_html`` records every plan and writes one page with all of them.
- ``PAGE`` is the page: Plotly draws the grid as a heatmap, and a small script
  plays the frames. It loads Plotly.js from its CDN, so opening it needs
  internet.

Storing every step as a full grid would make the page very large, so frames
are stored compactly:

- Each cell's look is a colour code (see ``STATES`` and ``AREA_COLOURS``).
- A keyframe holds every cell's code, one character per cell, every
  ``KEYFRAME_EVERY`` frames.
- Each frame stores only the cells that changed since the frame before, as
  ``[cell index, code, cell index, code, ...]``.
"""

import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

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

PLOTLY_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"

MAX_FRAMES = 20000
"""Most frames per house when no pace is given. Larger plans skip steps evenly."""

KEYFRAME_EVERY = 200
"""Frames between full snapshots. Jumping to any frame replays at most this many."""

DIRECTIONS = {(-1, 0): "above", (1, 0): "below", (0, -1): "left of", (0, 1): "right of"}
"""Words for the four neighbour offsets, in the order ``_walk_area`` checks them."""

STACK_SHOWN = 6
"""How many stack entries the status panel lists before saying "and N more"."""

STATES = (
    ("floor", "#ffffff", "not reached yet"),
    ("wall", "#868e96", "wall"),
    ("outside", "#dee2e6", "outside the building"),
    ("problem", "#e03131", "area rejected by _add_area"),
    ("stack", "#66d9e8", "waiting on the stack"),
    ("expanding", "#f06595", "cell being expanded"),
    ("look-scan", "#f59f00", "scan starts a new area here"),
    ("scan-path", "#ffec99", "cells the scan walked past"),
    ("look-added", "#40c057", "neighbour pushed onto the stack"),
    ("look-wall", "#fa5252", "neighbour is a wall"),
    ("look-visited", "#4dabf7", "neighbour already reached"),
    ("look-record", "#ff922b", "chair or label recorded"),
)
"""Each cell state from ``FrameRecorder.cell_state`` with its colour and legend text.

A state's position in this tuple is its colour code.
"""

AREA_COLOURS = ("#d0ebff", "#d3f9d8", "#e5dbff", "#ffe8cc", "#f3d9fa", "#e6fcf5", "#edf2ff")
"""Pale colours for enclosed areas, used in turn. Their codes follow ``STATES``."""

STATE_CODES = {state: code for code, (state, _, _) in enumerate(STATES)}
FIRST_CODE_CHAR = ord("A")
"""Keyframes store code ``n`` as the character ``chr(FIRST_CODE_CHAR + n)``."""


def counts_text(chairs: Counter[str]) -> str:
    """Format chair counts in report order, including zeros: ``W: 1, P: 0, S: 0, C: 2``."""
    return ", ".join(f"{chair}: {chairs[chair]}" for chair in CHAIR_TYPES)


def _upper_first(text: str) -> str:
    """Capitalise the first letter only, so room names keep their own case."""
    return text[:1].upper() + text[1:]


@dataclass
class ShownArea:
    """An area found by the search, plus what the page needs to know about it.

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


class FrameRecorder:
    """Turn the search's trace events into numbered steps and record a frame per step.

    The search calls ``trace`` for every event (see ``floor_plan.Trace``), and
    ``trace_plan`` calls ``area_finished`` after each area and ``finish`` at the
    end. Each of these produces one step through ``_step``, which updates the
    step text and the highlighted cells, then records a frame.

    A frame has two parts:

    - The colour code of every cell, decided by ``cell_state``: the cell being
      looked at, the cell being expanded, cells on the stack, filled areas,
      walls and untouched floor. Only the changes are stored, in ``deltas``.
    - The status lines from ``status_lines``: the current step, the top of the
      stack, the area being filled, and the report so far.

    When recording every step, only the cells that can have changed are
    recomputed: the cells highlighted in this frame or the last one, and the
    cells that joined or left the stack. Everything is recomputed for the first
    frame, when frames skip steps, and when an area is rejected and turns red.

    Attributes:
        report: The report built by calling ``_add_area`` on each finished area,
            exactly as ``count_chairs`` does.
        shown: Every area found so far, in scan order.
        current: The area being filled, or ``None`` once the scan has finished.
        first_error: The first rule violation, which is the error
            ``count_chairs`` would raise. ``None`` if the plan is valid.
        label_text: The label characters ``_parse_plan`` removed from the grid,
            by position, so the page can still show room names.
        codes: The colour code of every cell, row by row, in the latest frame.
        keyframes: A full snapshot of ``codes`` every ``KEYFRAME_EVERY`` frames.
        deltas: For each frame, the changed cells as ``[index, code, ...]``,
            where ``index`` is ``row * width + column``.
        statuses: For each frame, the status lines from ``status_lines``.
        area_starts: Frame numbers where the scan starts a new area.
    """

    def __init__(self, plan: str, grid: list[str], every: int = 1) -> None:
        """Prepare to record one plan.

        Args:
            plan: The plan text, used to show room labels in the grid.
            grid: The padded grid from ``_parse_plan``.
            every: Record a frame every this many steps. A frame is also
                recorded at the first step and whenever an area starts or ends.
        """
        self.grid = grid
        self.height, self.width = len(grid), len(grid[0])
        self.every = every
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

        # The current step.
        self.step_number = 0
        self.step_text = ""
        self.next_frame = 1  # Always record the first step.
        self.focus: Position | None = None  # The cell the current step looks at.
        self.focus_style = ""  # How that look turned out, e.g. "wall" or "added".
        self.source: Position | None = None  # The cell being expanded.
        self.scan_path: set[Position] = set()  # Cells the scan just walked past.

        # Recorded frames.
        self.codes = [[STATE_CODES["floor"]] * self.width for _ in range(self.height)]
        self.keyframes: list[str] = []
        self.deltas: list[list[int]] = []
        self.statuses: list[list[str]] = []
        self.area_starts: list[int] = []
        self._last_marked: set[Position] = set()
        self._last_stack: set[Position] = set()
        self._last_problems = 0

    # Search events ----------------------------------------------------------

    def trace(self, event: str, position: Position, **details: Any) -> None:
        """Receive one event from the search and turn it into a step.

        This is the ``trace`` function passed to ``_find_areas``. Scan events for
        walls and visited cells are only collected here; they are reported
        together with the next step, which shows them as the scan path, so the
        page is not flooded with them. The start of a new area always gets a
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
            self.area_starts.append(len(self.statuses))  # The frame about to be recorded.
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

        ``count_chairs`` stops at the first rule violation. The recorder marks
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

    def hover_text(self, position: Position) -> str:
        """Describe a cell for the page's hover box, e.g. "line 3, col 5: chair 'W'"."""
        return f"{self._where(position)}: {self.describe(position)}"

    def status_lines(self) -> list[str]:
        """Describe the current state in a few lines of text.

        Returns:
            The step number and area, the step's explanation, the top of the
            stack, the current area's cells, chairs and labels so far, and the
            report so far.
        """
        where = self.current.name if self.current else "scanning"
        lines = [f"Step {self.step_number} | {where}", self.step_text]
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
        """Record one step, and a frame if one is due.

        Args:
            text: The explanation of the step.
            focus: The cell this step looks at, if any.
            style: How the look turned out, which sets the focus cell's colour:
                ``"scan"``, ``"added"``, ``"wall"``, ``"visited"`` or ``"record"``.
            source: The cell being expanded, if any.
            scan_path: Cells the scan walked past to reach this step.
            force: Record a frame even if one is not due, e.g. when an area
                starts or is done.
        """
        self.step_number += 1
        self.step_text = text
        self.focus, self.focus_style, self.source = focus, style, source
        self.scan_path = set(scan_path)
        if self.step_number >= self.next_frame or force:
            self.next_frame = self.step_number + self.every
            self._record_frame()

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

    def _record_frame(self) -> None:
        """Store the current state as a frame: the changed cells and the status lines."""
        stack = set(self.stack)
        marked = {cell for cell in (self.focus, self.source) if cell is not None}
        marked |= self.scan_path
        problems = sum(1 for shown in self.shown if shown.problem)

        if not self.statuses or self.every != 1 or problems != self._last_problems:
            candidates = [(row, column) for row in range(self.height) for column in range(self.width)]
        else:
            candidates = self._last_marked | marked | (stack ^ self._last_stack)

        changes = []
        for row, column in candidates:
            code = self._code(*self.cell_state((row, column), stack))
            if code != self.codes[row][column]:
                self.codes[row][column] = code
                changes += [row * self.width + column, code]

        if len(self.statuses) % KEYFRAME_EVERY == 0:
            self.keyframes.append(
                "".join(chr(FIRST_CODE_CHAR + code) for line in self.codes for code in line)
            )
        self.deltas.append(changes)
        self.statuses.append(self.status_lines())
        self._last_marked, self._last_stack, self._last_problems = marked, stack, problems

    @staticmethod
    def _code(state: str, shown: ShownArea | None) -> int:
        """Turn a cell state into its colour code (see ``STATES`` and ``AREA_COLOURS``)."""
        if state == "area":
            return len(STATES) + (shown.number - 1) % len(AREA_COLOURS)
        return STATE_CODES[state]


# Recording plans --------------------------------------------------------------


def estimate_steps(grid: list[str]) -> int:
    """Estimate the number of steps: roughly one pop and four checks per open cell."""
    return 5 * sum(cell not in WALLS for line in grid for cell in line)


def trace_plan(recorder: FrameRecorder, grid: list[str], labels: dict[Position, str]) -> None:
    """Run the search on a parsed plan and send every event to the recorder.

    This follows ``count_chairs``: find each area, then add it to the report.
    """
    for area in _find_areas(grid, labels, recorder.trace):
        recorder.area_finished(area)
    recorder.finish()


def house_name(path: Path) -> str:
    """Name a house after its plan file, e.g. ``family_house.txt`` -> "family house"."""
    return path.stem.replace("_", " ")


def write_html(houses: Sequence[tuple[str, str]], path: Path, every: int | None = None) -> None:
    """Record the search for each house and write one page with all of them.

    Args:
        houses: ``(name, plan text)`` pairs, in the order the drop-down lists them.
            A plan that breaks a rule still gets its animation, with the error
            shown as its final report.
        path: The HTML file to write.
        every: Record a frame every this many steps. ``None`` records every
            step, unless that would be more than ``MAX_FRAMES`` frames.

    Raises:
        ValueError: If a plan cannot be parsed at all. The message names the house.
        OSError: If the page cannot be written.
    """
    records = []
    for name, plan in houses:
        try:
            grid, labels = _parse_plan(plan)
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from error
        pace = every or max(1, math.ceil(estimate_steps(grid) / MAX_FRAMES))
        recorder = FrameRecorder(plan, grid, pace)
        trace_plan(recorder, grid, labels)
        records.append(_house(name, recorder))

    path.write_text(_page(records), encoding="utf-8")


def _house(name: str, recorder: FrameRecorder) -> dict:
    """Package one recorded house for the page.

    Returns:
        The house's ``name``, grid size, recorded frames (``keyframes``,
        ``deltas``, ``statuses``), ``areaStarts``, the Plotly ``trace`` and
        ``layout``, and the ``result`` text: the final report, or the reason
        the plan was rejected.
    """
    if recorder.first_error is not None:
        result = f"count_chairs rejects this plan: {recorder.first_error}"
    else:
        result = format_report(recorder.report)
    trace, layout = _figure(recorder)
    return {
        "name": name,
        "width": recorder.width,
        "height": recorder.height,
        "keyEvery": KEYFRAME_EVERY,
        "keyframes": recorder.keyframes,
        "deltas": recorder.deltas,
        "statuses": recorder.statuses,
        "areaStarts": recorder.area_starts,
        "trace": trace,
        "layout": layout,
        "result": result,
    }


def _figure(recorder: FrameRecorder) -> tuple[dict, dict]:
    """Build the Plotly heatmap and layout for one house, without the cell colours.

    The heatmap's values are colour codes, which the page fills in for each
    frame. A heatmap normally blends colours, so the colour scale is built from
    flat bands, one per code: code ``i`` is drawn in colour ``i`` only. The
    characters and hover text are the same in every frame.

    The figure has no fixed size. The page sizes it to the space available,
    keeps every cell square, and sets the text size to match the cells.

    Returns:
        The heatmap trace and the layout.
    """
    colours = [colour for _, colour, _ in STATES] + list(AREA_COLOURS)
    bands = len(colours)
    scale = []
    for code, colour in enumerate(colours):
        scale += [[code / bands, colour], [(code + 1) / bands, colour]]

    text = [
        [recorder.label_text.get((row, column), char) for column, char in enumerate(line)]
        for row, line in enumerate(recorder.grid)
    ]
    hover = [
        [recorder.hover_text((row, column)) for column in range(recorder.width)]
        for row in range(recorder.height)
    ]
    trace = {
        "type": "heatmap",
        "text": text,
        "customdata": hover,
        "texttemplate": "%{text}",
        "textfont": {"family": "Consolas, Menlo, monospace", "size": 12, "color": "#212529"},
        "hovertemplate": "%{customdata}<extra></extra>",
        "colorscale": scale,
        "zmin": -0.5,  # With these limits, code i sits in the middle of band i.
        "zmax": bands - 0.5,
        "showscale": False,
        "xgap": 1,
        "ygap": 1,
    }
    layout = {
        "autosize": True,
        "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        # Square cells: one y unit is as long as one x unit. "domain" shrinks
        # whichever axis has spare room, so the grid fits without stretching.
        "xaxis": {"visible": False, "constrain": "domain"},
        "yaxis": {"visible": False, "autorange": "reversed", "scaleanchor": "x", "constrain": "domain"},
    }
    return trace, layout


def _page(houses: list[dict]) -> str:
    """Fill in the page template with the legend and every house's data.

    Args:
        houses: Entries from ``_house``.

    Returns:
        The complete HTML page.
    """
    legend = "\n".join(
        f'    <li><span class="swatch" style="background:{colour}"></span>{text}</li>'
        for _, colour, text in STATES
    )
    legend += (
        '\n    <li><span class="swatch" style="background:linear-gradient(90deg,'
        f'{",".join(AREA_COLOURS)})"></span>reached, one colour per area</li>'
    )
    payload = json.dumps({"houses": houses}, ensure_ascii=False, separators=(",", ":"))
    # "</" inside a <script> block could close it early, so escape it.
    return PAGE.substitute(
        plotly=PLOTLY_URL,
        legend=legend,
        first_code_char=FIRST_CODE_CHAR,
        data=payload.replace("</", "<\\/"),
    )


# The page fills the browser window without scrolling: a control bar on top,
# the grid on the left using all remaining space, and a side panel with the
# current step, the legend and the final report.
#
# The script keeps `codes`, the colour code of every cell in the frame on
# screen. Moving one frame forward applies that frame's changes; jumping
# rebuilds the frame from the nearest keyframe. Playing applies a few frames per
# tick and redraws the heatmap with Plotly.restyle.
#
# In a Template, $name is replaced by substitute() and $$ stands for a literal $.
PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chair counter search</title>
<script src="$plotly"></script>
<style>
  :root { --bg: #f8f9fa; --fg: #212529; --muted: #495057; --panel: #ffffff; --border: #dee2e6; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #1a1b1e; --fg: #e9ecef; --muted: #adb5bd; --panel: #25262b; --border: #373a40; }
  }
  html, body { height: 100%; margin: 0; }
  body { display: flex; flex-direction: column; overflow: hidden; background: var(--bg);
         color: var(--fg); font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px;
           padding: 10px 16px; border-bottom: 1px solid var(--border); }
  h1 { font-size: 1.05rem; margin: 0 8px 0 0; white-space: nowrap; }
  h2 { font-size: 0.85rem; margin: 0 0 6px; text-transform: uppercase; letter-spacing: 0.04em;
       color: var(--muted); }
  button, select { font: inherit; padding: 4px 10px; border-radius: 6px; cursor: pointer;
                   border: 1px solid var(--border); background: var(--panel); color: var(--fg); }
  #play { min-width: 5.5em; font-weight: 600; }
  #frame { flex: 1; min-width: 160px; }
  #position { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  label { white-space: nowrap; }
  .main { flex: 1; min-height: 0; display: flex; gap: 14px; padding: 12px 16px; }
  #chart { flex: 1; min-width: 0; min-height: 0; }
  aside { width: 400px; flex: none; display: flex; flex-direction: column; gap: 10px; min-height: 0; }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
           padding: 10px 12px; }
  #status { flex: none; max-height: 50%; overflow: auto; font: 12px/1.45 Consolas, Menlo, monospace;
            overflow-wrap: anywhere; }
  #status p { margin: 0 0 3px; }
  #status .event { font-weight: 600; }
  #status .detail { color: var(--muted); }
  #status.new-area { border-color: #f59f00; box-shadow: 0 0 0 2px #f59f00 inset; }
  .legend { flex: none; list-style: none; margin: 0; display: grid;
            grid-template-columns: 1fr 1fr; gap: 3px 10px; color: var(--muted); font-size: 12px; }
  .swatch { display: inline-block; width: 12px; height: 12px; border-radius: 3px;
            border: 1px solid var(--border); vertical-align: -2px; margin-right: 6px; }
  .report { flex: 1; min-height: 0; overflow: auto; }
  #result { margin: 0; font: 12px/1.45 Consolas, Menlo, monospace; white-space: pre-wrap; }
  /* Narrow screens: stack everything and let the page scroll. */
  @media (max-width: 900px) {
    body { overflow: auto; height: auto; }
    .main { flex-direction: column; }
    #chart { flex: none; height: 75vh; }
    aside { width: auto; }
  }
</style>
</head>
<body>
<header>
  <h1>Chair counter search</h1>
  <span id="picker"><label for="house">House</label> <select id="house"></select></span>
  <button id="play" type="button" title="Play or pause (Space)">&#9654; Play</button>
  <button id="prev-area" type="button" title="Start of the previous area (Page Up)">&#9198; Area</button>
  <button id="prev" type="button" title="Previous step (Left arrow)">&#9664;</button>
  <button id="next" type="button" title="Next step (Right arrow)">&#9654;</button>
  <button id="next-area" type="button" title="Start of the next area (Page Down)">Area &#9197;</button>
  <input id="frame" type="range" min="0" value="0" aria-label="Step">
  <span id="position"></span>
  <label for="speed">Speed</label>
  <select id="speed">
    <option value="2">2 steps/s</option>
    <option value="5">5 steps/s</option>
    <option value="10">10 steps/s</option>
    <option value="25" selected>25 steps/s</option>
    <option value="60">60 steps/s</option>
    <option value="200">200 steps/s</option>
    <option value="1000">1000 steps/s</option>
  </select>
  <label title="Stop playing when the scan starts a new area">
    <input id="stop-at-area" type="checkbox" checked> Pause at each new area
  </label>
</header>
<div class="main">
  <div id="chart"></div>
  <aside>
    <section id="status" class="panel" aria-live="polite"></section>
    <ul class="legend panel">
$legend
    </ul>
    <section class="report panel">
      <h2>Final report</h2>
      <pre id="result"></pre>
    </section>
  </aside>
</div>
<script>
const HOUSES = $data.houses;
const FIRST_CODE_CHAR = $first_code_char;
const chart = document.getElementById("chart");
const status = document.getElementById("status");
const picker = document.getElementById("house");
const playButton = document.getElementById("play");
const slider = document.getElementById("frame");
const position = document.getElementById("position");
const speed = document.getElementById("speed");
const stopAtArea = document.getElementById("stop-at-area");
let house = HOUSES[0];
let codes = [];     // Colour code of every cell in the frame on screen.
let current = 0;    // Frame on screen.
let timer = null;   // Set while playing.

HOUSES.forEach((item, index) => picker.add(new Option(item.name, String(index))));
if (HOUSES.length < 2) document.getElementById("picker").hidden = true;

const lastFrame = () => house.statuses.length - 1;

// Apply one frame's changes ([cell index, code, ...]) to `codes`.
function applyChanges(frame) {
  const changes = house.deltas[frame];
  for (let n = 0; n < changes.length; n += 2) {
    const cell = changes[n];
    codes[Math.floor(cell / house.width)][cell % house.width] = changes[n + 1];
  }
}

// Rebuild frame `index` from the nearest keyframe at or before it.
function rebuild(index) {
  const key = Math.floor(index / house.keyEvery);
  const snapshot = house.keyframes[key];
  codes = [];
  for (let row = 0; row < house.height; row++) {
    const line = [];
    for (let column = 0; column < house.width; column++) {
      line.push(snapshot.charCodeAt(row * house.width + column) - FIRST_CODE_CHAR);
    }
    codes.push(line);
  }
  for (let frame = key * house.keyEvery + 1; frame <= index; frame++) applyChanges(frame);
}

function draw() {
  Plotly.restyle(chart, { z: [codes.map((line) => line.slice())] }, [0]);
}

// Show frame `index` in the status panel, slider and step counter.
function show(index) {
  current = index;
  slider.value = String(index);
  const lines = house.statuses[index];
  position.textContent = lines[0].split(" |")[0] + " of " + house.statuses.length;
  status.classList.toggle("new-area", house.areaStarts.includes(index));
  status.replaceChildren(...lines.map((text, line) => {
    const p = document.createElement("p");
    p.className = line === 1 ? "event" : "detail";
    p.textContent = text;
    return p;
  }));
}

// Go to frame `index`, stepping forward cheaply when possible.
function go(index) {
  index = Math.max(0, Math.min(lastFrame(), index));
  if (index === current + 1) applyChanges(index);
  else if (index !== current) rebuild(index);
  draw();
  show(index);
}

function pause() {
  clearInterval(timer);
  timer = null;
  playButton.innerHTML = "&#9654; Play";
}

function play() {
  if (current >= lastFrame()) go(0);  // Start again from the beginning.
  const perSecond = Number(speed.value);
  const interval = Math.max(50, 1000 / perSecond);  // At most 20 redraws a second.
  const perTick = Math.max(1, Math.round(perSecond * interval / 1000));
  playButton.innerHTML = "&#10074;&#10074; Pause";
  timer = setInterval(() => {
    let frame = current;
    for (let n = 0; n < perTick && frame < lastFrame(); n++) {
      frame++;
      applyChanges(frame);
      if (stopAtArea.checked && house.areaStarts.includes(frame)) break;
    }
    draw();
    show(frame);
    const atNewArea = stopAtArea.checked && house.areaStarts.includes(frame) && frame > 0;
    if (frame >= lastFrame() || atNewArea) pause();
  }, interval);
}

function nextArea(direction) {
  const starts = house.areaStarts;
  const target = direction > 0
    ? starts.find((frame) => frame > current)
    : [...starts].reverse().find((frame) => frame < current);
  pause();
  go(target === undefined ? (direction > 0 ? lastFrame() : 0) : target);
}

// Size the characters to the cells, which depend on the window size.
function fitText() {
  const cell = Math.min(chart.clientWidth / house.width, chart.clientHeight / house.height);
  Plotly.restyle(chart, { "textfont.size": Math.max(5, Math.floor(cell * 0.62)) }, [0]);
}

function load(index, frame = 0) {
  pause();
  house = HOUSES[index];
  picker.value = String(index);
  slider.max = String(lastFrame());
  document.getElementById("result").textContent = house.result;
  rebuild(0);
  current = 0;
  Plotly.purge(chart);
  const trace = { ...house.trace, z: codes.map((line) => line.slice()) };
  return Plotly.newPlot(chart, [trace], house.layout, { responsive: true, displaylogo: false })
    .then(() => {
      fitText();
      show(0);
      if (frame > 0) go(frame);
    });
}

picker.addEventListener("change", () => {
  load(Number(picker.value));
  history.replaceState(null, "", "#house=" + encodeURIComponent(house.name));
});
playButton.addEventListener("click", () => (timer ? pause() : play()));
document.getElementById("prev").addEventListener("click", () => { pause(); go(current - 1); });
document.getElementById("next").addEventListener("click", () => { pause(); go(current + 1); });
document.getElementById("prev-area").addEventListener("click", () => nextArea(-1));
document.getElementById("next-area").addEventListener("click", () => nextArea(1));
slider.addEventListener("input", () => { pause(); go(Number(slider.value)); });
speed.addEventListener("change", () => { if (timer) { pause(); play(); } });
document.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLSelectElement || event.target === slider) return;
  if (event.key === " ") { event.preventDefault(); timer ? pause() : play(); }
  if (event.key === "ArrowLeft") { pause(); go(current - 1); }
  if (event.key === "ArrowRight") { pause(); go(current + 1); }
  if (event.key === "PageUp") { event.preventDefault(); nextArea(-1); }
  if (event.key === "PageDown") { event.preventDefault(); nextArea(1); }
});
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(fitText, 150);
});

const hash = location.hash.slice(1);
const params = new URLSearchParams(/^\\d+$$/.test(hash) ? "frame=" + hash : hash);
const named = HOUSES.findIndex((item) => item.name === params.get("house"));
load(Math.max(0, named), Number(params.get("frame")) || 0);
</script>
</body>
</html>
""")
