"""Read ASCII floor plans and report chair counts.

The public interface is ``count_chairs(plan)``, which returns a ``ChairReport``,
and ``format_report(report)``, which produces the text the old system reads.
``count_chairs_room_seeded(plan)`` is a second approach that gives the same
report by flood-filling from each room name (see ``room_seeded.py``).
"""

from .floor_plan import ChairReport, count_chairs, format_report
from .room_seeded import count_chairs_room_seeded

__all__ = ["ChairReport", "count_chairs", "count_chairs_room_seeded", "format_report"]
