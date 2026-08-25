"""
The Cut — city geometry.

Built programmatically from a compact block spec rather than a hand-drawn tile sheet, so a
location can be moved or resized by editing one line instead of repainting a grid.

Buildings are "roofless dollhouse": walls plus a visible walkable interior, furnished. That
keeps everyone on screen — a character who goes home to watch television is still watchable,
and we never need interior scene-switching or a second camera mode.

Furniture is generated deterministically per building rather than hand-placed, because 30
buildings of hand-placed props is a maintenance job nobody will do twice. It exists for two
reasons: rooms that read as rooms, and anchors for what people are actually doing — you
cannot sit on a sofa the map does not have.

**The city is no longer a constant.** `BASE_BUILDINGS` is only the seed; the live list is
persisted in `state/city.json` and can be damaged, ruined, rebuilt and extended while the
city runs (see `sim/construction.py`). Everything downstream reads the module globals
`GRID / LOCATIONS / ANCHORS / FURNITURE`, which `rebuild()` recomputes in place — so call
sites did not have to learn that the ground can move under them.

**Footprints are deliberately irregular.** Every building used to be h=8 sitting on one of
four y values, which is why the city read as four rows of identical boxes. Buildings now
vary in width, depth and setback; `wings` lets one building occupy several rectangles, so a
warehouse can be L-shaped and an apartment block can enclose a courtyard; and shops on
Delmar and the houses in the Terraces are authored as *attached rows* that share party
walls, which is what actually makes a street look like a street. `selftest.py` asserts no
two buildings overlap and none is laid on top of a road.

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
    x  rubble      walkable — what is left of a destroyed building
    s  scaffold    blocked — a building going back up
"""

import hashlib
import heapq
import random
from collections import deque

TILE = 16
# The map was 96x72 and effectively full — one 8x6 plot left and nothing bigger, so the
# expansion system had nowhere to put anything and the city could not visibly grow. The
# original blocks keep their exact coordinates; the extra ground is added to the south and
# east as open land for the city to spread into.
W, H = 128, 104

PAVEMENT, ROAD, LINE, CROSS, GRASS = ".", ",", ":", "=", "g"
WALL, FLOOR, DOOR, WATER = "#", "f", "D", "~"
RUBBLE, SCAFFOLD = "x", "s"

# Rubble is walkable on purpose: a burnt-out shell is somewhere people can still stand,
# pick through, and hold a vigil. Scaffolding is not — a site under construction is closed.
WALKABLE = {PAVEMENT, ROAD, LINE, CROSS, GRASS, FLOOR, DOOR, RUBBLE}

# (start, width) — roads are 4 wide with painted centre lines, pavements are added either side
H_ROADS = [(10, 4), (26, 4), (42, 4), (58, 4), (74, 4), (90, 4)]
V_ROADS = [(12, 4), (40, 4), (68, 4), (96, 4), (112, 4)]

DISTRICTS = {
    "riverside": {"name": "Riverside", "y": (0, 25)},
    "delmar":    {"name": "Delmar Row", "y": (26, 41)},
    "terraces":  {"name": "The Terraces", "y": (42, 57)},
    "civic":     {"name": "Civic End", "y": (58, 73)},
    # Open ground the city has not reached yet. Buildings appear here as it grows, which is
    # the whole point of having it — an empty district is a promise, not a gap.
    "flats":     {"name": "The Flats", "y": (74, 103)},
}

# Anything past these is undeveloped: scrub and open ground rather than paved street, so the
# edge of town reads as somewhere the city has not got to instead of an empty car park.
BUILT_EDGE_Y = 74
BUILT_EDGE_X = 100

RIVER_DEPTH = 4     # the water Riverside is named after


def _b(bid, name, district, x, y, w, h, door, kind, style, is_open=False,
       wings=(), floors=1):
    """One building. `wings` are extra rectangles offset from (x, y), which is what turns a
    plain box into an L, a U or a courtyard block."""
    return {"id": bid, "name": name, "district": district,
            "x": x, "y": y, "w": w, "h": h, "door": door, "kind": kind,
            "style": style, "open": is_open, "wings": [list(v) for v in wings],
            "floors": floors, "condition": "standing", "since_day": 0}


# The seed city. Ids here are load-bearing — agents reference their home and work by id, so
# an id may be re-skinned but must not vanish.
BASE_BUILDINGS = [
    # ── Riverside ────────────────────────────────────────────────────────────
    # The warehouse is L-shaped around its own loading yard.
    _b("warehouse",  "Pier 9 Warehouse",  "riverside", 1,  15, 10, 7, "S", "industrial", "metal",
       wings=[(0, 7, 6, 4)], floors=2),
    _b("laundromat", "Spin Cycle",        "riverside", 17, 18, 9,  7, "S", "business",   "shopfront"),
    _b("harborbar",  "The Harbor Bar",    "riverside", 27, 15, 10, 6, "S", "social",     "brick", floors=2),
    # Sits in the bar's back lot — the gap between them is an alley, not a field.
    _b("tenement",   "Kessler Tenement",  "riverside", 27, 22, 10, 4, "S", "home",       "brownstone", floors=3),
    _b("docks",      "Kessler Docks",     "riverside", 45, 15, 13, 8, "S", "outdoor",    "none", is_open=True),
    _b("cannery",    "Delgado Cannery",   "riverside", 59, 15, 8,  11, "S", "industrial", "metal", floors=2),
    # U-shaped around a courtyard, the way a real block of flats encloses its yard.
    _b("riverflats", "Riverside Flats",   "riverside", 73, 15, 13, 4, "S", "home",       "concrete",
       wings=[(0, 4, 4, 7), (9, 4, 4, 7)], floors=3),

    # ── Delmar Row ───────────────────────────────────────────────────────────
    _b("cornerstore", "Calloway's Corner", "delmar",   1,  31, 10, 6, "S", "business",   "shopfront", floors=2),
    _b("printshop",   "Ruiz Print & Sign", "delmar",   1,  38, 8,  4, "S", "business",   "brick"),
    # An attached run of shopfronts sharing party walls — the actual high street.
    _b("barbershop",  "Tee's Barbershop",  "delmar",   17, 31, 7,  6, "S", "social",     "shopfront", floors=2),
    _b("diner",       "The Blue Spoon",    "delmar",   24, 31, 8,  6, "S", "social",     "shopfront", floors=2),
    _b("pawnshop",    "Lyle Pawn & Loan",  "delmar",   32, 31, 6,  6, "S", "business",   "brownstone", floors=2),
    # Set back off the street with a porch pushed out towards it.
    _b("church",      "St. Brendan's",     "delmar",   45, 33, 11, 9, "S", "civic",      "stone",
       wings=[(4, -2, 3, 2)], floors=2),
    _b("bodega",      "Okafor Bodega",     "delmar",   59, 31, 7,  5, "S", "business",   "shopfront"),
    _b("courthouse",  "Delmar Courthouse", "delmar",   59, 37, 8,  5, "S", "civic",      "stone", floors=2),
    _b("delmarflats", "Delmar Apartments", "delmar",   73, 31, 12, 7, "S", "home",       "brownstone",
       wings=[(0, 7, 7, 4)], floors=4),

    # ── The Terraces ─────────────────────────────────────────────────────────
    # Two attached pairs and a row of three: narrow, deep, sharing walls.
    _b("terrace_a",  "Terrace Block A",   "terraces",  1,  47, 5,  8, "S", "home", "brownstone", floors=2),
    _b("terrace_b",  "Terrace Block B",   "terraces",  6,  47, 5,  8, "S", "home", "brownstone", floors=2),
    _b("terrace_c",  "12 Marrow Row",     "terraces",  17, 47, 4,  9, "S", "home", "brownstone", floors=2),
    _b("terrace_d",  "14 Marrow Row",     "terraces",  21, 47, 4,  9, "S", "home", "brownstone", floors=2),
    _b("terrace_e",  "16 Marrow Row",     "terraces",  25, 47, 4,  9, "S", "home", "brownstone", floors=2),
    _b("vasquez",    "The Vasquez House", "terraces",  30, 47, 8,  7, "S", "home", "clapboard"),
    _b("lot",        "The Vacant Lot",    "terraces",  45, 47, 12, 8, "S", "outdoor", "none", is_open=True),
    _b("okonkwo",    "The Okonkwo House", "terraces",  59, 48, 8,  7, "S", "home", "clapboard"),
    _b("green",      "Marrow Green",      "terraces",  73, 47, 14, 9, "S", "outdoor", "none", is_open=True),

    # ── Civic End ────────────────────────────────────────────────────────────
    _b("precinct",  "9th Precinct",       "civic",     1,  63, 10, 8, "N", "civic",      "stone", floors=2),
    _b("clinic",    "Halloway Clinic",    "civic",     17, 63, 9,  8, "N", "civic",      "concrete", floors=2),
    _b("school",    "Delmar High",        "civic",     28, 63, 11, 9, "N", "civic",      "brick", floors=2),
    _b("autoshop",  "Vasquez Auto Body",  "civic",     45, 63, 10, 7, "N", "business",   "metal"),
    _b("underpass", "The Underpass",      "civic",     59, 63, 8,  8, "N", "outdoor",    "none", is_open=True),
    _b("depot",     "Transit Depot",      "civic",     73, 63, 12, 9, "N", "industrial", "concrete", floors=2),
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

# Conditions a building can be in. Only "standing" is a working location.
STANDING, DAMAGED, RUIN, REBUILDING = "standing", "damaged", "ruin", "rebuilding"
USABLE = {STANDING, DAMAGED}


def rects(b):
    """Every rectangle this building occupies — the main block plus any wings."""
    out = [(b["x"], b["y"], b["w"], b["h"])]
    for dx, dy, w, h in b.get("wings") or []:
        out.append((b["x"] + dx, b["y"] + dy, w, h))
    return out


def cells(b):
    out = set()
    for x, y, w, h in rects(b):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if 0 <= xx < W and 0 <= yy < H:
                    out.add((xx, yy))
    return out


def bounds(b):
    cs = cells(b)
    xs = [c[0] for c in cs] or [b["x"]]
    ys = [c[1] for c in cs] or [b["y"]]
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def _blank():
    """Default to pavement, not grass.

    Grass as the default made every gap between buildings a field — about a third of the
    map — which reads as parkland with some sheds on it rather than a city. Green is now
    something a tile has to earn: the parks, the back yards, and the river bank.
    """
    g = [[PAVEMENT for _ in range(W)] for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if y >= BUILT_EDGE_Y or x >= BUILT_EDGE_X:
                g[y][x] = GRASS            # open ground the city has not built on yet
    for y in range(RIVER_DEPTH):
        for x in range(W):
            g[y][x] = WATER
    for x in range(W):
        g[RIVER_DEPTH][x] = GRASS          # bank
    return g


def _paint_yards(g, buildings):
    """A strip of green behind each house. Cheap, and it stops the residential rows
    looking like the same terrace repeated six times."""
    for b in buildings:
        if b["kind"] != "home" or b["open"]:
            continue
        x, y, w, _h = bounds(b)
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


def _door_tile(b, cs=None):
    """Pick a wall cell that actually faces the street.

    The old version assumed a plain rectangle and returned the midpoint of one edge. On an
    L-shaped building that lands on the *seam* between the block and its wing — a cell with
    building on both sides — so the door opened into another room and the whole place became
    unreachable. Instead: take the boundary cells that genuinely touch open ground, prefer
    the requested side, and break ties deterministically so the city is stable run to run.
    """
    cs = cs if cs is not None else cells(b)
    side = b["door"]
    outward = {"S": (0, 1), "N": (0, -1), "W": (-1, 0), "E": (1, 0)}[side]

    def opens_inward(cell):
        x, y = cell
        return any(n in cs and _interior(cs, n)
                   for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    facing, any_side = [], []
    for (x, y) in cs:
        if _interior(cs, (x, y)) or not opens_inward((x, y)):
            continue
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            n = (x + dx, y + dy)
            if n in cs or not (0 <= n[0] < W and 0 <= n[1] < H):
                continue
            any_side.append((x, y))
            if (dx, dy) == outward:
                facing.append((x, y))
            break

    pool = facing or any_side
    if not pool:
        return b["x"], b["y"]

    # Deepest wall on the requested side, then nearest that wall's midpoint — a corner door
    # is both ugly and, on an L-shape, frequently sealed by the building's own walls.
    horiz = side in ("S", "N")
    depth = (lambda c: -c[1]) if side == "S" else (lambda c: c[1]) if side == "N"         else (lambda c: c[0]) if side == "W" else (lambda c: -c[0])
    best = depth(min(pool, key=depth))
    run = [c for c in pool if depth(c) == best]
    mid = sum(c[0] if horiz else c[1] for c in run) / len(run)
    return min(run, key=lambda c: (abs((c[0] if horiz else c[1]) - mid), c))


def _furnish(b):
    """Deterministic per building: same city every run, and diffs stay readable."""
    plan = FURNITURE_PLAN.get(b["kind"], [])
    rng = random.Random(f'furnish:{b["id"]}:{b.get("generation", 0)}')
    cs = cells(b)
    interior = [c for c in cs if _interior(cs, c)]
    rng.shuffle(interior)

    door = None if b["open"] else _door_tile(b, cs)
    out, used = [], set()
    for kind_name, count in plan:
        for _ in range(count):
            while interior:
                sx, sy = interior.pop()
                # Never block the doorway or the tile just inside it.
                if door and abs(sx - door[0]) <= 1 and abs(sy - door[1]) <= 1:
                    continue
                if (sx, sy) in used:
                    continue
                used.add((sx, sy))
                out.append({"type": kind_name, "x": sx, "y": sy})
                break
    return out


def _interior(cs, cell):
    """A cell is interior when all four of its neighbours are also part of the building —
    which is what makes an L or a U wall itself correctly without special-casing shapes.
    Takes the cell set rather than the building so build_grid computes it once."""
    x, y = cell
    return all(n in cs for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))


def build_grid(buildings):
    g = _blank()
    _paint_roads(g)
    _paint_yards(g, buildings)

    anchors, furniture = {}, {}
    for b in buildings:
        cond = b.get("condition", STANDING)
        cs = cells(b)

        if cond == RUIN:
            # A shell. Walkable, so people can stand in what is left of it.
            for (xx, yy) in cs:
                g[yy][xx] = RUBBLE
            anchors[b["id"]] = _centre(cs)
            furniture[b["id"]] = []
            continue

        if cond == REBUILDING:
            for (xx, yy) in cs:
                g[yy][xx] = SCAFFOLD
            anchors[b["id"]] = _centre(cs)
            furniture[b["id"]] = []
            continue

        if b["open"]:
            for (xx, yy) in cs:
                g[yy][xx] = GRASS if b["kind"] == "outdoor" else FLOOR
            anchors[b["id"]] = _centre(cs)
        else:
            for (xx, yy) in cs:
                g[yy][xx] = FLOOR if _interior(cs, (xx, yy)) else WALL
            dx, dy = _door_tile(b, cs)
            g[dy][dx] = DOOR
            # Stand just inside the door, whichever way "inside" happens to be for this shape.
            inside = next((n for n in ((dx, dy - 1), (dx, dy + 1), (dx + 1, dy), (dx - 1, dy))
                           if n in cs and _interior(cs, n)), None)
            anchors[b["id"]] = inside or _centre(cs)
        furniture[b["id"]] = _furnish(b)

    return g, anchors, furniture


def _centre(cs):
    xs = sorted(c[0] for c in cs)
    ys = sorted(c[1] for c in cs)
    return (xs[len(xs) // 2], ys[len(ys) // 2])


# ── the live city ────────────────────────────────────────────────────────────
# Module globals so every existing call site keeps working; `rebuild()` swaps them when the
# city is damaged, repaired or extended.

BUILDINGS = [dict(b) for b in BASE_BUILDINGS]   # replaced wholesale by rebuild()
GRID, ANCHORS, FURNITURE = build_grid(BUILDINGS)
LOCATIONS = {}
HOMES = []


def rebuild(buildings=None):
    """Recompute the world from a building list. Call after anything structural changes.

    The list is adopted **by reference**, not copied. That matters: the caller (the world)
    owns the buildings, and this module is a derived view of them. Copying here meant a fire
    recorded in city.BUILDINGS never reached the world that was supposed to persist it, and
    two simulations in one process silently shared one city — which is exactly how the
    determinism invariant caught it.
    """
    global BUILDINGS, GRID, ANCHORS, FURNITURE, LOCATIONS, HOMES
    if buildings is not None:
        BUILDINGS = buildings
    GRID, ANCHORS, FURNITURE = build_grid(BUILDINGS)
    LOCATIONS = {
        b["id"]: {
            "id": b["id"], "name": b["name"], "district": b["district"],
            "rect": list(bounds(b)),
            "rects": [list(r) for r in rects(b)],
            "kind": b["kind"], "style": b["style"], "floors": b.get("floors", 1),
            "open": b["open"],
            "condition": b.get("condition", STANDING),
            "anchor": list(ANCHORS[b["id"]]),
            "furniture": FURNITURE[b["id"]],
        }
        for b in BUILDINGS
    }
    HOMES = [b["id"] for b in BUILDINGS
             if b["kind"] == "home" and b.get("condition", STANDING) in USABLE]
    return LOCATIONS


rebuild()


def usable(loc_id):
    """Can somebody actually be inside this place right now?"""
    loc = LOCATIONS.get(loc_id)
    return bool(loc) and loc["condition"] in USABLE


def walkable(x, y):
    return 0 <= x < W and 0 <= y < H and GRID[y][x] in WALKABLE


def furniture_of(loc_id, types):
    """Positions in this location matching any of `types` — where an activity happens."""
    loc = LOCATIONS.get(loc_id)
    if not loc:
        return []
    return [f for f in loc["furniture"] if f["type"] in types]


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


def map_version():
    """Cheap signature of the city's *shape*.

    The browser polls the map every refresh now that buildings can burn down, but rebuilding
    the background canvas is expensive. This lets it redraw only when something actually
    moved rather than every few seconds.
    """
    parts = [f'{b["id"]}:{b.get("condition")}:{b["x"]},{b["y"]},{b["w"]},{b["h"]}:'
             f'{b["kind"]}:{b["style"]}:{b.get("generation", 0)}'
             for b in BUILDINGS]
    # Not hash(): Python salts it per process, so the version would change on every run and
    # the browser would rebuild its background canvas forever.
    return hashlib.md5("|".join(sorted(parts)).encode()).hexdigest()[:12]


# What a tile costs to drive over. Roads are free; everything else is something you would
# only cross to get to or from one, which is what keeps cars on the streets instead of
# cutting diagonally across Marrow Green.
DRIVE_COST = {ROAD: 1, LINE: 1, CROSS: 1, PAVEMENT: 4, GRASS: 9,
              FLOOR: 14, DOOR: 14, RUBBLE: 12}


def road_path(start, goal):
    """The way you would actually drive it: down the street, not through the park.

    Dijkstra rather than the BFS used for walking, because the point is not the fewest tiles
    but the cheapest ones — a route two tiles longer that stays on tarmac is the right answer
    and a breadth-first search cannot express that.
    """
    if start == goal:
        return [start]
    if not walkable(*goal):
        return [start]

    dist = {start: 0}
    prev = {start: None}
    q = [(0, start)]
    while q:
        d, cur = heapq.heappop(q)
        if cur == goal:
            break
        if d > dist.get(cur, 1 << 30):
            continue
        cx, cy = cur
        for nxt in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if not walkable(*nxt):
                continue
            step = DRIVE_COST.get(GRID[nxt[1]][nxt[0]], 8)
            nd = d + step
            if nd < dist.get(nxt, 1 << 30):
                dist[nxt] = nd
                prev[nxt] = cur
                heapq.heappush(q, (nd, nxt))

    if goal not in prev:
        return path(start, goal)          # unreachable by road; walk it
    out, node = [], goal
    while node is not None:
        out.append(node)
        node = prev[node]
    return list(reversed(out))


# ── land the city has not needed yet ─────────────────────────────────────────
# The map used to be a fixed rectangle, so "expand the city" eventually meant "there is
# nowhere left". It now grows on demand: when nothing of a useful size will fit any more,
# another strip is added and the road grid is extended into it at the same pitch.
#
# Not literally infinite — the browser downloads the grid, so there is a practical ceiling
# measured in hundreds of tiles rather than a hard limit in the code. Growth is in chunks
# because re-exporting the map is the expensive part, not the tiles themselves.
GROW_CHUNK = 32
ROAD_PITCH = 16
MAX_SIDE = 512          # a 512x512 grid is a ~1MB map.json; past that the browser suffers


def resize(new_w, new_h):
    """Extend the world, laying new roads only in ground that did not exist before.

    Roads are added strictly beyond the old edges so nothing already built can find a
    carriageway through the middle of it.
    """
    global W, H
    old_w, old_h = W, H
    W, H = min(MAX_SIDE, max(W, new_w)), min(MAX_SIDE, max(H, new_h))

    for y in range(((old_h // ROAD_PITCH) + 1) * ROAD_PITCH, H - 6, ROAD_PITCH):
        if all(y0 != y for y0, _ in H_ROADS):
            H_ROADS.append((y, 4))
    for x in range(((old_w // ROAD_PITCH) + 1) * ROAD_PITCH, W - 6, ROAD_PITCH):
        if all(x0 != x for x0, _ in V_ROADS):
            V_ROADS.append((x, 4))

    # The outermost district stretches to cover whatever was just added, so district_at()
    # never returns a name for ground that has no district.
    last = max(DISTRICTS, key=lambda d: DISTRICTS[d]["y"][1])
    lo, _hi = DISTRICTS[last]["y"]
    DISTRICTS[last]["y"] = (lo, H - 1)
    return W, H


def room_left(buildings, w=12, h=8):
    """Is there anywhere sensible left to put a building of this size?"""
    from . import construction
    return construction.find_plot(buildings, w, h) is not None


def grow_if_needed(world, buildings):
    """Add another strip of land when the city is running out. Returns True if it grew."""
    if room_left(buildings):
        return False
    if W >= MAX_SIDE and H >= MAX_SIDE:
        return False
    # Grow the shorter side first so the city stays roughly square rather than becoming a
    # corridor, which is what repeatedly extending one axis produces.
    if H <= W:
        resize(W, H + GROW_CHUNK)
    else:
        resize(W + GROW_CHUNK, H)
    world["map_w"], world["map_h"] = W, H
    rebuild(buildings)
    return True


def export_map():
    return {
        "tile": TILE, "w": W, "h": H, "version": map_version(),
        "grid": ["".join(row) for row in GRID],
        "districts": DISTRICTS,
        "locations": LOCATIONS,
    }
