"""
The Cut — money, work, and what the city can afford.

The block had debts between people and nothing else: no wages, no jobs anybody could lose,
no treasury, and therefore nothing a leader could actually spend or run out of. This is the
layer that turns a simulation into something you can govern badly.

**Everything is derived from things already on the map.** A building of the right kind has
jobs in it; somebody employed there earns a wage; the city takes a cut; the treasury pays
for what gets built next. No invented numbers — if the cannery burns down, the jobs in it go
with it, the people who worked there stop earning, and the tax take falls. That chain is the
whole point, because it means a fire is an economic event and not just an orange shape.

Free, like everything else here: no model calls, just arithmetic once a city-day.
"""

import random

# Jobs a standing building of each kind supports, and what it pays a day.
EMPLOYERS = {
    "business":   (3, 46),
    "social":     (3, 38),
    "industrial": (6, 52),
    "civic":      (4, 58),
    "home":       (0, 0),
    "outdoor":    (0, 0),
}

# What a building of each kind turns over a day, before wages. Civic buildings cost money
# rather than making it — a clinic is a thing you pay for because you want it.
REVENUE = {"business": 190, "social": 150, "industrial": 260, "civic": -90,
           "home": 0, "outdoor": 0}

STARTING_TREASURY = 12_000
DEFAULT_TAX = 0.18            # share of wages and takings the city collects
MAX_TAX = 0.45

WORKING_AGE = 16
RETIREMENT_AGE = 68

SKILL_GAIN = 0.5              # per city-day in work
SKILL_DECAY = 0.2             # per city-day out of it
DOLE = 12                     # what the city pays somebody with no work, per day


# ── what somebody can be put to ──────────────────────────────────────────────
# Everyone starts as a person with a trade, not a unit. A mayor can direct somebody into a
# public role, and that role is what turns a populace into a police force, a hospital or an
# army — but it is a request, not a conscription: see sim/directives.py for who says no.
#
# `needs` is the kind of building the role has to be carried out in, so you cannot have
# nurses without a clinic or soldiers without a barracks. That is the point of the chain:
# ordering people about is only as good as what you have built for them.
ROLES = {
    "labourer": {"needs": None,      "pay": 40, "title": "labouring where they are needed"},
    "nurse":    {"needs": "civic",   "pay": 56, "title": "nursing at the clinic",
                 "health": 1.4},
    "teacher":  {"needs": "civic",   "pay": 54, "title": "teaching",
                 "skill": 0.35},
    "officer":  {"needs": "civic",   "pay": 58, "title": "on the strength of the 9th",
                 "heat": -1.6},
    "soldier":  {"needs": "civic",   "pay": 60, "title": "under arms for the city",
                 "upkeep": 22, "order": 1.1},
    "builder":  {"needs": "industrial", "pay": 52, "title": "on the works crews",
                 "build": 1},
}

FORCE_ROLES = ("officer", "soldier")


def ensure(world, agents):
    world.setdefault("treasury", STARTING_TREASURY)
    world.setdefault("tax_rate", DEFAULT_TAX)
    world.setdefault("ledger", [])
    for a in agents.values():
        a.setdefault("money", 200)
        a.setdefault("skill", 30)
        a.setdefault("job", None)


def working_age(a):
    return WORKING_AGE <= a.get("age", 30) < RETIREMENT_AGE


def jobs_at(building):
    """How many people this building can employ, and the going daily rate."""
    if building.get("condition") not in ("standing", "damaged"):
        return 0, 0                      # a burnt shell employs nobody
    n, pay = EMPLOYERS.get(building["kind"], (0, 0))
    if building.get("condition") == "damaged":
        n = max(0, n - 1)                # half open, half the work
    return n, pay


def workforce(agents):
    return [a for a in agents.values()
            if a.get("alive", True) and working_age(a) and not a.get("detained_until")]


def vacancies(world, agents):
    """Open positions by building id, after everyone currently employed is counted."""
    taken = {}
    for a in agents.values():
        j = a.get("job")
        if j and a.get("alive", True):
            taken[j["at"]] = taken.get(j["at"], 0) + 1
    out = {}
    for b in world.get("buildings", []):
        n, pay = jobs_at(b)
        free = n - taken.get(b["id"], 0)
        if free > 0:
            out[b["id"]] = (free, pay)
    return out


def match_jobs(world, agents, day, rng=None):
    """Put people into work. Returns records.

    Deliberately simple and a little unfair: the most skilled applicant gets the best-paid
    vacancy. That is what produces an underclass without anybody designing one, and an
    underclass is what makes the society score mean something.
    """
    ensure(world, agents)
    rng = rng or random.Random(f'jobs:{day}')
    out = []

    # Anybody whose employer stopped existing is out of work as of now.
    live_ids = {b["id"] for b in world.get("buildings", [])
                if b.get("condition") in ("standing", "damaged")}
    for a in agents.values():
        j = a.get("job")
        if j and j["at"] not in live_ids:
            a["job"] = None
            out.append({"kind": "job", "event": "lost", "who": a["id"], "name": a["name"],
                        "at": j["at"], "day": day,
                        "text": f'{a["name"]} is out of work — {j["title"]} is gone.'})

    seeking = [a for a in workforce(agents)
               if not a.get("job") and not a.get("role_job")]
    if not seeking:
        return out
    open_roles = vacancies(world, agents)
    if not open_roles:
        return out

    by_id = {b["id"]: b for b in world.get("buildings", [])}

    # First pass: put people back into their own trade. Without this the matcher sorted
    # everybody by skill and handed out the best-paid vacancies in order, which put the
    # detective and the man who runs the corner crew side by side on a hospital ward. What
    # somebody does is most of who they are, and the roster already says what that is.
    for a in list(seeking):
        home_job = a.get("work")
        if home_job in open_roles:
            free, pay = open_roles[home_job]
            b = by_id[home_job]
            a["job"] = {"at": home_job, "title": _own_trade(a),
                        "wage": int(pay * (0.7 + a.get("skill", 30) / 140.0)),
                        "since_day": day}
            out.append({"kind": "job", "event": "hired", "who": a["id"], "name": a["name"],
                        "at": home_job, "wage": a["job"]["wage"], "day": day,
                        "text": f'{a["name"]} is working at {b["name"]}.'})
            seeking.remove(a)
            if free - 1 > 0:
                open_roles[home_job] = (free - 1, pay)
            else:
                del open_roles[home_job]

    # Whoever is left takes what is going, best-paid to most skilled. That is what quietly
    # produces an underclass, and an underclass is what makes the society score mean
    # something.
    seeking.sort(key=lambda a: -a.get("skill", 30))
    roles = []
    for bid, (free, pay) in open_roles.items():
        roles += [(bid, pay)] * free
    roles.sort(key=lambda r: -r[1])

    for a, (bid, pay) in zip(seeking, roles):
        b = by_id[bid]
        wage = int(pay * (0.7 + a.get("skill", 30) / 140.0))
        a["job"] = {"at": bid, "title": _title(b, rng), "wage": wage, "since_day": day}
        out.append({"kind": "job", "event": "hired", "who": a["id"], "name": a["name"],
                    "at": bid, "wage": wage, "day": day,
                    "text": f'{a["name"]} starts at {b["name"]}.'})
    return out


def _own_trade(a):
    """Somebody in their own workplace does their own job, and the roster already says what
    that is in better words than a generic table can — "narcotics detective, 9th Precinct"
    beats "on the ward" for a detective standing in a police station."""
    role = (a.get("role") or "working").strip()
    return role[:1].lower() + role[1:] if role else "working"


def _title(building, rng):
    return rng.choice({
        "business":   ["behind the counter", "on the till", "stocking and lifting"],
        "social":     ["pulling pints", "waiting tables", "on the door"],
        "industrial": ["on the line", "loading", "on nights"],
        "civic":      ["on the desk", "on the ward", "in the office"],
    }.get(building["kind"], ["working"]))


def settle_day(world, agents, day):
    """Wages, takings, tax and the dole, once a city-day. Returns records."""
    ensure(world, agents)
    by_id = {b["id"]: b for b in world.get("buildings", [])}
    tax = max(0.0, min(MAX_TAX, float(world.get("tax_rate", DEFAULT_TAX))))

    wages = takings = collected = welfare = 0

    for b in world.get("buildings", []):
        if b.get("condition") in ("standing", "damaged"):
            rev = REVENUE.get(b["kind"], 0)
            if b.get("condition") == "damaged":
                rev = int(rev * 0.5)
            takings += rev

    for a in agents.values():
        if not a.get("alive", True):
            continue
        job = a.get("job")
        if job and job["at"] in by_id:
            pay = job["wage"]
            a["money"] = a.get("money", 0) + int(pay * (1 - tax))
            collected += int(pay * tax)
            wages += pay
            a["skill"] = min(100, a.get("skill", 30) + SKILL_GAIN)
            # Work is most of what stops somebody unravelling.
            a["mood"]["stress"] = max(0, a["mood"].get("stress", 30) - 1)
        elif working_age(a):
            a["money"] = a.get("money", 0) + DOLE
            welfare += DOLE
            a["skill"] = max(0, a.get("skill", 30) - SKILL_DECAY)
            a["mood"]["stress"] = min(100, a["mood"].get("stress", 30) + 2)
            a["mood"]["happiness"] = max(0, a["mood"].get("happiness", 50) - 1)

    # The city's cut of trade, minus what it pays out.
    trade_tax = int(max(0, takings) * tax)
    civic_cost = -sum(REVENUE.get(b["kind"], 0) for b in world.get("buildings", [])
                      if b["kind"] == "civic" and b.get("condition") in ("standing", "damaged"))
    net = collected + trade_tax - welfare - civic_cost
    world["treasury"] = int(world.get("treasury", 0) + net)

    entry = {"day": day, "wages": wages, "takings": takings, "tax": collected + trade_tax,
             "welfare": welfare, "civic": civic_cost, "net": net,
             "treasury": world["treasury"]}
    world["ledger"] = ([entry] + world.get("ledger", []))[:30]
    return [{"kind": "economy", "day": day, "text":
             f'Day {day}: the city took ${collected + trade_tax:,} and spent '
             f'${welfare + civic_cost:,}. Treasury ${world["treasury"]:,}.', **entry}]


def assign_role(world, agents, aid, role, day):
    """Put somebody into a public role, if the city has anywhere to put them."""
    spec = ROLES.get(role)
    a = agents.get(aid)
    if not spec or not a or not a.get("alive", True):
        return None
    if not working_age(a):
        return {"kind": "role", "ok": False, "who": aid, "name": a["name"], "day": day,
                "text": f'{a["name"]} is not old enough to be a {role}.'}

    where = None
    if spec["needs"]:
        options = [b for b in world.get("buildings", [])
                   if b["kind"] == spec["needs"] and b.get("condition") in ("standing", "damaged")]
        if not options:
            return {"kind": "role", "ok": False, "who": aid, "name": a["name"], "day": day,
                    "text": f'There is nowhere for a {role} to work — build a '
                            f'{spec["needs"]} building first.'}
        where = min(options, key=lambda b: abs(b["x"] - a["pos"][0])
                    + abs(b["y"] - a["pos"][1]))["id"]

    a["role_job"] = role
    a["work"] = where or a.get("work")
    a["job"] = {"at": where or a.get("work"), "title": spec["title"],
                "wage": int(spec["pay"] * (0.7 + a.get("skill", 30) / 140.0)),
                "since_day": day, "role": role}
    return {"kind": "role", "ok": True, "who": aid, "name": a["name"], "role": role,
            "day": day, "text": f'{a["name"]} is now {spec["title"]}.'}


def forces(agents):
    """How many people the city currently has under each public role."""
    out = {}
    for a in agents.values():
        if not a.get("alive", True):
            continue
        r = (a.get("job") or {}).get("role") or a.get("role_job")
        if r:
            out[r] = out.get(r, 0) + 1
    return out


def apply_roles(world, agents, day):
    """What having a police force, a hospital or an army actually does. Once a city-day."""
    f = forces(agents)
    notes = []

    officers = f.get("officer", 0)
    if officers:
        drop = int(officers * abs(ROLES["officer"]["heat"]))
        for d in world.get("heat", {}):
            world["heat"][d] = max(0, world["heat"][d] - drop)
        notes.append(f"{officers} on the strength")

    soldiers = f.get("soldier", 0)
    if soldiers:
        # An army is a standing cost. It is the one role that takes money out every day for
        # something you hope never to need.
        cost = soldiers * ROLES["soldier"]["upkeep"]
        world["treasury"] = int(world.get("treasury", 0) - cost)
        notes.append(f"{soldiers} under arms costing ${cost}/day")

    nurses = f.get("nurse", 0)
    if nurses:
        for a in agents.values():
            if a.get("alive", True):
                a["health"] = min(100, a.get("health", 80) + nurses * 0.25)
        notes.append(f"{nurses} nursing")

    teachers = f.get("teacher", 0)
    if teachers:
        for a in agents.values():
            if a.get("alive", True) and working_age(a):
                a["skill"] = min(100, a.get("skill", 30) + teachers * 0.12)
        notes.append(f"{teachers} teaching")

    world["forces"] = f
    if not notes:
        return []
    return [{"kind": "forces", "day": day, "text": "The city's people at work: "
             + ", ".join(notes) + "."}]


def employment_rate(agents):
    pool = [a for a in agents.values() if a.get("alive", True) and working_age(a)]
    if not pool:
        return 1.0
    return sum(1 for a in pool if a.get("job")) / len(pool)


def can_afford(world, cost):
    return world.get("treasury", 0) >= cost


def spend(world, cost, reason, day):
    if not can_afford(world, cost):
        return False
    world["treasury"] = int(world["treasury"] - cost)
    world.setdefault("ledger", []).insert(
        0, {"day": day, "spend": cost, "reason": reason, "treasury": world["treasury"]})
    return True
