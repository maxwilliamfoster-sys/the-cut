"""
The Cut — things you can stand and watch.

Everything dramatic in this city used to resolve inside a single beat and leave nothing but
a line of text. Somebody was put against a wall, somebody died, the 9th kicked a door — and
on the map it all looked identical to a quiet afternoon. The drama was real and completely
invisible.

An incident is a dramatic event given a **place and a duration**, so the browser has
something to draw and somebody looking at the city has something to catch. A beat is fifteen
real minutes, so a two-beat fight is half an hour of watchable trouble on a street corner.

Nothing here decides anything. Incidents are opened by the systems that already exist —
drama, mortality, law, construction — and this module only remembers where they are and how
long they last. It costs no tokens at all.

Deliberately not graphic. A fight is a scuffle of shapes; a shooting is flashes and people
scattering. The register is a police report seen from across the street, not a set piece.
"""

# How long each kind stays on the map, in beats (a beat is 15 real minutes).
DURATION = {
    "row":      1,
    "fight":    2,
    "shooting": 2,
    "raid":     2,
    "arrest":   1,
    "fire":     3,
    "vigil":    2,
    "works":    1,      # refreshed every beat while a site is active
    "opening":  2,      # a new building's first day
}

# What the renderer should draw. Kept here rather than in the browser so the simulation
# stays the single source of truth about what is happening and where.
EFFECT = {
    "row":      "row",
    "fight":    "scuffle",
    "shooting": "flashes",
    "raid":     "lights",
    "arrest":   "lights",
    "fire":     "flames",
    "vigil":    "crowd",
    "works":    "works",
    "opening":  "opening",
}

MAX_LIVE = 12          # more than this on screen at once is noise, not drama


def ensure(world):
    world.setdefault("incidents", [])


def open_incident(world, kind, beat, where=None, who=(), text="", pos=None):
    """Put something on the map for a while. Returns the incident, or None if unplaceable."""
    from . import city
    ensure(world)

    if pos is None:
        loc = city.LOCATIONS.get(where or "")
        if not loc:
            return None
        pos = loc["anchor"]

    inc = {
        "id": f"inc{beat}-{kind}-{len(world['incidents'])}",
        "kind": kind, "effect": EFFECT.get(kind, "scuffle"),
        "at": where, "x": int(pos[0]), "y": int(pos[1]),
        "who": [w for w in who][:4],
        "text": text[:160],
        "started": beat, "until": beat + DURATION.get(kind, 1),
    }
    # Newest first, and hard-capped: a busy night should read as a busy night, not as a
    # screen of overlapping effects with nothing legible in it.
    world["incidents"] = ([inc] + world["incidents"])[:MAX_LIVE]
    return inc


def expire(world, beat):
    """Drop anything whose time is up. Called once a beat."""
    ensure(world)
    world["incidents"] = [i for i in world["incidents"] if i.get("until", 0) > beat]
    return world["incidents"]


def live(world, beat):
    return [i for i in world.get("incidents", []) if i.get("until", 0) > beat]


def from_records(world, agents, records, beat):
    """Turn this beat's events into things visible on the street.

    One place that knows which record kinds deserve to be seen, rather than every system
    growing its own opinion about the renderer.
    """
    from . import city
    ensure(world)
    made = []
    for r in records:
        kind = r.get("kind")

        if kind == "confrontation" and r.get("outcome") in ("violent", "refused"):
            # A flat refusal in front of people is a scene worth seeing too, and there are
            # far more of those than there are beatings — which is as it should be.
            violent = r.get("outcome") == "violent"
            creditor = agents.get(r.get("creditor")) or {}
            # Somebody volatile enough turns a debt collection into shots fired. Rare, and
            # it has to be earned by who is doing the collecting.
            shots = violent and creditor.get("volatility", 45) >= 78
            made.append(open_incident(
                world, "shooting" if shots else "fight" if violent else "row", beat,
                where=_at(agents, r.get("creditor"), r.get("debtor")),
                who=[r.get("creditor"), r.get("debtor")], text=r.get("text", "")))

        elif kind == "death" and r.get("cause") == "violence":
            made.append(open_incident(
                world, "shooting", beat, where=_at(agents, r.get("who")),
                who=[r.get("who")], text=r.get("text", "")))

        elif kind == "charge":
            made.append(open_incident(
                world, "arrest", beat, where="precinct",
                who=[r.get("who")], text=r.get("text", "")))

        elif kind == "structure" and r.get("event") in ("destroyed", "damaged"):
            made.append(open_incident(
                world, "fire", beat, where=r.get("building"), text=r.get("text", "")))

        elif kind == "structure" and r.get("event") == "rebuilding":
            made.append(open_incident(
                world, "works", beat, where=r.get("building"), text=r.get("text", "")))

        elif kind == "structure" and r.get("event") in ("built", "rebuilt"):
            made.append(open_incident(
                world, "opening", beat, where=r.get("building"), text=r.get("text", "")))

    # An event the whole block can see, rather than one between two people.
    ev = (world.get("events") or [{}])[0]
    # Only an actual raid. patrol_surge fires roughly six times a real day, and putting
    # police lights on the map that often makes them mean nothing.
    if ev.get("id") == "raid" and ev.get("beat") == beat:
        hottest = max((world.get("heat") or {"delmar": 0}).items(), key=lambda kv: kv[1])[0]
        spot = next((l for l in city.LOCATIONS.values()
                     if l["district"] == hottest and l["kind"] == "civic"), None)
        if spot:
            made.append(open_incident(world, "raid", beat, where=spot["id"],
                                      text=ev.get("text", "")))

    # A funeral lasts a city-day, which is four beats — without this it opened a fresh
    # vigil on every one of them and the churchyard stacked up four identical crowds.
    f = world.get("funeral") or {}
    if (f.get("day") == beat // 4 and city.usable("church")
            and f.get("marked") != f.get("day")):
        f["marked"] = f["day"]
        made.append(open_incident(world, "vigil", beat, where="church",
                                  text=f'The block turns out for {f.get("for", "somebody")}.'))

    return [m for m in made if m]


def _at(agents, *ids):
    """Where the people involved actually are. The record carries names, not coordinates,
    and an earlier version tried to recover the place by looking for its name inside the
    narration — which found the wrong building whenever two were mentioned in one line."""
    for aid in ids:
        a = agents.get(aid or "")
        if a and a.get("at"):
            return a["at"]
    return None
