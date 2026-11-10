"""Check that the visualiser follows count_chairs and reports its result."""

import io
import unittest

from chair_counter.visualize import run

TWO_ROOMS = (
    "+---------+---------+\n"
    "|(Studio) |         |\n"
    "| W       | P       |\n"
    "+---------+---------+\n"
)


class VisualizeTests(unittest.TestCase):
    """Exercise plain and animated output without a real terminal."""

    def test_plain_output_lists_areas_and_report(self) -> None:
        """Print one frame per area, then the same report as count_chairs."""
        out = io.StringIO()

        code = run(TWO_ROOMS, out, colour=False, animate=False)

        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("|.W.......|", text)
        self.assertIn("area 1 (Studio): 18 cells, W: 1, P: 0, S: 0, C: 0", text)
        self.assertIn("area 2 (no label): 18 cells, W: 0, P: 1, S: 0, C: 0", text)
        self.assertTrue(text.endswith("Studio:\nW: 1, P: 0, S: 0, C: 0\n"))

    def test_gap_in_outer_wall_is_flagged(self) -> None:
        """Show the chair that leaks outside and return a failing exit code."""
        out = io.StringIO()

        code = run("+-----+\n| W   \n+-----+\n", out, colour=False, animate=False)

        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("chairs found: W: 1", text)
        self.assertIn("count_chairs rejects this plan", text)

    def test_animation_runs_without_a_terminal(self) -> None:
        """Draw coloured frames in place and restore the cursor afterwards."""
        out = io.StringIO()

        code = run(TWO_ROOMS, out, colour=True, animate=True, delay=0)

        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("\x1b[48;5;", text)
        self.assertIn("\x1b[?25h", text)


if __name__ == "__main__":
    unittest.main()
