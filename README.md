# ASCII floor plan chair counter

Count chairs across an apartment and in each named room. The tool requires Python 3.10 or later and uses the standard library at runtime.

## Run

From the repository root, pass the path to an extracted floor plan.

```powershell
python -m chair_counter "C:/path/to/rooms.txt"
```

For the `chair-counter` command, install the package with `python -m pip install .`.

## Watch the algorithm

The visualiser draws the plan in the terminal and animates how the counter fills each area, then prints the same report. Run it from the repository root, or from anywhere after installing the package.

```powershell
python -m chair_counter.visualize "C:/path/to/rooms.txt"
```

Use a real terminal, such as the VS Code integrated terminal, for the coloured animation. When the output is piped or redirected, the visualiser prints plain frames instead.

| Option | Effect |
| --- | --- |
| `--step` | Pause after each area. Press Enter to continue. |
| `--delay SECONDS` | Time per frame. The default is `0.03`. |
| `--cells-per-frame N` | Cells filled between frames. Use `1` to watch every step. |
| `--plain` | Print one frame per area without colour, marking the current area with dots. |

Press Ctrl+C to stop. The command exits with code 1 when the plan is rejected and 2 when the file cannot be read or parsed. The [solution write-up](docs/solution.md#watching-the-algorithm) explains what the colours mean.

## Test

```powershell
python -m unittest -v
```

## Project layout

- `chair_counter/` contains the parser, connected-area search, output formatter, command-line interface, and visualiser (`visualize.py`).
- `tests/` checks diagonal walls, indented rooms, unnamed areas, empty rooms, ambiguous labels, invalid input, and the visualiser output.
- [Solution write-up](docs/solution.md) explains the algorithm, input rules, and how to extend it.
