"""
The Cut — people can be lost.

A cast that cannot die has no stakes: every threat is theatre, every debt is survivable, and
the audience learns within a week that nothing said in this city is ever true. Death is what
makes the rest of the simulation mean something.

Three rules shape everything here.

**Death is rare and earned.** Thirty people losing somebody every week is not a drama, it is
a massacre. The per-beat chance is tiny and is driven by things the city already tracks —
age, sustained stress and fear, the heat on the district, whether a building came down on
top of somebody. So when it happens there is a reason sitting in the log.

**The reaction is the point, not the death.** The moment somebody dies, everybody who knew
them gets a high-importance memory and a mood hit scaled by how they actually felt about
them — including the people who are quietly relieved, because a relationship at -80 should
not produce grief. Grief then *persists*: `grief` decays over days and is shown in the
prompt, so a character reads as bereaved for a week rather than for one beat.

**The city does not empty.** People arrive. New residents are generated procedurally rather
than by the model — the token budget is fully committed to cognition — but they arrive with
a name, a trade and a temperament, and everything that makes them a person after that
(memories, beliefs, relationships) is earned in play exactly like everyone else's.
"""

import random

from . import city, memory

# Per beat, per person, and there are ~30 people and 96 beats in a real day — so these
# numbers compound about 2,900x faster than they read. The first set killed five people in
# thirty city-days, which is not a drama, it is a plague. Calibrated so a death lands
# roughly every three real days — often enough that the grief system is visible to
# somebody checking in daily, rare enough that it still lands — with stress and district
# heat doing most of the moving.
BASE_DEATH = 0.000045
AGE_FACTOR = 0.0000040       # per year over 40
STRESS_FACTOR = 0.0000075    # per point of stress over 70
HEAT_FACTOR = 0.0000032      # per point of district heat
FRAIL_HEALTH = 35            # below this, health itself starts killing people

GRIEF_DECAY = 3              # per city-day
FUNERAL_DELAY = 2            # city-days between a death and the funeral

NATURAL = [
    ("heart", "{name} dies at {place}. It is quick, and it is nobody's fault."),
    ("illness", "{name} does not get up. The clinic says it had been coming for a while."),
]
VIOLENT = [
    ("violence", "{name} is found at {place}. The 9th are calling it suspicious."),
    ("violence", "{name} is killed at {place}. Everybody has a theory by morning."),
    ("overdose", "{name} is found at {place}. There is a needle and there is no note."),
]
ACCIDENT = [
    ("accident", "{name} is pulled out of {place}. Too late."),
]

# New arrivals. Procedural, but not anonymous.
FIRST = ["Nia", "Cal", "Rosa", "Tomas", "Iris", "Dev", "Marta", "Errol", "June", "Sami",
         "Blaise", "Odette", "Kwame", "Lena", "Vic", "Ade", "Farrah", "Gil"]
LAST = ["Mbeki", "Doyle", "Serrano", "Kowal", "Amadi", "Petrakis", "Lindqvist", "Brannon",
        "Osei", "Ferreira", "Nakamura", "Bright"]
TRADES = [
    ("keeps books for people who cannot", "business", ["precise", "incurious by choice"]),
    ("drives nights for a car service", "business", ["watchful", "tired"]),
    ("works the line at the cannery", "industrial", ["steady", "slow to anger"]),
    ("cuts and sets hair out of a back room", "social", ["talkative", "sharp-eyed"]),
    ("does agency shifts at the clinic", "civic", ["kind", "unsentimental about bodies"]),
    ("fixes what other people throw out", "business", ["resourceful", "proud"]),
    ("preaches to whoever turns up", "civic", ["certain", "lonely"]),
]
AMBITIONS = [
    "keep my head down long enough to be left alone",
    "be somebody on this block inside a year",
    "get my family out of here",
    "find out what happened to my brother",
    "own the room I work in",
]
FEARS = [
    "that I have already missed my chance",
    "that people can tell what I did before I came here",
    "that I will die owing somebody",
]


def _rng(world, beat, salt):
    return random.Random(f'{world.get("seed", 0)}:{beat}:{salt}')


def living(agents):
    return {aid: a for aid, a in agents.items() if a.get("alive", True)}


def ensure_fields(agents):
    """Older saves predate mortality entirely; give everybody a life to lose."""
    for a in agents.values():
        a.setdefault("alive", True)
        a.setdefault("health", 80)
        a.setdefault("grief", 0)


# ── dying ────────────────────────────────────────────────────────────────────

def _risk(a, world):
    if not a.get("alive", True):
        return 0.0
    mood = a.get("mood") or {}
    risk = BASE_DEATH
    risk += max(0, a.get("age", 30) - 40) * AGE_FACTOR
    risk += max(0, mood.get("stress", 0) - 70) * STRESS_FACTOR
    heat = (world.get("heat") or {}).get(city.district_at(a.get("pos", [0, 0])[1]), 0)
    risk += heat * HEAT_FACTOR
    if a.get("health", 80) < FRAIL_HEALTH:
        risk *= 2.5
    return risk


def roll_death(world, agents, beat, day):
    """At most one death per beat. Returns a record, or None."""
    rng = _rng(world, beat, "death")
    alive = list(living(agents).values())
    if len(alive) <= 8:          # never let the block empty out entirely
        return None

    for a in alive:
        if rng.random() >= _risk(a, world):
            continue
        heat = (world.get("heat") or {}).get(city.district_at(a.get("pos", [0, 0])[1]), 0)
        table = VIOLENT if (heat > 45 and rng.random() < 0.6) else NATURAL
        return kill(world, agents, a, rng.choice(table), beat, day, rng)
    return None


def kill(world, agents, a, entry, beat, day, rng=None, place=None):
    """Take somebody out of the city, and put them into everybody else's head."""
    rng = rng or random.Random(f'{a["id"]}:{day}')
    cause, tmpl = entry
    where = place or city.LOCATIONS.get(a.get("at"), {}).get("name", "the block")

    a["alive"] = False
    a["died_day"] = day
    a["died_beat"] = beat
    a["cause"] = cause
    a["action"] = "is gone"
    a["speech"] = None

    text = tmpl.format(name=a["name"], place=where)
    world.setdefault("dead", []).insert(0, {
        "id": a["id"], "name": a["name"], "day": day, "cause": cause, "where": where})
    world["funeral"] = {"day": day + FUNERAL_DELAY, "for": a["name"], "id": a["id"]}

    mourned = grieve(agents, a, beat, day)
    return {"kind": "death", "who": a["id"], "name": a["name"], "cause": cause,
            "where": where, "text": text, "day": day, "beat": beat, "mourned_by": mourned}


def grieve(agents, dead, beat, day):
    """Everybody who knew them reacts — in the direction they actually felt.

    Scaling by affinity matters more than it looks: a city where all thirty people mourn
    identically reads as a chorus, not a cast. Somebody who hated the deceased gets relief
    and a little fear, which is far more interesting than sadness applied evenly.
    """
    out = []
    for a in agents.values():
        if a["id"] == dead["id"] or not a.get("alive", True):
            continue
        rel = (a.get("relationships") or {}).get(dead["id"])
        aff = (rel or {}).get("affinity", 0)
        knew = rel is not None or a.get("faction") == dead.get("faction")
        if not knew and abs(aff) < 10:
            # Still a death on your block. Everyone feels the temperature drop.
            _mood(a, happiness=-3, stress=+4, fear=+5)
            memory.remember(a, beat, day, f'{dead["name"]} died. I barely knew them.', 5)
            continue

        if aff >= 40:
            _mood(a, happiness=-28, stress=+22, fear=+12, energy=-10)
            a["grief"] = max(a.get("grief", 0), 60 + aff // 4)
            what = f'{dead["name"]} is dead. I do not know what to do with that.'
        elif aff >= 0:
            _mood(a, happiness=-14, stress=+12, fear=+9)
            a["grief"] = max(a.get("grief", 0), 30)
            what = f'{dead["name"]} is dead.'
        else:
            # Relief, and the fear that comes with getting what you wanted.
            _mood(a, happiness=+4, stress=+8, fear=+14)
            a["grief"] = max(a.get("grief", 0), 10)
            what = f'{dead["name"]} is dead. I am not sorry, and that frightens me.'

        memory.remember(a, beat, day, what, 9)
        memory.prune(a)
        out.append(a["id"])
    return out


def _mood(a, **deltas):
    m = a.setdefault("mood", {})
    for k, v in deltas.items():
        m[k] = max(0, min(100, m.get(k, 50) + v))


def decay_grief(agents):
    """Called once per city-day. Grief has to fade or the whole cast is permanently flat."""
    for a in agents.values():
        if a.get("grief"):
            a["grief"] = max(0, a["grief"] - GRIEF_DECAY)


def funeral_today(world, day):
    f = world.get("funeral")
    return f if f and f.get("day") == day else None


# ── arriving ─────────────────────────────────────────────────────────────────

def maybe_arrival(world, agents, buildings, beat, day):
    """Somebody moves onto the block. The city loses people; it has to gain them too."""
    rng = _rng(world, beat, "arrival")
    alive = living(agents)
    homes = [b for b in buildings if b["kind"] == "home" and b["condition"] in city.USABLE]
    if beat % 4 != 0 or not homes or len(alive) >= 34 or rng.random() > 0.06:
        return None
    # Only when there is actually room, or the block has thinned out.
    if len(alive) / max(1, len(homes)) > 3.0 and len(alive) > 24:
        return None

    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    aid = _free_id(agents, name)
    trade, workkind, traits = rng.choice(TRADES)
    home = rng.choice(homes)["id"]
    work = next((b["id"] for b in rng.sample(buildings, len(buildings))
                 if b["kind"] == workkind and b["condition"] in city.USABLE), home)
    anchor = city.LOCATIONS[home]["anchor"]

    agents[aid] = {
        "id": aid, "name": name, "age": rng.randint(19, 58), "role": trade,
        "faction": "civilian", "home": home, "work": work, "principal": False,
        "traits": list(traits), "ambition": rng.choice(AMBITIONS),
        "private_fear": rng.choice(FEARS),
        "voice": "still working out how people here talk",
        "routine": {"morning": work, "afternoon": work, "evening": home, "night": home},
        "pos": list(anchor), "dest": list(anchor), "at": home, "spot": list(anchor),
        "mood": {"energy": 70, "happiness": 52, "stress": 35, "social_need": 60, "fear": 25},
        "relationships": {}, "memories": [], "belief": "",
        "alive": True, "health": 82, "grief": 0,
        "arrived_day": day, "last_thought_beat": 0,
    }
    memory.remember(agents[aid], beat, day, f"I moved onto this block today.", 7)
    return {"kind": "arrival", "who": aid, "name": name, "day": day, "beat": beat,
            "text": f'{name} moves into {city.LOCATIONS[home]["name"]}. Nobody knows them yet.'}


def _free_id(agents, name):
    base = name.split()[0].lower()
    aid, n = base, 2
    while aid in agents:
        aid, n = f"{base}{n}", n + 1
    return aid
