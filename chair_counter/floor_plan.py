"""Count the chairs in an ASCII floor plan, for the whole apartment and per room.

This module holds all of the counting logic. ``count_chairs`` runs four steps:

1. ``_parse_plan`` turns the text into a rectangular grid of characters with a
   blank border around it, and takes the room labels such as ``(office)`` out
   of the grid so their letters are not counted as chairs.
2. ``_find_areas`` scans the grid row by row. Every open cell that is not yet
   part of an area starts a new area.
3. ``_walk_area`` fills one area: starting from a cell, it keeps moving up,
   down, left and right until walls stop it (a flood fill using a stack).
4. ``_add_area`` checks each finished area against the input rules and adds
   its chairs to the ``ChairReport``.

``format_report`` then turns the report into the text format the old system
reads. The animation in ``plotly_html.py`` reuses these same functions
through the optional ``trace`` hook described in ``Trace``.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass

CHAIR_TYPES = ("W", "P", "S", "C")
"""Chair markers in report order: wooden, plastic, sofa and china chairs."""

WALLS = frozenset("+-|/\\")
"""Characters that block movement between cells."""

PLAN_CHARACTERS = WALLS.union(CHAIR_TYPES, " ")
"""Every character allowed in a plan outside of room labels."""

ROOM_LABEL = re.compile(r"\(([^()]*)\)")
"""A room label such as ``(living room)``. Group 1 is the name."""

Position = tuple[int, int]
"""A (row, column) cell in the padded grid. Row r is line r of the plan file."""

Trace = Callable[..., None]
"""A function that observes the search, called as ``trace(event, position, **details)``.

The events are:

- ``"scan"``: the row-by-row scan looked at a cell. ``result`` is ``"wall"``,
  ``"visited"`` or ``"new area"``. A new area also comes with ``area``.
- ``"visit"``: a cell was popped from the stack. ``stack`` is the live stack.
- ``"check"``: a neighbour of ``source`` was checked. ``result`` is
  ``"off grid"``, ``"visited"``, ``"wall"`` or ``"added"`` (pushed onto the stack).
- ``"label"`` and ``"chair"``: the area being filled recorded a room name
  (``name``) or a chair (``chair``). Both come with ``area``.

``count_chairs`` uses ``_no_trace``, so tracing costs nothing there.
"""


def _no_trace(event: str, position: Position, **details: object) -> None:
    """Ignore a search event. This is the default ``trace`` for the search functions."""


@dataclass
class ChairReport:
    """Chair counts for the whole apartment and for each named room.

    Attributes:
        total: Number of chairs of each type in all enclosed areas, named or not.
        rooms: Chair counts for each named room, keyed by room name.
    """

    total: Counter[str]
    rooms: dict[str, Counter[str]]


@dataclass
class Area:
    """One connected area of open cells, as found by ``_find_areas``.

    Attributes:
        cells: Every cell in the area, in the order the flood fill reached them.
        chairs: Number of chairs of each type in the area.
        names: Room labels found in the area. A valid area has at most one.
    """

    cells: list[Position]
    chairs: Counter[str]
    names: list[str]

    @property
    def is_exterior(self) -> bool:
        """Whether this area is the outside of the building.

        The scan starts at (0, 0), the top-left corner of the blank border that
        ``_parse_plan`` adds, so the area that starts there is the outside.
        """
        return self.cells[0] == (0, 0)


def _parse_plan(plan: str) -> tuple[list[str], dict[Position, str]]:
    """Turn the plan text into a padded grid and find the room labels.

    Each label is replaced by spaces in the grid, so the letters in a name such
    as ``(office)`` are treated as floor rather than chairs. Shorter lines are
    padded on the right, and one blank cell is added on every side so the
    outside of the building is a single connected area.

    Args:
        plan: The floor plan text.

    Returns:
        The grid as a list of equal-length strings, and a mapping from the
        position of each label's opening parenthesis to the room name.

    Raises:
        ValueError: If the plan is empty, a label is empty, or a character is
            not a wall, chair, space or part of a label.
    """
    if not plan.strip():
        raise ValueError("The floor plan is empty.")

    lines = plan.splitlines()
    width = max(map(len, lines))
    border = " " * (width + 2)
    grid = [border]
    labels = {}

    for row, line in enumerate(lines, start=1):
        cells = list(line)
        for match in ROOM_LABEL.finditer(line):
            name = match.group(1).strip()
            if not name:
                raise ValueError(f"Empty room label on line {row}.")
            labels[row, match.start() + 1] = name
            cells[match.start():match.end()] = " " * len(match.group())

        for column, cell in enumerate(cells, start=1):
            if cell not in PLAN_CHARACTERS:
                raise ValueError(
                    f"Unexpected character {cell!r} on line {row}, column {column}."
                )

        grid.append(" " + "".join(cells).ljust(width) + " ")

    grid.append(border)
    return grid, labels


def _walk_area(
    grid: list[str],
    start: Position,
    visited: set[Position],
    trace: Trace = _no_trace,
) -> Iterator[Position]:
    """Flood-fill one area and yield each of its cells.

    The fill keeps a stack of cells still to expand. Each step pops a cell,
    yields it, and checks its four neighbours. A neighbour is pushed onto the
    stack unless it is off the grid, already visited, or a wall. Moving only
    up, down, left and right means two diagonal wall characters that touch at
    a corner, such as ``/`` above-right of ``/``, form a closed wall.

    Args:
        grid: The padded grid from ``_parse_plan``.
        start: An open cell that is not yet in ``visited``.
        visited: Cells already assigned to an area. Updated as cells are reached.
        trace: Receives a ``"visit"`` event per popped cell and a ``"check"``
            event per neighbour (see ``Trace``).

    Yields:
        Each cell of the area, in the order it is popped from the stack.
    """
    height, width = len(grid), len(grid[0])
    pending = [start]
    visited.add(start)

    while pending:
        row, column = pending.pop()
        trace("visit", (row, column), stack=pending)
        yield row, column

        for neighbour in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            next_row, next_column = neighbour
            if not (0 <= next_row < height and 0 <= next_column < width):
                result = "off grid"
            elif neighbour in visited:
                result = "visited"
            elif grid[next_row][next_column] in WALLS:
                result = "wall"
            else:
                visited.add(neighbour)
                pending.append(neighbour)
                result = "added"
            trace("check", neighbour, source=(row, column), result=result)


def _find_areas(
    grid: list[str], labels: dict[Position, str], trace: Trace = _no_trace
) -> Iterator[Area]:
    """Split the grid into connected areas and yield them one at a time.

    The scan visits every cell row by row. A wall or an already visited cell is
    skipped. Any other cell starts a new area, which ``_walk_area`` fills while
    this function records the labels and chairs it passes over. The first area
    is always the outside of the building.

    Args:
        grid: The padded grid from ``_parse_plan``.
        labels: Room names by position, from ``_parse_plan``.
        trace: Receives ``"scan"``, ``"label"`` and ``"chair"`` events, plus the
            events of ``_walk_area`` (see ``Trace``).

    Yields:
        Each area once it has been completely filled.
    """
    visited: set[Position] = set()

    for row, line in enumerate(grid):
        for column, cell in enumerate(line):
            start = (row, column)
            if cell in WALLS:
                trace("scan", start, result="wall")
                continue
            if start in visited:
                trace("scan", start, result="visited")
                continue

            area = Area(cells=[], chairs=Counter(), names=[])
            trace("scan", start, result="new area", area=area)
            for position in _walk_area(grid, start, visited, trace):
                area.cells.append(position)
                name = labels.get(position)
                if name is not None:
                    area.names.append(name)
                    trace("label", position, name=name, area=area)
                marker = grid[position[0]][position[1]]
                if marker in CHAIR_TYPES:
                    area.chairs[marker] += 1
                    trace("chair", position, chair=marker, area=area)
            yield area


def _add_area(report: ChairReport, area: Area) -> None:
    """Check an area against the input rules and add its chairs to the report.

    The outside adds nothing, but must not contain chairs or labels. An enclosed
    area adds its chairs to the total, and to a room subtotal if it is named.

    Args:
        report: The report being built. Left unchanged if the area is rejected.
        area: A finished area from ``_find_areas``.

    Raises:
        ValueError: If a chair or label is outside the walls, an area has more
            than one label, or a room name is used twice.
    """
    if area.is_exterior:
        if area.names or area.chairs:
            raise ValueError(
                "A room label or chair is connected to the exterior. "
                "Check the outer walls for gaps."
            )
        return

    if len(area.names) > 1:
        names = ", ".join(area.names)
        raise ValueError(f"One connected area has multiple room labels: {names}.")
    if area.names:
        name = area.names[0]
        if name in report.rooms:
            raise ValueError(f"Duplicate room label {name!r}.")
        report.rooms[name] = area.chairs
    report.total.update(area.chairs)


def count_chairs(plan: str) -> ChairReport:
    """Count the chairs in a floor plan, in total and for each named room.

    Chairs in enclosed areas without a label count toward the total only.
    An open passage joins the areas on both sides into one area.

    Args:
        plan: The floor plan text.

    Returns:
        The counts for the whole apartment and for each named room.

    Raises:
        ValueError: If the text is malformed, a label is duplicated or shares an
            area with another label, or a chair or label is outside the walls.
    """
    grid, labels = _parse_plan(plan)
    report = ChairReport(total=Counter(), rooms={})
    for area in _find_areas(grid, labels):
        _add_area(report, area)
    return report


def format_report(report: ChairReport) -> str:
    """Format a report in the exact text layout the old system reads.

    The total comes first, then each room in alphabetical order, ignoring case.
    Each section is a ``name:`` line followed by the counts of all four chair
    types, including zeros, for example ``W: 3, P: 2, S: 0, C: 0``.

    Args:
        report: The counts from ``count_chairs``.

    Returns:
        The report text, without a trailing newline.
    """
    sections = [("total", report.total)]
    sections.extend(
        (name, report.rooms[name]) for name in sorted(report.rooms, key=str.casefold)
    )

    lines = []
    for name, counts in sections:
        lines.append(f"{name}:")
        lines.append(", ".join(f"{chair}: {counts[chair]}" for chair in CHAIR_TYPES))
    return "\n".join(lines)
