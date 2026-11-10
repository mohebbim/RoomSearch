# How the chair counter works

The plan is a grid of characters. Walls split the grid into separate areas. A room is the area that contains its label, and its chairs are the chairs in that same area.

## Input rules

- The plan is UTF-8 text. Rows may have different lengths, and leading spaces are kept.
- Walls are `+ - | / \`. Chairs are `W` (wooden), `P` (plastic), `S` (sofa) and `C` (china). Everything else is a space or part of a room label such as `(office)`.
- Each enclosed area has at most one label, and room names are unique.
- Chairs in an area without a label count toward the total only. A named room with no chairs is still listed, with zeros.
- An open passage joins the areas on both sides. In `inputs/rooms.txt`, the hallway chair is therefore part of the living room.
- Every room must be closed off from the outside. A chair or label reachable from the outside is an error.

## Algorithm

All of it is in `chair_counter/floor_plan.py`. `count_chairs` runs these steps:

1. **Parse** (`_parse_plan`). Pad the lines into a rectangle and add a one-cell blank border around it. Record each label's position and name, then blank it out, so the letters of a name are not counted as chairs.
2. **Scan** (`_find_areas`). Visit every cell row by row. Each open cell that is not yet in an area starts a new one. The first area starts in the border, so it is the outside of the building.
3. **Fill** (`_walk_area`). From the start cell, flood-fill with a stack: pop a cell, then push each neighbour above, below, left and right that is not a wall and not yet visited. Moving only in these four directions means diagonal walls such as `/` stay closed. The scan records each label and chair the fill passes over.
4. **Report** (`_add_area`). Apply the rules above to each area, then add its chairs to the total, and to a room subtotal if it has a label.

`format_report` prints the total first, then the rooms in alphabetical order, each with all four chair types including zeros.

Each cell is filled once, so for a plan of height `H` and width `W` the time and memory are `O(H × W)`. Sorting `R` room names adds `O(R log R)`.

## Watching the search

The visualisers reuse these functions instead of copying them. `_find_areas` and `_walk_area` take an optional `trace` function, which does nothing when `count_chairs` runs. The visualiser passes its own `trace`, which receives one event per action (`scan`, `visit`, `check`, `label`, `chair`), and turns each event into a numbered step with an explanation. When an area is finished, it calls `_add_area` exactly as `count_chairs` does.

Colours in each frame:

| Colour | Meaning |
| --- | --- |
| Magenta | The cell being expanded. |
| Cyan | Cells waiting on the stack. |
| Green / red / blue | The neighbour just checked was pushed, was a wall, or had already been reached. |
| Orange | A chair or label was recorded. |
| Dark yellow, pale yellow | The scan starts a new area here, after walking past the pale yellow cells (walls and cells already in an area). |
| Grey | The outside. Each enclosed area has its own colour, and a rejected area is red. |

## Changing the format

The wall and chair characters are defined at the top of `floor_plan.py`. A format that marks doorways would need a rule for whether a doorway separates two rooms.
