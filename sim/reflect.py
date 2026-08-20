"""
The Cut — the end of a day.

Two things happen when a city-day closes.

**Reflection** is what turns a pile of incidents into a character. During the day people
record what happened to them; at night they decide what it *meant*. "Ruiz asked about my
father twice" and "a stranger knew about the shop" are two memories; "somebody is building
a case against Dad" is a belief, and beliefs are what change how a person behaves next
week. Without this the cast has perfect recall and no interpretation, which reads as
uncanny rather than alive.

**The Gazette** is the same day written from the outside. It is the single highest-value
thing for somebody returning to a city that ran without them: not a diff, a front page.

Model split is forced by the budget rather than chosen. Both models now get 200K tokens a
day, and there are 24 city-days in a real day, so neither allowance is big enough to be
spent casually. Reflection — a summarising job the small model does perfectly well — runs
on FAST, and the Gazette gets DEEP, so the scarcer, better model is spent where prose
quality is the whole point.
"""

import json
import os

from . import cognition, llm, memory, state

REFLECT_SYSTEM = """You are the reflective layer of THE CUT, a simulated American city block.

A day has ended. For each person you are given what they will remember from today. Decide
what they now BELIEVE — the conclusion they have drawn, which is not the same as what
happened.

RULES
- A belief is an interpretation, not a summary. Given a day of "the landlord came by twice"
  and "the rent went up", the memory is those events; the belief is "they are trying to
  push us out". Write the belief, not the events.
- The line above is an ILLUSTRATION of the difference. Never output it, or any wording from
  it, as somebody's belief. Every belief must come from that person's own day.
- Beliefs can be wrong. People draw the conclusion their fears and loyalties point at, not
  the correct one. A frightened person concludes something a calm one would not.
- If nothing today would change how this person sees anything, return belief: null. A quiet
  day should produce no belief at all.
- Only revise `ambition` when the day genuinely moved somebody - a betrayal, a threat, an
  unexpected kindness. Most days, omit it.
- MAX 20 WORDS per belief. Be terse.
- Never describe how anything illegal is actually done.

Return JSON only:
{"people":[{"id":"dez","belief":"what they now think is true, or null",
            "ambition":"only if it genuinely changed, else omit",
            "feels_about":{"malik":{"shift":-8,"opinion":"MAX 10 WORDS"}}}]}"""

GAZETTE_SYSTEM = """You write the front page of a small American city newspaper covering one
block: THE CUT GAZETTE. You are given a log of one day.

Write a SHORT front page in markdown:
- one headline (## ), six words or fewer, about the most CONSEQUENTIAL thing in the log -
  who did what to whom. Never headline the weather; a small paper leads on people.
- two or three short items, 1-2 sentences each, each with a bold lead-in
- a closing one-line "Also on the block:" with a single wry observation

Local-paper register: plain, slightly dry, faintly nosy. Report only what is in the log -
never invent an event. Where the log is thin, say so in the paper's own voice rather than
inventing drama. Names as given. No sensationalism, no gore, and never describe how
anything illegal is done. Under 160 words total."""


def _today(agent, day):
    return [m for m in (agent.get("memories") or []) if m.get("day") == day]


def reflect(world, agents, budget, day, beat):
    """One batched call. Returns log records."""
    budget.ensure_day(day)

    lines = []
    for aid in sorted(agents):
        a = agents[aid]
        mems = _today(a, day)
        if not mems:
            continue
        m = a["mood"]
        lines.append(
            f'[{aid}] {a["name"]} - {"; ".join(a["traits"][:2])}\n'
            f'  wants: {a["ambition"]}\n'
            f'  today: {" | ".join(x["what"] for x in mems[-5:])}\n'
            f'  ends the day: stress {m["stress"]}, fear {m["fear"]}, happiness {m["happiness"]}'
        )

    if not lines:
        print("[reflect] nobody had a day worth interpreting.")
        return []

    prompt = f"END OF DAY {day}.\n\n" + "\n".join(lines) + \
             f"\n\nReturn JSON for these {len(lines)} people."
    room = llm.fit_max_tokens(llm.FAST, len(REFLECT_SYSTEM) + len(prompt), want=1200)
    if not budget.can_afford(llm.FAST, (len(REFLECT_SYSTEM + prompt)) // 4 + room):
        print("[reflect] no budget left today — skipping.")
        return []

    try:
        text, used = llm.chat(
            [{"role": "system", "content": REFLECT_SYSTEM},
             {"role": "user", "content": prompt}],
            model=llm.FAST, max_tokens=room, temperature=0.85)
    except Exception as e:
        print(f"[reflect] failed: {e}")
        return []
    budget.charge(llm.FAST, used)

    data = llm.parse_json(text)
    if not data:
        print("[reflect] unparseable response")
        return []

    records, n = [], 0
    for row in cognition.rows_of(data):
        a = agents.get((row or {}).get("id"))
        if not a:
            continue
        belief = (row.get("belief") or "").strip()
        if belief and belief.lower() not in ("null", "none"):
            # Stored as a high-importance memory so retrieval surfaces it for days: a
            # conclusion should outlive the incidents that produced it.
            memory.remember(a, beat, day, belief, 8)
            memory.prune(a)
            a["belief"] = belief
            n += 1
            records.append({"beat": beat, "day": day, "kind": "belief",
                            "who": a["id"], "name": a["name"], "belief": belief})

        amb = (row.get("ambition") or "").strip()
        if amb and len(amb) > 8 and amb != a["ambition"]:
            records.append({"beat": beat, "day": day, "kind": "ambition", "who": a["id"],
                            "name": a["name"], "from": a["ambition"], "to": amb[:140]})
            a["ambition"] = amb[:140]

        for other, chg in (row.get("feels_about") or {}).items():
            if other not in agents or other == a["id"] or not isinstance(chg, dict):
                continue
            rel = a["relationships"].setdefault(
                other, {"affinity": 0, "opinion": "knows the face, not much else"})
            sh = chg.get("shift")
            if isinstance(sh, (int, float)):
                rel["affinity"] = max(-100, min(100, rel["affinity"] + int(max(-20, min(20, sh)))))
            if chg.get("opinion"):
                rel["opinion"] = str(chg["opinion"])[:110]

    print(f"[reflect] day {day}: {n} beliefs formed, {used} tokens")
    return records


def gazette(world, agents, budget, day, records_today, dry_run=False):
    """Write the day's front page. Returns log records."""
    path = os.path.join(state.GAZETTE_DIR, f"day-{day:03d}.md")
    if os.path.exists(path) or world.get("last_gazette_day", -1) >= day:
        return []

    events, acts, said, beliefs = [], [], [], []
    for r in records_today:
        if r.get("event"):
            events.append(r["event"])
        elif r.get("kind") == "act":
            if r.get("speech") and r["speech"].get("text"):
                said.append(f'{r["name"]}: "{r["speech"]["text"]}"')
            elif r.get("action"):
                acts.append(f'{r["name"]} {r["action"]}')
        elif r.get("kind") == "belief":
            beliefs.append(f'{r["name"]} has decided: {r["belief"]}')
        elif r.get("kind") == "player":
            said.append(f'A stranger asked {r["name"]}: "{r["line"]}"')

    if not (events or said or beliefs):
        return []

    body = (
        f"DAY {day} on the block. Weather {world['weather']}. "
        f"Police attention: {', '.join(f'{k} {v}' for k, v in world['heat'].items())}.\n\n"
        f"WHAT HAPPENED\n" + ("\n".join(f"- {e}" for e in events[:8]) or "- nothing reported") +
        f"\n\nOVERHEARD\n" + ("\n".join(f"- {s}" for s in said[-10:]) or "- nothing worth repeating") +
        f"\n\nPEOPLE ARE SAYING\n" + ("\n".join(f"- {b}" for b in beliefs[:6]) or "- little") +
        f"\n\nSEEN AROUND\n" + "\n".join(f"- {a}" for a in acts[-6:])
    )

    room = llm.fit_max_tokens(llm.DEEP, len(GAZETTE_SYSTEM) + len(body), want=520)
    est = (len(GAZETTE_SYSTEM + body)) // 4 + room
    model = llm.DEEP
    if not budget.can_afford(llm.DEEP, est):
        # The good model is the whole point of the Gazette, but a plain front page beats
        # no front page at all.
        print(f"[gazette] 70b budget spent ({budget.remaining(llm.DEEP)} left) — falling back to 8b.")
        model = llm.FAST
        room = llm.fit_max_tokens(llm.FAST, len(GAZETTE_SYSTEM) + len(body), want=520)
        if not budget.can_afford(llm.FAST, (len(GAZETTE_SYSTEM + body)) // 4 + room):
            return []

    try:
        text, used = llm.chat(
            [{"role": "system", "content": GAZETTE_SYSTEM},
             {"role": "user", "content": body}],
            model=model, max_tokens=room, temperature=0.85, json_mode=False)
    except Exception as e:
        print(f"[gazette] failed: {e}")
        return []
    budget.charge(model, used)

    page = (text or "").strip()
    if not page:
        return []
    if llm.trips_guardrail(page):
        print("[gazette] guardrail tripped — front page withheld.")
        return []

    # The Gazette writes its own file rather than going through state.save_*, so it used
    # to slip past --dry-run entirely and leave a real front page on disk under a run that
    # had just printed "nothing written". A dry run that quietly writes is worse than no
    # dry run at all.
    if dry_run:
        print(f"[gazette] --dry-run: day {day} front page not written to disk.")
    else:
        os.makedirs(state.GAZETTE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"*The Cut Gazette — day {day}*\n\n{page}\n")
        world["last_gazette_day"] = day

    headline = next((l.lstrip("# ").strip() for l in page.splitlines()
                     if l.strip().startswith("#")), "The day on the block")
    print(f"[gazette] day {day} ({model}, {used} tokens): {headline}")
    return [{"beat": world["beat"], "day": day, "kind": "gazette",
             "headline": headline, "path": f"state/gazette/day-{day:03d}.md"}]
