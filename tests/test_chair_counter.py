"""Regression tests for the floor plan rules and legacy report format.

Every test runs against both counting approaches: ``count_chairs`` (connected
areas, the default) and ``count_chairs_room_seeded`` (flood fill from each room
name). They must give the exact expected output and agree with each other.
"""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from chair_counter import count_chairs, count_chairs_room_seeded, format_report
from chair_counter.cli import main

APPROACHES = {
    "connected-areas": count_chairs,
    "room-seeded": count_chairs_room_seeded,
}
INPUTS = Path(__file__).resolve().parent.parent / "inputs"


class ChairCounterTests(unittest.TestCase):
    """Exercise both approaches on distinct floor plan layouts."""

    def assert_report(self, plan: str, expected: str) -> None:
        """Check that every approach prints exactly ``expected`` for ``plan``."""
        for name, count in APPROACHES.items():
            with self.subTest(approach=name):
                self.assertEqual(format_report(count(plan)), expected)

    def assert_rejected(self, plan: str, message: str) -> None:
        """Check that every approach rejects ``plan`` with an error matching ``message``."""
        for name, count in APPROACHES.items():
            with self.subTest(approach=name), self.assertRaisesRegex(ValueError, message):
                count(plan)

    def test_supplied_plan(self) -> None:
        """The supplied plan's total, and seven wooden chairs in the living room.

        The hallway below the closet opens into the living room, so under the
        wall-boundary rule its chair belongs to the living room: 6 + 1 = 7.
        """
        plan = (INPUTS / "rooms.txt").read_text(encoding="utf-8")
        for name, count in APPROACHES.items():
            with self.subTest(approach=name):
                report = count(plan)
                self.assertEqual(report.total, {"W": 14, "P": 7, "S": 3, "C": 1})
                self.assertEqual(report.rooms["living room"]["W"], 7)

    def test_both_approaches_agree_on_every_sample_plan(self) -> None:
        """Print the same report for every plan in inputs/."""
        for path in sorted(INPUTS.glob("*.txt")):
            plan = path.read_text(encoding="utf-8")
            reports = {format_report(count(plan)) for count in APPROACHES.values()}
            with self.subTest(plan=path.name):
                self.assertEqual(len(reports), 1)

    def test_indented_empty_room_and_unlabelled_area(self) -> None:
        """Keep an indented empty room, count unlabelled chairs, and ignore label letters."""
        plan = (
            "+---------+---------+\n"
            "|(Studio) |         |\n"
            "| W       | P       |\n"
            "+---------+---------+\n"
            "          |(closet) |\n"
            "          +---------+\n"
        )

        self.assert_report(
            plan,
            "total:\n"
            "W: 1, P: 1, S: 0, C: 0\n"
            "closet:\n"
            "W: 0, P: 0, S: 0, C: 0\n"
            "Studio:\n"
            "W: 1, P: 0, S: 0, C: 0",
        )

    def test_diagonal_wall(self) -> None:
        """Keep spaces separated by a diagonal chain of wall cells."""
        plan = (
            "+-----------+\n"
            "| (A)   /   |\n"
            "|      / W  |\n"
            "|  S  /     |\n"
            "|    /  (B) |\n"
            "+-----------+\n"
        )

        self.assert_report(
            plan,
            "total:\n"
            "W: 1, P: 0, S: 1, C: 0\n"
            "A:\n"
            "W: 0, P: 0, S: 1, C: 0\n"
            "B:\n"
            "W: 1, P: 0, S: 0, C: 0",
        )

    def test_label_or_chair_connected_to_exterior(self) -> None:
        """Reject a gap in the exterior wall that exposes a label or chair."""
        for interior in ("|(A)  |", "|   C |"):
            with self.subTest(interior=interior):
                self.assert_rejected(f"+-----+\n{interior}\n+-- --+\n", "connected to the exterior")

    def test_two_labels_in_one_area(self) -> None:
        """Reject a connected area whose label is ambiguous."""
        self.assert_rejected("+-------+\n|(A) (B)|\n+-------+\n", "multiple room labels")

    def test_duplicate_room_names(self) -> None:
        """Reject duplicate room names in different areas."""
        self.assert_rejected("+---+---+\n|(A)|(A)|\n+---+---+\n", "Duplicate room label")

    def test_unknown_character(self) -> None:
        """Report the original coordinates of an unknown character."""
        self.assert_rejected("+---+\n| X |\n+---+\n", r"'X' on line 2, column 3")

    def test_cli_approach_option(self) -> None:
        """Print the same report with either --approach, and default to connected areas."""
        plan = str(INPUTS / "rooms.txt")
        printed = {}
        for argv in ([plan], ["--approach", "connected-areas", plan], ["--approach", "room-seeded", plan]):
            with redirect_stdout(io.StringIO()) as out:
                main(argv)
            printed[" ".join(argv[:-1]) or "default"] = out.getvalue()

        self.assertEqual(len(set(printed.values())), 1)
        self.assertTrue(printed["default"].startswith("total:\nW: 14, P: 7, S: 3, C: 1\n"))


if __name__ == "__main__":
    unittest.main()
