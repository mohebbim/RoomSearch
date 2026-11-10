"""Regression tests for the floor plan rules and legacy report format."""

import unittest

from chair_counter import count_chairs, format_report


class ChairCounterTests(unittest.TestCase):
    """Exercise connected areas across distinct floor plan layouts."""

    def test_indented_empty_room_and_unlabelled_area(self) -> None:
        """Keep an indented room, count unlabelled chairs, and ignore label letters."""
        plan = (
            "+---------+---------+\n"
            "|(Studio) |         |\n"
            "| W       | P       |\n"
            "+---------+---------+\n"
            "          |(closet) |\n"
            "          +---------+\n"
        )

        self.assertEqual(
            format_report(count_chairs(plan)),
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

        report = count_chairs(plan)
        self.assertEqual(report.rooms, {"A": {"S": 1}, "B": {"W": 1}})

    def test_label_or_chair_connected_to_exterior(self) -> None:
        """Reject a gap in the exterior wall that exposes a label or chair."""
        for interior in ("|(A)  |", "|   C |"):
            with self.subTest(interior=interior):
                plan = f"+-----+\n{interior}\n+-- --+\n"
                with self.assertRaisesRegex(ValueError, "connected to the exterior"):
                    count_chairs(plan)

    def test_two_labels_in_one_area(self) -> None:
        """Reject a connected area whose label is ambiguous."""
        plan = "+-------+\n|(A) (B)|\n+-------+\n"

        with self.assertRaisesRegex(ValueError, "multiple room labels"):
            count_chairs(plan)

    def test_duplicate_room_names(self) -> None:
        """Reject duplicate room names in different areas."""
        plan = "+---+---+\n|(A)|(A)|\n+---+---+\n"

        with self.assertRaisesRegex(ValueError, "Duplicate room label"):
            count_chairs(plan)

    def test_unknown_character(self) -> None:
        """Report the original coordinates of an unknown character."""
        plan = "+---+\n| X |\n+---+\n"

        with self.assertRaisesRegex(ValueError, r"'X' on line 2, column 3"):
            count_chairs(plan)


if __name__ == "__main__":
    unittest.main()
