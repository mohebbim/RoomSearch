"""A second way to count chairs: flood-fill outwards from each room name.

``floor_plan.count_chairs`` (the default, "connected areas") scans the whole
grid and fills every connected area it finds, then decides what each area is.
``count_chairs_room_seeded`` here starts from what the report needs instead:

1. Parse the plan with ``floor_plan._parse_plan``, which records the position
   of every room label and checks the characters.
2. Flood-fill from the padded border's corner to find the exterior. A chair
   or label reached here means a gap in the outer wall.
3. Count the apartment total in a separate scan: every chair in a cell that is
   not part of the exterior. This includes chairs in unlabelled spaces, which
   no room fill reaches.
4. Flood-fill from each room label to find that room's cells and chairs. A
   shared ``visited`` set means no cell is ever filled twice, so two labels in
   one space cannot double-count; the fill that finds both reports an error.

Everything except the order of the work is shared with ``floor_plan``: the
parser, the fill (``_fill_area``, built on the four-direction ``_walk_area``),
the input rules (``_check_exterior``, ``_room_name``, ``_add_room``) and the
report (``ChairReport`` and ``format_report``). The two approaches therefore
give the same report and the same errors.
"""

from collections import Counter

from .floor_plan import (
    CHAIR_TYPES,
    WALLS,
    Area,
    ChairReport,
    Position,
    Trace,
    _add_room,
    _check_exterior,
    _fill_area,
    _no_trace,
    _parse_plan,
    _room_name,
)

EXTERIOR_START: Position = (0, 0)
"""The top-left corner of the blank border ``_parse_plan`` adds, always outside."""


def _fill_exterior(
    grid: list[str],
    labels: dict[Position, str],
    visited: set[Position],
    report: ChairReport,
    trace: Trace = _no_trace,
) -> Area:
    """Flood-fill the outside of the building and check nothing belongs to it.

    Args:
        grid: The padded grid from ``_parse_plan``.
        labels: Room names by position, from ``_parse_plan``.
        visited: The cells reached so far. The exterior's cells are added.
        report: The report being built, passed to ``trace`` only.
        trace: Receives ``"seed"`` and ``"exterior"`` events, plus the events of
            ``_fill_area``.

    Returns:
        The exterior area.

    Raises:
        ValueError: If a chair or a label is reachable from the outside.
    """
    area = Area(cells=[], chairs=Counter(), names=[])
    trace("seed", EXTERIOR_START, role="exterior", area=area, report=report)
    _fill_area(grid, labels, EXTERIOR_START, visited, area, trace)
    _check_exterior(area)
    trace("exterior", EXTERIOR_START, area=area)
    return area


def _count_enclosed_chairs(
    grid: list[str], exterior: set[Position], total: Counter[str], trace: Trace = _no_trace
) -> None:
    """Add every chair inside the building, named room or not, to ``total``.

    This is a plain scan of the grid, separate from the room fills, so chairs
    in unlabelled spaces such as corridors are part of the total.

    Args:
        grid: The padded grid from ``_parse_plan``.
        exterior: The exterior's cells, from ``_fill_exterior``.
        total: The apartment total, updated in place.
        trace: Receives a ``"total"`` event for every cell, whose ``result`` is
            ``"outside"``, ``"wall"``, ``"floor"`` or ``"chair"``.
    """
    for row, line in enumerate(grid):
        for column, cell in enumerate(line):
            position = (row, column)
            if position in exterior:
                result = "outside"
            elif cell in WALLS:
                result = "wall"
            elif cell in CHAIR_TYPES:
                total[cell] += 1
                result = "chair"
            else:
                result = "floor"
            trace("total", position, result=result, chair=cell, total=total)


def _fill_room(
    grid: list[str],
    labels: dict[Position, str],
    start: Position,
    visited: set[Position],
    report: ChairReport,
    trace: Trace = _no_trace,
) -> None:
    """Flood-fill one room from its label and store its chair subtotal.

    Args:
        grid: The padded grid from ``_parse_plan``.
        labels: Room names by position, from ``_parse_plan``.
        start: The position of the room's label, which is open floor.
        visited: The cells reached so far. The room's cells are added.
        report: The report the room's subtotal is added to.
        trace: Receives ``"seed"`` and ``"room"`` events, plus the events of
            ``_fill_area``.

    Raises:
        ValueError: If the fill reaches a second label, or the name is taken.
    """
    area = Area(cells=[], chairs=Counter(), names=[])
    trace("seed", start, role="room", name=labels[start], area=area)
    _fill_area(grid, labels, start, visited, area, trace)
    name = _room_name(area)
    _add_room(report, name, area.chairs)
    trace("room", start, name=name, area=area)


def count_parsed_room_seeded(
    grid: list[str], labels: dict[Position, str], trace: Trace = _no_trace
) -> ChairReport:
    """Count the chairs in an already parsed plan by filling from each room label.

    Args:
        grid: The padded grid from ``_parse_plan``.
        labels: Room names by position, from ``_parse_plan``.
        trace: Receives every search event (see ``floor_plan.Trace``).

    Returns:
        The counts for the whole apartment and for each named room.

    Raises:
        ValueError: If a label shares a space with another label or is used
            twice, or a chair or label is outside the walls.
    """
    report = ChairReport(total=Counter(), rooms={})
    visited: set[Position] = set()

    exterior = _fill_exterior(grid, labels, visited, report, trace)
    _count_enclosed_chairs(grid, set(exterior.cells), report.total, trace)
    for position in labels:
        if position in visited:
            # An earlier room's fill reached this label, and would already have
            # raised the "multiple room labels" error. A space is never filled
            # twice, so its chairs can never be counted twice.
            continue
        _fill_room(grid, labels, position, visited, report, trace)
    return report


def count_chairs_room_seeded(plan: str) -> ChairReport:
    """Count the chairs in a floor plan by filling outwards from each room label.

    Gives the same result as ``floor_plan.count_chairs`` and raises the same
    errors, but fills only the exterior and the named rooms. Unlabelled spaces
    are never filled; their chairs reach the total through a separate scan.

    Args:
        plan: The floor plan text.

    Returns:
        The counts for the whole apartment and for each named room.

    Raises:
        ValueError: If the text is malformed, a label is duplicated or shares a
            space with another label, or a chair or label is outside the walls.
    """
    grid, labels = _parse_plan(plan)
    return count_parsed_room_seeded(grid, labels)
