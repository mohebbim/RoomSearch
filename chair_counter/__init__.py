"""Read ASCII floor plans and report chair counts.

The public interface is ``count_chairs(plan)``, which returns a ``ChairReport``,
and ``format_report(report)``, which produces the text the old system reads.
"""

from .floor_plan import ChairReport, count_chairs, format_report

__all__ = ["ChairReport", "count_chairs", "format_report"]
