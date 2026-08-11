"""
The Cut — city geometry.

The map is built programmatically from a compact block spec rather than stored as a
hand-drawn tile sheet, so a location can be moved or resized by editing one line here
instead of repainting a grid.

Buildings are "roofless dollhouse" style: walls plus a visible walkable interior. That
means a character entering the laundromat stays on screen and stays watchable, and we
never need interior scene-switching or a second camera mode.

Tile legend (also consumed by the front-end renderer):
    .  pavement   walkable
    ,  road       walkable (characters prefer pavement; purely visual weighting)
    #  wall       blocked
    f  floor      walkable, inside a building
    D  door       walkable, the seam between street and interior
    ~  water      blocked
"""

from collections import deque

TILE = 16
W, H = 64, 44

PAVEMENT, ROAD, WALL, FLOOR, DOOR, WATER = ".", ",", "#", "f", "D", "~"
WALKABLE = {PAVEMENT, ROAD, FLOOR, DOOR}

# Horizontal roads as (y_start, height); vertical as (x_start, width).
H_ROADS = [(3, 2), (13, 2), (23, 2), (33, 2), (42, 2)]
V_ROADS = [(2, 2), (60, 2)]

DISTRICTS = {
    "riverside": {"name": "Riverside", "y": (0, 12)},
    "delmar":    {"name": "Delmar Row", "y": (13, 22)},
    "terraces":  {"name": "The Terraces", "y": (23, 32)},
    "civic":     {"name": "Civic End", "y": (33, 43)},
}

# id, display name, district, x, y, w, h, door side, kind, open (no walls)
BUILDINGS = [
    ("warehouse",  "Pier 9 Warehouse",     "riverside", 5,  6, 12, 6, "S", "industrial", False),
    ("laundromat", "Spin Cycle Laundromat","riverside", 21, 6,  9, 6, "S", "business",   False),
    ("harborbar",  "The Harbor Bar",       "riverside", 35, 6,  9, 6, "S", "social",     False),
    ("docks",      "Kessler Docks",        "riverside", 48, 6, 11, 6, "S", "industrial", True),

    ("cornerstore","Calloway's Corner",    "delmar",    5,  16, 9, 6, "S", "business",   False),
    ("barbershop", "Tee's Barbershop",     "delmar",    18, 16, 9, 6, "S", "social",     False),
    ("diner",      "The Blue Spoon",       "delmar",    31, 16,10, 6, "S", "social",     False),
    ("pawnshop",   "Lyle Pawn & Loan",     "delmar",    45, 16,10, 6, "S", "business",   False),

    ("terrace_a",  "Terrace Block A",      "terraces",  5,  26,10, 6, "S", "home",       False),
    ("terrace_b",  "Terrace Block B",      "terraces",  19, 26,10, 6, "S", "home",       False),
    ("vasquez",    "The Vasquez House",    "terraces",  33, 26, 9, 6, "S", "home",       False),
    ("lot",        "The Vacant Lot",       "terraces",  46, 26,12, 6, "S", "outdoor",    True),

    ("precinct",   "9th Precinct",         "civic",     5,  35,11, 6, "N", "civic",      False),
    ("clinic",     "Halloway Clinic",      "civic",     20, 35,10, 6, "N", "civic",      False),
    ("autoshop",   "Vasquez Auto Body",    "civic",     34, 35,10, 6, "N", "business",   False),
    ("underpass",  "The Underpass",        "civic",     48, 35,11, 6, "N", "outdoor",    True),
]


def _blank():
    return [[PAVEMENT for _ in range(W)] for _ in range(H)]


def _paint_roads(g):
    for y0, h in H_ROADS:
        for y in range(y0, min(y0 + h, H)):
            for x in range(W):
                g[y][x] = ROAD
    for x0, w in V_ROADS:
        for x in range(x0, min(x0 + w, W)):
            for y in range(H):
                g[y][x] = ROAD


def _door_tile(x, y, w, h, side):
    """Door sits in the middle of the chosen wall."""
    if side == "S":
        return x + w // 2, y + h - 1
    if side == "N":
        return x + w // 2, y
    if side == "W":
        return x, y + h // 2
    return x + w - 1, y + h // 2


def _paint_buildings(g):
    anchors = {}
    for bid, _name, _district, x, y, w, h, side, _kind, is_open in BUILDINGS:
        if is_open:
            # Open sites (docks, vacant lot, underpass) have no walls — just a marked floor.
            for yy in range(y, y + h):
                for xx in range(x, x + w):
                    g[yy][xx] = FLOOR
            anchors[bid] = (x + w // 2, y + h // 2)
            continue

        for yy in range(y, y + h):
            for xx in range(x, x + w):
                edge = yy in (y, y + h - 1) or xx in (x, x + w - 1)
                g[yy][xx] = WALL if edge else FLOOR

        dx, dy = _door_tile(x, y, w, h, side)
        g[dy][dx] = DOOR
        # Anchor is one tile inside the door — where a character "stands" at this location.
        inside = {"S": (dx, dy - 1), "N": (dx, dy + 1), "W": (dx + 1, dy), "E": (dx - 1, dy)}[side]
        anchors[bid] = inside
    return anchors


def build_grid():
    g = _blank()
    _paint_roads(g)
    anchors = _paint_buildings(g)
    return g, anchors


GRID, ANCHORS = build_grid()
LOCATIONS = {
    b[0]: {
        "id": b[0], "name": b[1], "district": b[2],
        "rect": [b[3], b[4], b[5], b[6]], "kind": b[8],
        "anchor": list(ANCHORS[b[0]]),
    }
    for b in BUILDINGS
}


def walkable(x, y):
    return 0 <= x < W and 0 <= y < H and GRID[y][x] in WALKABLE


def district_at(y):
    for did, d in DISTRICTS.items():
        lo, hi = d["y"]
        if lo <= y <= hi:
            return did
    return "delmar"


def path(start, goal):
    """BFS over walkable tiles. Grid is tiny (64x44) so an exact search beats A* heuristics
    in both simplicity and debuggability, and runs in well under a millisecond."""
    if start == goal:
        return [start]
    sx, sy = start
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
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if (nx, ny) not in prev and walkable(nx, ny):
                prev[(nx, ny)] = cur
                q.append((nx, ny))

    if goal not in prev:
        return [start]
    out, node = [], goal
    while node is not None:
        out.append(node)
        node = prev[node]
    return list(reversed(out))


def export_map():
    """Serialised once at bootstrap; the front-end fetches this instead of rebuilding it."""
    return {
        "tile": TILE, "w": W, "h": H,
        "grid": ["".join(row) for row in GRID],
        "districts": DISTRICTS,
        "locations": LOCATIONS,
    }
