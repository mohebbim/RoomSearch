# Counting chairs by connected area

The floor plan is a grid. Each character occupies one cell, and the wall cells divide the grid into separate spaces. A room name belongs to the same space as every chair you can reach from it by moving up, down, left, or right without crossing a wall.

## How the algorithm works

1. **Read the plan.** Preserve leading spaces and pad shorter lines on the right. Record the name and location of each parenthesized label, then replace the label with spaces. This keeps the grid aligned and prevents letters in room names from being counted as chairs.
2. **Find the exterior.** Add a border of blank cells around the grid. The first search starts in the top-left corner of that border, so every cell it can reach belongs to the exterior. A room label or chair reached in this search is an input error.
3. **Find enclosed areas.** Scan the rest of the grid. Start a flood fill at each unvisited floor cell and collect the labels and chair markers in its connected area. Mark cells as visited when adding them to the search stack so each cell is processed once. Four-direction movement keeps the search from passing between consecutive diagonal wall cells.
4. **Build the report.** Add the chairs from every enclosed area to the apartment total. Add a room subtotal when an area has a name. Print the total first, then the rooms alphabetically, with counts in `W`, `P`, `S`, `C` order and zeros included.

In `chair_counter/floor_plan.py`, step 1 is `_parse_plan`. Steps 2 and 3 are `_find_areas`, which scans the grid and uses `_walk_area` for each flood fill. Step 4 is `_add_area`, which also applies the input rules. `count_chairs` calls these in order.

## Watching the algorithm

Run `python -m chair_counter.visualize PLAN` to see the steps above on a real plan. The visualiser has no counting logic of its own. It calls `_parse_plan`, `_find_areas`, and `_add_area`, then replays each area's cells in the order the flood fill reached them.

- The first area is the exterior, which starts in the blank border and is drawn in dark grey.
- Each enclosed area gets its own colour. The cells reached most recently are highlighted in yellow, so you can watch the fill spread and stop at walls.
- An area that `_add_area` rejects is drawn in red, with the error message beside its summary. The visualiser keeps going to show the rest of the plan, then reports the first error, which is the one `count_chairs` raises.
- Below the drawing, one line per finished area lists its label, cell count, and chairs. The final report comes from `format_report`.

Add `--step` to pause after each area. The [README](../README.md#watch-the-algorithm) lists the other options.

## Input rules

- The plan is UTF-8 text. Spaces preserve the layout, and rows can have different lengths.
- The wall symbols are `+`, `-`, `|`, `/`, and `\`. The chair markers are `W`, `P`, `S`, and `C`.
- An enclosed area can have one room label in parentheses. Room names must be unique. Multiple labels in one area or duplicate names produce an error.
- Chairs in unlabelled enclosed areas count toward the apartment total. A labelled room with zero chairs still gets a subtotal.
- An uninterrupted passage belongs to the same area on both sides. In the supplied plan, the hallway chair is therefore part of the living room, which has seven wooden chairs.

## Why connected areas

The text already provides the grid needed for the search. Finding every area gives the program one consistent source for apartment totals, room subtotals, and input validation. For a padded grid with height `H` and width `W`, the parser and search take `O(H × W)` time and use `O(H × W)` space. Sorting `R` room names for output adds `O(R log R)` time.

## Adapting the solution

`count_chairs(plan)` returns a `ChairReport`, and `format_report(report)` produces the legacy text output. Other callers can use the counts directly. Wall and chair symbols are defined at the top of `chair_counter/floor_plan.py`. A format with different symbols can change those definitions. A format that marks room boundaries at open doorways would need an explicit rule for how those markers affect movement.
