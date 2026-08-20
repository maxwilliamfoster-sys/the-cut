"""
The Cut — law the city writes for itself.

Nobody authored these laws. There is no statute book in the repo. The block accumulates
incidents — a fire nobody claims, a body in the Terraces, three weeks of somebody's debts
being collected loudly — and when the pressure is high enough the model is asked, once, to
write **one** law in response to what has actually happened. The city's legal code is
therefore a readable record of everything that has gone wrong in it.

The expensive half is the only half the model does.

    propose  ── LLM, rare, budget-capped ──> a law, with keywords
    detect   ── plain Python ─────────────> keyword match on narrated actions
    arrest   ── plain Python ─────────────> caught or not, by heat and witnesses
    trial    ── plain Python ─────────────> a jury of actual characters
    sentence ── plain Python ─────────────> fine, jail, service, or acquittal

**Why juries are mechanical and still interesting:** the verdict is voted on by real
characters, weighted by how they actually feel about the accused and how much they fear the
district's heat. A popular defendant walks. Somebody the block has turned on does not. That
is the social graph deciding the law's outcome, and it costs nothing — no model call could
have produced a more grounded answer than the affinities the city has spent weeks building.

**Why keywords:** matching free text against a law is a semantic problem, and a semantic
problem per action per beat would cost more tokens than the entire simulation. So the model
supplies the keywords when it writes the law, and detection is a deterministic scan. The
model does the judgement once; the machine applies it ten thousand times.
"""

import random
import re

from . import llm, memory

# Law-writing is the only LLM cost in this module, so it is capped hard. The city's whole
# allowance is committed to cognition; civic life gets the crumbs and must survive on them.
LAW_TOKENS_PER_DAY = 4000
MIN_DAYS_BETWEEN_LAWS = 3
PRESSURE_TO_LEGISLATE = 3        # unaddressed incidents before the block acts

TRIAL_DELAY = 2                  # city-days between charge and trial
MAX_LAWS = 14                    # beyond this the block repeals before it adds

LAW_SYSTEM = """You write law for THE CUT, one block of a small American city. The block has
started policing itself and you are drafting what it decides.

You are given what has actually happened here recently and the laws already in force. Write
ONE new local ordinance that responds to those events. It must be something THIS block would
plausibly pass after THESE incidents — not general criminal law, not federal law, not
anything already covered by an existing law below.

RULES
- The law must be traceable to at least one incident in the list. Petty and specific is
  better than grand and vague: "no unlicensed burning in yards after dark" beats "arson is
  forbidden".
- `keywords` is how the law gets enforced: 3-6 short lowercase words or phrases that would
  appear in a description of somebody breaking it. Use plain, likely words ("burn", "fire",
  "torch"), not legal terms. This matters more than the wording of the law.
- `title` MAX 6 WORDS. `text` MAX 22 WORDS, written as an ordinance.
- `proposed_by` must be an id from the people listed. Pick whoever these events hurt most.
- Penalty must fit the block's means: a fine in dollars, days in a cell, or days of service.
- Never describe how anything illegal is actually done.

Return JSON only:
{"title":"...","text":"...","keywords":["...","..."],
 "penalty":{"type":"fine|jail|service","amount":50},
 "proposed_by":"dez","because":"MAX 12 WORDS naming the incident"}"""


def ensure(world):
    world.setdefault("laws", [])
    world.setdefault("charges", [])
    world.setdefault("law_pressure", 0)
    world.setdefault("last_law_day", -99)


def in_force(world):
    return [l for l in world.get("laws", []) if l.get("status") == "enacted"]


# ── pressure ─────────────────────────────────────────────────────────────────

def note_pressure(world, records):
    """Incidents the block might want a rule about. Deaths and fires weigh most."""
    add = 0
    for r in records:
        k = r.get("kind")
        if k == "death" and r.get("cause") in ("violence", "overdose"):
            add += 3
        elif k == "structure" and r.get("event") == "destroyed":
            add += 2
        elif k == "act" and r.get("action"):
            # Only things nothing already covers push towards new law.
            if not match_laws(world, r["action"]):
                if re.search(r"\b(steal|stole|threat|beat|burn|smash|rob|jump|cut|gun|knife)",
                             r["action"], re.I):
                    add += 1
    if add:
        world["law_pressure"] = world.get("law_pressure", 0) + add
    return add


def should_legislate(world, day):
    return (world.get("law_pressure", 0) >= PRESSURE_TO_LEGISLATE
            and day - world.get("last_law_day", -99) >= MIN_DAYS_BETWEEN_LAWS
            and len(in_force(world)) < MAX_LAWS)


# ── writing a law ────────────────────────────────────────────────────────────

def propose_law(world, agents, budget, day, beat, recent):
    """One law, from what has actually happened. Returns records."""
    ensure(world)
    living = [a for a in agents.values() if a.get("alive", True)]
    if not living or not recent:
        return []

    if not budget.can_afford(llm.FAST, LAW_TOKENS_PER_DAY):
        print("[law] no budget for legislation today.")
        return []

    people = "\n".join(f'[{a["id"]}] {a["name"]} — {a["role"]}'
                       for a in living[:18])
    laws = "\n".join(f'- {l["title"]}: {l["text"]}' for l in in_force(world)) or "(none yet)"
    incidents = "\n".join(f"- {t}" for t in recent[:12])

    prompt = (f"RECENT INCIDENTS ON THE BLOCK (day {day}):\n{incidents}\n\n"
              f"LAWS ALREADY IN FORCE:\n{laws}\n\n"
              f"PEOPLE:\n{people}\n\nWrite one new ordinance.")

    room = llm.fit_max_tokens(llm.FAST, len(LAW_SYSTEM) + len(prompt), want=420)
    try:
        text, used = llm.chat(
            [{"role": "system", "content": LAW_SYSTEM},
             {"role": "user", "content": prompt}],
            model=llm.FAST, max_tokens=room, temperature=0.8)
    except Exception as e:
        print(f"[law] drafting failed: {e}")
        return []
    budget.charge(llm.FAST, used)

    data = llm.parse_json(text)
    if not isinstance(data, dict) or not data.get("title"):
        print("[law] unparseable draft")
        return []

    body = f'{data.get("title","")} {data.get("text","")}'
    hit = llm.trips_guardrail(body)
    if hit:
        print(f"[law] draft tripped the guardrail on {hit!r} — discarded.")
        return []

    kws = [str(k).lower().strip() for k in (data.get("keywords") or []) if str(k).strip()]
    kws = [k for k in kws if 2 < len(k) < 24][:6]
    if not kws:
        print("[law] draft had no usable keywords — discarded.")
        return []

    pen = data.get("penalty") or {}
    ptype = pen.get("type") if pen.get("type") in ("fine", "jail", "service") else "fine"
    try:
        amount = max(1, min(500, int(pen.get("amount") or 50)))
    except (TypeError, ValueError):
        amount = 50
    if ptype in ("jail", "service"):
        amount = max(1, min(10, amount))

    proposer = data.get("proposed_by")
    if proposer not in agents or not agents[proposer].get("alive", True):
        proposer = max(living, key=lambda a: a["mood"].get("stress", 0))["id"]

    law = {
        "id": f"law{len(world['laws']) + 1:02d}",
        "title": str(data["title"])[:60],
        "text": str(data.get("text", ""))[:200],
        "keywords": kws,
        "penalty": {"type": ptype, "amount": amount},
        "proposed_by": proposer,
        "because": str(data.get("because", ""))[:90],
        "day_enacted": day, "status": "enacted", "convictions": 0,
    }
    world["laws"].append(law)
    world["last_law_day"] = day
    world["law_pressure"] = 0

    for a in agents.values():
        if a.get("alive", True):
            memory.remember(a, beat, day,
                            f'The block passed a rule: {law["title"]}.', 6)
    print(f'[law] day {day}: "{law["title"]}" ({ptype} {amount}), {used} tokens')
    return [{"kind": "law", "event": "enacted", "law": law["id"], "title": law["title"],
             "text": law["text"], "by": proposer, "day": day, "beat": beat,
             "text_log": f'{law["title"]} — {law["text"]}'}]


# ── enforcement ──────────────────────────────────────────────────────────────

def match_laws(world, action_text):
    """Which laws this action appears to break. Deterministic, cheap, runs every beat."""
    if not action_text:
        return []
    low = action_text.lower()
    out = []
    for l in in_force(world):
        if any(re.search(r"\b" + re.escape(k), low) for k in l["keywords"]):
            out.append(l)
    return out


def detect(world, agents, records, beat, day):
    """Scan what people just did for anything the block has outlawed."""
    ensure(world)
    out = []
    for r in records:
        if r.get("kind") != "act" or not r.get("action"):
            continue
        who = agents.get(r.get("who"))
        if not who or not who.get("alive", True) or who.get("detained_until"):
            continue
        for law in match_laws(world, r["action"]):
            if any(c["who"] == who["id"] and c["law"] == law["id"]
                   and c["status"] == "awaiting_trial" for c in world["charges"]):
                continue
            heat = (world.get("heat") or {}).get(
                (r.get("district") or "delmar"), 0)
            witnesses = sum(1 for a in agents.values()
                            if a.get("alive", True) and a["id"] != who["id"]
                            and a.get("at") == who.get("at"))
            # Being seen is what gets you charged, not what you did.
            caught = (heat / 220.0) + (witnesses * 0.09) + 0.06
            # random.Random, not hash(): Python salts hash() per process, so whether
            # somebody got arrested would differ between two runs of the same beat and the
            # city would stop being reproducible — the one property that makes a bug here
            # findable at all.
            roll = random.Random(f'{who["id"]}:{law["id"]}:{beat}').random()
            if roll > min(0.85, caught):
                continue
            charge = {
                "id": f'c{len(world["charges"]) + 1:03d}',
                "who": who["id"], "name": who["name"], "law": law["id"],
                "law_title": law["title"], "evidence": r["action"][:140],
                "day": day, "trial_day": day + TRIAL_DELAY,
                "status": "awaiting_trial", "witnesses": witnesses,
            }
            world["charges"].append(charge)
            who["detained_until"] = day + TRIAL_DELAY
            who["charged_with"] = law["title"]
            memory.remember(who, beat, day,
                            f'I was taken in over {law["title"]}.', 8)
            out.append({"kind": "charge", "who": who["id"], "name": who["name"],
                        "law": law["id"], "title": law["title"], "day": day, "beat": beat,
                        "text": f'{who["name"]} is taken to the 9th over {law["title"]}.'})
            break
    return out


# ── trial ────────────────────────────────────────────────────────────────────

def _jury(agents, accused_id, world):
    """Twelve is too many for thirty people. Take who is alive and has a view."""
    pool = [a for a in agents.values()
            if a.get("alive", True) and a["id"] != accused_id and not a.get("detained_until")]
    pool.sort(key=lambda a: a["id"])
    return pool[:9]


def try_cases(world, agents, beat, day):
    """Every case whose day has come. The jury is the block, and it votes its feelings."""
    ensure(world)
    out = []
    for c in world["charges"]:
        if c["status"] != "awaiting_trial" or day < c["trial_day"]:
            continue
        accused = agents.get(c["who"])
        law = next((l for l in world["laws"] if l["id"] == c["law"]), None)
        if not accused or not law:
            c["status"] = "dropped"
            continue
        if not accused.get("alive", True):
            c["status"] = "dropped"
            out.append({"kind": "verdict", "who": c["who"], "name": c["name"],
                        "verdict": "dropped", "day": day, "beat": beat,
                        "text": f'The case against {c["name"]} dies with them.'})
            continue

        jury = _jury(agents, accused["id"], world)
        guilty = 0
        for j in jury:
            aff = (j.get("relationships") or {}).get(accused["id"], {}).get("affinity", 0)
            # Fear of the block's own disorder pushes towards conviction; affection pulls away.
            lean = (j["mood"].get("fear", 0) + j["mood"].get("stress", 0)) / 2.0
            score = lean - aff - (c["witnesses"] * 4)
            if score < 30:
                guilty += 1
        convicted = guilty > len(jury) / 2 if jury else False

        accused.pop("charged_with", None)
        if convicted:
            law["convictions"] = law.get("convictions", 0) + 1
            rec = _sentence(world, accused, law, c, beat, day)
            c["status"], c["verdict"] = "convicted", "guilty"
            out.append(rec)
        else:
            c["status"], c["verdict"] = "acquitted", "not guilty"
            accused["detained_until"] = 0
            memory.remember(accused, beat, day, "They could not make it stick.", 7)
            out.append({"kind": "verdict", "who": accused["id"], "name": accused["name"],
                        "verdict": "acquitted", "law": law["id"], "day": day, "beat": beat,
                        "text": f'{accused["name"]} walks. {guilty} of {len(jury)} '
                                f'would have convicted.'})

        for a in agents.values():
            if a.get("alive", True) and a["id"] != accused["id"]:
                memory.remember(a, beat, day,
                                f'{accused["name"]} was '
                                f'{"convicted" if convicted else "acquitted"} '
                                f'over {law["title"]}.', 6)
    world["charges"] = [c for c in world["charges"]][-60:]
    return out


def _sentence(world, a, law, charge, beat, day):
    pen = law.get("penalty") or {}
    ptype, amount = pen.get("type", "fine"), pen.get("amount", 50)

    if ptype == "jail":
        a["detained_until"] = day + amount
        what = f"{amount} days in a cell"
    elif ptype == "service":
        a["detained_until"] = 0
        a["service_until"] = day + amount
        what = f"{amount} days of service to the block"
    else:
        a["detained_until"] = 0
        world.setdefault("debts", []).append({
            "id": f'fine{len(world.get("debts", [])) + 1}', "who": a["id"],
            "to": "the block", "kind": "money", "amount": amount,
            "reason": f'fine — {law["title"]}', "settled": False, "day": day})
        what = f"a ${amount} fine"

    a["mood"]["stress"] = min(100, a["mood"].get("stress", 0) + 18)
    a["mood"]["happiness"] = max(0, a["mood"].get("happiness", 0) - 15)
    memory.remember(a, beat, day, f'I was convicted over {law["title"]}: {what}.', 9)
    memory.prune(a)
    return {"kind": "verdict", "who": a["id"], "name": a["name"], "verdict": "convicted",
            "law": law["id"], "sentence": what, "day": day, "beat": beat,
            "text": f'{a["name"]} is convicted over {law["title"]} — {what}.'}


def release(agents, day, beat):
    """Let people out when their time is done."""
    out = []
    for a in agents.values():
        if a.get("detained_until") and day >= a["detained_until"]:
            a["detained_until"] = 0
            a.pop("charged_with", None)
            memory.remember(a, beat, day, "I came out today.", 7)
            out.append({"kind": "release", "who": a["id"], "name": a["name"],
                        "day": day, "beat": beat,
                        "text": f'{a["name"]} is back on the block.'})
        if a.get("service_until") and day >= a["service_until"]:
            a["service_until"] = 0
    return out


def detained(a):
    return bool(a.get("detained_until"))
