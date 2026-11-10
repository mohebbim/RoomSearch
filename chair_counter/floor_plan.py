"""Count chair markers in an ASCII floor plan and print a room-by-room report."""

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass

CHAIR_TYPES = ("W", "P", "S", "C")
WALLS = frozenset("+-|/\\")
PLAN_CHARACTERS = WALLS.union(CHAIR_TYPES, " ")
ROOM_LABEL = re.compile(r"\(([^()]*)\)")

Position = tuple[int, int]
Trace = Callable[..., None]


def _no_trace(event: str, position: Position, **details: object) -> None:
    """Ignore search events. Pass another function as trace to observe the search."""


@dataclass
class ChairReport:
    """Hold apartment-wide counts and a count for each named room."""

    total: Counter[str]
    rooms: dict[str, Counter[str]]


def _parse_plan(plan: str) -> tuple[list[str], dict[Position, str]]:
    """Extract room names and return a rectangular grid with an exterior border."""
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
    """Yield each cell reachable from start by moving along rows and columns.

    trace receives a "visit" event for each cell taken from the stack and a
    "check" event for each of its neighbours, with the result of the check.
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


@dataclass
class Area:
    """One connected area: its cells in search order, chairs and room labels."""

    cells: list[Position]
    chairs: Counter[str]
    names: list[str]

    @property
    def is_exterior(self) -> bool:
        """The scan starts in the padded border, so that area is the outside."""
        return self.cells[0] == (0, 0)


def _find_areas(
    grid: list[str], labels: dict[Position, str], trace: Trace = _no_trace
) -> Iterator[Area]:
    """Scan the grid row by row and yield each connected area once.

    trace receives a "scan" event for each cell the scan looks at, "label" and
    "chair" events when an area records one, and the events of _walk_area.
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
    """Add an area's chairs to the report, or raise ValueError if it breaks a rule.

    The report is left unchanged when the area is rejected.
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
    """Count chairs in enclosed areas, with subtotals for uniquely named rooms.

    Areas are separated by the drawn walls. Unlabelled enclosed areas contribute
    to the apartment total. Raise ValueError for malformed text, duplicate or
    conflicting room labels, or chairs and labels connected to the exterior.
    """
    grid, labels = _parse_plan(plan)
    report = ChairReport(total=Counter(), rooms={})
    for area in _find_areas(grid, labels):
        _add_area(report, area)
    return report


def format_report(report: ChairReport) -> str:
    """Return the legacy report with alphabetized rooms and all chair types."""
    sections = [("total", report.total)]
    sections.extend(
        (name, report.rooms[name]) for name in sorted(report.rooms, key=str.casefold)
    )

    lines = []
    for name, counts in sections:
        lines.append(f"{name}:")
        lines.append(", ".join(f"{chair}: {counts[chair]}" for chair in CHAIR_TYPES))
    return "\n".join(lines)
