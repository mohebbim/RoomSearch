"""Count chair markers in an ASCII floor plan and print a room-by-room report."""

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

CHAIR_TYPES = ("W", "P", "S", "C")
WALLS = frozenset("+-|/\\")
PLAN_CHARACTERS = WALLS.union(CHAIR_TYPES, " ")
ROOM_LABEL = re.compile(r"\(([^()]*)\)")

Position = tuple[int, int]


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
    grid: list[str], start: Position, visited: set[Position]
) -> Iterator[Position]:
    """Yield each cell reachable from start by moving along rows and columns."""
    height, width = len(grid), len(grid[0])
    pending = [start]
    visited.add(start)

    while pending:
        row, column = pending.pop()
        yield row, column

        for next_row, next_column in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            if not (0 <= next_row < height and 0 <= next_column < width):
                continue
            neighbour = (next_row, next_column)
            if neighbour in visited or grid[next_row][next_column] in WALLS:
                continue
            visited.add(neighbour)
            pending.append(neighbour)


def count_chairs(plan: str) -> ChairReport:
    """Count chairs in enclosed areas, with subtotals for uniquely named rooms.

    Areas are separated by the drawn walls. Unlabelled enclosed areas contribute
    to the apartment total. Raise ValueError for malformed text, duplicate or
    conflicting room labels, or chairs and labels connected to the exterior.
    """
    grid, labels = _parse_plan(plan)
    visited: set[Position] = set()
    report = ChairReport(total=Counter(), rooms={})

    for row, line in enumerate(grid):
        for column, cell in enumerate(line):
            start = (row, column)
            if cell in WALLS or start in visited:
                continue

            area_chairs: Counter[str] = Counter()
            area_names: list[str] = []
            for area_row, area_column in _walk_area(grid, start, visited):
                name = labels.get((area_row, area_column))
                if name is not None:
                    area_names.append(name)
                marker = grid[area_row][area_column]
                if marker in CHAIR_TYPES:
                    area_chairs[marker] += 1

            if start == (0, 0):
                if area_names or area_chairs:
                    raise ValueError(
                        "A room label or chair is connected to the exterior. "
                        "Check the outer walls for gaps."
                    )
                continue

            if len(area_names) > 1:
                names = ", ".join(area_names)
                raise ValueError(f"One connected area has multiple room labels: {names}.")
            if area_names:
                name = area_names[0]
                if name in report.rooms:
                    raise ValueError(f"Duplicate room label {name!r}.")
                report.rooms[name] = area_chairs
            report.total.update(area_chairs)

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
