"""
The Cut — invariant checks.

These cover the things that fail silently and would only be noticed days later, when the
city's clock had quietly drifted away from reality or a long outage had blown the token
budget. Run before enabling the cron, and after touching sim/clock.py.

    py selftest.py
"""

import copy
import sys
from datetime import timedelta

from sim import city, clock, cognition, events, llm, reflect, state, tick

FAILS = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  — ' + detail if detail and not cond else ''}")
    if not cond:
        FAILS.append(name)


# ── clock ────────────────────────────────────────────────────────────────────

start = clock.iso(clock.now_utc() - timedelta(seconds=clock.BEAT_SECONDS * 7 + 200))
check("beats_owed counts whole beats only",
      clock.beats_owed(start) == 7, f"got {clock.beats_owed(start)}")

check("beats_owed is 0 before a full beat elapses",
      clock.beats_owed(clock.iso(clock.now_utc())) == 0)

# No drift: paying N beats must move the marker by exactly N*BEAT_SECONDS, never to `now`.
# Jumping to `now` would discard the sub-beat remainder and lose ~7 minutes of city time
# on every single run, which compounds to hours a day.
before = clock.parse(start)
after = clock.parse(clock.advance(start, 7))
check("advance() does not drift",
      (after - before).total_seconds() == 7 * clock.BEAT_SECONDS,
      f"moved {(after - before).total_seconds()}s")

remainder_start = clock.advance(start, 7)
check("sub-beat remainder carries to the next run",
      clock.beats_owed(remainder_start) == 0)

# A marker in the future makes beats_owed return 0 for as long as the drift lasts, so the
# city freezes with no error anywhere. Caught in production after `--owe` testing left it
# two hours ahead; tick.py now detects the drift and pulls the marker back.
check("a future last_beat_at owes nothing (so it must be detected, not ignored)",
      clock.beats_owed(clock.iso(clock.now_utc() + timedelta(hours=2))) == 0)

check("split() leaves a short backlog fully narrated", clock.split(6) == (0, 6))
check("split() caps cognition on a long outage",
      clock.split(200) == (200 - clock.MAX_COGNITION_BEATS, clock.MAX_COGNITION_BEATS),
      f"got {clock.split(200)}")

check("a real hour is a city day",
      3600 // clock.BEAT_SECONDS == clock.BEATS_PER_DAY)
check("day/block indexing lines up",
      clock.day_of(4) == 1 and clock.block_of(4) == "morning" and clock.is_day_end(3))


# ── city ─────────────────────────────────────────────────────────────────────

anchors = {k: tuple(v["anchor"]) for k, v in city.LOCATIONS.items()}
check("every location anchor is walkable",
      all(city.walkable(*a) for a in anchors.values()))

unreachable = [(a, b) for a in anchors for b in anchors
               if a < b and len(city.path(anchors[a], anchors[b])) < 2]
check("every location reaches every other", not unreachable, f"{unreachable[:3]}")

check("every routine target is a real location",
      all(loc in city.LOCATIONS
          for spec in __import__("sim.roster", fromlist=["ROSTER"]).ROSTER
          for loc in spec["routine"].values()))


# ── simulation ───────────────────────────────────────────────────────────────

world = state.load_world()
agents = state.load_agents()

if not world:
    check("state exists (run --bootstrap first)", False)
else:
    w, a = copy.deepcopy(world), copy.deepcopy(agents)

    # Relationships are sparse by design — filling all 30x29 pairs with "knows the face"
    # would be most of agents.json and most of every diff, saying nothing.
    check("relationships only reference real people",
          all(k in a for x in a.values() for k in x["relationships"]))
    check("everyone has at least one authored tie or none at all",
          all(isinstance(x["relationships"], dict) for x in a.values()))
    check("every home and workplace is a real location",
          all(x["home"] in city.LOCATIONS and x["work"] in city.LOCATIONS for x in a.values()))

    # Determinism: same seed + same beat must produce the same city, or no bug is ever
    # reproducible and an interesting week can never be replayed.
    w1, a1 = copy.deepcopy(w), copy.deepcopy(a)
    w2, a2 = copy.deepcopy(w), copy.deepcopy(a)
    for _ in range(8):
        tick.run_beat(w1, a1)
        tick.run_beat(w2, a2)
    check("beats are deterministic under a fixed seed",
          [x["pos"] for x in a1.values()] == [x["pos"] for x in a2.values()]
          and w1["weather"] == w2["weather"] and w1["heat"] == w2["heat"])

    w3, a3 = copy.deepcopy(w), copy.deepcopy(a)
    for _ in range(120):
        tick.run_beat(w3, a3)
    moods = [v for x in a3.values() for v in x["mood"].values()]
    check("moods stay inside 0..100 over 30 city-days",
          all(0 <= m <= 100 for m in moods), f"range {min(moods)}..{max(moods)}")
    check("heat stays inside 0..100",
          all(0 <= h <= 100 for h in w3["heat"].values()), f"{w3['heat']}")
    check("everyone is somewhere real after 120 beats",
          all(x["at"] in city.LOCATIONS for x in a3.values()))
    check("nobody is stranded off-grid",
          all(city.walkable(*x["pos"]) for x in a3.values()))

    # Both heat and stress/fear originally decayed faster than the event table could feed
    # them, so they sat pinned at their floor forever: dead bars in the UI and, worse, a
    # character snapshot that never reflected a bad week. Sample the whole run and insist
    # every stat actually moves.
    samples = {k: [] for k in state.MOOD_KEYS}
    heat_samples = []
    w4, a4 = copy.deepcopy(w), copy.deepcopy(a)
    for _ in range(160):
        tick.run_beat(w4, a4)
        for x in a4.values():
            for k in state.MOOD_KEYS:
                samples[k].append(x["mood"][k])
        heat_samples.extend(w4["heat"].values())

    for k, vals in samples.items():
        spread = max(vals) - min(vals)
        pinned = all(v == vals[0] for v in vals)
        check(f"mood '{k}' is a live system, not pinned",
              spread >= 10 and not pinned, f"spread {spread}, min {min(vals)}, max {max(vals)}")

    check("police heat actually moves",
          max(heat_samples) - min(heat_samples) >= 8,
          f"range {min(heat_samples)}..{max(heat_samples)}")

    visited = {loc for x in a3.values() for loc in [x["at"]]}
    check("the cast actually spreads across the map", len(visited) >= 8, f"only {visited}")

    # The whole point of the activity layer: nobody is ever just standing there.
    idle = [x["name"] for x in a3.values() if not (x.get("activity") or "").strip()]
    check("everybody is always doing something", not idle, f"{idle[:4]}")

    # And what they are doing has to be possible where they are standing.
    misplaced = [(x["name"], x["activity"]) for x in a3.values()
                 if x.get("spot") and not city.walkable(*x["spot"])]
    check("activity spots are all reachable", not misplaced, f"{misplaced[:3]}")

    # Rotation fairness: over a couple of city-days nobody should go completely unheard.
    w6, a6 = copy.deepcopy(w), copy.deepcopy(a)
    heard = set()
    for _ in range(10):
        g6 = tick.colocation(a6)
        for aid in cognition.select(w6, a6, g6, [], None, w6["beat"]):
            heard.add(aid)
            a6[aid]["last_thought_beat"] = w6["beat"]
        tick.run_beat(w6, a6)
    check("attention rotates across the whole cast",
          len(heard) >= len(a6) * 0.7,
          f"only {len(heard)}/{len(a6)} heard in 10 beats")

    ev_count = sum(1 for _ in range(400)
                   if events.roll_event(__import__("random").Random(_), a3, w3["factions"]))
    check("event table fires sometimes but not constantly",
          80 < ev_count < 340, f"{ev_count}/400 beats had an event")


    # Groq reserves prompt + max_tokens against the per-minute ceiling and refuses the whole
    # request with a 413 if the sum exceeds it. This caught a live failure where a generous
    # max_tokens silently made every call impossible. Checked against a *worn-in* city,
    # because the prompt grows as characters accumulate memories.
    w5, a5 = copy.deepcopy(w), copy.deepcopy(a)
    for i in range(40):                                    # age it so memory lines are full
        for x in a5.values():
            memory_mod = __import__("sim.memory", fromlist=["remember"])
            memory_mod.remember(x, i, i // 4,
                                f"Something happened involving {i} that they keep turning over.", 6)
        tick.run_beat(w5, a5)

    groups5 = tick.colocation(a5)
    chosen5 = cognition.select(w5, a5, groups5, [], None, w5["beat"])
    check("cognition rations attention rather than prompting the whole cast",
          len(chosen5) <= cognition.COGNITION_SLOTS < len(a5),
          f"chose {len(chosen5)} of {len(a5)}")
    prompt = cognition.build_prompt(w5, a5, groups5, [], None,
                                    w5["beat"], clock.day_of(w5["beat"]),
                                    clock.block_of(w5["beat"]), chosen5)
    chars = len(cognition.SYSTEM) + len(prompt)
    reply = llm.fit_max_tokens(llm.FAST, chars)
    total = chars // 4 + reply
    # Dialogue collapsed to roughly one line per city-day because companions were listed by
    # NAME while the schema asked for `to` as an id — the id of somebody standing in the
    # same room never appeared in the prompt unless they happened to be selected too. It
    # read as characters being reticent; it was a missing identifier.
    w7, a7 = copy.deepcopy(w), copy.deepcopy(a)
    for _ in range(3):
        tick.run_beat(w7, a7)
    g7 = tick.colocation(a7)
    crowd = max(g7.values(), key=len)
    chosen7 = list(dict.fromkeys(crowd + cognition.select(w7, a7, g7, [], None, w7["beat"])))
    p7 = cognition.build_prompt(w7, a7, g7, [], None, w7["beat"], 0, "evening", chosen7)
    companions = [o for o in crowd[1:]]
    check("companions are named in the prompt with their ids",
          len(crowd) < 2 or all(f"[{o}]" in p7 for o in companions),
          f"missing ids for {[o for o in companions if f'[{o}]' not in p7]}")
    check("the prompt tells them to talk to each other",
          "TALK TO EACH OTHER" in cognition.SYSTEM)

    check("cognition request fits Groq's per-minute reservation",
          total <= llm.TPM[llm.FAST],
          f"prompt ~{chars//4} + reply {reply} = {total} > {llm.TPM[llm.FAST]}")
    check("reply allowance stays big enough for the whole cast",
          reply >= 900, f"only {reply} tokens for {len(a5)} people")


    # The reflection prompt illustrates the memory/belief distinction with a worked example,
    # and the model once emitted that example verbatim as a character's actual belief —
    # Dez concluded "somebody is building a case against Dad", which is not his storyline.
    # Any wording lifted straight from the prompt is a leak, not a thought.
    from sim import reflect
    leaked = []
    for phrase in ("building a case against dad", "the landlord came by twice",
                   "trying to push us out"):
        for x in a.values():
            if x.get("belief") and phrase in x["belief"].lower():
                leaked.append((x["name"], phrase))
            for m in (x.get("memories") or []):
                if phrase in m["what"].lower():
                    leaked.append((x["name"], phrase))
    check("no prompt example has leaked into anyone's beliefs", not leaked, f"{leaked[:3]}")

    # The model's reply is untrusted input. A bare array instead of {"people":[...]} crashed
    # the live cron for two hours, so every shape it has actually produced must parse, and
    # anything unrecognised must degrade to "nobody narrated" rather than a traceback.
    shapes = {
        "documented object": ({"people": [{"id": "dez", "action": "x"}]}, 1),
        "bare array": ([{"id": "dez", "action": "x"}], 1),
        "keyed by id": ({"dez": {"action": "x"}, "ivy": {"action": "y"}}, 2),
        "alternate key": ({"agents": [{"id": "dez"}]}, 1),
        "null": (None, 0),
        "junk string": ("nope", 0),
        "list of junk": ([1, 2, "three"], 0),
    }
    bad = []
    for label, (payload, expect) in shapes.items():
        try:
            got = len(cognition.rows_of(payload))
        except Exception as e:
            got = f"raised {type(e).__name__}"
        if got != expect:
            bad.append((label, got, expect))
    check("every response shape the model emits parses without raising", not bad, f"{bad}")
    check("the reflection prompt still warns against reusing its example",
          "Never output it" in reflect.REFLECT_SYSTEM)


# Durability of a run is half Python and half workflow, and the workflow half cannot be
# exercised locally. Two failures took the live city down for two hours: the tick threw, so
# every beat it had already paid was discarded, and the default fail-fast then skipped the
# commit step so nothing reached the repo either.
import inspect
import os as _os

src = inspect.getsource(tick.main)
check("the tick persists paid beats in a finally, not only on success",
      "finally:" in src and "state.save_world" in src.split("finally:")[1])

wf = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                   ".github", "workflows", "tick.yml")
wf_src = open(wf, encoding="utf-8").read() if _os.path.exists(wf) else ""
commit_block = wf_src.split("Commit the new state")[-1]
check("the workflow commits state even when the tick fails",
      "if: always()" in commit_block.split("run:")[0],
      "commit step would be skipped on failure, stranding paid beats on the runner")

check("cognition failures cannot take the beat down with them",
      "except Exception" in inspect.getsource(tick.run_beat))


# ── the silent-death invariants ──────────────────────────────────────────────────
# Groq retired both Llama models and the city ran on for 85 city-days: green runs, a
# perfect clock, committed state, and 30 people frozen mid-stride. Every check below
# exists because nothing existing caught that.

RETIRED = {"llama-3.1-8b-instant", "llama-3.3-70b-versatile", "llama3-8b-8192",
           "llama3-70b-8192", "mixtral-8x7b-32768"}
check("the city is not pointed at a decommissioned model",
      not ({llm.FAST, llm.DEEP} & RETIRED),
      f"FAST={llm.FAST} DEEP={llm.DEEP} — retired by Groq, every call will 404")

# A reasoning model that spends its whole allowance thinking returns HTTP 200 with an
# empty body. Returning "" to the caller reads as "the model had nothing to say" and the
# beat is quietly dropped — indistinguishable from a healthy quiet beat. It must raise.
chat_src = inspect.getsource(llm.chat)
check("an empty model reply is an error, never an empty string",
      "raise RuntimeError" in chat_src.split("if not content:")[-1],
      "chat() can hand back empty content and the city dies quietly again")

check("reasoning tokens are budgeted for, not discovered at runtime",
      llm.REASONING_RESERVE > 0
      and "REASONING_RESERVE" in inspect.getsource(llm.fit_max_tokens),
      "reply allowance ignores the hidden channel; content will come back empty")

check("reasoning effort is pinned low on the reasoning models",
      "reasoning_effort" in chat_src and llm.REASONING_EFFORT == "low")

# 200K/day does not cover 96 beats. The two buckets are separate, so a spent workhorse
# must move the beat onto the other model rather than silencing the city until midnight.
cog_src = inspect.getsource(cognition.make_cognition)
check("a spent budget spills onto the other model instead of silencing the city",
      "llm.DEEP" in cog_src and "budget.can_afford(llm.DEEP" in cog_src,
      "cognition goes quiet for the rest of the day once FAST is spent")

# The alarm itself: paying thinking beats while nobody acts must eventually go red.
main_src = inspect.getsource(tick.main)
check("a city that ticks without thinking eventually fails the run",
      "silent_runs" in main_src and "return 1" in main_src
      and tick.SILENT_RUNS_ALARM >= 1,
      "cognition can break permanently and every run stays green")

# Anchored to the alarm's own marker, not to the first `return 1` in main() — that one is
# the pre-flight bail for a missing world.json, which fires before there is any state to lose.
# The quota is metered per real UTC day; a city-day is 4 beats and resets 24x as fast, so
# keying the budget on it made the guard unable to bind at all.
b = llm.Budget({"day": "1999-01-01", "spent": {llm.FAST: 999_999}}, 7)
check("the token budget is measured in the same day Groq meters",
      b.day == llm.quota_day() and b.remaining(llm.FAST) == llm.DAILY_BUDGET[llm.FAST],
      "budget keyed on the city day; the real 200K cap is hit with the guard still open")

check("running out of allowance is not treated as an outage",
      "skipped_budget" in inspect.getsource(cognition.make_cognition)
      and "skipped_budget" in main_src,
      "a legitimately quiet end-of-day would fail the run every single day")

# --dry-run printed "nothing written" while the Gazette wrote a real front page to disk,
# because it opens its own file instead of going through state.save_*.
check("a dry run cannot write a front page to disk",
      "dry_run" in inspect.getsource(reflect.gazette)
      and "dry_run=args.dry_run" in main_src,
      "--dry-run still writes state/gazette/day-NNN.md")

check("the alarm is raised only after state is safely written",
      main_src.index("state.save_world") < main_src.index("::error::"),
      "failing the run before the save would cost the city its beats")


print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
    sys.exit(1)
print("All invariants hold.")
