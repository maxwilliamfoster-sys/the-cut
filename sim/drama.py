"""
The Cut — the part where somebody finally does something about it.

The debt ledger was described in the README as "the most reliable story engine in the
table". It was not running. Every debt in the live city was **over two hundred city-days
overdue** and nothing had ever happened, because the only mechanical effect of being late
was a little stress on the person who owed — and stress relaxes back to baseline every beat.
The person who was *owed* felt nothing at all, never went looking, and nothing in the
codebase could mark a debt settled. Six grudges sat frozen for the city's entire life.

This module is the missing half. Three systems, all plain Python — the token budget is
fully committed to cognition, so drama has to be free.

**Patience.** Every overdue debt burns the creditor's patience. When it runs out they get
angry rather than sad: affinity toward the debtor drops, and they start *chasing* — routing
sends them to wherever that person is. A confrontation has to physically happen for anybody
to see it.

**Confrontations resolve.** When a creditor and their debtor end up in the same room past
patience, it goes one of four ways — paid, promised, refused, or it turns physical — decided
by the debtor's fear, how many times they have been asked before, how much the creditor
actually hates them by now, and who is watching. Debts can finally *end*. That matters more
than it sounds: an obligation that can never be discharged is scenery, not pressure.

**Volatility.** Some people start things. `volatility` is the one number that says who —
it decides who escalates a confrontation into violence, who picks at an old grudge when
they are miserable, and who gets extra weight in cognition.select() so the block's
troublemakers are actually in the room being narrated. Low-volatility characters de-escalate
and are worth having for exactly that reason.

Feuds are what is left when a confrontation goes badly enough. They persist, they pull two
people toward each other, and they decay only if nothing feeds them.
"""

import random
import re

from . import city, memory
from .roster import VOLATILITY

# How many city-days a creditor waits past the due date before they come looking. Short:
# the whole complaint was that nothing happened, and 4 beats to a city-day means this is a
# couple of real hours.
BASE_PATIENCE = 3
PATIENCE_PER_ASK = 3             # a promise buys the debtor this much more time

CHASE_AFFINITY_DROP = 4          # per city-day of being ignored
FEUD_AT = -55                    # affinity below this and it is a feud, not a disagreement
FEUD_DECAY = 2                   # per city-day with nothing feeding it

CONFRONT_COOLDOWN = 1            # city-days between confrontations over the same debt

# Without this one person does all of it. Dez started twenty-five of twenty-five arguments
# in a three-day test run, which reads as one lunatic rather than a volatile block.
INSTIGATE_COOLDOWN = 3           # city-days before the same person starts something again
# Aggregate rate matters more than any individual's. Ten volatile people each rolling every
# beat produced 138 arguments in three real days and drove the whole cast into sixteen
# feuds — at which point everybody hates everybody and none of it means anything. Scaled so
# the block gets roughly one started argument a city-day.
INSTIGATE_SCALE = 0.22


def ensure(world, agents):
    world.setdefault("feuds", [])
    for d in world.get("debts", []):
        d.setdefault("patience", BASE_PATIENCE)
        d.setdefault("asked", 0)
        d.setdefault("last_confront_day", -99)
    for a in agents.values():
        # Authored value first: the live city's agents.json predates the field, and
        # inferring it from trait prose flattened the whole cast to 45.
        if "volatility" not in a:
            a["volatility"] = VOLATILITY.get(a["id"], _volatility_from_traits(a))
        a.setdefault("chasing", None)


def _volatility_from_traits(a):
    """A sensible default for anybody who predates the field — read off their own prose."""
    text = " ".join(a.get("traits", [])) + " " + a.get("ambition", "")
    hot = ("impulsive", "proud", "angry", "temper", "violent", "ruthless", "crush",
           "hates", "sharp", "loud", "vengeful")
    cool = ("patient", "calm", "kind", "gentle", "quiet", "steady", "slow to anger",
            "peace", "careful")
    v = 45
    v += sum(12 for w in hot if w in text.lower())
    v -= sum(12 for w in cool if w in text.lower())
    return max(5, min(95, v))


def volatile(a):
    return a.get("volatility", 45) >= 65


# ── debts that finally bite ───────────────────────────────────────────────────

def press_debts(world, agents, day):
    """Erode patience, anger the creditor, and set them chasing. Returns prompt pressures.

    This replaces tick_debts' one-sided version, which only ever stressed the debtor.
    """
    ensure(world, agents)
    pressures = []
    for a in agents.values():
        a["chasing"] = None

    for d in world.get("debts", []):
        if d.get("settled"):
            continue
        if day < d.get("due_day", 0):
            continue
        overdue = day - d["due_day"]
        debtor, creditor = agents.get(d["from"]), agents.get(d["to"])
        if not debtor or not creditor:
            continue
        if not debtor.get("alive", True) or not creditor.get("alive", True):
            d["settled"] = True          # you cannot chase the dead
            continue

        _mood(debtor, stress=min(4 + overdue, 14), fear=min(2 + overdue, 10))

        patience = d.get("patience", BASE_PATIENCE)
        out_of_patience = overdue > patience
        if out_of_patience:
            # Anger, not sadness. This is the line that was missing entirely.
            _mood(creditor, stress=min(3 + overdue // 2, 16), happiness=-min(2 + overdue // 3, 12))
            rel = creditor.setdefault("relationships", {}).setdefault(
                d["from"], {"affinity": 0, "opinion": "owes me"})
            rel["affinity"] = max(-100, rel["affinity"] - CHASE_AFFINITY_DROP)
            rel["opinion"] = _owed_opinion(d, overdue)
            if not creditor.get("detained_until"):
                creditor["chasing"] = d["from"]

        pressures.append({
            "debt_id": d["id"], "from": debtor["name"], "to": creditor["name"],
            "from_id": debtor["id"], "to_id": creditor["id"],
            "kind": d["kind"], "amount": d["amount"], "days_overdue": overdue,
            "note": d.get("note", ""), "asked": d.get("asked", 0),
            "chasing": out_of_patience,
        })
    return pressures


def _owed_opinion(d, overdue):
    if d.get("asked", 0) >= 3:
        return "has looked me in the eye and lied three times"
    if overdue > 12:
        return "owes me and thinks I have forgotten"
    return "owes me and is avoiding me"


def what_is_owed(d):
    if d["kind"] == "money":
        return f'${d["amount"]:,}'
    if d["kind"] == "product":
        return "what they were fronted"
    return "a favour they have never repaid"


# ── the confrontation ─────────────────────────────────────────────────────────

def confrontations(world, agents, groups, beat, day):
    """A creditor and their debtor are in the same room, and the creditor has had enough."""
    ensure(world, agents)
    out = []
    for d in world.get("debts", []):
        if d.get("settled") or day < d.get("due_day", 0):
            continue
        if day - d.get("last_confront_day", -99) < CONFRONT_COOLDOWN:
            continue
        overdue = day - d["due_day"]
        if overdue <= d.get("patience", BASE_PATIENCE):
            continue
        debtor, creditor = agents.get(d["from"]), agents.get(d["to"])
        if not debtor or not creditor:
            continue
        if not debtor.get("alive", True) or not creditor.get("alive", True):
            continue
        if debtor.get("at") != creditor.get("at"):
            continue
        if creditor.get("detained_until") or debtor.get("detained_until"):
            continue

        rng = random.Random(f'{d["id"]}:{beat}:confront')
        witnesses = max(0, len(groups.get(creditor["at"], [])) - 2)
        out.append(_resolve(world, agents, d, creditor, debtor, witnesses, beat, day, rng))
        d["last_confront_day"] = day
    return [r for r in out if r]


def _resolve(world, agents, d, creditor, debtor, witnesses, beat, day, rng):
    rel = creditor.setdefault("relationships", {}).setdefault(
        d["from"], {"affinity": 0, "opinion": "owes me"})
    aff = rel["affinity"]
    asked = d.get("asked", 0)
    overdue = day - d["due_day"]
    where = city.LOCATIONS.get(creditor["at"], {}).get("name", "the block")
    owed = what_is_owed(d)

    # Fear is what actually makes somebody pay. Being asked repeatedly in front of people
    # wears them down too — and a big number is harder to produce on the spot.
    pay = 0.12 + debtor["mood"].get("fear", 0) / 260.0 + asked * 0.06 + witnesses * 0.03
    if d["kind"] == "money" and d.get("amount", 0) > 3000:
        pay -= 0.10
    pay = max(0.03, min(0.7, pay))

    if rng.random() < pay:
        d["settled"] = True
        rel["affinity"] = min(100, aff + 18)
        rel["opinion"] = "paid up, in the end"
        _mood(creditor, happiness=+16, stress=-14)
        _mood(debtor, stress=-18, fear=-10, happiness=-4)
        text = (f'{debtor["name"]} settles with {creditor["name"]} at {where}. '
                f'{owed}, {overdue} days late.')
        _lines(rng, "settled", debtor, creditor)
        _both(creditor, debtor, beat, day,
              f'{debtor["name"]} finally paid me.', f'I paid {creditor["name"]} off.', 8)
        return _rec("settled", d, creditor, debtor, text, beat, day)

    # Not paying. How badly it goes is the creditor's temperament meeting their patience.
    heat_for_violence = (creditor.get("volatility", 45) / 100.0) + (asked * 0.12) \
        + (max(0, -aff) / 200.0) - (witnesses * 0.05)
    if rng.random() < heat_for_violence - 0.55:
        return _violence(world, agents, d, creditor, debtor, where, beat, day, rng)

    if rng.random() < 0.45:
        d["patience"] = d.get("patience", BASE_PATIENCE) + PATIENCE_PER_ASK
        d["asked"] = asked + 1
        rel["affinity"] = max(-100, aff - 6)
        _mood(creditor, stress=+6, happiness=-5)
        _mood(debtor, stress=+10, fear=+6)
        text = (f'{creditor["name"]} corners {debtor["name"]} at {where} about {owed}. '
                f'They get another promise.')
        _lines(rng, "promised", debtor, creditor)
        _both(creditor, debtor, beat, day,
              f'{debtor["name"]} promised me again. That is {asked + 1} times.',
              f'I bought myself more time with {creditor["name"]}.', 7)
        return _rec("promised", d, creditor, debtor, text, beat, day)

    # Flat refusal. This is where feuds come from.
    d["asked"] = asked + 1
    rel["affinity"] = max(-100, aff - 20)
    rel["opinion"] = "told me no to my face"
    _mood(creditor, stress=+18, happiness=-14)
    _mood(debtor, stress=+14, fear=+10)
    _both(creditor, debtor, beat, day,
          f'{debtor["name"]} refused me in front of people.',
          f'I told {creditor["name"]} no. That will cost me.', 8)
    open_feud(world, creditor, debtor, day, f'{owed} never repaid')
    _lines(rng, "refused", debtor, creditor)
    text = (f'{creditor["name"]} asks {debtor["name"]} for {owed} at {where}, in front of '
            f'people, and is refused.')
    return _rec("refused", d, creditor, debtor, text, beat, day)


def _violence(world, agents, d, creditor, debtor, where, beat, day, rng):
    from . import mortality
    rel = creditor["relationships"][d["from"]]
    rel["affinity"] = max(-100, rel["affinity"] - 30)
    rel["opinion"] = "we are past talking"
    _mood(creditor, stress=+20, happiness=-10, fear=+8)
    _mood(debtor, stress=+30, fear=+34, happiness=-22)
    debtor["health"] = max(5, debtor.get("health", 80) - rng.randint(12, 30))

    district = city.LOCATIONS.get(creditor["at"], {}).get("district", "delmar")
    if district in world.get("heat", {}):
        world["heat"][district] = min(100, world["heat"][district] + 16)

    open_feud(world, creditor, debtor, day, "it turned physical")
    _both(creditor, debtor, beat, day,
          f'I put hands on {debtor["name"]} over what I am owed.',
          f'{creditor["name"]} put hands on me. Everyone saw.', 9)

    _lines(rng, "violent", debtor, creditor)
    text = (f'{creditor["name"]} puts {debtor["name"]} against a wall at {where} over '
            f'{what_is_owed(d)}. People stop to watch.')
    rec = _rec("violent", d, creditor, debtor, text, beat, day)
    # Rarely, it goes further than anyone meant it to.
    if debtor.get("health", 80) < 25 and rng.random() < 0.10:
        rec["fatal"] = True
    return rec


# What people actually say when these things happen. The model writes far better lines, but
# it costs tokens and the day's allowance runs out; these cost nothing and mean the block is
# never completely mute. A confrontation you can SEE — a speech bubble over the person doing
# the shouting — is most of what makes the city look alive from the outside.
SAID = {
    "settled":  [("Take it. We are square.", "Then we are done."),
                 ("That is all of it.", "About time."),
                 ("Count it if you want.", "I will, actually."),
                 ("We good now?", "We are good. For now.")],
    "promised": [("Give me two more days.", "You said that last week."),
                 ("I am good for it.", "You keep saying."),
                 ("Friday. I mean it.", "You meant it last Friday."),
                 ("Do not do this here.", "Then do not make me come here.")],
    "refused":  [("You are not getting it.", "Say that again."),
                 ("I do not have it and I am done being asked.", "Then we have a problem."),
                 ("Take me to court.", "That is not how this works."),
                 ("No.", "No? In front of everyone, no?")],
    "violent":  [("Do not.", "You made me do this."),
                 ("Get off me.", "Where is it?"),
                 ("Not here, not here.", "Here is exactly where."),
                 ("You are going to regret this.", "I already do.")],
}


def _say(a, to, text):
    """Put words in somebody's mouth for this beat. Cognition overwrites this for whoever it
    narrates, so a real line always wins over a canned one."""
    a["speech"] = {"to": to["id"], "text": text}


def _rec(kind, d, creditor, debtor, text, beat, day):
    return {"kind": "confrontation", "outcome": kind, "debt": d["id"],
            "creditor": creditor["id"], "debtor": debtor["id"],
            "creditor_name": creditor["name"], "debtor_name": debtor["name"],
            "text": text, "beat": beat, "day": day,
            "action": text}          # so law.detect and the Gazette both see it


def _lines(rng, outcome, debtor, creditor):
    """Both halves of the exchange, so the bubble over one head answers the other."""
    debtor_line, creditor_line = rng.choice(SAID[outcome])
    _say(debtor, creditor, debtor_line)
    _say(creditor, debtor, creditor_line)


def _both(a, b, beat, day, a_mem, b_mem, weight):
    memory.remember(a, beat, day, a_mem, weight)
    memory.remember(b, beat, day, b_mem, weight)
    memory.prune(a)
    memory.prune(b)


# ── feuds ─────────────────────────────────────────────────────────────────────

def open_feud(world, a, b, day, cause):
    pair = tuple(sorted((a["id"], b["id"])))
    aff = (a.get("relationships", {}).get(b["id"], {}) or {}).get("affinity", 0)
    if aff > FEUD_AT:
        return None
    for f in world.setdefault("feuds", []):
        if tuple(sorted((f["a"], f["b"]))) == pair:
            f["heat"] = min(100, f.get("heat", 40) + 20)
            f["cause"] = cause
            return f
    f = {"a": pair[0], "b": pair[1], "since_day": day, "cause": cause, "heat": 55}
    world["feuds"].append(f)
    return f


def tick_feuds(world, agents, day):
    """Feuds cool if nothing feeds them, and end when they stop meaning anything."""
    live = []
    for f in world.get("feuds", []):
        a, b = agents.get(f["a"]), agents.get(f["b"])
        if not a or not b or not a.get("alive", True) or not b.get("alive", True):
            continue
        aff = (a.get("relationships", {}).get(b["id"], {}) or {}).get("affinity", 0)
        f["heat"] = max(0, f.get("heat", 40) - FEUD_DECAY)
        if f["heat"] <= 0 and aff > FEUD_AT:
            continue
        live.append(f)
    world["feuds"] = live
    return live


def feud_partner(world, aid):
    for f in world.get("feuds", []):
        if f["a"] == aid:
            return f["b"]
        if f["b"] == aid:
            return f["a"]
    return None


# ── people who start things ───────────────────────────────────────────────────

INSTIGATIONS = [
    ("rumour", "{who} tells the room something about {other} that may not be true.",
     {"stress": 10, "happiness": -6},
     ["Ask them where they were Tuesday.", "That is not what I heard.",
      "Somebody should say it, so I will.", "Funny, the story keeps changing."]),
    ("callout", "{who} brings up, loudly, what {other} still owes.", {"stress": 12},
     ["Tell them what you owe. Go on.", "How long has it been now?",
      "Say it out loud, in front of everyone.", "Still nothing? Still nothing."]),
    ("needle", "{who} will not let go of something {other} said weeks ago.",
     {"stress": 9, "happiness": -8},
     ["You said it. I heard you say it.", "You do not get to take that back.",
      "Weeks, and you have not apologised.", "I remember it differently."]),
    ("side", "{who} takes a side in something that was not their argument.", {"stress": 8},
     ["No, he is right, and you know it.", "Do not look at me. Answer them.",
      "Everybody here saw what happened.", "You started this, not them."]),
]


def instigate(world, agents, groups, beat, day):
    """Somebody volatile, unhappy and in company picks at something.

    This is the difference between a block where trouble arrives from the event table and a
    block where trouble has an author. It fires on people the roster marks as volatile, and
    it prefers a target they already have a problem with.
    """
    ensure(world, agents)
    rng = random.Random(f'{world.get("seed", 0)}:{beat}:instigate')
    pool = [a for a in agents.values()
            if a.get("alive", True) and volatile(a) and not a.get("detained_until")
            and len(groups.get(a["at"], [])) > 1]
    if not pool:
        return []
    rng.shuffle(pool)

    for a in pool:
        if day - a.get("last_instigated_day", -99) < INSTIGATE_COOLDOWN:
            continue
        chance = (a["volatility"] - 60) / 420.0
        chance += a["mood"].get("stress", 0) / 900.0
        chance += (100 - a["mood"].get("happiness", 50)) / 1400.0
        if rng.random() > max(0.0, chance) * INSTIGATE_SCALE:
            continue

        here = [agents[o] for o in groups.get(a["at"], []) if o != a["id"] and o in agents]
        if not here:
            continue
        # Prefer somebody they already dislike, or are feuding with.
        enemy = feud_partner(world, a["id"])
        target = next((x for x in here if x["id"] == enemy), None)
        if target is None:
            here.sort(key=lambda x: (a.get("relationships", {}).get(x["id"], {}) or {})
                      .get("affinity", 0))
            target = here[0]

        a["last_instigated_day"] = day
        kind, tmpl, mood, lines = rng.choice(INSTIGATIONS)
        text = tmpl.format(who=a["name"], other=target["name"])
        _say(a, target, rng.choice(lines))   # a bubble, not only a line in the log
        _mood(target, **mood)
        _mood(a, stress=+4)
        rel = a.setdefault("relationships", {}).setdefault(
            target["id"], {"affinity": 0, "opinion": "not sure about them"})
        rel["affinity"] = max(-100, rel["affinity"] - 8)
        trel = target.setdefault("relationships", {}).setdefault(
            a["id"], {"affinity": 0, "opinion": "not sure about them"})
        trel["affinity"] = max(-100, trel["affinity"] - 12)
        memory.remember(target, beat, day, f'{a["name"]} started on me in front of people.', 7)
        memory.prune(target)
        if trel["affinity"] <= FEUD_AT:
            open_feud(world, target, a, day, "would not let it go")
        return [{"kind": "instigation", "who": a["id"], "name": a["name"],
                 "target": target["id"], "target_name": target["name"],
                 "instigation": kind, "text": text, "action": text,
                 "beat": beat, "day": day}]
    return []


def _mood(a, **deltas):
    m = a.setdefault("mood", {})
    for k, v in deltas.items():
        m[k] = max(0, min(100, m.get(k, 50) + v))


# ── the ledger refills ───────────────────────────────────────────────────────
# Every seeded debt settled inside three real days once confrontations worked, and a city
# with nothing outstanding has no deadlines and therefore no pressure. Obligations have to
# keep forming, or the engine runs once and dies.

NEW_DEBT_CHANCE = 0.16           # per city-day
DEBT_KINDS = [
    ("money", "fronted cash and expects it back"),
    ("money", "covered somebody's shortfall, once"),
    ("product", "was fronted and has not squared it"),
    ("favour", "owes a favour that was not small"),
    ("favour", "was got out of something and knows it"),
]


def maybe_new_debt(world, agents, beat, day):
    """Two people form a new obligation. Preferably people who already know each other —
    debt between strangers is arithmetic; debt between people with history is a story."""
    if beat % 4 != 0:
        return []
    rng = random.Random(f'{world.get("seed", 0)}:{day}:newdebt')
    if rng.random() > NEW_DEBT_CHANCE:
        return []
    living = [a for a in agents.values()
              if a.get("alive", True) and not a.get("detained_until")]
    if len(living) < 4:
        return []

    open_now = [d for d in world.get("debts", []) if not d.get("settled")]
    if len(open_now) >= 9:
        return []

    creditor = rng.choice([a for a in living
                           if a.get("faction") in ("grey", "crew") or rng.random() < 0.4])
    known = [x for x in living
             if x["id"] != creditor["id"]
             and x["id"] not in {d["from"] for d in open_now if d["to"] == creditor["id"]}]
    if not known:
        return []
    known.sort(key=lambda x: -abs((creditor.get("relationships", {}).get(x["id"], {}) or {})
                                  .get("affinity", 0)))
    debtor = known[0] if rng.random() < 0.6 else rng.choice(known)

    kind, note = rng.choice(DEBT_KINDS)
    amount = rng.choice([200, 400, 600, 900, 1500, 2500]) if kind == "money" else 1
    debt = {"id": f'debt{len(world.get("debts", [])) + 1}',
            "from": debtor["id"], "to": creditor["id"], "kind": kind, "amount": amount,
            "due_day": day + rng.randint(2, 6), "note": note, "settled": False,
            "patience": BASE_PATIENCE, "asked": 0, "last_confront_day": -99}
    world.setdefault("debts", []).append(debt)
    memory.remember(debtor, beat, day,
                    f'I took something from {creditor["name"]} that I have to give back.', 6)
    return [{"kind": "debt", "event": "opened", "from": debtor["id"], "to": creditor["id"],
             "text": f'{debtor["name"]} {note} — {creditor["name"]}.',
             "beat": beat, "day": day}]


# ── things the player told them ──────────────────────────────────────────────
# You are the only source of information in this city that did not come from inside it. If
# you tell somebody that Malik has been talking to the police, that has to be able to travel
# — otherwise talking to people is a novelty act rather than a way of affecting anything.
#
# A claim becomes a LEAD: an unverified thing this person now carries. They go and find the
# person it is about, and when they do it resolves against the city's own record — the
# subject's actual memories — rather than against a coin flip. So a true rumour lands and a
# lie mostly does not, and neither outcome was scripted.

LEAD_STALE_DAYS = 8              # after this they stop caring
MIN_CORROBORATION = 2            # overlapping significant words to count as "something in it"

_STOPWORDS = {"the", "a", "an", "and", "is", "was", "has", "have", "been", "to", "of", "in",
              "on", "for", "with", "that", "this", "it", "he", "she", "they", "them", "his",
              "her", "about", "me", "my", "you", "your", "at", "be", "are", "were", "not"}


def open_lead(a, about, what, day, source="a stranger"):
    """Somebody has been told something about somebody else, and has not checked it."""
    if not about or about == a["id"] or not what:
        return None
    leads = a.setdefault("leads", [])
    for l in leads:
        if l["about"] == about and not l.get("checked"):
            l["what"] = what          # they heard it again; same lead, fresher wording
            l["day"] = day
            return l
    lead = {"about": about, "what": str(what)[:120], "day": day,
            "source": source, "checked": False}
    leads.append(lead)
    del leads[:-4]
    return lead


def press_leads(world, agents, day):
    """Anybody carrying an unchecked lead goes looking for the person it is about."""
    for a in agents.values():
        for l in list(a.get("leads", [])):
            if l.get("checked"):
                continue
            if day - l.get("day", day) > LEAD_STALE_DAYS:
                l["checked"] = "gave up"
                continue
            # A debt outranks a rumour: money first, gossip second.
            if not a.get("chasing") and not a.get("detained_until") and l["about"] in agents:
                a["checking"] = l["about"]
                break


def _significant(text):
    return {w for w in re.findall(r"[a-z']+", (text or "").lower())
            if len(w) > 3 and w not in _STOPWORDS}


def _document_frequency(agents):
    """How many people's memories each word appears in.

    Plain word overlap does not work: "Malik has been talking to the police" shares
    *police* and *talking* with half the memories in a city about police and talk, so an
    invented rumour corroborated itself immediately. A word only counts as evidence if it
    is rare across the block — which is cheap to work out from the city's own record.
    """
    df = {}
    for a in agents.values():
        seen = set()
        for m in (a.get("memories") or []):
            seen |= _significant(m.get("what", ""))
        for w in seen:
            df[w] = df.get(w, 0) + 1
    return df


def corroborated(subject, what, df=None, population=1):
    """Is there anything in this person's own history that matches the claim?

    This is the trick that keeps the player honest: the city already holds a record of what
    everybody actually did, so a claim can be checked against it without asking the model
    anything. A rumour that happens to be true finds its evidence; an invented one usually
    does not — provided the match is on something *distinctive* rather than on the ordinary
    vocabulary of the place.
    """
    words = _significant(what)
    if not words:
        return False
    df = df or {}
    rare_at = max(2, population * 0.25)

    def hit(text):
        overlap = words & _significant(text)
        if len(overlap) < MIN_CORROBORATION:
            return False
        # At least one of the matching words has to be something not everybody says.
        return any(df.get(w, 0) <= rare_at for w in overlap)

    for m in (subject.get("memories") or []):
        if hit(m.get("what", "")):
            return True
    return hit(subject.get("belief", ""))


def check_leads(world, agents, groups, beat, day):
    """They have found the person the rumour was about. Now they ask."""
    out = []
    df = _document_frequency(agents)
    for a in agents.values():
        if not a.get("alive", True) or a.get("detained_until"):
            continue
        lead = next((l for l in a.get("leads", [])
                     if not l.get("checked") and l["about"] in agents), None)
        if not lead:
            continue
        subject = agents[lead["about"]]
        if not subject.get("alive", True) or subject.get("at") != a.get("at"):
            continue

        rng = random.Random(f'{a["id"]}:{lead["about"]}:{beat}:lead')
        true_ish = corroborated(subject, lead["what"], df, len(agents))
        rel = a.setdefault("relationships", {}).setdefault(
            subject["id"], {"affinity": 0, "opinion": "not sure about them"})
        where = city.LOCATIONS.get(a["at"], {}).get("name", "the block")

        if true_ish:
            lead["checked"] = "true"
            rel["affinity"] = max(-100, rel["affinity"] - 22)
            rel["opinion"] = "it turned out to be true"
            _mood(a, stress=+14, fear=+10, happiness=-10)
            _mood(subject, stress=+16, fear=+14)
            memory.remember(a, beat, day,
                            f'I asked {subject["name"]} about it. There was something in it.', 8)
            memory.remember(subject, beat, day,
                            f'{a["name"]} came at me about {lead["what"]}. Somebody has been talking.', 8)
            if rel["affinity"] <= FEUD_AT:
                open_feud(world, a, subject, day, "a rumour that turned out to be true")
            text = (f'{a["name"]} puts it to {subject["name"]} at {where} — {lead["what"]} — '
                    f'and does not like the answer.')
        else:
            # Nothing in the record. Whether they let it go is a question of temperament.
            believes = rng.random() < (a.get("volatility", 45) / 260.0
                                       + a["mood"].get("fear", 0) / 320.0)
            lead["checked"] = "believed anyway" if believes else "false"
            if believes:
                rel["affinity"] = max(-100, rel["affinity"] - 12)
                rel["opinion"] = "I do not believe the denial"
                _mood(a, stress=+8, fear=+6)
                memory.remember(a, beat, day,
                                f'{subject["name"]} denied it. I did not believe them.', 7)
                text = (f'{a["name"]} asks {subject["name"]} about {lead["what"]} at {where}. '
                        f'The denial does not take.')
            else:
                rel["affinity"] = min(100, rel["affinity"] + 6)
                _mood(a, stress=-4)
                memory.remember(a, beat, day,
                                f'I asked {subject["name"]} about it. It was nothing.', 5)
                text = (f'{a["name"]} asks {subject["name"]} about {lead["what"]} at {where}, '
                        f'and lets it drop.')
            memory.remember(subject, beat, day,
                            f'{a["name"]} asked me about something a stranger told them.', 6)

        memory.prune(a)
        memory.prune(subject)
        a["checking"] = None
        out.append({"kind": "lead", "who": a["id"], "name": a["name"],
                    "about": subject["id"], "about_name": subject["name"],
                    "verdict": lead["checked"], "what": lead["what"],
                    "text": text, "action": text, "beat": beat, "day": day})
    return out
