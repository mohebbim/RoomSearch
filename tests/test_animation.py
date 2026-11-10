"""Check that the animation follows count_chairs step by step, and the CLI options around it."""

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from chair_counter import count_chairs, format_report
from chair_counter.cli import collect_plans, main
from chair_counter.floor_plan import _find_areas, _parse_plan
from chair_counter.plotly_html import FrameRecorder, trace_plan, trace_room_seeded, write_html

TWO_ROOMS = (
    "+---------+---------+\n"
    "|(Studio) |         |\n"
    "| W       | P       |\n"
    "+---------+---------+\n"
)
LEAKY = "+-----+\n| W   \n+-----+\n"


def houses_in(page: str) -> list[dict]:
    """Return the house data embedded in a generated page."""
    payload = re.search(r"const HOUSES = (.*)\.houses;\n", page, re.S).group(1)
    return json.loads(payload)["houses"]


def record(
    houses: list[tuple[str, str]], every: int | None = None, approach: str = "connected-areas"
) -> list[dict]:
    """Write a page for the houses and return each house's recording of one approach."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "search.html"
        write_html(houses, path, every=every)
        page = path.read_text(encoding="utf-8")
    assert '<button id="play"' in page and '<select id="approach">' in page
    runs = [{run["approach"]: run for run in house["runs"]} for house in houses_in(page)]
    return [{**by_approach[approach], "name": house["name"]}
            for house, by_approach in zip(houses_in(page), runs)]


def run_cli(*argv: str) -> str:
    """Run the command line and return what it printed."""
    with redirect_stdout(io.StringIO()) as printed:
        main(list(argv))
    return printed.getvalue()


class AnimationTests(unittest.TestCase):
    """The recorded frames explain each step and match the real result."""

    def test_steps_explain_scans_checks_and_recordings(self) -> None:
        """Explain scans, neighbour checks, chairs, labels and finished areas."""
        house = record([("two rooms", TWO_ROOMS)])[0]
        steps = [status[1] for status in house["statuses"]]

        self.assertEqual(
            steps[0],
            "border cell (0, 0) is open and in no area yet, "
            "so start the outside here and push it onto the stack.",
        )
        self.assertIn(
            "Look below border cell (0, 1): line 1, col 1 is a wall '+', blocked. "
            "It is part of the boundary of the outside.",
            steps,
        )
        self.assertTrue(any(s.startswith("The label (Studio) starts at line 2, col 2") for s in steps))
        self.assertTrue(any("line 3, col 3 holds chair W. Area 1 (Studio) now has W: 1" in s for s in steps))
        self.assertTrue(any("_add_area records room 'Studio' with W: 1, P: 0, S: 0, C: 0" in s for s in steps))
        self.assertEqual(house["result"], format_report(count_chairs(TWO_ROOMS)))

    def test_every_step_is_a_frame_and_new_areas_are_marked(self) -> None:
        """Record each step by default and list the frames where new areas start."""
        house = record([("two rooms", TWO_ROOMS)])[0]

        steps = [int(status[0].split()[1]) for status in house["statuses"]]
        self.assertEqual(steps, list(range(1, len(steps) + 1)))
        self.assertEqual(len(house["deltas"]), len(house["statuses"]))
        self.assertEqual(len(house["areaStarts"]), 3)  # The outside and two rooms.
        for frame in house["areaStarts"]:
            self.assertIn("so start", house["statuses"][frame][1])
        studio = house["statuses"][house["areaStarts"][1]][1]
        self.assertTrue(studio.startswith("The scan moves past"))

    def test_every_skips_steps_but_keeps_area_starts(self) -> None:
        """With every=10, record steps 1, 11, 21, ... plus every area start and end."""
        house = record([("two rooms", TWO_ROOMS)], every=10)[0]

        self.assertNotIn("height", house["layout"])  # The page sizes the grid.
        self.assertEqual(house["statuses"][0][0], "Step 1 | the outside")
        self.assertEqual(house["statuses"][1][0], "Step 11 | the outside")
        self.assertEqual(len(house["areaStarts"]), 3)
        self.assertIn("Report so far: total W: 1, P: 1", house["statuses"][-1][-1])

    def test_recorded_colours_match_a_full_redraw_on_every_frame(self) -> None:
        """Updating only the changed cells gives the same colours as recomputing all."""

        class CheckedRecorder(FrameRecorder):
            def _record_frame(self) -> None:
                super()._record_frame()
                stack = set(self.stack)
                expected = [
                    [self._code(*self.cell_state((row, column), stack)) for column in range(self.width)]
                    for row in range(self.height)
                ]
                if expected != self.codes:
                    raise AssertionError(f"Colours differ at step {self.step_number}.")

        for plan in (TWO_ROOMS, LEAKY, "+---+---+\n|(A)|(A)|\n+---+---+\n"):
            for run in (trace_plan, trace_room_seeded):
                with self.subTest(plan=plan, run=run.__name__):
                    grid, labels = _parse_plan(plan)
                    recorder = CheckedRecorder(plan, grid)
                    run(recorder, grid, labels)
                    self.assertEqual(len(recorder.deltas), recorder.step_number)

    def test_walls_change_colour_once_a_fill_finds_them(self) -> None:
        """Walls start unfound, belong to the area that bumps into them, then stay found."""
        grid, labels = _parse_plan(TWO_ROOMS)
        recorder = FrameRecorder(TWO_ROOMS, grid)
        walls = {(r, c) for r, line in enumerate(grid) for c, cell in enumerate(line) if cell in "+-|"}
        states = []

        def watch(event: str, position: tuple[int, int], **details: object) -> None:
            recorder.trace(event, position, **details)
            if event == "scan" and details["result"] == "new area":
                states.append({recorder.cell_state(wall, set())[0] for wall in walls})

        for area in _find_areas(grid, labels, watch):
            recorder.area_finished(area)
        recorder.finish()
        recorder.scan_path = set()  # The last step highlights the scan path; look past it.

        self.assertEqual(states[0], {"wall"})  # Before the outside is filled.
        self.assertIn("wall-found", states[1])  # The outer walls, found by the outside.
        self.assertIn("wall", states[1])  # The middle wall is out of the outside's reach.
        self.assertEqual({recorder.cell_state(wall, set())[0] for wall in walls}, {"wall-found"})
        steps = "\n".join(status[1] for status in recorder.statuses)
        self.assertIn("It is part of the boundary of area 1 (Studio).", steps)

    def test_room_seeded_recording_follows_its_own_search(self) -> None:
        """Fill the exterior, scan for the total, then fill from each label."""
        house = record([("two rooms", TWO_ROOMS)], approach="room-seeded")[0]
        steps = [status[1] for status in house["statuses"]]

        self.assertTrue(steps[0].startswith("Start the exterior fill at border cell (0, 0)"))
        self.assertTrue(any("Next, scan every cell for chairs that are not outside" in s for s in steps))
        self.assertTrue(any("holds chair P and is not outside, so add it to the apartment total" in s
                            for s in steps))
        self.assertTrue(any("Start a flood fill from the label (Studio) at line 2, col 2" in s for s in steps))
        self.assertTrue(any("room 'Studio' is complete" in s for s in steps))
        self.assertEqual(len(house["areaStarts"]), 2)  # The exterior and Studio only.
        self.assertEqual(house["result"], format_report(count_chairs(TWO_ROOMS)))

    def test_room_seeded_marks_unlabelled_space_and_ends_without_highlights(self) -> None:
        """The unlabelled space stays marked as swept, its chair as counted, and nothing is yellow at the end."""
        grid, labels = _parse_plan(TWO_ROOMS)
        recorder = FrameRecorder(TWO_ROOMS, grid)
        trace_room_seeded(recorder, grid, labels)

        state = lambda cell: recorder.cell_state(cell, set())[0]  # noqa: E731
        self.assertEqual(state((3, 13)), "chair-total")  # The P in the unlabelled space.
        self.assertEqual(state((2, 14)), "inside-swept")
        self.assertEqual(state((3, 3)), "area")  # The W, claimed by the Studio fill.
        self.assertTrue(any(s[1].startswith("The scan moves past") and "Row 2 is done" in s[1]
                            for s in recorder.statuses))
        for run in (trace_plan, trace_room_seeded):
            recorder = FrameRecorder(TWO_ROOMS, grid)
            run(recorder, grid, labels)
            self.assertEqual(recorder.scan_path, set(), run.__name__)

    def test_report_panel_counts_up_as_the_frames_play(self) -> None:
        """Start from zero counts, change only as chairs are counted, and end on the final report."""
        for approach in ("connected-areas", "room-seeded"):
            with self.subTest(approach=approach):
                house = record([("two rooms", TWO_ROOMS)], approach=approach)[0]
                frames = [frame for frame, _ in house["reports"]]
                self.assertEqual(frames[0], 0)
                self.assertEqual(frames, sorted(set(frames)))
                self.assertEqual(house["reports"][0][1].splitlines()[1], "W: 0, P: 0, S: 0, C: 0")
                self.assertEqual(house["reports"][-1][1], house["result"])
                self.assertGreater(len(frames), 2)

    def test_room_seeded_recording_stops_at_the_first_error(self) -> None:
        """Show the error and stop, as count_chairs_room_seeded does."""
        house = record([("leaky", LEAKY)], approach="room-seeded")[0]

        self.assertTrue(house["result"].startswith("count_chairs_room_seeded rejects this plan"))
        self.assertIn("The search stops here and rejects the plan", house["statuses"][-2][1])

    def test_several_houses_keep_each_result(self) -> None:
        """Put every house on one page, including the error for a rejected plan."""
        recorded = record([("two rooms", TWO_ROOMS), ("leaky", LEAKY)])

        self.assertEqual([house["name"] for house in recorded], ["two rooms", "leaky"])
        self.assertTrue(recorded[1]["result"].startswith("count_chairs rejects this plan"))
        self.assertIn("_add_area rejects it", "\n".join(s[1] for s in recorded[1]["statuses"]))


class CliTests(unittest.TestCase):
    """The optional report files and animation of ``python -m chair_counter``."""

    def setUp(self) -> None:
        """Make a folder with plans in it, and an output folder name next to it."""
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.output = self.root / "output"
        self.plans = self.root / "plans"
        self.plans.mkdir()
        for name in ("studio.txt", "family_house.txt"):
            (self.plans / name).write_text(TWO_ROOMS, encoding="utf-8")

    def tearDown(self) -> None:
        self.folder.cleanup()

    def test_output_saves_a_report_named_after_the_plan(self) -> None:
        """Save the printed report as <plan>_report.txt, with no web page by default."""
        printed = run_cli(str(self.plans / "studio.txt"), "--output", str(self.output))

        report = (self.output / "studio_report.txt").read_text(encoding="utf-8")
        self.assertEqual(report, format_report(count_chairs(TWO_ROOMS)) + "\n")
        self.assertEqual(printed, report)
        self.assertEqual([path.name for path in self.output.iterdir()], ["studio_report.txt"])

    def test_animation_adds_a_page_named_after_the_plan(self) -> None:
        """Write <plan>_search.html next to the report when --animation is given."""
        run_cli(str(self.plans / "family_house.txt"), "--output", str(self.output), "--animation")

        page = (self.output / "family_house_search.html").read_text(encoding="utf-8")
        self.assertEqual([house["name"] for house in houses_in(page)], ["family house"])

    def test_folder_gives_a_report_each_and_one_page_with_every_house(self) -> None:
        """A folder of plans gives one report per plan and search.html with a drop-down."""
        printed = run_cli(str(self.plans), "--output", str(self.output), "--animation", "--every", "5")

        files = sorted(path.name for path in self.output.iterdir())
        self.assertEqual(files, ["family_house_report.txt", "search.html", "studio_report.txt"])
        page = (self.output / "search.html").read_text(encoding="utf-8")
        houses = houses_in(page)
        self.assertEqual([house["name"] for house in houses], ["family house", "studio"])
        self.assertEqual(houses[0]["runs"][0]["statuses"][1][0], "Step 6 | the outside")
        self.assertIn(f"== {self.plans / 'studio.txt'}\ntotal:", printed)

    def test_animation_has_both_approaches_opening_on_the_chosen_one(self) -> None:
        """Record both approaches, with the --approach choice first in the drop-down."""
        plan = str(self.plans / "studio.txt")
        for approach, order in (
            ("connected-areas", ["connected-areas", "room-seeded"]),
            ("room-seeded", ["room-seeded", "connected-areas"]),
        ):
            with self.subTest(approach=approach):
                run_cli("--approach", approach, plan, "--output", str(self.output), "--animation")
                page = (self.output / "studio_search.html").read_text(encoding="utf-8")
                runs = houses_in(page)[0]["runs"]
                self.assertEqual([run["approach"] for run in runs], order)
                self.assertEqual(runs[0]["result"], runs[1]["result"])

    def test_bad_option_combinations_exit_with_code_2(self) -> None:
        """Refuse --animation without --output, and --every without --animation or below 1."""
        plan = str(self.plans / "studio.txt")
        for argv in (
            [plan, "--animation"],
            [plan, "--output", str(self.output), "--every", "5"],
            [plan, "--output", str(self.output), "--animation", "--every", "0"],
            [plan, "--approach", "breadth-first"],
        ):
            with self.subTest(argv=argv):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                    main(argv)
                self.assertEqual(stopped.exception.code, 2)

    def test_invalid_plan_is_named_and_nothing_is_saved(self) -> None:
        """Stop with the plan's name in the message before writing any file."""
        (self.plans / "leaky.txt").write_text(LEAKY, encoding="utf-8")

        with redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
            run_cli(str(self.plans), "--output", str(self.output))

        self.assertIn("leaky.txt: A room label or chair is connected to the exterior", errors.getvalue())
        self.assertFalse(self.output.exists())

    def test_collect_plans_reads_every_plan_in_a_folder(self) -> None:
        """Expand a folder into its .txt plans, sorted by name, and refuse clashing names."""
        (self.plans / "notes.md").write_text("not a plan", encoding="utf-8")

        plans = collect_plans([self.plans])

        self.assertEqual([path.name for path in plans], ["family_house.txt", "studio.txt"])
        with self.assertRaises(ValueError):
            collect_plans([self.plans, self.plans / "studio.txt"])


if __name__ == "__main__":
    unittest.main()
