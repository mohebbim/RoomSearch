# ASCII floor plan chair counter

Counts the chairs in an ASCII floor plan, for the whole apartment and for each room, and prints them in the exact text format the old system reads. Requires Python 3.10 or later. It uses only the standard library.

- **How it works:** [docs/solution.md](docs/solution.md) explains the search algorithm step by step, with a worked example.
- **Watch it run:** [open the animated search in your browser](https://raw.githack.com/mohebbim/RoomSearch/master/output/search.html), with all four sample houses. The file is [output/search.html](output/search.html); in a clone, open it straight from disk.

## Example with this repository

The sample plans are in `inputs/` and the results go to `output/`. Run these from the repository folder:

```powershell
# One plan: print its report and save it, with its animation.
python -m chair_counter inputs/rooms.txt --output output --animation

# Every plan in inputs/: a report for each, and one page with a house type drop-down.
python -m chair_counter inputs --output output --animation

# Open the page in your default browser (on macOS use `open`, on Linux `xdg-open`).
Start-Process output/search.html
```

```
inputs/                        output/
  rooms.txt          ──►         rooms_report.txt
  studio.txt                     studio_report.txt
  family_house.txt               family_house_report.txt
  bungalow.txt                   bungalow_report.txt
                                 rooms_search.html   (first command)
                                 search.html         (second command)
```

Leave out `--animation` to save only the reports, or `--output output` as well to only print the report.

## Count chairs

```powershell
python -m chair_counter inputs/rooms.txt
```

```
total:
W: 14, P: 7, S: 3, C: 1
balcony:
W: 0, P: 2, S: 0, C: 0
...
```

Everything beyond the printed report is optional:

| Option | Effect |
| --- | --- |
| `--output DIR` | Also save the report as `DIR/<plan>_report.txt`, e.g. `output/rooms_report.txt`. |
| `--animation` | With `--output`, also save a web page that animates the search (see below). |
| `--every N` | With `--animation`, record one frame every `N` steps instead of every step, for a smaller page. |

`<plan>` is the plan's file name without `.txt`, so plans never overwrite each other's files.

You can pass several plans, or a folder to use every `.txt` plan in it. Each report is then printed under a `== <file>` heading, and saved to its own file:

```powershell
python -m chair_counter inputs --output output --animation
```

`--help` explains the plan format. Errors such as a missing file, an invalid plan or a bad option combination print one line and exit with code 2, before any file is written. Run `python -m pip install .` to get a `chair-counter` command that does the same.

## Watch the search

`--animation` writes a web page that replays the search one step at a time: every cell the scan passes, every cell popped from the stack, every neighbour check, and every chair or label recorded. Each step comes with a sentence explaining it.

| Plans given | Page |
| --- | --- |
| One | `DIR/<plan>_search.html` |
| Several, or a folder | `DIR/search.html`, with a drop-down to pick the house |

The page fits the browser window and has these controls:

- Play/Pause (Space), a speed setting in steps per second, and an option to pause whenever a new area starts.
- ◀ ▶ (arrow keys) to move one step, and ⏮ Area / Area ⏭ (Page Up / Page Down) to jump to where an area starts.
- A slider to jump to any step. Hover over a cell to see what it holds.

It loads Plotly from the internet, so it needs a connection to open.

| Colour | Meaning |
| --- | --- |
| Magenta | The cell being expanded. |
| Cyan | Cells waiting on the stack. |
| Green / red / blue | The neighbour just checked was pushed, was a wall, or had already been reached. |
| Orange | A chair or label was recorded. |
| Dark yellow, pale yellow | The scan starts a new area here, after walking past the pale yellow cells. |
| Light grey | Wall (input): not reached yet. |
| Violet | Wall detected by the area being filled, so its outline appears as it fills. |
| Dark grey | Wall detected earlier, by a finished area. |
| Pale grey, pastels, red | The outside, each enclosed area, a rejected area. |

The page is made by `chair_counter/plotly_html.py`. It runs the same search functions as `count_chairs`, through an optional `trace` hook that does nothing during a normal count.

## Project layout

| Path | Contents |
| --- | --- |
| `chair_counter/floor_plan.py` | All counting logic. Start here. |
| `chair_counter/cli.py` | The `python -m chair_counter` command and its options. |
| `chair_counter/plotly_html.py` | The animation page, built on the counting functions. |
| `inputs/` | Sample plans: `rooms.txt` (supplied), `studio.txt`, `family_house.txt`, `bungalow.txt`. |
| [`output/`](output/) | A report for each sample plan and [`search.html`](output/search.html) with all of them, made with the folder command above. |
| `tests/` | Unit tests. Run them with `python -m unittest -v`. |
| [`docs/solution.md`](docs/solution.md) | The search algorithm, step by step, with a worked example. |
