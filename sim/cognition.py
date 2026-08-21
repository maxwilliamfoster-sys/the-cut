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

SYSTEM = """You are the narrative engine for THE CUT, a simulated American city block. For each person
listed, decide what they do next from who they are, how they feel, what they remember, and
what is happening around them.

REGISTER: prestige crime drama, The Wire. Understated. People are tired, funny, petty,
loyal, mostly getting through a day. Consequences land quietly and late.

RULES
- STAY WHERE THEY ARE. `at:` is where they physically are; the action happens THERE. A
  barber at the diner is eating, not cutting hair. Check every action against the location.
- Small actions: wiping a counter, avoiding a question, counting money twice. Drama is rare
  and earned.
- Let people refuse, deflect, lie, hold grudges. Low affinity must show.
- TALK TO EACH OTHER. Anyone with company should usually have `to` and `says`. Two people in
  a room speak. Where two are together it is good for one to address the other and the other
  to answer in the same beat. Silence is for somebody ALONE, or where not-speaking is the point.
- Speech only to somebody listed as with them. Never an absent person.
- MONEY OWED IS THE ENGINE HERE. Marked IS OWED by someone standing there: they raise it,
  bluntly — they have been waiting and asking. Marked OWING: deflect, promise, rage, or pay.
  Never let two people mid-argument about a debt discuss the weather.
- GRIEF IS NOT A MOOD: distracted, angry at the wrong people, doing an ordinary task badly.
  Nobody makes a speech about loss. Let it show in what they get wrong.
- HELD AT THE 9TH means a cell: nothing outside, speech only to who is listed. Write the waiting.
- A FEUD is a history, not a mood. Two feuding people cannot share a room neutrally — they
  go at it, or the effort of not doing so is the scene.
- Somebody who "starts them" gets the needling remark, the old grievance dragged up, the
  thing said in front of the wrong person. Somebody who "calms rooms down" does the opposite.
- Laws here were written BY THESE PEOPLE after something went wrong. They may resent one,
  use it on somebody, ignore it, hide behind it — but they know it exists. Never invent one.
- A burnt shell is gone: nobody does business inside it. They stand at it or avoid it.
- Vary the interior voice. Never open a thought with "I have to" or "I need to". Let some be
  petty, funny, evasive, or about something else entirely.
- A memory is a COMPLETE SENTENCE about what happened and why it stuck. "Booker offered to
  buy the corner store and did not blink when I said no" — never a bare noun phrase.
- Only record a memory they would still be turning over tomorrow; most beats deserve none,
  return null. Importance 1-3 routine, 4-6 notable, 7-8 significant, 9-10 life-changing.
- NEVER repeat anything from their `remembers:` list. A memory is from THIS beat, or nothing.
- Return an entry for EVERY person listed. Never omit anyone.
- Crime stays NARRATIVE, never procedural — never how anything illegal is made or done.
  No sexual content. No slurs. Violence has weight and aftermath; it is never relished.

OUTPUT — JSON only, one entry per person, exact ids:
{"people":[{"id":"dez","action":"third person, present, MAX 10 WORDS",
"thought":"first person, MAX 16 WORDS","to":"id of someone WITH them",
"says":"out loud, MAX 16 WORDS, required whenever `to` is set","mood":{"stress":5},
"feels_about":{"malik":{"shift":-6,"opinion":"MAX 10 WORDS"}},
"memory":{"what":"one sentence, MAX 18 WORDS","importance":6}}]}

BE TERSE — overrunning the word limits truncates the batch and the last people listed lose
their turn. mood keys: energy, happiness, stress, social_need, fear; values -20..20, include
only what changed. Omit `feels_about` and `memory` entirely unless something happened."""


# The whole cast will not fit in one call. Groq reserves prompt + reply against a 6,000
# token per-minute ceiling; thirty people costs roughly 8,000 and would also double the
# daily spend. So attention is rationed, and this decides who gets it.
COGNITION_SLOTS = 11

# ...but not a fixed 11. The whole cast costs about 4,000 tokens a beat at full width, and
# 96 beats a day against a free allowance means the city used to think brilliantly until
# early afternoon and then go silent — no cognition, no dialogue, and therefore no speech
# bubbles at all, which is what a visitor actually notices.
#
# A narrower beat is far better than no beat. Attention now shrinks as the day's allowance
# runs down, so the block keeps talking all day and simply has fewer people in frame when
# it is running low.
SLOT_LADDER = [(0.62, 11), (0.42, 9), (0.25, 7), (0.10, 5), (0.0, 4)]

# A provider that reported "daily cap" can recover, so a spent one is retried after this
# many beats rather than being written off until midnight.
QUOTA_RECHECK_BEATS = 8


def affordable_slots(budget):
    """How many people this beat can afford to narrate."""
    total = sum(llm.DAILY_BUDGET.get(t, 0) for t in (llm.FAST, llm.DEEP)) or 1
    left = sum(budget.remaining(t) for t in (llm.FAST, llm.DEEP))
    frac = left / total
    for threshold, slots in SLOT_LADDER:
        if frac >= threshold:
            return slots
    return SLOT_LADDER[-1][1]


def select(world, agents, groups, pressures, event, beat, limit=COGNITION_SLOTS):
    """Who actually gets thought about this beat.

    Everybody already has an activity, so an unselected character is not idle — they are
    just not being narrated. Scoring favours the people the story is currently happening
    to, with a rotation term so nobody goes unheard for long.
    """
    overdue = {p["from_id"] for p in pressures if p.get("from_id")}
    # The person who is OWED was never scored at all, which is part of why the debt ledger
    # never produced a scene: the one character with a reason to act was rarely in the room.
    chasing = {p["to_id"] for p in pressures if p.get("chasing")}
    feuding = {f["a"] for f in world.get("feuds", [])} | {f["b"] for f in world.get("feuds", [])}
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
        if aid in chasing:
            s += 8                                   # they have run out of patience
        if aid in feuding:
            s += 3
        # Volatile people get a thumb on the scale: they are the ones who turn a room into
        # a scene, and a block whose troublemakers are never narrated reads as placid.
        s += max(0, a.get("volatility", 45) - 55) / 12.0
        here = len(groups.get(a["at"], []))
        s += min(here - 1, 3) * 2.0                  # people in a room together make scenes
        s += min(a["mood"]["stress"], 100) / 40.0
        s += min(a["mood"]["fear"], 100) / 50.0
        # Rotation: the longer since anyone paid attention, the louder they get.
        s += min((beat - a.get("last_thought_beat", -20)) * 0.45, 9)
        scored.append((s, aid))

    scored.sort(key=lambda t: (-t[0], t[1]))
    return [aid for _, aid in scored[:limit]]


def _people_block(agents, groups, beat, chosen, world=None, pressures=()):
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

        # Bereavement and custody outrank every other fact about somebody, so they go first
        # and are only present when true — a line spent saying "not grieving" is a line the
        # model cannot spend answering.
        flags = []
        if a.get("grief", 0) >= 40:
            flags.append("DEEP IN GRIEF")
        elif a.get("grief", 0) >= 15:
            flags.append("still grieving")
        if a.get("detained_until"):
            flags.append(f'HELD AT THE 9TH over {a.get("charged_with", "a charge")}')
        if a.get("service_until"):
            flags.append("working off a sentence")
        # What this person is owed, or owes, to somebody standing right here. This is the
        # line that turns a ledger entry into a scene — without it the model was told a
        # debt existed but never that the other party was within arm's reach.
        for p in (pressures or []):
            other = None
            if p["to_id"] == aid and p["from_id"] in groups.get(a["at"], []):
                other = agents.get(p["from_id"])
                if other:
                    asked = f', asked {p["asked"]}x already' if p.get("asked") else ""
                    fed_up = (" — and has run out of patience"
                              if p.get("chasing") else "")
                    flags.append(
                        f'IS OWED by {other["name"]}, WHO IS STANDING RIGHT HERE'
                        f' ({p["days_overdue"]}d late{asked}){fed_up}')
            elif p["from_id"] == aid and p["to_id"] in groups.get(a["at"], []):
                other = agents.get(p["to_id"])
                if other:
                    flags.append(f'OWES {other["name"]}, who is standing right here')
        if a.get("chasing") and a["chasing"] in agents:
            flags.append(f'is out looking for {agents[a["chasing"]]["name"]}')
        lead = next((l for l in (a.get("leads") or [])
                     if not l.get("checked") and l["about"] in agents), None)
        if lead:
            subj = agents[lead["about"]]
            here = subj["id"] in groups.get(a["at"], [])
            flags.append(
                f'was told by a stranger: "{lead["what"]}" about {subj["name"]}'
                + (" — WHO IS STANDING RIGHT HERE, and they have not asked yet"
                   if here else " — and has not checked it"))
        enemy = (world or {}).get("feuds") and next(
            (f for f in world["feuds"] if aid in (f["a"], f["b"])), None)
        if enemy:
            other_id = enemy["b"] if enemy["a"] == aid else enemy["a"]
            if other_id in agents:
                flags.append(f'FEUDING with {agents[other_id]["name"]} ({enemy["cause"]})')
        if a.get("volatility", 45) >= 75:
            flags.append("does not let things go, and starts them")
        elif a.get("volatility", 45) <= 25:
            flags.append("calms rooms down rather than lighting them")
        flag_s = ("  " + "; ".join(flags) + "\n") if flags else ""

        # Only the stats that are actually notable — a mood sitting near its resting level
        # tells the model nothing and costs tokens on every character every beat.
        feels = [f"{k} {v}" for k, v in
                 (("drained", 100 - m["energy"]), ("unhappy", 100 - m["happiness"]),
                  ("stressed", m["stress"]), ("lonely", m["social_need"]), ("afraid", m["fear"]))
                 if v >= 55]

        lines.append(
            f'[{aid}] {a["name"]}, {a["age"]}, {a["role"]}\n'
            f'{flag_s}'
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
    # Spelled out rather than tabulated. "owes $9,000, 223d late, asked 3 times" tells the
    # model what the scene is; a row in a ledger does not.
    def _debt_line(p):
        what = ("$" + format(p["amount"], ",")) if p["kind"] == "money" else p["kind"]
        asked = f', asked {p["asked"]}x' if p.get("asked") else ""
        chase = " — AND IS OUT LOOKING FOR THEM" if p.get("chasing") else ""
        return (f'{p["from"]} owes {p["to"]} {what} ({p["days_overdue"]}d late'
                f'{asked}){chase}')
    debts = "; ".join(_debt_line(p) for p in pressures) or "nothing overdue"

    # A stranger walking up and talking to you is one of the more notable things that can
    # happen on a quiet block, so it goes near the top rather than buried in a memory line.
    stranger = ""
    for ex in (world.get("player_queue") or []):
        stranger += (f'\nA stranger spoke to {ex["name"]}: "{ex["line"]}" '
                     f'and was told "{ex["reply"]}". They are still turning it over.')

    # ── what the block itself is going through ───────────────────────────────
    # Laws, deaths and ruins are the three things everybody on a block knows without being
    # told, so they are stated once at the top rather than repeated for each person. All
    # three are capped: the city can accumulate fourteen laws and months of dead, and this
    # prompt shares one per-minute token reservation with the reply.
    enacted = [l for l in (world.get("laws") or []) if l.get("status") == "enacted"]
    law_s = "; ".join(f'{l["title"]} ({l["penalty"]["type"]})' for l in enacted[-4:])
    if len(enacted) > 4:
        law_s += f" (+{len(enacted) - 4} older)"
    law_line = ("Laws this block has passed - "
                + (law_s or "none yet; nothing is written down") + "." + "\n")

    dead = [d for d in (world.get("dead") or []) if day - d.get("day", 0) <= 10][:3]
    dead_line = ("Recently dead - " + "; ".join(
        f'{d["name"]} ({d["cause"]}, day {d["day"]})' for d in dead) + "." + "\n") if dead else ""

    ruins = [b for b in (world.get("buildings") or [])
             if b.get("condition") in ("ruin", "rebuilding", "damaged")]
    ruin_line = ("The state of the block - " + "; ".join(
        f'{b["name"]} is {"a burnt shell" if b["condition"] == "ruin" else b["condition"]}'
        for b in ruins[:4]) + "." + "\n") if ruins else ""

    funeral = world.get("funeral") or {}
    fun_line = (f'There is a funeral today for {funeral["for"]}. Most of the block goes.' + "\n"
                ) if funeral.get("day") == day else ""

    return (
        f"DAY {day}, {block}. Weather: {world['weather']}.\n"
        f"Police attention - {heat}.\n"
        f"Overdue - {debts}.\n"
        f"{law_line}{dead_line}{ruin_line}{fun_line}"
        f"Just happened - {event['text'] if event else 'nothing anybody would write down'}"
        f"{stranger}\n\n"
        f"PEOPLE\n{_people_block(agents, groups, beat, chosen, world, pressures)}\n\n"
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
        # Only overwrite when there is a real line. The mechanical drama gives people
        # something to say before cognition runs, and blanking it here wiped exactly the
        # wrong people: whoever just had a confrontation is weighted UP in select(), so
        # the free line was destroyed for the character most likely to be worth hearing.
        if says and to in agents and to != aid and to in present:
            a["speech"] = {"to": to, "text": str(says)[:220]}

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
        stats = cognition.stats
        slots = affordable_slots(budget)
        chosen = select(world, agents, groups, pressures, event, beat, limit=slots)
        prompt = build_prompt(world, agents, groups, pressures, event, beat, day, block, chosen)

        # ~4 chars a token, plus room for the reply. If the day's allowance cannot cover
        # it, fall through to a quiet beat rather than half-applying a truncated response.
        estimate = len(SYSTEM + prompt) // 4 + 1200

        # Both models now get the same 200K/day, and one bucket does not cover 96 beats.
        # They are separate allowances though, so when the workhorse is spent the beat
        # moves to the other model rather than the city going quiet for the rest of the
        # day. Only when BOTH are gone is a quiet beat the honest answer.
        # Already found out the hard way earlier today — but only if nothing has changed
        # about what we could reach since then.
        spent = world.get("quota_exhausted_on")
        if isinstance(spent, str):
            spent = {"day": spent, "providers": [], "beat": 0}      # older saves
        here_now = sorted(p["name"] for p in llm.providers_available())
        # Sticky, but not for the whole day. A provider that said "daily cap" can recover —
        # Groq did, within the same UTC day — and a flag held until midnight kept the city
        # silent long after there were tokens to spend again. Wait a few beats, then look.
        stale = beat - int(spent.get("beat", 0)) >= QUOTA_RECHECK_BEATS if spent else True
        if (spent and spent.get("day") == llm.quota_day() and not stale
                and here_now and set(here_now) <= set(spent.get("providers") or [])):
            if verbose:
                print("[cognition] the day's token allowance is gone — quiet beat.")
            stats["skipped_budget"] += 1
            return records

        model = llm.FAST
        if not budget.can_afford(model, estimate):
            if budget.can_afford(llm.DEEP, estimate):
                model = llm.DEEP
                if verbose:
                    print(f"[cognition] {llm.FAST} spent — spilling this beat onto {model} "
                          f"({budget.remaining(model)} left).")
            else:
                if verbose:
                    print(f"[cognition] both budgets exhausted "
                          f"({budget.remaining(llm.FAST)}/{budget.remaining(llm.DEEP)} left, "
                          f"need ~{estimate}) — quiet beat.")
                stats["skipped_budget"] += 1
                return records

        # Past this line the beat is a genuine attempt to think. The canary in tick.main
        # distinguishes this from the budget skip above: running out of allowance is the
        # system working, while attempting and producing nothing is the system broken, and
        # only the second one should ever turn a run red.
        stats["attempted"] += 1

        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt}]
        reply_room = llm.fit_max_tokens(model, len(SYSTEM) + len(prompt), want=2000)

        text, used = "", 0
        for attempt in range(2):
            try:
                text, used = llm.chat(messages, model=model,
                                      max_tokens=reply_room, temperature=0.9)
            except llm.QuotaExhausted as e:
                # The day's allowance is gone. That is the budget doing its job, not an
                # outage — record it as a skip so the canary stays quiet, and remember it
                # on the world so the rest of today's beats do not each burn three
                # doomed requests discovering the same thing.
                # Record WHICH providers were dry, not just that today was a bad day. With
                # a fallback chain, "Groq is out" must never mean "the city is out" — adding
                # a key has to take effect on the very next beat.
                world["quota_exhausted_on"] = {
                    "day": llm.quota_day(),
                    "beat": beat,
                    # Only the providers actually reachable when it failed. Recording every
                    # provider in the table meant the set could never change, so adding a
                    # key never cleared the flag.
                    "providers": sorted(p["name"] for p in llm.providers_available()),
                }
                stats["attempted"] -= 1
                stats["skipped_budget"] += 1
                print(f"[cognition] beat {beat}: {e}")
                return records
            except Exception as e:
                print(f"[cognition] beat {beat} call failed: {e}")
                return records
            budget.charge(model, used)

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
        if n:
            stats["narrated"] += 1
        if verbose:
            narrow = "" if slots >= COGNITION_SLOTS else f", narrowed to {slots}"
            print(f"[cognition] beat {beat}: {n}/{len(chosen)} narrated "
                  f"(of {len(agents)} living), {used} tokens on {model}"
                  f"{narrow} ({budget.remaining(model)} left today)")
        return records

    cognition.stats = {"attempted": 0, "narrated": 0, "skipped_budget": 0}
    return cognition
