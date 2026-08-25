"""
The Cut — telling somebody to do something, and finding out whether they will.

The mayor can now give an instruction rather than just make conversation. What makes this
worth having is that it can **fail**. A directive is a request with authority behind it, not
a remote control: whether it gets carried out depends on how the person regards you, how
volatile they are, and whether you have just raised their tax.

    standing    0-100, per person, how they regard the office. Everyone starts sceptical.
    compliance  rolled per directive from standing, temperament and what is being asked
    refusal     is a real outcome, is spoken out loud, and costs you standing with others

That last part matters. A city where every instruction lands is an interface with extra
steps; the interesting play is working out who will actually do things for you, and what it
costs to keep them onside.

Five shapes are understood mechanically — go somewhere, work somewhere, make peace, settle
a debt, go and speak to somebody. Anything else becomes a standing instruction the person
carries and the narration is told about, which is how an order gets interpreted rather than
executed. Free: no model calls.
"""

import random
import re

from . import city, memory

START_STANDING = 45           # sceptical, not hostile
STANDING_OBEYED = 4
STANDING_REFUSED = -7
STANDING_TAX_RISE = -10       # per five points of tax
STANDING_BUILT_NEARBY = 3
STANDING_PROGRAMME = 2

DIRECTIVE_DAYS = 3            # how long somebody carries an instruction before it lapses


def ensure(agents):
    for a in agents.values():
        a.setdefault("standing", START_STANDING)
        a.setdefault("directive", None)


# ── reading the instruction ──────────────────────────────────────────────────

_GO = re.compile(r"\b(?:go|get|head|move)\s+(?:to|over to|down to|back to)\s+(.+)", re.I)
_WORK = re.compile(r"\b(?:work|get a job|take a job|start)\s+(?:at|in|for)\s+(.+)", re.I)
_PEACE = re.compile(r"\b(?:make peace|make it up|settle it|sort it out|leave)\s+(?:with\s+)?(.+)", re.I)
_PAY = re.compile(r"\b(?:pay|settle (?:up )?with|square (?:up )?with|repay)\s+(.+)", re.I)
_SPEAK = re.compile(r"\b(?:talk|speak|have a word)\s+(?:to|with)\s+(.+)", re.I)

# An instruction is a sentence aimed at somebody. These are the shapes an order takes when
# it is not one of the five above, and they are what tells a plain remark from a command.
_IMPERATIVE = re.compile(
    r"\b(?:you (?:need to|have to|must|should)|i want you to|i need you to|"
    r"stop|start|don't|do not|make sure|see to it|from now on|get)\b", re.I)


def read(line, speaker_id, agents):
    """Turn a line from the mayor into a directive, or None if it was just talk."""
    text = (line or "").strip()
    if not text:
        return None

    for pattern, kind in ((_WORK, "work"), (_GO, "go"), (_PAY, "pay"),
                          (_PEACE, "peace"), (_SPEAK, "speak")):
        m = pattern.search(text)
        if not m:
            continue
        tail = m.group(1)
        if kind in ("go", "work"):
            place = _find_place(tail)
            if place:
                return {"kind": kind, "target": place, "text": text[:140]}
        else:
            who = _find_person(tail, agents, speaker_id)
            if who:
                return {"kind": kind, "target": who, "text": text[:140]}

    if _IMPERATIVE.search(text):
        # Understood as an instruction without a mechanical handle. It still lands: the
        # person carries it, and the narration is told they were told.
        return {"kind": "general", "target": None, "text": text[:140]}
    return None


def _find_place(tail):
    low = f" {tail.lower()} "
    best = None
    for lid, loc in city.LOCATIONS.items():
        for name in (loc["name"].lower(), lid.lower()):
            if len(name) > 3 and name in low and (not best or len(name) > best[1]):
                best = (lid, len(name))
    return best[0] if best else None


def _find_person(tail, agents, speaker_id):
    low = f" {tail.lower()} "
    best = None
    for aid, o in agents.items():
        if aid == speaker_id or not o.get("alive", True):
            continue
        parts = [p.strip(".,'").lower() for p in str(o["name"]).split()]
        for n in [str(o["name"]).lower()] + [p for p in parts if len(p) >= 3]:
            if f" {n} " in low or f" {n}." in low or f" {n}," in low:
                if not best or len(n) > best[1]:
                    best = (aid, len(n))
    return best[0] if best else None


# ── will they do it ──────────────────────────────────────────────────────────

def _weight(kind):
    """How much you are asking for. Telling somebody to change job is a bigger favour than
    telling them to walk somewhere."""
    return {"go": 0.10, "speak": 0.05, "peace": -0.18, "pay": -0.12,
            "work": -0.08, "general": 0.0}.get(kind, 0.0)


def will_comply(a, directive, rng):
    standing = a.get("standing", START_STANDING)
    chance = standing / 140.0 + 0.22 + _weight(directive["kind"])
    chance -= max(0, a.get("volatility", 45) - 50) / 220.0
    # Somebody frightened does as they are told; somebody furious does not.
    chance += a["mood"].get("fear", 20) / 400.0
    chance -= a["mood"].get("stress", 30) / 500.0
    return rng.random() < max(0.04, min(0.94, chance))


def give(world, agents, aid, line, day, beat):
    """Hand somebody an instruction. Returns a record, or None if it was only talk."""
    ensure(agents)
    a = agents.get(aid)
    if not a or not a.get("alive", True):
        return None
    d = read(line, aid, agents)
    if not d:
        return None

    rng = random.Random(f'{aid}:{day}:{beat}:directive')
    d.update({"given_day": day, "status": "pending", "from": "the mayor"})

    if not will_comply(a, d, rng):
        d["status"] = "refused"
        a["standing"] = max(0, a.get("standing", START_STANDING) + STANDING_REFUSED)
        a["directive"] = None
        memory.remember(a, beat, day, f'The mayor told me to {_short(d)}. I said no.', 8)
        memory.prune(a)
        say = rng.choice(["Not for you, not today.", "You can ask. I can say no.",
                          "That is not happening.", "With respect — no."])
        a["speech"] = {"to": None, "text": say}
        return {"kind": "directive", "ok": False, "who": aid, "name": a["name"],
                "what": d["kind"], "day": day, "beat": beat, "said": say,
                "text": f'{a["name"]} refuses: "{say}"'}

    a["directive"] = d
    a["standing"] = min(100, a.get("standing", START_STANDING) + STANDING_OBEYED)
    memory.remember(a, beat, day, f'The mayor told me to {_short(d)}.', 7)
    memory.prune(a)
    return {"kind": "directive", "ok": True, "who": aid, "name": a["name"],
            "what": d["kind"], "target": d.get("target"), "day": day, "beat": beat,
            "text": f'{a["name"]} agrees to {_short(d)}.'}


def _short(d):
    t = d.get("target")
    if d["kind"] == "go":
        return f'go to {city.LOCATIONS.get(t, {}).get("name", t)}'
    if d["kind"] == "work":
        return f'work at {city.LOCATIONS.get(t, {}).get("name", t)}'
    if d["kind"] in ("peace", "pay", "speak"):
        return f'{d["kind"]} with {t}'
    return d.get("text", "do something")[:60]


# ── carrying it out ──────────────────────────────────────────────────────────

def destination(a):
    """Where an outstanding instruction is sending somebody, if anywhere. Consulted by
    routing, which is what makes 'go to the clinic' actually move them."""
    d = a.get("directive")
    if not d or d.get("status") != "pending":
        return None
    if d["kind"] == "go" and city.usable(d.get("target")):
        return d["target"]
    if d["kind"] in ("speak", "peace", "pay"):
        return None            # handled by chasing, not by a fixed destination
    return None


def follow_up(world, agents, day, beat):
    """Resolve, expire and act on outstanding instructions. Once a city-day."""
    ensure(agents)
    out = []
    for a in agents.values():
        d = a.get("directive")
        if not d or d.get("status") != "pending":
            continue

        if d["kind"] == "go" and a.get("at") == d.get("target"):
            d["status"] = "done"
            out.append(_done(a, d, day, beat, f'{a["name"]} is where they were told to be.'))

        elif d["kind"] == "work":
            if (a.get("job") or {}).get("at") == d.get("target"):
                d["status"] = "done"
                out.append(_done(a, d, day, beat,
                                 f'{a["name"]} is working where the mayor wanted.'))
            else:
                a["work"] = d["target"]       # they will take the job when one is going
                a["job"] = None

        elif d["kind"] == "peace":
            other = agents.get(d.get("target"))
            if other:
                for x, y in ((a, other), (other, a)):
                    rel = x.setdefault("relationships", {}).setdefault(
                        y["id"], {"affinity": 0, "opinion": "we have history"})
                    rel["affinity"] = min(100, rel["affinity"] + 22)
                world["feuds"] = [f for f in world.get("feuds", [])
                                  if {f["a"], f["b"]} != {a["id"], other["id"]}]
                d["status"] = "done"
                out.append(_done(a, d, day, beat,
                                 f'{a["name"]} and {other["name"]} call it off.'))

        elif d["kind"] == "pay":
            paid = False
            for debt in world.get("debts", []):
                if (not debt.get("settled") and debt.get("from") == a["id"]
                        and debt.get("to") == d.get("target")):
                    debt["settled"] = True
                    paid = True
            if paid:
                d["status"] = "done"
                out.append(_done(a, d, day, beat, f'{a["name"]} settles up as instructed.'))

        elif d["kind"] == "speak":
            a["checking"] = d.get("target")

        if d.get("status") == "pending" and day - d.get("given_day", day) >= DIRECTIVE_DAYS:
            d["status"] = "lapsed"
            a["standing"] = max(0, a.get("standing", START_STANDING) - 2)
            out.append({"kind": "directive", "ok": False, "who": a["id"], "name": a["name"],
                        "day": day, "beat": beat, "what": d["kind"],
                        "text": f'{a["name"]} never got round to what they were told.'})
            a["directive"] = None
    return out


def _done(a, d, day, beat, text):
    a["directive"] = None
    a["standing"] = min(100, a.get("standing", START_STANDING) + STANDING_OBEYED)
    memory.remember(a, beat, day, f'I did what the mayor asked.', 6)
    return {"kind": "directive", "ok": True, "done": True, "who": a["id"],
            "name": a["name"], "what": d["kind"], "day": day, "beat": beat, "text": text}


# ── how the office is regarded ───────────────────────────────────────────────

def shift_standing(agents, amount, reason=""):
    for a in agents.values():
        if a.get("alive", True):
            a["standing"] = max(0, min(100, a.get("standing", START_STANDING) + amount))


def average_standing(agents):
    live = [a for a in agents.values() if a.get("alive", True)]
    if not live:
        return START_STANDING
    return round(sum(a.get("standing", START_STANDING) for a in live) / len(live))
