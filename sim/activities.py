"""
The Cut — what everybody is doing right now.

A character standing motionless on a tile reads as a bug even when the simulation is
working perfectly. Somebody has to be asleep in a bed, wiping a counter, or watching
television, and almost none of that is worth an LLM call: a background character loading a
dishwasher does not need a language model to decide that.

So every character gets a deterministic activity every beat, chosen from where they are,
what time it is, and whether they are at work, at home, or visiting. The LLM's attention is
then a scarce resource spent only where it changes the story — see cognition.select().

Activities also place people. An activity names the furniture it happens at, so somebody
asleep is drawn in a bed rather than standing on top of one.
"""

import random

# (text, furniture it happens at, weight). Empty furniture tuple = anywhere in the room.
HOME = {
    "night": [
        ("asleep", ("bed",), 60), ("lying awake", ("bed",), 12),
        ("up for a glass of water", ("sink",), 6), ("dozing in front of the TV", ("sofa",), 10),
    ],
    "morning": [
        ("making coffee", ("sink",), 18), ("still in bed", ("bed",), 10),
        ("watching the news", ("tv", "sofa"), 14), ("eating breakfast standing up", ("table",), 14),
        ("looking for keys", (), 8), ("on the phone", ("sofa",), 8),
    ],
    "afternoon": [
        ("doing the washing up", ("sink",), 16), ("watching television", ("tv", "sofa"), 18),
        ("folding laundry", ("table",), 12), ("napping on the sofa", ("sofa",), 10),
        ("on hold with somebody", ("sofa",), 8), ("watering a plant", ("plant",), 6),
    ],
    "evening": [
        ("eating at the table", ("table",), 20), ("watching television", ("tv", "sofa"), 22),
        ("washing up", ("sink",), 14), ("sitting with the radio on", ("sofa",), 10),
        ("going through the post", ("table",), 8),
    ],
}

WORK = {
    "social": [
        ("wiping down the counter", ("counter",), 20), ("pouring for somebody", ("counter",), 16),
        ("clearing tables", ("table",), 14), ("restocking the back bar", ("shelf",), 10),
        ("leaning on the counter", ("counter",), 12),
    ],
    "business": [
        ("behind the till", ("till", "counter"), 22), ("restocking shelves", ("shelf",), 18),
        ("counting the float", ("counter",), 12), ("signing for a delivery", ("crate",), 10),
        ("watching the door", ("counter",), 10),
    ],
    "civic": [
        ("at the desk", ("desk",), 24), ("filing paperwork", ("shelf",), 16),
        ("on the phone", ("desk",), 14), ("reading a file", ("desk",), 14),
        ("making bad coffee", (), 8),
    ],
    "industrial": [
        ("shifting crates", ("crate",), 22), ("running the machine", ("machine",), 18),
        ("checking a manifest", ("shelf",), 12), ("having a smoke by the door", (), 10),
    ],
    "outdoor": [
        ("sitting on a bench", ("bench",), 18), ("standing around", (), 16),
        ("kicking at the gravel", (), 10), ("watching the road", (), 12),
    ],
    "home": [
        ("working from the kitchen table", ("table",), 20), ("on a call", ("sofa",), 12),
    ],
}

VISIT = {
    "social": [
        ("nursing a drink", ("table", "chair"), 22), ("waiting to be served", ("counter",), 14),
        ("in the chair", ("chair",), 12), ("talking over the table", ("table",), 16),
        ("reading the paper", ("table",), 10),
    ],
    "business": [
        ("browsing the shelves", ("shelf",), 20), ("queueing", ("counter",), 14),
        ("counting out change", ("till", "counter"), 12), ("looking at nothing in particular", (), 10),
    ],
    "civic": [
        ("waiting to be seen", ("chair", "desk"), 20), ("filling in a form", ("desk",), 14),
        ("sitting very still", ("chair",), 12), ("pacing", (), 10),
    ],
    "industrial": [
        ("keeping out of the way", ("crate",), 16), ("waiting for somebody", (), 14),
    ],
    "outdoor": [
        ("sitting on a bench", ("bench",), 20), ("smoking", (), 14),
        ("watching the street", (), 14), ("sheltering from the weather", ("tree",), 10),
    ],
    "home": [
        ("sitting in someone else's kitchen", ("table",), 18), ("perched on the arm of the sofa", ("sofa",), 12),
    ],
}

# Weather and mood colour the phrasing without needing a separate table for every case.
WEATHER_TINT = {
    "rain": "out of the rain", "heavy rain": "listening to the rain",
    "first snow": "watching the snow", "cold snap": "keeping warm",
    "fog off the water": "in the fog", "heat": "in the heat",
}


def _pick(rng, table):
    total = sum(w for _, _, w in table)
    roll, upto = rng.uniform(0, total), 0
    for text, furn, w in table:
        upto += w
        if roll <= upto:
            return text, furn
    return table[-1][0], table[-1][1]


def choose(agent, loc, block, weather, rng):
    """Return (text, spot) for this beat. `loc` is a LOCATIONS entry."""
    kind = loc["kind"]
    at_home = loc["id"] == agent.get("home")
    at_work = loc["id"] == agent.get("work")

    if at_home and kind == "home":
        table = HOME[block]
    elif at_work:
        table = WORK.get(kind) or WORK["outdoor"]
    else:
        table = VISIT.get(kind) or VISIT["outdoor"]

    text, furn_types = _pick(rng, table)

    # Exhaustion overrides the roll: somebody running on empty is not restocking shelves.
    if agent["mood"]["energy"] < 12 and block != "night":
        text, furn_types = ("sitting down for a minute", ("chair", "sofa", "bench", "bed"))

    spot = None
    if furn_types:
        options = [f for f in loc["furniture"] if f["type"] in furn_types]
        if options:
            f = options[rng.randrange(len(options))]
            spot = [f["x"], f["y"]]

    tint = WEATHER_TINT.get(weather)
    if tint and rng.random() < 0.18:
        text = f"{text}, {tint}"
    return text, spot
