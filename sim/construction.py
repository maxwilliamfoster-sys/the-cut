"""
The Cut — the city as something that can be lost.

Until now the map was a constant. A city where the buildings can never change is a stage
set: the people move, the place does not, and after a hundred days it reads as scenery. This
module lets the block actually take damage — burn, be condemned, stand as a ruin, get pulled
down and go back up as something else — and lets the city grow onto empty land.

**Everything here is mechanical.** Not one LLM call. The city already spends its entire free
token allowance thinking, so structural change is decided in plain Python and *narrated* by
the systems that were going to run anyway: the beat's cognition sees the ruin in its prompt,
and the Gazette reports the fire because the fire is in the day's log. That is also why it
survives an outage — a city that cannot afford to think can still burn down.

The lifecycle, and why it has these stages:

    standing --damage--> damaged --damage--> ruin --(RUIN_DAYS)--> rebuilding --> standing

`damaged` exists so that fire is not binary; a place can be hurt and still used, which is
what puts pressure on people before it takes anything away. `ruin` is walkable rubble on
purpose — people stand in it, hold vigils in it, and it stays visible in the skyline as a
gap for days, so loss has a location. `rebuilding` is scaffolding: closed, but visibly
coming back.

Rebuilt blocks may come back as something else entirely (a burnt cannery reopens as a
market), which is how the city's character drifts over months without anybody authoring it.
"""

import random

from . import city

# A building sits as rubble for this many city-days before anyone starts rebuilding, then
# spends this long behind scaffolding. 4 beats to a city-day, 24 city-days to a real day —
# so these are hours of real time, which is the right scale for the player to notice.
RUIN_DAYS = 6
REBUILD_DAYS = 5

# Structural disaster is rare on purpose: a block that burns weekly is a comedy.
# These are per beat, PER BUILDING, and there are ~31 buildings and 96 beats in a real day —
# so the headline number is roughly 31 * 96 * BASE times larger than it looks. The first
# values here were 0.006, which levelled half the city inside a single real day. Calibrated
# against the 120-beat run in selftest.py: a fire of some kind every ~3 real days, and a
# building actually lost every week or so, which is rare enough to matter when it happens.
BASE_FIRE_CHANCE = 0.00006        # per beat, before modifiers
HEAT_FIRE_FACTOR = 0.0000020      # per point of district heat
DERELICT_FACTOR = 3.0             # a damaged building is far likelier to go completely

# Some kinds are more flammable than others, and the civic spine is protected — not immune.
KIND_RISK = {"industrial": 2.0, "business": 1.2, "home": 1.0,
             "social": 1.1, "civic": 0.35, "outdoor": 0.0}

CAUSES = [
    ("fire", "A fire takes {name}. It burns for most of the night."),
    ("fire", "{name} goes up before dawn. Nobody agrees on how it started."),
    ("collapse", "The back wall of {name} comes down. The rest follows."),
    ("arson", "{name} burns, and the way it burns says somebody meant it."),
    ("gas", "A gas leak tears through {name}."),
]

DAMAGE_TEXT = [
    "A fire is put out at {name} before it takes the whole building.",
    "Part of {name} is condemned. Tape across half the frontage.",
    "{name} floods to the joists. It stays open. Barely.",
]

# What a cleared plot can become. The city drifts by rebuilding as something the block needs
# now rather than what stood there before.
REBUILD_AS = {
    "home":       [("home", "brownstone", "{street} House"), ("home", "clapboard", "New {street}")],
    "business":   [("business", "shopfront", "{street} Market"), ("business", "brick", "{street} Supply")],
    "social":     [("social", "shopfront", "The New {street}"), ("social", "brick", "{street} Social Club")],
    "industrial": [("industrial", "metal", "{street} Works"), ("business", "metal", "{street} Yard")],
    "civic":      [("civic", "stone", "{street} Hall")],
}

STREET_NAMES = ["Marrow", "Delmar", "Kessler", "Brendan", "Pier", "Halloway",
                "Vasquez", "Okonkwo", "Calloway", "Riverside"]

# New buildings the city can raise on empty land as it grows.
EXPANSIONS = [
    ("home",     "brownstone", "{street} Tenement", 8,  6, 3),
    ("home",     "clapboard",  "{street} Cottages", 7,  6, 2),
    ("business", "shopfront",  "{street} Market",   9,  5, 1),
    ("social",   "brick",      "The {street} Rooms", 8, 5, 2),
    ("civic",    "concrete",   "{street} Library",  10, 6, 2),
]


def _rng(world, beat, salt):
    return random.Random(f'{world.get("seed", 0)}:{beat}:{salt}')


def _by_id(buildings):
    return {b["id"]: b for b in buildings}


# ── damage ───────────────────────────────────────────────────────────────────

def _risk(b, world):
    if b["open"] or b["condition"] in (city.RUIN, city.REBUILDING):
        return 0.0
    heat = (world.get("heat") or {}).get(b["district"], 0)
    risk = BASE_FIRE_CHANCE + heat * HEAT_FIRE_FACTOR
    risk *= KIND_RISK.get(b["kind"], 1.0)
    if b["condition"] == city.DAMAGED:
        risk *= DERELICT_FACTOR
    return risk


def roll_disaster(world, buildings, beat, day):
    """At most one structural event per beat. Returns (record, building) or (None, None)."""
    rng = _rng(world, beat, "disaster")
    live = [b for b in buildings if _risk(b, world) > 0]
    if not live:
        return None, None

    for b in live:
        if rng.random() >= _risk(b, world):
            continue
        # A standing building is usually only damaged; a damaged one usually goes.
        goes = b["condition"] == city.DAMAGED or rng.random() < 0.35
        if goes:
            cause, tmpl = rng.choice(CAUSES)
            b["condition"] = city.RUIN
            b["since_day"] = day
            text = tmpl.format(name=b["name"])
            return {"kind": "structure", "event": "destroyed", "building": b["id"],
                    "name": b["name"], "district": b["district"], "cause": cause,
                    "text": text, "day": day, "beat": beat}, b
        b["condition"] = city.DAMAGED
        b["since_day"] = day
        text = rng.choice(DAMAGE_TEXT).format(name=b["name"])
        return {"kind": "structure", "event": "damaged", "building": b["id"],
                "name": b["name"], "district": b["district"], "cause": "fire",
                "text": text, "day": day, "beat": beat}, b
    return None, None


# ── rebuilding ───────────────────────────────────────────────────────────────

def advance_works(world, buildings, beat, day):
    """Move ruins towards scaffolding and scaffolding back to standing."""
    out = []
    rng = _rng(world, beat, "works")
    for b in buildings:
        age = day - b.get("since_day", day)
        if b["condition"] == city.RUIN and age >= RUIN_DAYS:
            b["condition"] = city.REBUILDING
            b["since_day"] = day
            out.append({"kind": "structure", "event": "rebuilding", "building": b["id"],
                        "name": b["name"], "district": b["district"], "day": day, "beat": beat,
                        "text": f'Hoarding goes up around the shell of {b["name"]}.'})
        elif b["condition"] == city.REBUILDING and age >= REBUILD_DAYS:
            old = b["name"]
            _reopen(b, rng)
            b["condition"] = city.STANDING
            b["since_day"] = day
            b["generation"] = b.get("generation", 0) + 1
            out.append({"kind": "structure", "event": "rebuilt", "building": b["id"],
                        "name": b["name"], "was": old, "district": b["district"],
                        "day": day, "beat": beat,
                        "text": f'{b["name"]} opens on the site of {old}.'})
    return out


def _reopen(b, rng):
    """A rebuilt plot usually comes back as itself, sometimes as something the block needs
    more. The id never changes — agents reference it — only the skin and the sign."""
    options = REBUILD_AS.get(b["kind"])
    if not options or rng.random() < 0.45:
        return
    kind, style, name_t = rng.choice(options)
    b["kind"], b["style"] = kind, style
    b["name"] = name_t.format(street=rng.choice(STREET_NAMES))


# ── expansion ────────────────────────────────────────────────────────────────

def blocked_cells(buildings):
    """Every tile a new building may not occupy: anything already built (plus a one-tile
    margin), every road and its verge, and the river."""
    taken = set()
    for b in buildings:
        for (x, y) in city.cells(b):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    taken.add((x + dx, y + dy))
    for y0, rh in city.H_ROADS:
        for y in range(y0 - 2, y0 + rh + 2):
            for x in range(city.W):
                taken.add((x, y))
    for x0, rw in city.V_ROADS:
        for x in range(x0 - 2, x0 + rw + 2):
            for y in range(city.H):
                taken.add((x, y))
    for y in range(city.RIVER_DEPTH + 2):
        for x in range(city.W):
            taken.add((x, y))
    return taken


def plot_free(buildings, x, y, w, h, blocked=None):
    """Can a building of this size go exactly here? Used when the mayor picks the spot."""
    if x < 1 or y < 1 or x + w > city.W - 1 or y + h > city.H - 1:
        return False
    blocked = blocked_cells(buildings) if blocked is None else blocked
    return not any((xx, yy) in blocked
                   for yy in range(y, y + h) for xx in range(x, x + w))


def find_plot(buildings, w, h, rng=None):
    """An empty rectangle with a pavement margin, clear of roads, water and everything
    already built. Returns (x, y, district) or None."""
    blocked = blocked_cells(buildings)

    # Collect every valid plot rather than returning the first one found. Scanning top-left
    # to bottom-right and taking the first hit put four consecutive new buildings in the
    # same corner while an entire empty district sat untouched.
    found = []
    for y in range(city.RIVER_DEPTH + 2, city.H - h, 2):
        for x in range(1, city.W - w, 2):
            if any((xx, yy) in blocked
                   for yy in range(y, y + h) for xx in range(x, x + w)):
                continue
            found.append((x, y, city.district_at(y)))
    if not found:
        return None

    # Prefer wherever the city is thinnest, so it spreads into open ground instead of
    # thickening one corner. That is what makes growth legible from the map.
    density = {}
    for b in buildings:
        density[b["district"]] = density.get(b["district"], 0) + 1
    rng = rng or random
    thin = min(density.get(d, 0) for (_x, _y, d) in found)
    best = [p for p in found if density.get(p[2], 0) <= thin + 1]
    return rng.choice(best or found)


def maybe_expand(world, agents, buildings, beat, day):
    """The city grows when it is under pressure to: more people than homes can hold, or a
    long stretch with nothing built. Growth is slow — one building at a time."""
    rng = _rng(world, beat, "expand")
    living = [a for a in agents.values() if a.get("alive", True)]
    homes = [b for b in buildings if b["kind"] == "home" and b["condition"] in city.USABLE]
    crowded = homes and len(living) / max(1, len(homes)) > 3.2

    # Once per city-day, not once per beat — this used to roll four times a day and the
    # city grew a new building roughly every eight city-hours.
    if beat % 4 != 0:
        return []
    # The map used to be full, so growth was throttled hard to stop it thrashing against
    # nowhere to build. There is open ground to the south and east now, and watching the
    # city actually spread onto it is the point — roughly a new building every couple of
    # real hours, which is a visible skyline change inside a single sitting.
    last = world.get("last_expansion_day", -999)
    overdue = day - last >= 18
    if not (crowded or overdue) or rng.random() > 0.35:
        return []

    # Crowding pushes towards housing, but not exclusively — a district of nothing but
    # tenements is not a city growing, it is a car park with beds in it.
    pool = EXPANSIONS
    if crowded and rng.random() < 0.6:
        pool = [e for e in EXPANSIONS if e[0] == "home"]
    kind, style, name_t, w, h, floors = rng.choice(pool)
    plot = find_plot(buildings, w, h, rng)
    if not plot:
        return []
    x, y, district = plot
    name = name_t.format(street=rng.choice(STREET_NAMES))
    bid = f"new_{kind}_{day}"
    if any(b["id"] == bid for b in buildings):
        return []

    door = "N" if district == "civic" else "S"
    buildings.append(city._b(bid, name, district, x, y, w, h, door, kind, style,
                             floors=floors))
    buildings[-1]["since_day"] = day
    world["last_expansion_day"] = day
    return [{"kind": "structure", "event": "built", "building": bid, "name": name,
             "district": district, "day": day, "beat": beat,
             "text": f"{name} opens on what was empty ground in "
                     f'{city.DISTRICTS[district]["name"]}.'}]


# ── people caught in it ──────────────────────────────────────────────────────

def displace(agents, buildings, bid, day):
    """Anyone who lived, worked or was standing in a lost building has to go somewhere.

    Without this a ruined home leaves people permanently routed to a location they can no
    longer enter, and the pathing quietly sends them to stand in rubble forever.
    """
    live = [b["id"] for b in buildings
            if b["kind"] == "home" and b["condition"] in city.USABLE and b["id"] != bid]
    work = [b["id"] for b in buildings
            if b["kind"] in ("business", "social", "industrial")
            and b["condition"] in city.USABLE and b["id"] != bid]
    out = []
    rng = random.Random(f"displace:{bid}:{day}")
    for a in agents.values():
        moved = []
        if a.get("home") == bid and live:
            a["home"] = rng.choice(live)
            moved.append("home")
        if a.get("work") == bid and work:
            a["work"] = rng.choice(work)
            moved.append("work")
        routine = a.get("routine") or {}
        for slot, loc in list(routine.items()):
            if loc == bid:
                routine[slot] = a["home"] if slot == "night" else (a.get("work") or a["home"])
        if moved:
            out.append({"who": a["id"], "name": a["name"], "lost": moved})
    return out
