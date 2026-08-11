"""
The Cut — city geometry.

Built programmatically from a compact block spec rather than a hand-drawn tile sheet, so a
location can be moved or resized by editing one line instead of repainting a grid.

Buildings are "roofless dollhouse": walls plus a visible walkable interior, furnished. That
keeps everyone on screen — a character who goes home to watch television is still watchable,
and we never need interior scene-switching or a second camera mode.

Furniture is generated deterministically per building rather than hand-placed, because 25
buildings of hand-placed props is a maintenance job nobody will do twice. It exists for two
reasons: rooms that read as rooms, and anchors for what people are actually doing — you
cannot sit on a sofa the map does not have.

Tile legend (also consumed by the front-end renderer):
    .  pavement    walkable
    ,  road        walkable
    :  road line   walkable, painted centre markings
    =  crossing    walkable, zebra stripes
    g  grass       walkable
    #  wall        blocked
    f  floor       walkable, inside a building
    D  door        walkable
    ~  water       blocked
"""

import random
from collections import deque

TILE = 16
W, H = 96, 72

PAVEMENT, ROAD, LINE, CROSS, GRASS = ".", ",", ":", "=", "g"
WALL, FLOOR, DOOR, WATER = "#", "f", "D", "~"
WALKABLE = {PAVEMENT, ROAD, LINE, CROSS, GRASS, FLOOR, DOOR}

# (start, width) — roads are 4 wide with painted centre lines, pavements are added either side
H_ROADS = [(10, 4), (26, 4), (42, 4), (58, 4)]
V_ROADS = [(12, 4), (40, 4), (68, 4)]

DISTRICTS = {
    "riverside": {"name": "Riverside", "y": (0, 25)},
    "delmar":    {"name": "Delmar Row", "y": (26, 41)},
    "terraces":  {"name": "The Terraces", "y": (42, 57)},
    "civic":     {"name": "Civic End", "y": (58, 71)},
}

# id, name, district, x, y, w, h, door, kind, style, open
BUILDINGS = [
    # ── Riverside ────────────────────────────────────────────────────────────
    ("warehouse",  "Pier 9 Warehouse",    "riverside", 2,  15, 9,  8, "S", "industrial", "metal",     False),
    ("laundromat", "Spin Cycle",          "riverside", 17, 15, 10, 8, "S", "business",   "shopfront", False),
    ("harborbar",  "The Harbor Bar",      "riverside", 29, 15, 10, 8, "S", "social",     "brick",     False),
    ("docks",      "Kessler Docks",       "riverside", 45, 15, 13, 8, "S", "outdoor",    "none",      True),
    ("cannery",    "Delgado Cannery",     "riverside", 59, 15, 8,  8, "S", "industrial", "metal",     False),
    ("riverflats", "Riverside Flats",     "riverside", 72, 15, 12, 8, "S", "home",       "concrete",  False),

    # ── Delmar Row ───────────────────────────────────────────────────────────
    ("cornerstore","Calloway's Corner",   "delmar",    2,  31, 9,  8, "S", "business",   "shopfront", False),
    ("barbershop", "Tee's Barbershop",    "delmar",    17, 31, 9,  8, "S", "social",     "shopfront", False),
    ("diner",      "The Blue Spoon",      "delmar",    29, 31, 10, 8, "S", "social",     "shopfront", False),
    ("pawnshop",   "Lyle Pawn & Loan",    "delmar",    45, 31, 10, 8, "S", "business",   "brownstone",False),
    ("church",     "St. Brendan's",       "delmar",    58, 31, 9,  8, "S", "civic",      "stone",     False),
    ("bodega",     "Okafor Bodega",       "delmar",    72, 31, 9,  8, "S", "business",   "shopfront", False),
    ("delmarflats","Delmar Apartments",   "delmar",    84, 31, 10, 8, "S", "home",       "brownstone",False),

    # ── The Terraces ─────────────────────────────────────────────────────────
    ("terrace_a",  "Terrace Block A",     "terraces",  2,  47, 9,  8, "S", "home",       "brownstone",False),
    ("terrace_b",  "Terrace Block B",     "terraces",  17, 47, 9,  8, "S", "home",       "brownstone",False),
    ("vasquez",    "The Vasquez House",   "terraces",  29, 47, 9,  8, "S", "home",       "clapboard", False),
    ("lot",        "The Vacant Lot",      "terraces",  45, 47, 12, 8, "S", "outdoor",    "none",      True),
    ("okonkwo",    "The Okonkwo House",   "terraces",  59, 47, 8,  8, "S", "home",       "clapboard", False),
    ("green",      "Marrow Green",        "terraces",  72, 47, 14, 8, "S", "outdoor",    "none",      True),

    # ── Civic End ────────────────────────────────────────────────────────────
    ("precinct",   "9th Precinct",        "civic",     2,  62, 9,  8, "N", "civic",      "stone",     False),
    ("clinic",     "Halloway Clinic",     "civic",     17, 62, 9,  8, "N", "civic",      "concrete",  False),
    ("school",     "Delmar High",         "civic",     29, 62, 10, 8, "N", "civic",      "brick",     False),
    ("autoshop",   "Vasquez Auto Body",   "civic",     45, 62, 10, 8, "N", "business",   "metal",     False),
    ("underpass",  "The Underpass",       "civic",     59, 62, 8,  8, "N", "outdoor",    "none",      True),
    ("depot",      "Transit Depot",       "civic",     72, 62, 12, 8, "N", "industrial", "concrete",  False),
]

# What each kind of interior is furnished with, and roughly how much of it. Order matters:
# earlier items get the better positions (against the back wall).
FURNITURE_PLAN = {
    "home":       [("bed", 2), ("sofa", 1), ("tv", 1), ("table", 1), ("sink", 1),
                   ("shelf", 1), ("plant", 1), ("rug", 1)],
    "social":     [("counter", 1), ("table", 3), ("chair", 3), ("shelf", 1), ("plant", 1)],
    "business":   [("counter", 1), ("till", 1), ("shelf", 3), ("crate", 1), ("plant", 1)],
    "civic":      [("desk", 3), ("chair", 2), ("shelf", 2), ("plant", 1)],
    "industrial": [("crate", 4), ("machine", 2), ("shelf", 1)],
    "outdoor":    [("bench", 2), ("bin", 1), ("tree", 3)],
}


RIVER_DEPTH = 4     # the water Riverside is named after


def _blank():
    """Default to pavement, not grass.

    Grass as the default made every gap between buildings a field — about a third of the
    map — which reads as parkland with some sheds on it rather than a city. Green is now
    something a tile has to earn: the parks, the back yards, and the river bank.
    """
    g = [[PAVEMENT for _ in range(W)] for _ in range(H)]
    for y in range(RIVER_DEPTH):
        for x in range(W):
            g[y][x] = WATER
    for x in range(W):
        g[RIVER_DEPTH][x] = GRASS          # bank
    return g


def _paint_yards(g):
    """A strip of green behind each house. Cheap, and it stops the residential rows
    looking like the same terrace repeated six times."""
    for bid, _n, _d, x, y, w, h, _s, kind, _st, is_open in BUILDINGS:
        if kind != "home" or is_open:
            continue
        for yy in range(max(0, y - 3), y):
            for xx in range(x, x + w):
                if g[yy][xx] == PAVEMENT:
                    g[yy][xx] = GRASS


def _paint_roads(g):
    """Roads get a pavement either side and a dashed centre line, which is most of what
    separates 'a city' from 'coloured rectangles on graph paper'."""
    for y0, h in H_ROADS:
        for y in range(max(0, y0 - 1), min(H, y0 + h + 1)):
            for x in range(W):
                if y0 <= y < y0 + h:
                    mid = y == y0 + h // 2 - 1
                    g[y][x] = LINE if (mid and (x // 2) % 2 == 0) else ROAD
                else:
                    g[y][x] = PAVEMENT

    for x0, w in V_ROADS:
        for x in range(max(0, x0 - 1), min(W, x0 + w + 1)):
            # Vertical roads run the height of the map, which would otherwise pave straight
            # across the river.
            for y in range(RIVER_DEPTH + 1, H):
                inter = any(y0 - 1 <= y < y0 + h + 1 for y0, h in H_ROADS)
                if x0 <= x < x0 + w:
                    if inter:
                        g[y][x] = ROAD
                    else:
                        mid = x == x0 + w // 2 - 1
                        g[y][x] = LINE if (mid and (y // 2) % 2 == 0) else ROAD
                elif not inter:
                    g[y][x] = PAVEMENT

    # Crossings on the approach to every junction.
    for y0, h in H_ROADS:
        for x0, w in V_ROADS:
            for x in range(x0, x0 + w):
                for y in (y0 - 1, y0 + h):
                    if 0 <= y < H:
                        g[y][x] = CROSS


def _door_tile(x, y, w, h, side):
    if side == "S":
        return x + w // 2, y + h - 1
    if side == "N":
        return x + w // 2, y
    if side == "W":
        return x, y + h // 2
    return x + w - 1, y + h // 2


def _furnish(bid, kind, x, y, w, h, is_open):
    """Deterministic per building: same city every run, and diffs stay readable."""
    plan = FURNITURE_PLAN.get(kind, [])
    rng = random.Random(f"furnish:{bid}")
    if is_open:
        spots = [(xx, yy) for yy in range(y + 1, y + h - 1) for xx in range(x + 1, x + w - 1)]
    else:
        spots = [(xx, yy) for yy in range(y + 1, y + h - 1) for xx in range(x + 1, x + w - 1)]
    rng.shuffle(spots)

    door = None if is_open else _door_tile(x, y, w, h, "S")
    out, used = [], set()
    for kind_name, count in plan:
        for _ in range(count):
            while spots:
                sx, sy = spots.pop()
                # Never block the doorway or the tile just inside it.
                if door and abs(sx - door[0]) <= 1 and abs(sy - door[1]) <= 1:
                    continue
                if (sx, sy) in used:
                    continue
                used.add((sx, sy))
                out.append({"type": kind_name, "x": sx, "y": sy})
                break
    return out


def build_grid():
    g = _blank()
    _paint_roads(g)
    _paint_yards(g)

    anchors, furniture = {}, {}
    for bid, _n, _d, x, y, w, h, side, kind, _style, is_open in BUILDINGS:
        if is_open:
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    g[yy][xx] = GRASS if kind == "outdoor" else FLOOR
            anchors[bid] = (x + w // 2, y + h // 2)
        else:
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    edge = yy in (y, y + h - 1) or xx in (x, x + w - 1)
                    g[yy][xx] = WALL if edge else FLOOR
            dx, dy = _door_tile(x, y, w, h, side)
            g[dy][dx] = DOOR
            inside = {"S": (dx, dy - 1), "N": (dx, dy + 1),
                      "W": (dx + 1, dy), "E": (dx - 1, dy)}[side]
            anchors[bid] = inside
        furniture[bid] = _furnish(bid, kind, x, y, w, h, is_open)

    return g, anchors, furniture


GRID, ANCHORS, FURNITURE = build_grid()

LOCATIONS = {
    b[0]: {
        "id": b[0], "name": b[1], "district": b[2],
        "rect": [b[3], b[4], b[5], b[6]], "kind": b[8], "style": b[9],
        "anchor": list(ANCHORS[b[0]]),
        "furniture": FURNITURE[b[0]],
    }
    for b in BUILDINGS
}

HOMES = [b[0] for b in BUILDINGS if b[8] == "home"]


def walkable(x, y):
    return 0 <= x < W and 0 <= y < H and GRID[y][x] in WALKABLE


def furniture_of(loc_id, types):
    """Positions in this location matching any of `types` — where an activity happens."""
    return [f for f in LOCATIONS[loc_id]["furniture"] if f["type"] in types]


def district_at(y):
    for did, d in DISTRICTS.items():
        lo, hi = d["y"]
        if lo <= y <= hi:
            return did
    return "delmar"


def path(start, goal):
    """BFS over walkable tiles. The grid is 96x72, so an exact search still runs in well
    under a millisecond and is far easier to reason about than a heuristic one."""
    if start == goal:
        return [start]
    gx, gy = goal
    if not walkable(gx, gy):
        return [start]

    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        cx, cy = cur
        for nxt in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if nxt not in prev and walkable(*nxt):
                prev[nxt] = cur
                q.append(nxt)

    if goal not in prev:
        return [start]
    out, node = [], goal
    while node is not None:
        out.append(node)
        node = prev[node]
    return list(reversed(out))


def export_map():
    return {
        "tile": TILE, "w": W, "h": H,
        "grid": ["".join(row) for row in GRID],
        "districts": DISTRICTS,
        "locations": LOCATIONS,
    }
