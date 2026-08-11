"""
The Cut — entropy.

Left alone, a routine-driven cast converges on a loop: everyone walks the same path,
says the same thing, and the week reads like the day. This table is the perturbation
that keeps the city from settling.

Events are rolled from a generator seeded on `(world_seed, beat)`, so the same beat always
produces the same event. That makes an interesting week reproducible and, more usefully,
makes a bug reproducible.

Events do not decide what anyone *does* — they change the conditions the model reasons
under. The model still chooses the reaction, which is why two characters can receive the
same event and respond in opposite directions.
"""

import random

# Ambient conditions — rolled every beat, no mechanical effect beyond flavour and a small
# nudge to whether people stay indoors.
WEATHER = [
    (28, "clear"), (20, "overcast"), (16, "rain"), (10, "heavy rain"),
    (8, "fog off the water"), (8, "cold snap"), (6, "heat"), (4, "first snow"),
]

# scope: "city" (everyone sees it) | "person" (lands on one character) | "pair" (two)
# heat: district -> delta, or "*" for citywide
# mood: stat -> delta, applied to whoever the event lands on ("city" scope applies to all)
EVENTS = [
    # — quiet beats are the majority; a table that fires every beat stops feeling like news
    {"id": "nothing", "weight": 34, "scope": "city", "text": None},

    {"id": "patrol_surge", "weight": 6, "scope": "city",
     "text": "Two extra cruisers have been sitting on Delmar since this morning.",
     "heat": {"delmar": 12}, "mood": {"stress": 6}},

    {"id": "shipment_light", "weight": 4, "scope": "person", "pool": "crew",
     "text": "{who} finds the count is short again. Not by much. Enough.",
     "mood": {"stress": 14, "happiness": -8}},

    {"id": "snitch_rumour", "weight": 4, "scope": "pair",
     "text": "Somebody tells {who} that {other} has been seen talking to police.",
     "mood": {"stress": 12, "fear": 10}},

    {"id": "overdose", "weight": 3, "scope": "city",
     "text": "An ambulance takes someone out of the Terraces before dawn. Nobody says a name.",
     "heat": {"terraces": 8}, "mood": {"happiness": -12, "stress": 8}},

    {"id": "raid", "weight": 2, "scope": "city",
     "text": "The 9th kicks a door on Riverside. Wrong door, as it turns out.",
     "heat": {"riverside": 25, "delmar": 8}, "mood": {"stress": 18, "fear": 14}},

    {"id": "debt_called", "weight": 4, "scope": "person",
     "text": "{who} gets word that what they owe is wanted sooner than agreed.",
     "mood": {"stress": 20, "fear": 12}},

    {"id": "money_found", "weight": 3, "scope": "person",
     "text": "Something pays out for {who}. More than expected, which is its own problem.",
     "mood": {"happiness": 15, "energy": 6}},

    {"id": "power_cut", "weight": 3, "scope": "city",
     "text": "The block loses power for six hours. Everything happens in the dark.",
     "heat": {"delmar": -6}, "mood": {"energy": -8}},

    {"id": "funeral", "weight": 2, "scope": "city",
     "text": "There is a funeral on Delmar. Most of the block goes. Some people who should be there are not.",
     "mood": {"happiness": -14, "social_need": -20}},

    {"id": "new_face", "weight": 3, "scope": "city",
     "text": "A car nobody recognises has been parked on the same corner for three days.",
     "mood": {"stress": 7}},

    {"id": "inspection", "weight": 3, "scope": "city",
     "text": "City inspectors are working their way down Delmar with clipboards.",
     "heat": {"delmar": 6}, "mood": {"stress": 9}},

    {"id": "fight", "weight": 3, "scope": "pair",
     "text": "{who} and {other} are seen arguing in the street loud enough that people stop.",
     "mood": {"stress": 15, "happiness": -10}},

    {"id": "kindness", "weight": 5, "scope": "pair",
     "text": "{other} does {who} a favour that costs them something real.",
     "mood": {"happiness": 14, "social_need": -15}},

    {"id": "eviction", "weight": 2, "scope": "city",
     "text": "Notices go up on two doors in the Terraces. The letterhead is a company nobody has heard of.",
     "mood": {"stress": 12, "happiness": -8}},

    {"id": "good_night", "weight": 4, "scope": "city",
     "text": "The Harbor Bar is full and loud and for a few hours nothing is wrong.",
     "mood": {"happiness": 16, "social_need": -25, "stress": -10}},

    {"id": "cold_case", "weight": 2, "scope": "person", "pool": "police",
     "text": "{who} pulls a file that should have been closed years ago and cannot put it back.",
     "mood": {"stress": 10, "energy": -6}},

    {"id": "hospital", "weight": 2, "scope": "person",
     "text": "{who} ends up at the clinic. The paperwork says one thing; the injury says another.",
     "heat": {"civic": 5}, "mood": {"energy": -20, "happiness": -12, "fear": 10}},
]


def _weighted(rng, table):
    total = sum(w for w, _ in table)
    roll = rng.uniform(0, total)
    upto = 0
    for w, item in table:
        upto += w
        if roll <= upto:
            return item
    return table[-1][1]


def roll_weather(rng):
    return _weighted(rng, WEATHER)


def roll_event(rng, agents, factions):
    """Pick one event and bind its placeholders to real people.

    Returns None for a quiet beat, otherwise a dict the tick loop applies and the prompt
    layer shows to the model as something that just happened.
    """
    table = [(e["weight"], e) for e in EVENTS]
    ev = _weighted(rng, table)
    if ev["text"] is None:
        return None

    ids = sorted(agents.keys())
    out = {"id": ev["id"], "heat": ev.get("heat", {}), "mood": ev.get("mood", {}), "targets": []}

    if ev["scope"] == "person":
        pool = ids
        if ev.get("pool"):
            pool = [a for a in ids if agents[a]["faction"] == ev["pool"]] or ids
        who = rng.choice(pool)
        out["targets"] = [who]
        out["text"] = ev["text"].format(who=agents[who]["name"])

    elif ev["scope"] == "pair":
        who, other = rng.sample(ids, 2)
        out["targets"] = [who, other]
        out["text"] = ev["text"].format(who=agents[who]["name"], other=agents[other]["name"])

    else:
        out["text"] = ev["text"]

    return out
