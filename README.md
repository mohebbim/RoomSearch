# ASCII floor plan chair counter

Counts the chairs in an ASCII floor plan, for the whole apartment and for each room, and prints them in the exact text format the old system reads. Requires Python 3.10 or later. It uses only the standard library.

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

| Option | Effect |
| --- | --- |
| `--output DIR` | Also save the report as `DIR/<plan>_report.txt`, e.g. `output/rooms_report.txt`. |
| `--animation` | With `--output`, also save an animation of the search as `DIR/<plan>_search.html`. |

`--help` explains the plan format. Errors such as a missing file or an invalid plan print one line and exit with code 2. Run `python -m pip install .` to get a `chair-counter` command that does the same.

## Watch the search

The visualiser shows each step of the search: every cell the scan passes, every cell popped from the stack, every neighbour check, and every chair or label recorded.

In the terminal:

```powershell
python -m chair_counter.visualize inputs/rooms.txt
```

| Option | Effect |
| --- | --- |
| `--step` | Pause after every frame. Enter continues, a number jumps that many steps, `c` runs to the end, `q` quits. |
| `--every N` | Draw a frame every `N` steps. |
| `--delay SECONDS` | Time per animated frame (default `0.03`). |
| `--plain` | No colour. Print every step as a line of text. |

As a web page with a Play button, a slider and a house drop-down. Pass plan files, or a folder to include every `.txt` plan in it:

```powershell
python -m chair_counter.visualize inputs --html output/search.html
```

Every step of the search is a frame. The page fits the browser window and has these controls:

- Play/Pause (Space), a speed setting in steps per second, and an option to pause whenever a new area starts.
- ◀ ▶ (arrow keys) to move one step, and ⏮ Area / Area ⏭ (Page Up / Page Down) to jump to where an area starts.

It loads Plotly from the internet, so it needs a connection to open. [docs/solution.md](docs/solution.md#watching-the-search) explains the colours.

## Project layout

| Path | Contents |
| --- | --- |
| `chair_counter/floor_plan.py` | All counting logic. Start here. |
| `chair_counter/cli.py` | The `python -m chair_counter` command. |
| `chair_counter/visualize.py` | Step-by-step terminal view, built on the counting functions. |
| `chair_counter/plotly_html.py` | The animated web page. |
| `inputs/` | Sample plans: `rooms.txt` (supplied), `studio.txt`, `family_house.txt`, `bungalow.txt`. |
| `output/` | A report for each sample plan and `search.html` with all of them, made with the commands above. |
| `tests/` | Unit tests. Run them with `python -m unittest -v`. |
| `docs/solution.md` | How the algorithm works and the input rules. |
