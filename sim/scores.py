"""
The Cut — how well the city is actually doing.

Five numbers and one that sums them up. Every one is **derived from state the simulation
already keeps** — no score is stored, incremented or awarded. That constraint is the whole
design: it means a score cannot be gamed except by changing the thing it measures, and it
means a number moving is always traceable to something that happened on the map.

    ECONOMY        who is in work, what the treasury is doing, how much trade there is
    WELLBEING      the mood of the people, grief, health, how many are grieving
    SOCIETY        feuds, crime, police attention, whether people like each other
    INFRASTRUCTURE what is standing, whether there are enough homes and civic buildings
    GROWTH         population and building trend over the last stretch

The composite is a weighted mean, and it is deliberately hard to max: a city with a full
treasury and a miserable, feuding population scores badly, which is the point.

Free — arithmetic over state that already exists.
"""

from . import economy

WEIGHTS = {"economy": 0.24, "wellbeing": 0.26, "society": 0.22,
           "infrastructure": 0.16, "growth": 0.12}

HISTORY = 48          # city-days of score history kept for the trend line


def _clamp(v):
    return max(0, min(100, int(round(v))))


def _living(agents):
    return [a for a in agents.values() if a.get("alive", True)]


def economy_score(world, agents):
    people = _living(agents)
    if not people:
        return 0
    employed = economy.employment_rate(agents) * 100

    # Treasury is scored on how many days of running costs it covers, not its raw size —
    # a big number means nothing without knowing what the city spends.
    ledger = world.get("ledger") or []
    outgoings = max(1, sum(abs(e.get("welfare", 0)) + abs(e.get("civic", 0))
                           for e in ledger[:7]) / max(1, len(ledger[:7])))
    runway = min(1.0, (world.get("treasury", 0) / outgoings) / 40.0) * 100

    trade = [b for b in world.get("buildings", [])
             if b["kind"] in ("business", "social", "industrial")
             and b.get("condition") in ("standing", "damaged")]
    density = min(1.0, (len(trade) / max(1, len(people))) / 0.45) * 100

    return _clamp(employed * 0.5 + runway * 0.3 + density * 0.2)


def wellbeing_score(world, agents):
    people = _living(agents)
    if not people:
        return 0
    n = len(people)
    happy = sum(a["mood"].get("happiness", 50) for a in people) / n
    stress = sum(a["mood"].get("stress", 30) for a in people) / n
    fear = sum(a["mood"].get("fear", 20) for a in people) / n
    lonely = sum(a["mood"].get("social_need", 40) for a in people) / n
    health = sum(a.get("health", 80) for a in people) / n
    grieving = sum(1 for a in people if a.get("grief", 0) >= 15) / n * 100

    return _clamp(happy * 0.30 + (100 - stress) * 0.22 + (100 - fear) * 0.18
                  + (100 - lonely) * 0.10 + health * 0.15 - grieving * 0.15)


def society_score(world, agents):
    people = _living(agents)
    if not people:
        return 0
    n = len(people)

    # How people actually feel about each other, averaged over every opinion held.
    ties = [v.get("affinity", 0) for a in people for v in (a.get("relationships") or {}).values()]
    warmth = ((sum(ties) / len(ties)) + 100) / 2 if ties else 50

    feuds = len(world.get("feuds") or [])
    open_charges = sum(1 for c in world.get("charges", []) if c.get("status") == "awaiting_trial")
    heat = sum((world.get("heat") or {}).values()) / max(1, len(world.get("heat") or {1: 1}))
    recent_violence = sum(1 for d in (world.get("dead") or [])[:6]
                          if d.get("cause") == "violence")

    return _clamp(warmth * 0.5 + (100 - heat) * 0.25
                  - (feuds / n * 100) * 0.8
                  - open_charges * 4
                  - recent_violence * 5)


def infrastructure_score(world, agents):
    buildings = world.get("buildings") or []
    if not buildings:
        return 0
    people = _living(agents)
    standing = [b for b in buildings if b.get("condition") == "standing"]
    broken = [b for b in buildings if b.get("condition") in ("ruin", "rebuilding", "damaged")]
    upkeep = len(standing) / len(buildings) * 100

    homes = [b for b in standing if b["kind"] == "home"]
    # Roughly three to a household before it counts as crowded.
    housing = min(1.0, (len(homes) * 3) / max(1, len(people))) * 100
    civic = min(1.0, len([b for b in standing if b["kind"] == "civic"]) / 6.0) * 100

    return _clamp(upkeep * 0.4 + housing * 0.4 + civic * 0.2 - len(broken) * 2)


def growth_score(world, agents):
    hist = world.get("score_history") or []
    people = len(_living(agents))
    buildings = len([b for b in world.get("buildings", [])
                     if b.get("condition") == "standing"])
    if len(hist) < 4:
        return 50                     # not enough history to judge a trend yet
    then = hist[-min(len(hist), 24)]
    dp = people - then.get("population", people)
    db = buildings - then.get("buildings", buildings)
    # A city that is standing still sits at 50; shrinking drops below it.
    return _clamp(50 + dp * 6 + db * 5)


def snapshot(world, agents, day):
    """Every score, plus the composite. Pure — call it as often as you like."""
    parts = {
        "economy": economy_score(world, agents),
        "wellbeing": wellbeing_score(world, agents),
        "society": society_score(world, agents),
        "infrastructure": infrastructure_score(world, agents),
        "growth": growth_score(world, agents),
    }
    overall = _clamp(sum(parts[k] * WEIGHTS[k] for k in WEIGHTS))
    return {
        "day": day, "overall": overall, **parts,
        "population": len(_living(agents)),
        "buildings": len([b for b in world.get("buildings", [])
                          if b.get("condition") == "standing"]),
        "treasury": int(world.get("treasury", 0)),
        "employment": round(economy.employment_rate(agents) * 100),
    }


def record(world, agents, day):
    """Take a reading once a city-day and keep it for the trend."""
    snap = snapshot(world, agents, day)
    hist = world.setdefault("score_history", [])
    if hist and hist[-1].get("day") == day:
        hist[-1] = snap
    else:
        hist.append(snap)
    del hist[:-HISTORY]
    world["scores"] = snap
    return snap


def grade(overall):
    """A word for the number, because 63 means nothing on its own."""
    for cutoff, word in ((85, "thriving"), (70, "doing well"), (55, "getting by"),
                         (40, "struggling"), (25, "in trouble")):
        if overall >= cutoff:
            return word
    return "failing"
