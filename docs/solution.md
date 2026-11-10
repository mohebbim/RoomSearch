# How the chair counter works

All the counting logic is in `chair_counter/floor_plan.py`, and `count_chairs` runs it.

## The idea

The plan is a grid of characters, and every character is one of two kinds:

- **Walls** (`+ - | / \`) block movement.
- **Everything else** is open: spaces, chairs (`W P S C`) and room labels.

The program never decides that a single character "is a room". Instead, it splits the open cells into **areas**: groups of open cells you can walk between, moving up, down, left and right, without crossing a wall. Each area is then one of three things:

- The **outside** of the building.
- A **room**, if a label such as `(office)` lies inside it.
- An **unlabelled area**, such as a corridor.

An area's chairs are the chair characters inside it.

The steps below use this plan as an example:

```
+-------+----+
|(A)  W |    |
|   P   | S  |
+-------+----+
```

## Step 1: Parse the plan (`_parse_plan`)

1. **Split into lines.** Lines may have different lengths, so each is padded with spaces to the length of the longest.
2. **Take out the labels.** A regular expression finds each `(name)`. The name is stored with the position of its `(`, then the label's characters are replaced with spaces. Otherwise the letters of a name like `(Sofa room)` would be counted as chairs.
3. **Check every character.** Anything that is not a wall, a chair or a space is an error.
4. **Add a blank border.** One cell of space goes around the whole plan. This guarantees that the outside is a single connected area that starts in the top-left corner, at row 0, column 0.

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

## Step 2: Scan for the start of each area (`_find_areas`)

The scan reads the grid row by row, left to right, and asks one question of every cell:

| Cell | What the scan does |
| --- | --- |
| A wall | Skip it. |
| Already in an area | Skip it. |
| Open and in no area yet | Start a new area here, and fill it (Step 3) before the scan moves on. |

There is one shared set, `visited`, that holds every cell any area has reached. It is how the scan knows which cells to skip.

In the example, the scan:

1. Starts the **outside** at `(0, 0)`, the border's corner. Filling it reaches the whole border, which is 40 cells.
2. Skips the rest of row 0, which is now visited, and the walls of row 1.
3. Starts area 1 at `(2, 2)`, where the label `(A)` was.
4. Starts area 2 at `(2, 10)`, the first cell right of the middle wall.
5. Finds every other cell is a wall or already visited, so stops after the last cell.

## Step 3: Fill one area and find its boundary (`_walk_area`)

The fill is a *flood fill* with a stack, which is a to-do list of cells still to expand:

```
pending = [start]          # The stack.
visited.add(start)

while pending is not empty:
    cell = pending.pop()   # Take the most recently added cell.
    give cell to the area (Step 4)
    for each neighbour above, below, left and right of cell:
        off the grid?       -> skip
        already visited?    -> skip
        a wall?             -> skip   (this is the area's boundary)
        otherwise           -> add to visited and push onto pending
```

When the stack is empty, every cell reachable from the start has been found, and the area is complete. The walls that blocked the fill are the area's **boundary**. They aren't stored, because the count only needs the cells inside.

Some details matter:

- **A cell is marked visited when it is pushed, not when it is popped.** That way a cell can never be on the stack twice, so each cell is expanded exactly once.
- **Moving only in four directions keeps diagonal walls closed.** In a wall like
  ```
   /
  /
  ```
  the two `/` touch only at a corner. A diagonal step would slip between them, but up, down, left and right cannot.
- **An open passage joins two spaces.** A gap in a wall is just open cells, so the fill flows through it, and both sides become one area. In `inputs/rooms.txt` this is why the hallway chair is counted in the living room.
- **The fill is a generator.** It yields each cell as it pops it, so Step 4 records the cells while the fill runs.

## Step 4: Record labels and chairs (`_find_areas`)

For each cell the fill yields, `_find_areas` adds the cell to the area and then makes two lookups:

- **Is there a label at this position?** If so, the name goes into `area.names`. The cell is in the labels dictionary from Step 1.
- **Is the character a chair?** If so, `area.chairs[chair] += 1`. `area.chairs` is a `Counter`, so missing chair types count as 0.

The finished `Area` holds its cells, its chair counts and its label names. In the example:

| Area | Starts at | Cells | Labels | Chairs |
| --- | --- | --- | --- | --- |
| Outside | `(0, 0)` | 40 | none | none |
| 1 | `(2, 2)` | 14 | `A` | W 1, P 1 |
| 2 | `(2, 10)` | 8 | none | S 1 |

## Step 5: Check each area and add it to the report (`_add_area`)

Each finished area is checked against the input rules, then counted:

| Area | Result |
| --- | --- |
| The outside, recognised because it starts at `(0, 0)` | Counts nothing. If it has a chair or label, a wall has a gap, so the plan is rejected. |
| Two or more labels | Rejected. Two rooms are joined without a wall between them. |
| One label already used by another room | Rejected. Room names must be unique. |
| One label | A room. Its chairs are stored under its name and added to the total. A room with no chairs is still listed, with zeros. |
| No label | Its chairs are added to the total only. |

A rejected plan raises a `ValueError` with the reason, and no report is printed.

## Step 6: Format the report (`format_report`)

The report prints `total:` first, then each room in alphabetical order, ignoring case. Each one is followed by all four chair types, including zeros. For the example:

```
total:
W: 1, P: 1, S: 1, C: 0
A:
W: 1, P: 1, S: 0, C: 0
```

The chair `S` in area 2 counts toward the total but appears under no room, because area 2 has no label.

## Cost

Each cell is pushed, popped and checked once, so for a plan of height `H` and width `W` the time and memory are `O(H × W)`. Sorting `R` room names adds `O(R log R)`.

## Changing the format

The wall and chair characters are defined at the top of `floor_plan.py`. A format that marks doorways would need a rule for whether a doorway separates two rooms.
