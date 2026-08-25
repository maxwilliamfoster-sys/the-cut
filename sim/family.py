"""
The Cut — people pairing off, children, and growing up.

Until now the only way the population changed was somebody dying or a stranger arriving. A
city you are meant to govern for months needs to renew itself from the inside: people who
like each other enough pair off, have children, and those children grow into the workforce
and take jobs the city built for them.

Children are **not** generic. They inherit a surname, a home, a blend of both parents'
temperament and volatility, and then accumulate their own memories and opinions from the day
they are born — which is what stops the second generation reading as filler.

Ageing is deliberately quicker than life: a city-year is twenty city-days, so a child born
today is working within about a fortnight of real time. Slow enough that growing up means
something, fast enough that a player sees it happen.

Free — no model calls.
"""

import random

from . import city, memory

CITY_DAYS_PER_YEAR = 20

PAIR_AT = 55                  # mutual affinity before anybody calls it anything
MIN_PARTNER_AGE = 18
MAX_BIRTH_AGE = 44
BIRTH_CHANCE = 0.09           # per couple per city-day, before modifiers
# Was 60. Attention is rationed per beat rather than per head, so the cast can be a town
# rather than a street without the prompt growing at all.
MAX_POPULATION = 220

CHILD_TRAITS = [
    "watchful", "loud about everything", "easily delighted", "solemn for their age",
    "always somewhere they should not be", "shy with strangers", "quick with numbers",
    "forever asking why", "gentle with animals", "stubborn as anything",
]
CHILD_WANTS = [
    "to be taken seriously by the grown-ups",
    "to be allowed further down the block than they are",
    "to be good at something nobody else here is",
    "to make their mother proud",
]


def ensure(world, agents):
    world.setdefault("births", [])
    for a in agents.values():
        a.setdefault("partner", None)
        a.setdefault("parents", [])
        a.setdefault("children", [])
        a.setdefault("birth_day", None)


def _related(a, b):
    """Parent, child or sibling. The cast is small and everybody knows everybody, so this
    check is doing real work rather than being defensive."""
    if b["id"] in a.get("children", []) or a["id"] in b.get("children", []):
        return True
    if b["id"] in a.get("parents", []) or a["id"] in b.get("parents", []):
        return True
    return bool(set(a.get("parents") or []) & set(b.get("parents") or []))


def _adults(agents):
    return [a for a in agents.values()
            if a.get("alive", True) and a.get("age", 0) >= MIN_PARTNER_AGE]


def form_couples(world, agents, day):
    """Two people who have grown to like each other a great deal stop being just friends."""
    ensure(world, agents)
    out = []
    for a in _adults(agents):
        if a.get("partner"):
            continue
        best, score = None, PAIR_AT
        for bid, rel in (a.get("relationships") or {}).items():
            b = agents.get(bid)
            if not b or not b.get("alive", True) or b.get("partner"):
                continue
            if b.get("age", 0) < MIN_PARTNER_AGE or _related(a, b):
                continue
            mutual = (b.get("relationships") or {}).get(a["id"], {}).get("affinity", 0)
            if rel.get("affinity", 0) >= PAIR_AT and mutual >= PAIR_AT:
                total = rel["affinity"] + mutual
                if total > score:
                    best, score = b, total
        if best:
            a["partner"], best["partner"] = best["id"], a["id"]
            for x, y in ((a, best), (best, a)):
                memory.remember(x, day * 4, day,
                                f'{y["name"]} and I are together now.', 9)
                memory.prune(x)
                x["mood"]["happiness"] = min(100, x["mood"].get("happiness", 50) + 18)
                x["mood"]["social_need"] = max(0, x["mood"].get("social_need", 40) - 30)
            out.append({"kind": "couple", "day": day, "who": a["id"], "with": best["id"],
                        "text": f'{a["name"]} and {best["name"]} are together.'})
    return out


def births(world, agents, day, beat, rng=None):
    """Children, to couples who have somewhere to put them."""
    ensure(world, agents)
    rng = rng or random.Random(f'births:{day}')
    living = [a for a in agents.values() if a.get("alive", True)]
    if len(living) >= MAX_POPULATION:
        return []

    homes = [b for b in world.get("buildings", [])
             if b["kind"] == "home" and b.get("condition") in ("standing", "damaged")]
    if not homes:
        return []
    # No room at home, no babies. This is the lever a player pulls by building housing.
    crowding = len(living) / max(1, len(homes) * 3)
    if crowding > 1.0 and rng.random() > 0.25:
        return []

    out = []
    seen = set()
    for a in living:
        pid = a.get("partner")
        if not pid or pid in seen or a["id"] in seen:
            continue
        b = agents.get(pid)
        if not b or not b.get("alive", True):
            continue
        seen.add(a["id"])
        seen.add(pid)
        if min(a.get("age", 99), b.get("age", 99)) > MAX_BIRTH_AGE:
            continue
        # Misery is contraceptive. A frightened, exhausted couple do not start a family.
        mood = (a["mood"].get("happiness", 50) + b["mood"].get("happiness", 50)) / 2
        chance = BIRTH_CHANCE * (0.4 + mood / 100.0)
        if rng.random() > chance:
            continue
        out.append(_born(world, agents, a, b, day, beat, rng))
    return [o for o in out if o]


def _born(world, agents, a, b, day, beat, rng):
    mother = a if a.get("age", 30) <= b.get("age", 30) else b
    surname = mother["name"].split()[-1]
    first = rng.choice([
        "Nyla", "Theo", "Maren", "Isaac", "Poppy", "Elias", "Sadie", "Rufus",
        "Clemmie", "Otis", "Wren", "Milo", "Ada", "Jonah", "Etta", "Cassius"])
    aid = _free_id(agents, first)
    home = mother.get("home")
    anchor = city.LOCATIONS.get(home, {}).get("anchor") or [10, 10]

    # Temperament from both parents, plus a wobble so siblings are not clones.
    vol = int((a.get("volatility", 45) + b.get("volatility", 45)) / 2
              + rng.randint(-14, 14))
    agents[aid] = {
        "id": aid, "name": f"{first} {surname}", "age": 0,
        "role": "a child of the block", "faction": mother.get("faction", "block"),
        "home": home, "work": home, "principal": False,
        "traits": rng.sample(CHILD_TRAITS, 2),
        "ambition": rng.choice(CHILD_WANTS),
        "private_fear": "that something is going on that nobody will explain",
        "voice": "still learning how people here talk",
        "routine": {k: home for k in ("morning", "afternoon", "evening", "night")},
        "pos": list(anchor), "dest": list(anchor), "at": home, "spot": list(anchor),
        "mood": {"energy": 85, "happiness": 70, "stress": 10, "social_need": 55, "fear": 15},
        "relationships": {
            a["id"]: {"affinity": 85, "opinion": "my parent"},
            b["id"]: {"affinity": 85, "opinion": "my parent"},
        },
        "memories": [], "belief": "", "alive": True, "health": 90, "grief": 0,
        "volatility": max(5, min(95, vol)), "vehicle": None,
        "money": 0, "skill": 0, "job": None,
        "parents": [a["id"], b["id"]], "children": [], "partner": None,
        "birth_day": day, "arrived_day": day, "last_thought_beat": 0,
    }
    for p in (a, b):
        p.setdefault("children", []).append(aid)
        p.setdefault("relationships", {})[aid] = {"affinity": 95, "opinion": "my child"}
        p["mood"]["happiness"] = min(100, p["mood"].get("happiness", 50) + 22)
        memory.remember(p, beat, day, f'{first} was born.', 10)
        memory.prune(p)

    world.setdefault("births", []).insert(0, {"id": aid, "name": agents[aid]["name"],
                                              "day": day, "parents": [a["id"], b["id"]]})
    return {"kind": "birth", "day": day, "beat": beat, "who": aid,
            "name": agents[aid]["name"], "parents": [a["id"], b["id"]],
            "text": f'{agents[aid]["name"]} is born to {a["name"]} and {b["name"]}.'}


def _free_id(agents, first):
    base, aid, n = first.lower(), first.lower(), 2
    while aid in agents:
        aid, n = f"{base}{n}", n + 1
    return aid


def age_everyone(world, agents, day):
    """A birthday every twenty city-days. Returns records for anybody who crossed a line."""
    ensure(world, agents)
    if day % CITY_DAYS_PER_YEAR:
        return []
    out = []
    for a in agents.values():
        if not a.get("alive", True):
            continue
        a["age"] = a.get("age", 30) + 1
        # Growing up is a real event: they stop being a child of the block and become
        # somebody the job market and the narration take seriously.
        if a["age"] == 16 and a.get("birth_day") is not None:
            a["role"] = "old enough to work, and looking"
            a["routine"]["morning"] = a["routine"]["afternoon"] = a.get("home")
            out.append({"kind": "cameofage", "day": day, "who": a["id"], "name": a["name"],
                        "text": f'{a["name"]} is sixteen and looking for work.'})
        elif a["age"] == 68:
            out.append({"kind": "retired", "day": day, "who": a["id"], "name": a["name"],
                        "text": f'{a["name"]} finishes work for the last time.'})
            a["job"] = None
    return out
