# ASCII floor plan chair counter

Count chairs across an apartment and in each named room. The tool requires Python 3.10 or later and uses the standard library at runtime.

## Run

From the repository root, pass the path to an extracted floor plan.

```powershell
python -m chair_counter "C:/path/to/rooms.txt"
```

For the `chair-counter` command, install the package with `python -m pip install .`.

## Test

```powershell
python -m unittest -v
```

## Project layout

- `chair_counter/` contains the parser, connected-area search, output formatter, and command-line interface.
- `tests/` checks diagonal walls, indented rooms, unnamed areas, empty rooms, ambiguous labels, and invalid input.
- [Solution write-up](docs/solution.md) explains the algorithm, input rules, and how to extend it.
