# How the chair counter works

The chair counter has two methods for counting, and both print the same report:

- **Method 1, connected areas** (the default, `count_chairs` in `chair_counter/floor_plan.py`), finds every enclosed area first, then decides what each one is.
- **Method 2, room seeded** (`count_chairs_room_seeded` in `chair_counter/room_seeded.py`), starts from each room's name and fills outwards from it.

This page explains both, step by step, on the same small plan. [comparison.md](comparison.md) sets them side by side and says when to choose each.

## The idea

The plan is a grid of characters, and every character is one of two kinds:

- **Walls** (`+ - | / \`) block movement.
- **Everything else** is open: spaces, chairs (`W P S C`) and room labels.

The program never decides that a single character "is a room". Instead, it works with **areas**: groups of open cells you can walk between, moving up, down, left and right, without crossing a wall. Each area is one of three things:

- The **outside** of the building.
- A **room**, if a label such as `(office)` lies inside it.
- An **unlabelled area**, such as a corridor.

An area's chairs are the chair characters inside it. The total counts the chairs in every area except the outside.

Both methods use this plan as their example. It has one named room, `A`, and one unlabelled area to its right:

```
+-------+----+
|(A)  W |    |
|   P   | S  |
+-------+----+
```

## Shared building blocks

The two methods differ only in the order of the work. Both are built from the same pieces in `floor_plan.py`.

### Parse the plan (`_parse_plan`)

1. **Split into lines.** Lines may have different lengths, so each is padded with spaces to the length of the longest.
2. **Take out the labels.** A regular expression finds each `(name)`. The name is stored with the position of its `(`, then the label's characters are replaced with spaces. Otherwise the letters of a name like `(Sofa room)` would be counted as chairs.
3. **Check every character.** Anything that is not a wall, a chair or a space is an error.
4. **Add a blank border.** One cell of space goes around the whole plan. This guarantees that the outside is a single connected area that includes the top-left corner, row 0, column 0.

The result is the grid, a list of equal-length strings, plus a dictionary of labels by position:

```
row 0   "                "
row 1   " +-------+----+ "
row 2   " |     W |    | "      labels = {(2, 2): "A"}
row 3   " |   P   | S  | "
row 4   " +-------+----+ "
row 5   "                "
```

A cell is a `(row, column)` tuple. Thanks to the border, row `r` is line `r` of the file.

### Flood-fill one area (`_walk_area` and `_fill_area`)

A flood fill finds every cell reachable from a start cell. It uses a stack, which is a to-do list of cells still to expand, and a set called `visited`, which holds every cell already reached:

```
pending = [start]          # The stack.
visited.add(start)

while pending is not empty:
    cell = pending.pop()   # Take the most recently added cell.
    record the cell (see below)
    for each neighbour above, below, left and right of cell:
        off the grid?       -> skip
        already visited?    -> skip
        a wall?             -> skip   (this is the area's boundary)
        otherwise           -> add to visited and push onto pending
```

When the stack is empty, every cell reachable from the start has been found, and the area is complete. The walls that blocked the fill are the area's **boundary**. They aren't stored, because the count only needs the cells inside.

`_walk_area` does the fill and hands over each cell as it pops it. `_fill_area` **records** each of those cells in an `Area`, which holds the area's cells, chairs and label names:

- **Is there a label at this position?** If so, the name goes into `area.names`.
- **Is the character a chair?** If so, `area.chairs[chair] += 1`. `area.chairs` is a `Counter`, so missing chair types count as 0.

Some details matter:

- **A cell is marked visited when it is pushed, not when it is popped.** That way a cell can never be on the stack twice, so each cell is expanded exactly once.
- **Moving only in four directions keeps diagonal walls closed.** In a wall like
  ```
   /
  /
  ```
  the two `/` touch only at a corner. A diagonal step would slip between them, but up, down, left and right cannot.
- **An open passage joins two spaces.** A gap in a wall is just open cells, so the fill flows through it, and both sides become one area. In `inputs/rooms.txt` this is why the hallway chair is counted in the living room.

### Input rules

Three small functions enforce the input rules, so both methods reject the same plans with the same messages:

| Function | Rule | Error if broken |
| --- | --- | --- |
| `_check_exterior` | The outside holds no chair or label. | "A room label or chair is connected to the exterior." There is a gap in the outer wall. |
| `_room_name` | An area has at most one label. | "One connected area has multiple room labels." Two rooms are joined without a wall. |
| `_add_room` | Each room name is used once. | "Duplicate room label." |

A rejected plan raises a `ValueError` with the reason, and no report is printed.

### Format the report (`format_report`)

The report prints `total:` first, then each room in alphabetical order, ignoring case. Each one is followed by all four chair types, including zeros. A room with no chairs is still listed. For the example, both methods print:

```
total:
W: 1, P: 1, S: 1, C: 0
A:
W: 1, P: 1, S: 0, C: 0
```

The `S` counts toward the total but appears under no room, because it is in the unlabelled area.

## Method 1: Connected areas (`count_chairs`)

**Idea:** find every area first, then decide what each one is.

### Step 1: Parse

`_parse_plan` builds the padded grid and the labels dictionary.

### Step 2: Scan for the start of each area (`_find_areas`)

The scan reads the grid row by row, left to right, and asks one question of every cell:

| Cell | What the scan does |
| --- | --- |
| A wall | Skip it. |
| Already in an area | Skip it. |
| Open and in no area yet | Start a new area here, and fill it (Step 3) before the scan moves on. |

One `visited` set is shared by every fill. It is how the scan knows which cells an earlier fill already reached.

### Step 3: Fill each area

Each new area is filled with `_fill_area`, which records its cells, labels and chairs. The scan's first open cell is always the border corner `(0, 0)`, so the first area is always the outside.

### Step 4: Check each area and add it to the report (`_add_area`)

As soon as an area is finished, it is judged:

| Area | Result |
| --- | --- |
| The outside, recognised because it starts at `(0, 0)` | `_check_exterior`. Counts nothing. |
| One label | `_room_name` and `_add_room`. A room: its chairs are stored under its name and added to the total. |
| No label | Its chairs are added to the total only. |
| Two labels, or a name already used | Rejected by `_room_name` or `_add_room`. |

### Step 5: Format

`format_report` prints the report.

### The example, step by step

1. The scan starts the **outside** at `(0, 0)`. The fill reaches the whole border, 40 cells, with no chairs or labels, so `_check_exterior` passes.
2. The scan skips the rest of row 0, which is now visited, and the walls of row 1.
3. At `(2, 2)`, where the label was, it starts **area 1**. The fill reaches 14 cells and records the label `A`, a `W` and a `P`. `_add_area` stores room `A` with W 1, P 1, and adds them to the total.
4. At `(2, 10)`, just right of the middle wall, it starts **area 2**. The fill reaches 8 cells with one `S` and no label, so the `S` is added to the total only.
5. Every remaining cell is a wall or already visited, so the scan ends.

| Area | Starts at | Cells | Labels | Chairs | Counted as |
| --- | --- | --- | --- | --- | --- |
| Outside | `(0, 0)` | 40 | none | none | nothing |
| 1 | `(2, 2)` | 14 | `A` | W 1, P 1 | room `A` and the total |
| 2 | `(2, 10)` | 8 | none | S 1 | the total only |

## Method 2: Room seeded (`count_chairs_room_seeded`)

**Idea:** start from what the report needs, which is the outside, the total and each named room.

### Step 1: Parse

`_parse_plan` builds the same padded grid and labels dictionary.

### Step 2: Fill the exterior (`_fill_exterior`)

It flood-fills from the border corner `(0, 0)`, which is always outside, using `_fill_area`. Then `_check_exterior` rejects the plan if the outside holds a chair or a label. The exterior's cells are kept as a set for the next step.

### Step 3: Scan for the apartment total (`_count_enclosed_chairs`)

A plain scan of the whole grid, with no flood fill:

| Cell | What the scan does |
| --- | --- |
| In the exterior | Skip it. |
| A wall | Skip it. |
| A chair | Add it to the total. |
| Anything else | Skip it. |

This pass is what counts chairs in **unlabelled areas**. No fill ever enters those areas, but their chairs are not outside, so the scan finds them.

### Step 4: Fill from each room label (`_fill_room`)

For each label, in the order the labels appear in the plan:

1. **Skip it if its cell is already visited.** This guards against counting one space twice. In practice an earlier fill that reached this label would already have raised the "multiple room labels" error.
2. **Flood-fill from the label's position** with `_fill_area`. The fill shares the `visited` set with the exterior fill and the other rooms.
3. **Check the result.** `_room_name` rejects the fill if it found a second label, and `_add_room` rejects a name that is already used.
4. **Store the room's chairs as its subtotal.** They are not added to the total again, because Step 3 already counted them.

### Step 5: Format

`format_report` prints the report, exactly as in Method 1.

### The example, step by step

1. **Exterior fill** from `(0, 0)`: the fill reaches the 40 border cells. There are no chairs or labels, so the outer walls are closed.
2. **Total scan:** reading row by row, the scan skips the 40 exterior cells and the walls, and finds three chairs that are not outside:
   - `W` at `(2, 7)`, so the total is W 1.
   - `P` at `(3, 5)`, so the total is W 1, P 1.
   - `S` at `(3, 11)`, so the total is W 1, P 1, S 1.
3. **Room fill** from label `A` at `(2, 2)`: the fill reaches 14 cells with one label, `A`, a `W` and a `P`. Room `A` gets W 1, P 1.
4. There are no more labels, so the search ends. The unlabelled area on the right was never filled. Its `S` was counted by the total scan in step 2.

| Pass | Starts at | Cells filled | Result |
| --- | --- | --- | --- |
| Exterior fill | `(0, 0)` | 40 | outside is closed |
| Total scan | every cell | none | total W 1, P 1, S 1 |
| Room fill `A` | `(2, 2)` | 14 | room `A`: W 1, P 1 |

## Cost

Both methods take `O(H × W)` time and memory for a plan of height `H` and width `W`:

- **Connected areas** scans every cell once and fills every cell once.
- **Room seeded** fills the exterior and the rooms, so each cell is filled at most once, and scans every cell once more for the total.

Sorting `R` room names for the report adds `O(R log R)`.

## Changing the format

The wall and chair characters are defined at the top of `floor_plan.py`. A format that marks doorways would need a rule for whether a doorway separates two rooms.
