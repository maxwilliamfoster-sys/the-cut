"""
The Cut — what people decide to do about their situation.

One call per beat for the whole cast. Not one per character: at four beats a city-day and
a city-day an hour, per-character calls would spend a day's token allowance in about an
hour. Batching also buys something the per-character version cannot — the model sees the
whole block at once, so two people in the same room can be given a single coherent
exchange rather than two monologues written in ignorance of each other.

Nothing here decides the plot. It is handed a situation (who is where, how they feel, what
they remember, what just happened, who owes whom) and asked only what these particular
people would do next. The story is whatever falls out of that, compounded over days.
"""

import json

from . import city, llm, memory

SYSTEM = """You are the narrative engine for THE CUT, a simulated American city block.

You are given the entire cast for one six-hour stretch. For each person, decide what they
do next, based strictly on who they are, how they feel, what they remember, and what is
happening around them.

REGISTER
Prestige-television crime drama - The Wire, not a video game and not a thriller trailer.
Understated. People are tired, funny, petty, loyal, and mostly trying to get through a day.
Consequences land quietly and much later.

RULES
- STAY WHERE THEY ARE. The `at:` line is where that person physically is right now. The
  action must happen THERE. If a barber is at the diner he is not cutting hair; he is
  eating. If a nurse is at home she is not treating patients. This is the rule most often
  got wrong - check every action against the location before you write it.
- Small actions. A beat is somebody wiping a counter, avoiding a question, counting money
  twice. Dramatic events are rare and earned by what came before.
- Let people refuse, deflect, lie and hold grudges. Characters who agree with each other
  are boring and wrong. If two people have low affinity, it should show.
- TALK TO EACH OTHER. If anyone is listed as being with them, they should usually say
  something to one of those people. Two people in a room speak; that is what rooms are for.
  Most of the people who have company should have a `to` and a `says` this beat. Silence is
  for somebody marked ALONE, or for two people whose not-speaking is itself the point.
- Speech can only be aimed at somebody listed as with them. Never at an absent person.
- Where two people are together, it is good for them to answer each other — one addresses
  the other, and the other replies to them in the same beat.
- Vary the interior voice. Do not begin thoughts with "I have to" or "I need to" - most
  people are not narrating their own resolve. Let some thoughts be petty, funny, evasive,
  or about something else entirely.
- A memory must be a COMPLETE SENTENCE describing what actually happened and why it stuck.
  "Booker offered to buy the corner store and did not blink when I said no" is a memory.
  "Booker's offer" is not - never write a bare noun phrase.
- Only record a memory if this person would still be turning it over tomorrow. Importance
  1-3 routine, 4-6 notable, 7-8 significant, 9-10 life-changing. Most beats deserve no
  memory at all - return null. Do not invent a memory to fill the field.
- NEVER repeat anything from that person's `remembers:` list. That is what they already
  know. A memory records something that happened in THIS beat, or nothing at all.
- Return an entry for EVERY person listed. Never omit anyone.
- Crime stays NARRATIVE, never procedural. "He moved the package through the laundromat"
  is right. Never describe how anything illegal is actually made, built, or done.
- No sexual content. No slurs. Violence has weight and aftermath; it is never relished.

OUTPUT
Return JSON only, exactly this shape, one entry per person, using their exact id:

{"people":[{
  "id": "dez",
  "action": "third person, present tense, MAX 10 WORDS",
  "thought": "first person, MAX 16 WORDS",
  "to": "id of someone listed as WITH them — set this whenever they have company",
  "says": "what they say out loud, MAX 16 WORDS, required whenever `to` is set",
  "mood": {"stress": 5},
  "feels_about": {"malik": {"shift": -6, "opinion": "MAX 10 WORDS"}},
  "memory": {"what": "one sentence, MAX 18 WORDS", "importance": 6}
}]}

BE TERSE. The word limits are hard - overrunning them truncates the batch and the last
people listed lose their turn entirely.

mood keys: energy, happiness, stress, social_need, fear. Values -20..20; include only keys
that actually changed. Omit `feels_about` and `memory` entirely unless something happened -
on a normal beat most people have neither."""


# The whole cast will not fit in one call. Groq reserves prompt + reply against a 6,000
# token per-minute ceiling; thirty people costs roughly 8,000 and would also double the
# daily spend. So attention is rationed, and this decides who gets it.
COGNITION_SLOTS = 11


def select(world, agents, groups, pressures, event, beat, limit=COGNITION_SLOTS):
    """Who actually gets thought about this beat.

    Everybody already has an activity, so an unselected character is not idle — they are
    just not being narrated. Scoring favours the people the story is currently happening
    to, with a rotation term so nobody goes unheard for long.
    """
    overdue = {p["from_id"] for p in pressures if p.get("from_id")}
    touched = set((event or {}).get("targets") or [])
    spoken_to = {q["agent"] for q in (world.get("player_queue") or [])}

    scored = []
    for aid, a in agents.items():
        s = 0.0
        if a.get("principal"):
            s += 6
        if aid in touched:
            s += 9                                   # the event happened to them
        if aid in spoken_to:
            s += 12                                  # the player spoke to them
        if aid in overdue:
            s += 5
        here = len(groups.get(a["at"], []))
        s += min(here - 1, 3) * 2.0                  # people in a room together make scenes
        s += min(a["mood"]["stress"], 100) / 40.0
        s += min(a["mood"]["fear"], 100) / 50.0
        # Rotation: the longer since anyone paid attention, the louder they get.
        s += min((beat - a.get("last_thought_beat", -20)) * 0.45, 9)
        scored.append((s, aid))

    scored.sort(key=lambda t: (-t[0], t[1]))
    return [aid for _, aid in scored[:limit]]


def _people_block(agents, groups, beat, chosen):
    lines = []
    for aid in chosen:
        a = agents[aid]
        # Companions are listed WITH THEIR IDS. Previously this was names only, so when the
        # schema asked for `to` as an id the model had no way to supply one — the id of
        # somebody standing in the room never appeared anywhere in the prompt unless they
        # happened to be selected too. Dialogue collapsed to almost nothing and looked like
        # reticence; it was a missing identifier.
        here = [f'[{o}] {agents[o]["name"]}' for o in groups.get(a["at"], []) if o != aid]
        loc = city.LOCATIONS[a["at"]]["name"]
        m = a["mood"]

        # Everything here is rationed. The prompt and the reply share one 6,000-token
        # per-minute reservation, so every line spent describing somebody is a line the
        # model cannot spend answering. Two relationships and three memories is the point
        # where characters still behave like themselves.
        rels = sorted(a["relationships"].items(),
                      key=lambda kv: abs(kv[1]["affinity"]), reverse=True)[:2]
        rel_s = "; ".join(
            f'{agents[k]["name"].split()[-1]}{v["affinity"]:+d} "{v["opinion"]}"'
            for k, v in rels if k in agents)

        query = f'{loc} {" ".join(here)} {a["ambition"]}'
        mems = memory.retrieve(a, beat, query, k=3)
        mem_s = " | ".join(f'd{m2["day"]}: {m2["what"]}' for m2 in mems) or "nothing yet"

        # Only the stats that are actually notable — a mood sitting near its resting level
        # tells the model nothing and costs tokens on every character every beat.
        feels = [f"{k} {v}" for k, v in
                 (("drained", 100 - m["energy"]), ("unhappy", 100 - m["happiness"]),
                  ("stressed", m["stress"]), ("lonely", m["social_need"]), ("afraid", m["fear"]))
                 if v >= 55]

        lines.append(
            f'[{aid}] {a["name"]}, {a["age"]}, {a["role"]}\n'
            f'  is: {"; ".join(a["traits"][:3])}\n'
            f'  wants: {a["ambition"]}\n'
            f'  at: {loc}, currently {a.get("activity", "here")}'
            f'{(" — with " + ", ".join(here)) if here else " (ALONE)"}\n'
            f'  feels: {", ".join(feels) if feels else "steady"}\n'
            f'  thinks: {rel_s or "no strong views on anyone"}\n'
            f'  remembers: {mem_s}'
        )
    return "\n".join(lines)


def build_prompt(world, agents, groups, pressures, event, beat, day, block, chosen):
    heat = ", ".join(f'{city.DISTRICTS[d]["name"]} {v}' for d, v in world["heat"].items())
    debts = "; ".join(
        f'{p["from"]} owes {p["to"]} '
        f'{"$" + format(p["amount"], ",") if p["kind"] == "money" else p["kind"]}'
        f' ({p["days_overdue"]}d late)'
        for p in pressures) or "nothing overdue"

    # A stranger walking up and talking to you is one of the more notable things that can
    # happen on a quiet block, so it goes near the top rather than buried in a memory line.
    stranger = ""
    for ex in (world.get("player_queue") or []):
        stranger += (f'\nA stranger spoke to {ex["name"]}: "{ex["line"]}" '
                     f'and was told "{ex["reply"]}". They are still turning it over.')

    return (
        f"DAY {day}, {block}. Weather: {world['weather']}.\n"
        f"Police attention - {heat}.\n"
        f"Overdue - {debts}.\n"
        f"Just happened - {event['text'] if event else 'nothing anybody would write down'}"
        f"{stranger}\n\n"
        f"PEOPLE\n{_people_block(agents, groups, beat, chosen)}\n\n"
        f"Return JSON for all {len(chosen)} people."
    )


def rows_of(data):
    """Pull the per-person list out of whatever shape came back.

    Asking for {"people":[...]} gets you {"people":[...]} almost always — and then one run
    in fifty returns a bare array, or keys the objects by id. The bare-array case crashed
    the live city's cron for two hours with 'list object has no attribute get'. The
    response is untrusted input; treat it like it.
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("people", "agents", "results", "characters"):
            v = data.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        # {"dez": {...}, "malik": {...}} — id as the key rather than a field
        if data and all(isinstance(v, dict) for v in data.values()):
            return [dict(v, id=v.get("id", k)) for k, v in data.items()]
    return []


def _apply(agents, data, groups, beat, day, records, chosen):
    """Apply whatever came back. A malformed entry is skipped rather than failing the beat —
    losing one person's turn is survivable; losing the whole city's is not."""
    applied, seen = 0, set()
    for row in rows_of(data):
        aid = (row or {}).get("id")
        a = agents.get(aid)
        if not a or aid in seen or aid not in chosen:
            continue
        seen.add(aid)
        a["last_thought_beat"] = beat

        a["action"] = str(row.get("action") or a["action"])[:120]
        a["thought"] = str(row.get("thought") or "")[:220]

        # The model will happily have someone speak to a person on the other side of the
        # city — caught live: Dez addressed Malik from the laundromat while Malik was at
        # home two districts away. Only accept speech aimed at someone actually here.
        to, says = row.get("to"), row.get("says")
        present = set(groups.get(a["at"], []))
        # It still answers with a name every so often. Resolve it rather than dropping the
        # line — a rejected line is indistinguishable from a silent character.
        if to and to not in agents:
            want = str(to).strip().lower()
            to = next((o for o in present
                       if agents[o]["name"].lower() == want
                       or agents[o]["name"].split()[-1].lower() == want
                       or agents[o]["name"].split()[0].lower() == want), to)
        a["speech"] = ({"to": to, "text": str(says)[:220]}
                       if says and to in agents and to != aid and to in present else None)

        for k, dv in (row.get("mood") or {}).items():
            if k in a["mood"] and isinstance(dv, (int, float)):
                a["mood"][k] = max(0, min(100, a["mood"][k] + int(max(-20, min(20, dv)))))

        for other, chg in (row.get("feels_about") or {}).items():
            if other not in agents or other == aid or not isinstance(chg, dict):
                continue
            rel = a["relationships"].setdefault(
                other, {"affinity": 0, "opinion": "knows the face, not much else"})
            shift = chg.get("shift")
            if isinstance(shift, (int, float)):
                rel["affinity"] = max(-100, min(100, rel["affinity"] + int(max(-20, min(20, shift)))))
            if chg.get("opinion"):
                rel["opinion"] = str(chg["opinion"])[:110]

        mem = row.get("memory")
        if isinstance(mem, dict) and mem.get("what"):
            memory.remember(a, beat, day, mem["what"], mem.get("importance", 4))
        memory.prune(a)

        records.append({
            "beat": beat, "day": day, "kind": "act", "who": aid, "name": a["name"],
            "at": a["at"], "action": a["action"], "thought": a["thought"],
            "speech": a["speech"],
        })
        applied += 1

    # The model quietly drops someone from the batch now and then. They keep the activity
    # the deterministic layer already gave them — so a dropped character is doing the
    # washing up, not standing blankly — but they still get logged and still count as
    # having had their turn, or the rotation would keep re-picking them forever.
    for aid in chosen:
        if aid in seen:
            continue
        a = agents[aid]
        a["last_thought_beat"] = beat
        records.append({"beat": beat, "day": day, "kind": "act", "who": aid,
                        "name": a["name"], "at": a["at"], "action": a["action"],
                        "thought": "", "speech": None, "omitted": True})
    return applied


def make_cognition(budget, verbose=True):
    """Returns the callable tick.run_beat expects. Closes over the day's token budget so
    spend accumulates across every beat paid in this run."""

    def cognition(world, agents, groups, pressures, event, beat, day, block):
        records = []
        budget.ensure_day(day)
        chosen = select(world, agents, groups, pressures, event, beat)
        prompt = build_prompt(world, agents, groups, pressures, event, beat, day, block, chosen)

        # ~4 chars a token, plus room for the reply. If the day's allowance cannot cover
        # it, fall through to a quiet beat rather than half-applying a truncated response.
        estimate = len(SYSTEM + prompt) // 4 + 1200
        if not budget.can_afford(llm.FAST, estimate):
            if verbose:
                print(f"[cognition] budget exhausted for {llm.FAST} "
                      f"({budget.remaining(llm.FAST)} left, need ~{estimate}) — quiet beat.")
            return records

        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt}]
        reply_room = llm.fit_max_tokens(llm.FAST, len(SYSTEM) + len(prompt), want=2000)

        text, used = "", 0
        for attempt in range(2):
            try:
                text, used = llm.chat(messages, model=llm.FAST,
                                      max_tokens=reply_room, temperature=0.9)
            except Exception as e:
                print(f"[cognition] beat {beat} call failed: {e}")
                return records
            budget.charge(llm.FAST, used)

            hit = llm.trips_guardrail(text)
            if not hit:
                break
            print(f"[cognition] guardrail tripped on {hit!r} — retrying once, stricter.")
            if attempt == 0:
                messages.append({"role": "user", "content":
                                 "That drifted into describing how something illegal is done. "
                                 "Rewrite: reference it only in passing, never the method."})
            else:
                print("[cognition] still tripping — dropping this beat's cognition.")
                return records

        data = llm.parse_json(text)
        if not data:
            print(f"[cognition] beat {beat}: unparseable response ({len(text)} chars)")
            return records

        n = _apply(agents, data, groups, beat, day, records, chosen)
        if verbose:
            print(f"[cognition] beat {beat}: {n}/{len(chosen)} narrated "
                  f"(of {len(agents)} living), {used} tokens "
                  f"({budget.remaining(llm.FAST)} left today)")
        return records

    return cognition
