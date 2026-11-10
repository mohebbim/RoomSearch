"""Check that the visualisers follow count_chairs step by step."""

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from chair_counter import count_chairs, format_report
from chair_counter.cli import main
from chair_counter.floor_plan import _parse_plan
from chair_counter.plotly_html import FrameRecorder, write_html
from chair_counter.visualize import collect_plans, trace_plan
from chair_counter.visualize import run

TWO_ROOMS = (
    "+---------+---------+\n"
    "|(Studio) |         |\n"
    "| W       | P       |\n"
    "+---------+---------+\n"
)


def houses_in(page: str) -> list[dict]:
    """Return the house data embedded in a generated page."""
    payload = re.search(r"const HOUSES = (.*)\.houses;\n", page, re.S).group(1)
    return json.loads(payload)["houses"]


class VisualizeTests(unittest.TestCase):
    """Exercise plain, animated and HTML output without a real terminal."""

    def test_plain_output_logs_each_step_and_the_report(self) -> None:
        """Log scans, pops, neighbour checks and recordings, then the report."""
        out = io.StringIO()

        code = run(TWO_ROOMS, out, colour=False, animate=False)

        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn(
            "     1  border cell (0, 0) is open and in no area yet, "
            "so start the outside here and push it onto the stack.",
            text,
        )
        self.assertIn("Look below border cell (0, 1): line 1, col 1 is a wall '+', blocked.", text)
        self.assertIn("The label (Studio) starts at line 2, col 2", text)
        self.assertIn("line 3, col 3 holds chair W. Area 1 (Studio) now has W: 1", text)
        self.assertIn("_add_area records room 'Studio' with W: 1, P: 0, S: 0, C: 0", text)
        self.assertIn("area 2 (no label): 18 cells, W: 0, P: 1, S: 0, C: 0", text)
        self.assertTrue(text.endswith("Studio:\nW: 1, P: 0, S: 0, C: 0\n"))

    def test_every_draws_frames_with_stack_and_report(self) -> None:
        """Draw a frame every N steps showing the stack and the report so far."""
        out = io.StringIO()

        run(TWO_ROOMS, out, colour=False, animate=False, every=50)

        text = out.getvalue()
        self.assertIn("Step 51 | the outside", text)
        self.assertIn("Stack (", text)
        self.assertIn("Report so far: total W: 1, P: 0, S: 0, C: 0 | rooms: Studio", text)

    def test_gap_in_outer_wall_is_flagged(self) -> None:
        """Show the chair that leaks outside and return a failing exit code."""
        out = io.StringIO()

        code = run("+-----+\n| W   \n+-----+\n", out, colour=False, animate=False)

        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("chairs found: W: 1", text)
        self.assertIn("_add_area rejects it: A room label or chair", text)
        self.assertIn("count_chairs rejects this plan", text)

    def test_animation_runs_without_a_terminal(self) -> None:
        """Draw coloured frames in place and restore the cursor afterwards."""
        out = io.StringIO()

        code = run(TWO_ROOMS, out, colour=True, animate=True, delay=0)

        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("\x1b[48;5;", text)
        self.assertIn("\x1b[?25h", text)

    def test_html_has_play_button_and_one_status_per_frame(self) -> None:
        """Write a Plotly page whose frames and status lines line up."""
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "search.html"
            code = write_html([("two rooms", TWO_ROOMS)], path, out, every=10)
            page = path.read_text(encoding="utf-8")
        house = houses_in(page)[0]

        self.assertEqual(code, 0)
        self.assertIn('<button id="play"', page)
        self.assertNotIn("height", house["layout"])  # The page sizes the grid.
        self.assertEqual(len(house["deltas"]), len(house["statuses"]))
        self.assertEqual(house["statuses"][0][0], "Step 1 | the outside")
        self.assertEqual(house["statuses"][1][0], "Step 11 | the outside")
        self.assertIn("Report so far: total W: 1, P: 1", house["statuses"][-1][-1])
        self.assertEqual(house["result"], format_report(count_chairs(TWO_ROOMS)))

    def test_every_step_is_a_frame_and_new_areas_are_marked(self) -> None:
        """Record each step by default and list the frames where new areas start."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "search.html"
            write_html([("two rooms", TWO_ROOMS)], path, io.StringIO())
            house = houses_in(path.read_text(encoding="utf-8"))[0]

        steps = [int(status[0].split()[1]) for status in house["statuses"]]
        self.assertEqual(steps, list(range(1, len(steps) + 1)))
        self.assertEqual(len(house["areaStarts"]), 3)  # The outside and two rooms.
        for frame in house["areaStarts"]:
            self.assertIn("so start", house["statuses"][frame][1])
        studio = house["statuses"][house["areaStarts"][1]][1]
        self.assertTrue(studio.startswith("The scan moves past"))

    def test_recorded_colours_match_a_full_redraw_on_every_frame(self) -> None:
        """Updating only the changed cells gives the same colours as recomputing all."""

        class CheckedRecorder(FrameRecorder):
            def show_frame(self, long_pause: bool) -> None:
                super().show_frame(long_pause)
                stack = set(self.stack)
                expected = [
                    [self._code(*self.cell_state((row, column), stack)) for column in range(self.width)]
                    for row in range(self.height)
                ]
                if expected != self.codes:
                    raise AssertionError(f"Colours differ at step {self.step_number}.")

        for plan in (TWO_ROOMS, "+-----+\n| W   \n+-----+\n"):
            grid, labels = _parse_plan(plan)
            recorder = CheckedRecorder(plan, grid, every=1)
            trace_plan(recorder, grid, labels)
            self.assertEqual(len(recorder.deltas), recorder.step_number)

    def test_html_with_several_houses_keeps_each_result(self) -> None:
        """Put every house on one page, including the error for a rejected plan."""
        out = io.StringIO()
        houses = [("two rooms", TWO_ROOMS), ("leaky", "+-----+\n| W   \n+-----+\n")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "search.html"
            code = write_html(houses, path, out)
            page = path.read_text(encoding="utf-8")

        recorded = houses_in(page)
        self.assertEqual(code, 1)
        self.assertIn('id="house"', page)
        self.assertEqual([house["name"] for house in recorded], ["two rooms", "leaky"])
        self.assertTrue(recorded[1]["result"].startswith("count_chairs rejects this plan"))

    def test_cli_output_saves_a_report_named_after_the_plan(self) -> None:
        """Save the printed report as <plan>_report.txt, with no web page by default."""
        with tempfile.TemporaryDirectory() as folder:
            plan = Path(folder) / "studio.txt"
            plan.write_text(TWO_ROOMS, encoding="utf-8")
            output = Path(folder) / "output"
            with redirect_stdout(io.StringIO()) as printed:
                main([str(plan), "--output", str(output)])
            report = (output / "studio_report.txt").read_text(encoding="utf-8")
            files = sorted(path.name for path in output.iterdir())

        self.assertEqual(report, format_report(count_chairs(TWO_ROOMS)) + "\n")
        self.assertEqual(printed.getvalue(), report)
        self.assertEqual(files, ["studio_report.txt"])

    def test_cli_animation_adds_a_page_named_after_the_plan(self) -> None:
        """Write <plan>_search.html next to the report when --animation is given."""
        with tempfile.TemporaryDirectory() as folder:
            plan = Path(folder) / "family_house.txt"
            plan.write_text(TWO_ROOMS, encoding="utf-8")
            output = Path(folder) / "output"
            with redirect_stdout(io.StringIO()):
                main([str(plan), "--output", str(output), "--animation"])
            page = (output / "family_house_search.html").read_text(encoding="utf-8")

        self.assertEqual([house["name"] for house in houses_in(page)], ["family house"])

    def test_cli_animation_needs_an_output_folder(self) -> None:
        """Refuse --animation without --output, with argparse's exit code 2."""
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            main(["plan.txt", "--animation"])

        self.assertEqual(stopped.exception.code, 2)

    def test_visualizer_reads_every_plan_in_a_folder(self) -> None:
        """Expand a folder into its .txt plans, sorted by name."""
        with tempfile.TemporaryDirectory() as folder:
            for name in ("b.txt", "a.txt", "notes.md"):
                (Path(folder) / name).write_text(TWO_ROOMS, encoding="utf-8")

            plans = collect_plans([Path(folder)])

        self.assertEqual([path.name for path in plans], ["a.txt", "b.txt"])


if __name__ == "__main__":
    unittest.main()
