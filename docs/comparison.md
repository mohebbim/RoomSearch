# Comparing the two approaches

The chair counter has two counting approaches. Both give the same report and raise the same errors. They differ in where the search starts and how the total is found.

| Approach | Function | Choose it with |
| --- | --- | --- |
| **Connected areas** (default) | `count_chairs` in `chair_counter/floor_plan.py` | `--approach connected-areas`, or no option |
| **Room seeded** | `count_chairs_room_seeded` in `chair_counter/room_seeded.py` | `--approach room-seeded` |

```powershell
python -m chair_counter --approach connected-areas inputs/rooms.txt
python -m chair_counter --approach room-seeded inputs/rooms.txt
```

[solution.md](solution.md) explains both approaches step by step, on the same worked example. The animated page (`--animation`) records both approaches, and its **Approach** drop-down switches between them.

## How each approach works

**Connected areas** scans every cell row by row. Each open cell that is not yet in an area starts a flood fill, which finds that whole area. Only once an area is finished does the approach ask what it is: the outside, a room (it holds one label) or an unlabelled space. The total is the sum of all enclosed areas' chairs.

**Room seeded** starts from what the report needs. It works in three passes:

1. **Exterior fill.** It flood-fills from the border's corner, `(0, 0)`, to find the exterior, and checks that no chair or label is in it.
2. **Total scan.** It scans the grid once and adds every chair that is not in the exterior to the total. This is how chairs in unlabelled spaces get counted, because no fill ever enters those spaces.
3. **Room fills.** It flood-fills from each room label to find that room's cells and subtotal.

## Side by side

| | Connected areas | Room seeded |
| --- | --- | --- |
| **Where searches start** | At every open cell the scan finds that is not yet in an area. The first is always the border corner `(0, 0)`, so it is the exterior. | At the border corner `(0, 0)` for the exterior, then at each room label's position. |
| **Areas filled** | All of them: the exterior, the rooms and the unlabelled spaces. | The exterior and the named rooms only. Unlabelled spaces are never filled. |
| **Apartment total** | Added up from each enclosed area's chairs as the areas are finished. | A separate scan of the whole grid: every chair outside the exterior. |
| **Room subtotal** | The chairs of the area that holds the label. | The chairs reached by the fill from the label. |
| **Chair or label outside** | Rejected when the exterior area is checked (`_check_exterior`). | Rejected right after the exterior fill (`_check_exterior`). |
| **Two labels in one space** | The area holds two labels (`_room_name`). | A room's fill reaches a second label (`_room_name`). The shared `visited` set means a space is never filled twice, so it can never be counted twice. |
| **Duplicate room name** | The second room with that name is rejected (`_add_room`). | The same (`_add_room`). |
| **Which error comes first** if a plan breaks several rules | The first broken rule in the order the scan finds the areas. | The exterior check first, then the rooms in the order their labels appear. |
| **Time** | `O(H × W)`: every cell is scanned once and filled once. | `O(H × W)`: one full scan for the total, plus fills of the exterior and the rooms, each cell filled at most once. |
| **Memory** | `O(H × W)` for the grid and the `visited` set. | `O(H × W)` for the grid, the `visited` set and the set of exterior cells. |

`H` and `W` are the plan's height and width. Neither approach sorts anything except the room names when printing: `O(R log R)` for `R` rooms.

## What they share

Only the order of the work differs. Both approaches use the same code in `floor_plan.py`:

- **Parser:** `_parse_plan`, with the same rules for spacing, wall characters and labels.
- **Flood fill:** `_fill_area`, built on the four-direction `_walk_area`, so diagonal walls behave the same.
- **Input rules:** `_check_exterior`, `_room_name` and `_add_room`, so the error messages are identical.
- **Report:** `ChairReport` and `format_report`, so the output text is identical: room order, chair type order and zero counts.

The tests in `tests/test_chair_counter.py` run every case against both approaches. They also check that both print the same report for every plan in `inputs/`.

## When to choose each

**Choose connected areas (the default)** when:

- You want one pass that sees the whole plan. Every space is found, including unlabelled ones, so it is easy to extend. For example, it could list unlabelled spaces or report every broken rule rather than just the first.
- You want the simplest correctness argument: every open cell belongs to exactly one area, and each area is judged once.

**Choose room seeded** when:

- The question is about named rooms. The work follows the labels, so it adapts easily to "count the chairs in this one room": skip the total scan and fill from that label only, for `O(size of the room)` work.
- The plan has large unlabelled spaces, and only the rooms need their cells found. The total still needs one plain scan, but that scan does no flood fill work.

For the plans in this repository, both run in a few milliseconds, so the choice is about clarity and what you plan to extend.
