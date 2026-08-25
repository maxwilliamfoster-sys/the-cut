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

import re
from sim import (city, clock, cognition, construction, drama, economy, events,
                 family, incidents, law, llm, mortality, orders, player, reflect,
                 roster, scores, state, tick)

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
    # The living only. The dead keep the position they fell in, and if a building is later
    # scaffolded over them that tile stops being walkable — which is not a bug, because a
    # corpse is neither drawn nor pathed. Checking everybody made this fail the first time
    # somebody happened to die indoors.
    check("nobody is stranded off-grid",
          all(city.walkable(*x["pos"]) for x in a3.values() if x.get("alive", True)))

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
    # Compressing the prompt to save tokens quietly dropped the explicit quantifier from
    # this rule, and the share of narrated people who actually spoke fell from ~45% to
    # ~18% — invisible in the logs and obvious on the map, because it is the speech
    # bubbles going away. A soft "should usually" is not an instruction; a number is.
    check("the prompt puts a countable floor on how many people speak",
          "AT LEAST HALF" in cognition.SYSTEM and "`to` and `says`" in cognition.SYSTEM,
          "without a number the model drifts to near-silence and the bubbles disappear")
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


# ── the city can change shape ────────────────────────────────────────────────────
# Buildings burn down, get rebuilt and go up on empty ground, and the layout is authored by
# hand. Both of those want checking mechanically rather than by looking at the map.

_cells = {}
_overlap = []
for _b in city.BUILDINGS:
    for _c in city.cells(_b):
        if _c in _cells:
            _overlap.append((_b["id"], _cells[_c], _c))
        _cells[_c] = _b["id"]
check("no two buildings occupy the same ground", not _overlap, f"{_overlap[:3]}")

_road = set()
for _y0, _h in city.H_ROADS:
    for _y in range(_y0, _y0 + _h):
        _road |= {(_x, _y) for _x in range(city.W)}
for _x0, _w in city.V_ROADS:
    for _x in range(_x0, _x0 + _w):
        _road |= {(_x, _y) for _y in range(city.RIVER_DEPTH + 1, city.H)}
check("nothing is built on top of a road",
      not [b["id"] for b in city.BUILDINGS if city.cells(b) & _road],
      f'{[b["id"] for b in city.BUILDINGS if city.cells(b) & _road][:3]}')

check("the city is not four rows of identical boxes",
      len({(b["w"], b["h"]) for b in city.BUILDINGS}) >= 12
      and len({b["y"] for b in city.BUILDINGS}) >= 8,
      "footprints and setbacks are too uniform — this is what made it read as a tilemap")

check("some buildings are not rectangles",
      any(b.get("wings") for b in city.BUILDINGS))

# The renderer keeps its own copy of which tiles can be walked on. When they disagree, the
# new tile type becomes an invisible wall that only the player collides with.
_html = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "index.html"),
             encoding="utf-8").read()
_m = re.search(r"const WALKABLE_TILES = '([^']*)'", _html)
check("the renderer agrees with the simulation about what is walkable",
      _m and set(_m.group(1)) == city.WALKABLE - {city.WATER},
      f'html={_m.group(1) if _m else "?"} sim={"".join(sorted(city.WALKABLE))}')

# ── the leader's controls ────────────────────────────────────────────────────────
_worker = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                             "worker", "src", "index.js"), encoding="utf-8").read()
check("the Worker will accept exactly what the simulation can build",
      all(f'"{k}"' in _worker.split("const BUILDABLE")[1][:300] for k in orders.BUILDABLE)
      and all(f'"{k}"' in _worker.split("const PROGRAMMES")[1][:300] for k in orders.PROGRAMMES),
      "an order the browser can send but the city cannot carry out, or the reverse")
check("orders reach the world the same way conversation does",
      "orders.queue" in inspect.getsource(player.absorb)
      and '"o:"' in _worker and "orders: await take" in _worker,
      "the browser can sign an order that never arrives")

# The Worker's catch-all used to answer unknown paths with 200, so the browser reported
# every order as signed while nothing at all was queued.
check("an unknown endpoint is a 404, not a cheerful 200",
      "no such endpoint" in _worker and "404" in _worker)
check("the browser insists on a real acknowledgement, not just a 200",
      "d.ok !== true" in _html and "queued" in _html,
      "a 200 from any endpoint would read as success")

check("orders are applied before the day is costed",
      inspect.getsource(tick.main).index("orders.apply_all")
      < inspect.getsource(tick.main).index("economy.settle_day"),
      "a building commissioned today would not be paid for until tomorrow")

# ── an economy, a population, and a score ────────────────────────────────────────
_w14 = copy.deepcopy(w)
_a14 = copy.deepcopy(a)
_w14["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w14["buildings"])
mortality.ensure_fields(_a14)
economy.ensure(_w14, _a14)
family.ensure(_w14, _a14)
orders.ensure(_w14)
_day14 = clock.day_of(_w14["beat"])

economy.match_jobs(_w14, _a14, _day14)
check("people get jobs in buildings that actually exist",
      0 < sum(1 for x in _a14.values() if x.get("job")) <= len(economy.workforce(_a14)))
check("only working-age people are employed",
      all(economy.working_age(x) for x in _a14.values() if x.get("job")))

# The chain that makes a fire an economic event rather than an orange shape.
_employer = next(b for b in _w14["buildings"] if b["kind"] == "industrial")
_lost = [x for x in _a14.values() if (x.get("job") or {}).get("at") == _employer["id"]]
_employer["condition"] = city.RUIN
city.rebuild(_w14["buildings"])
economy.match_jobs(_w14, _a14, _day14 + 1)
check("a building that burns down takes its jobs with it",
      all((x.get("job") or {}).get("at") != _employer["id"] for x in _a14.values()),
      "somebody is still employed by a ruin")

_before = _w14["treasury"]
economy.settle_day(_w14, _a14, _day14)
check("wages are paid and the city takes its cut",
      _w14["treasury"] != _before and any(x.get("money", 0) > 200 for x in _a14.values()))

# Scores are DERIVED. Nothing awards them, so they can only move by moving the thing
# underneath — which is what stops them being a number that drifts upward on its own.
_s1 = scores.snapshot(_w14, _a14, _day14)
for _x in _a14.values():
    _x["mood"]["happiness"] = 5
    _x["mood"]["stress"] = 95
_s2 = scores.snapshot(_w14, _a14, _day14)
check("a miserable city scores worse without anything being subtracted by hand",
      _s2["wellbeing"] < _s1["wellbeing"] and _s2["overall"] < _s1["overall"])
check("every score stays inside 0..100",
      all(0 <= _s2[k] <= 100 for k in
          ("overall", "economy", "wellbeing", "society", "infrastructure", "growth")))
check("the composite is a weighted mean of the parts, not a sixth number",
      abs(sum(scores.WEIGHTS.values()) - 1.0) < 0.001)

# Family: children have parents, and nobody pairs off with their own relatives.
# Both forced alive and of age: the live save is months old and whoever this test names
# may well have died in it, which is not what the check is about.
_p1, _p2 = _a14["dez"], _a14["junie"]
_p1["alive"] = _p2["alive"] = True
_p1["age"] = _p2["age"] = 30
_p1["relationships"][_p2["id"]] = {"affinity": 90, "opinion": "everything"}
_p2["relationships"][_p1["id"]] = {"affinity": 90, "opinion": "everything"}
_p1["partner"] = _p2["partner"] = None
family.form_couples(_w14, _a14, _day14)
check("two people who love each other pair off", _p1.get("partner") == _p2["id"])
_kids = family.births(_w14, _a14, _day14, _w14["beat"],
                      __import__("random").Random(1))
_born = [_a14[k["who"]] for k in _kids]
check("a child knows who its parents are",
      not _born or set(_born[0]["parents"]) == {_p1["id"], _p2["id"]})
check("a newborn is nobody's employee", all(not b.get("job") for b in _born))
check("children are not clones — they get their own temperament",
      not _born or _born[0]["volatility"] != _p1["volatility"]
      or _born[0]["traits"] != _p1["traits"])
if _born:
    _kid = _born[0]
    _kid["age"] = 30
    _kid["relationships"][_p1["id"]] = {"affinity": 99, "opinion": "x"}
    _p1["relationships"][_kid["id"]] = {"affinity": 99, "opinion": "x"}
    _p1["partner"] = _kid["partner"] = None
    family.form_couples(_w14, _a14, _day14)
    check("nobody pairs off with their own child", _p1.get("partner") != _kid["id"])

# Orders: a leader with an empty treasury cannot commission anything.
_w14["treasury"] = 10
_broke = orders._apply(_w14, _a14, {"kind": "build", "what": "clinic"}, _day14, _w14["beat"])
check("you cannot build what the city cannot pay for",
      _broke and not _broke.get("ok") and _w14["treasury"] == 10)
_w14["treasury"] = 50_000
_n_before = len(_w14["buildings"])
_built = orders._apply(_w14, _a14, {"kind": "build", "what": "clinic"}, _day14, _w14["beat"])
check("a funded order actually puts a building on the map",
      _built and _built.get("ok") and len(_w14["buildings"]) == _n_before + 1
      and _w14["treasury"] < 50_000)

# The economy must not be a luxury that stops when the model does.
_main = inspect.getsource(tick.main)
_free = _main.split("if clock.is_day_end")[1].split("if cog and clock.is_day_end")[0]
check("wages and births do not stop when the city runs out of tokens",
      "economy.settle_day" in _free and "family.births" in _free
      and "scores.record" in _free,
      "the economy is gated on cognition, so a spent budget freezes the city's life")

# ── people who drive ─────────────────────────────────────────────────────────────
# Ambient traffic was decoration. These are journeys somebody in the cast is actually making.
_w13 = copy.deepcopy(w)
_w13["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w13["buildings"])
_a13 = copy.deepcopy(a)
for _x in _a13.values():
    _x["vehicle"] = roster.VEHICLES.get(_x["id"])

# A field added to roster._p() only reaches people created at bootstrap. The live city's
# cast is months old, so an authored field is simply absent and everything reading it does
# nothing at all — twelve drivers were assigned and none of them drove, because not one of
# them had the key. Volatility hit this first; vehicles hit it again.
_stale = {k: {kk: vv for kk, vv in v.items() if kk not in ("vehicle", "volatility")}
          for k, v in copy.deepcopy(a).items()}
roster.equip(_stale)
check("authored roster fields reach a city that is already running",
      all(x.get("volatility") for x in _stale.values())
      and sum(1 for x in _stale.values() if x.get("vehicle")) == len(roster.VEHICLES),
      "a new roster field is invisible to everyone who already exists")
check("the beat equips the cast, not just the bootstrap",
      "roster.equip" in inspect.getsource(tick.run_beat),
      "the field only lands on a city built from scratch")

check("some people drive and most people do not",
      0 < len(roster.VEHICLES) < len(_a13) / 2,
      "a block where everybody owns a car is a suburb")
check("the renderer can draw every vehicle the roster hands out",
      all(f"{v}:" in _html.split("VEHICLE_LOOK")[1][:400] for v in set(roster.VEHICLES.values())),
      "an unknown vehicle silently falls back to a car")

# A car should go round by the street, not diagonally across the park.
_from = tuple(city.LOCATIONS["warehouse"]["anchor"])
_to = tuple(city.LOCATIONS["depot"]["anchor"])
_walk, _drive = city.path(_from, _to), city.road_path(_from, _to)
_on_road = lambda pth: sum(1 for x, y in pth if city.GRID[y][x] in ",:=") / max(1, len(pth))
check("driving follows the roads more closely than walking does",
      _on_road(_drive) > _on_road(_walk) + 0.1,
      f"walk {_on_road(_walk):.0%} vs drive {_on_road(_drive):.0%} on tarmac")
check("an unreachable destination falls back to walking rather than failing",
      city.road_path((1, 1), (1, 1)) == [(1, 1)])

# Distance decides it, not mood: nobody drives to the end of their own street.
_driver = _a13["ruiz"]
_driver["pos"] = list(city.LOCATIONS["warehouse"]["anchor"])
tick.move(_driver, "depot", "morning", "clear", __import__("random").Random(3))
check("a long journey is driven by somebody with a vehicle", bool(_driver.get("driving")))
_driver["pos"] = list(city.LOCATIONS["precinct"]["anchor"])
tick.move(_driver, "precinct", "morning", "clear", __import__("random").Random(3))
check("a short journey is walked even by a driver", not _driver.get("driving"))
_walker = _a13["tiny"]
_walker["pos"] = list(city.LOCATIONS["warehouse"]["anchor"])
tick.move(_walker, "depot", "morning", "clear", __import__("random").Random(3))
check("somebody with no vehicle walks it however far it is",
      not _walker.get("driving"))

# ── things you can stand and watch ───────────────────────────────────────────────
# Every dramatic event used to resolve inside one beat and leave only text, so on the map a
# beating looked exactly like a quiet afternoon.
_w12 = copy.deepcopy(w)
_w12["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w12["buildings"])
_w12["incidents"] = []
incidents.open_incident(_w12, "fight", 100, where="diner", who=["dez"], text="a scuffle")
check("an incident is placed somewhere real and lasts longer than a beat",
      _w12["incidents"] and _w12["incidents"][0]["until"] > 101
      and _w12["incidents"][0]["x"] > 0)
incidents.expire(_w12, 200)
check("incidents expire instead of piling up forever", not _w12["incidents"])

for _ in range(incidents.MAX_LIVE + 6):
    incidents.open_incident(_w12, "row", 300, where="diner")
check("a busy night is capped so the map stays legible",
      len(_w12["incidents"]) <= incidents.MAX_LIVE)

# Same front-end/back-end contract as the walkability table: the renderer switches on the
# effect name the simulation sends, so an unknown one silently draws nothing.
_effects = set(incidents.EFFECT.values())
check("the renderer can draw every effect the simulation emits",
      all(f"case '{e}':" in _html for e in _effects),
      f"no renderer case for {[e for e in _effects if chr(39) + e + chr(39) not in _html]}")
check("every incident kind has a label and colour in the panel",
      all(f"{k}:" in _html.split("INCIDENT_LOOK")[1][:600] for k in incidents.DURATION),
      "an incident with no entry shows as a blank row")

# ── room to grow ─────────────────────────────────────────────────────────────────
# The map was full: one 8x6 plot left and nothing bigger, so expansion had nowhere to put
# anything and the city could never visibly change shape.
_plots = [construction.find_plot([dict(b) for b in city.BASE_BUILDINGS], wd, ht,
                                 __import__("random").Random(1))
          for wd, ht in ((8, 6), (10, 6), (12, 8))]
check("the city has somewhere left to build",
      all(p is not None for p in _plots),
      "no free plot — expansion is a no-op and the city cannot grow")
check("there is an undeveloped district to grow into",
      "flats" in city.DISTRICTS
      and not [b for b in city.BASE_BUILDINGS if b["district"] == "flats"],
      "open ground is what makes growth visible")

# The map overlay reads agent fields directly to decide what dot to draw over somebody.
# That is the same front-end/back-end contract that WALKABLE_TILES broke once already: if
# the simulation renames a field, the dot silently stops appearing and nothing complains.
_overlay_fields = re.findall(r"a\.(chasing|checking|detained_until|grief)", _html)
check("the map overlay reads fields the simulation actually writes",
      set(_overlay_fields) == {"chasing", "checking", "detained_until", "grief"}
      and all(f in inspect.getsource(drama) or f in inspect.getsource(law)
              or f in inspect.getsource(mortality)
              for f in ("chasing", "checking", "detained_until", "grief")),
      f"overlay reads {sorted(set(_overlay_fields))}")
check("the overlay legend covers every state it can draw",
      all(k in _html for k in ("'owed'", "'feud'", "'held'", "'grief'", "'rumour'")),
      "a dot with no legend entry is a colour nobody can interpret")

# A lost building must actually be lost: not usable, and not somewhere routine sends people.
_w4 = copy.deepcopy(w)
_a4 = copy.deepcopy(a)
_w4["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w4["buildings"])
mortality.ensure_fields(_a4)
_victim = next(b for b in _w4["buildings"] if b["kind"] == "home")
_victim["condition"] = city.RUIN
city.rebuild(_w4["buildings"])
check("a burnt building stops being a usable location", not city.usable(_victim["id"]))
check("rubble can be stood in but scaffolding cannot",
      city.RUBBLE in city.WALKABLE and city.SCAFFOLD not in city.WALKABLE)

construction.displace(_a4, _w4["buildings"], _victim["id"], 1)
for _ in range(6):
    tick.run_beat(_w4, _a4)
check("nobody is routed into a building that no longer exists",
      not [x["name"] for x in _a4.values()
           if x.get("alive", True) and x.get("at") == _victim["id"]],
      "somebody is still going to work in a ruin")

check("everyone is still on walkable ground after the city changed shape",
      all(city.walkable(*x["pos"]) for x in _a4.values() if x.get("alive", True)))

# ── death, and what it does to everybody else ────────────────────────────────────
_w5 = copy.deepcopy(w)
_a5 = copy.deepcopy(a)
_w5["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w5["buildings"])
mortality.ensure_fields(_a5)
_dead = _a5["dez"]
_friend = max((x for x in _a5.values() if x["id"] != "dez"),
              key=lambda x: x.get("relationships", {}).get("dez", {}).get("affinity", 0))
_enemy = min((x for x in _a5.values() if x["id"] != "dez"),
             key=lambda x: x.get("relationships", {}).get("dez", {}).get("affinity", 0))
_before = (_friend["mood"]["happiness"], _enemy["mood"]["happiness"])
mortality.kill(_w5, _a5, _dead, mortality.NATURAL[0], _w5["beat"], 300)

check("the dead are actually dead", _dead["alive"] is False and _w5["dead"][0]["id"] == "dez")
check("a death reaches everybody who knew them",
      any("dez" in str(m.get("what", "")) or "Dez" in str(m.get("what", ""))
          for m in _friend.get("memories", [])),
      "nobody remembers it happening")
check("grief is scaled by how people actually felt, not applied evenly",
      _friend["mood"]["happiness"] < _before[0] and _friend.get("grief", 0) > 0,
      "the closest person to the deceased did not grieve")
check("a funeral gets scheduled", (_w5.get("funeral") or {}).get("id") == "dez")

_a5["dez"]["grief"] = 0
for _x in _a5.values():
    _x["grief"] = 50
mortality.decay_grief(_a5)
check("grief fades instead of pinning the whole cast flat",
      all(x["grief"] < 50 for x in _a5.values()))

_cog5 = cognition.select(_w5, mortality.living(_a5), {}, [], None, _w5["beat"])
check("nobody dead is asked what they are doing", "dez" not in _cog5)

# ── law the city wrote itself ────────────────────────────────────────────────────
_w6 = copy.deepcopy(w)
_a6 = copy.deepcopy(a)
_w6["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w6["buildings"])
law.ensure(_w6)
mortality.ensure_fields(_a6)
_w6["laws"] = [{"id": "law01", "title": "No burning in the yards",
                "text": "No unlicensed burning after dark.",
                "keywords": ["burn", "torch"], "penalty": {"type": "jail", "amount": 3},
                "proposed_by": "dez", "because": "a fire", "day_enacted": 1,
                "status": "enacted", "convictions": 0}]
_w6["heat"]["delmar"] = 100
_day6 = clock.day_of(_w6["beat"])
_acts = [{"kind": "act", "who": "malik", "name": _a6["malik"]["name"],
          "action": "decides to burn the crates out the back", "district": "delmar"}]
# Whether any single offence is SEEN is a deterministic roll on (who, law, beat) — being
# caught is meant to be uncertain. An earlier version of this check used the live world's
# beat, so it passed or failed depending on where the city happened to be when it ran. Walk
# a few beats and assert the mechanism fires, not that one particular roll came up.
_charges = []
for _b6 in range(_w6["beat"], _w6["beat"] + 12):
    _charges = law.detect(_w6, _a6, _acts, _b6, _day6)
    if _charges:
        break
check("breaking a law the block passed gets you charged",
      bool(_charges) and _w6["charges"][0]["who"] == "malik",
      "twelve consecutive offences in a hot district and nobody was ever seen")
check("being charged puts you in a cell rather than back on the street",
      bool(_a6["malik"].get("detained_until")))

_verdicts = law.try_cases(_w6, _a6, _w6["beat"], _day6 + law.TRIAL_DELAY)
check("a charge is actually tried", bool(_verdicts)
      and _w6["charges"][0]["status"] in ("convicted", "acquitted"))
check("the jury is the block, so the verdict follows the social graph",
      "affinity" in inspect.getsource(law.try_cases)
      and "_jury(" in inspect.getsource(law.try_cases),
      "verdicts do not consult how people actually feel about the accused")

_a6["malik"]["detained_until"] = _day6 + 1
check("people come back out",
      bool(law.release(_a6, _day6 + 5, _w6["beat"]))
      and not _a6["malik"].get("detained_until"))

check("an action nothing outlaws is not a crime",
      not law.match_laws(_w6, "wipes down the counter and counts the till twice"))

check("legislation is rationed like every other model call",
      law.LAW_TOKENS_PER_DAY <= 8000 and law.MIN_DAYS_BETWEEN_LAWS >= 1
      and "can_afford" in inspect.getsource(law.propose_law))


# ── the debt engine actually runs ────────────────────────────────────────────────
# The README called debts "the most reliable story engine in the table". It was inert:
# only the debtor was ever touched, the creditor felt nothing, nothing could mark a debt
# settled, and every debt in the live city sat 220+ city-days overdue with no consequence.

_w7 = copy.deepcopy(w)
_a7 = copy.deepcopy(a)
_w7["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w7["buildings"])
mortality.ensure_fields(_a7)
_day7 = clock.day_of(_w7["beat"])
_w7["debts"] = [{"id": "dtest", "from": "malik", "to": "dez", "kind": "money",
                 "amount": 500, "due_day": _day7 - 20, "note": "fronted", "settled": False}]
_a7["dez"]["relationships"]["malik"] = {"affinity": 20, "opinion": "fine"}
_before7 = _a7["dez"]["relationships"]["malik"]["affinity"]
_pres7 = drama.press_debts(_w7, mortality.living(_a7), _day7)

check("being owed and ignored makes the creditor angry, not sad",
      _a7["dez"]["relationships"]["malik"]["affinity"] < _before7,
      "the person owed money felt nothing at all — the original bug")
check("a creditor out of patience goes looking for the debtor",
      _a7["dez"].get("chasing") == "malik")
check("routing sends them where the debtor actually is",
      tick.target_location(_a7["dez"], "morning", _w7, mortality.living(_a7))
      in (_a7["malik"].get("at"), _a7["malik"].get("work"), _a7["malik"].get("home")),
      "chasing is set but routine still wins, so they never meet")
check("the prompt is told the creditor has run out of patience",
      any(p.get("chasing") for p in _pres7))

# Put them in the same room and it has to resolve — one way or another.
_a7["malik"]["at"] = _a7["dez"]["at"]
_groups7 = tick.colocation(mortality.living(_a7))
_conf = drama.confrontations(_w7, mortality.living(_a7), _groups7, _w7["beat"], _day7)
check("creditor and debtor in the same room produces a confrontation", bool(_conf))
check("a confrontation has an outcome, not just a mood change",
      _conf and _conf[0]["outcome"] in ("settled", "promised", "refused", "violent"))
check("a debt can actually be discharged",
      "settled" in inspect.getsource(drama._resolve)
      and 'd["settled"] = True' in inspect.getsource(drama._resolve),
      "nothing in the codebase can mark a debt settled — this was literally true before")

# And the ledger has to refill, or the engine runs once and the city is square forever.
_w8 = copy.deepcopy(_w7)
_a8 = copy.deepcopy(_a7)
for _d in _w8["debts"]:
    _d["settled"] = True
_opened = []
for _i in range(400):
    _opened += drama.maybe_new_debt(_w8, mortality.living(_a8), _i * 4, _day7 + _i)
check("new obligations keep forming so the city is never square forever",
      bool(_opened), "every debt settles and no new one is ever created")

# ── who starts things ────────────────────────────────────────────────────────────
_vols = [x.get("volatility", 45) for x in _a7.values()]
check("volatility is authored across the cast, not one flat number",
      len(set(_vols)) >= 8 and max(_vols) >= 75 and min(_vols) <= 25,
      f"spread {min(_vols)}..{max(_vols)} over {len(set(_vols))} distinct values")
check("the block has several instigators, not one lunatic",
      sum(1 for v in _vols if v >= 65) >= 5,
      "inferring volatility from trait prose put everyone on 45 except Dez")
check("it also has people who calm rooms down",
      sum(1 for v in _vols if v <= 25) >= 3)
check("the same person cannot start everything",
      drama.INSTIGATE_COOLDOWN >= 2 and "last_instigated_day" in inspect.getsource(drama.instigate))
check("volatile people are more likely to be narrated",
      "volatility" in inspect.getsource(cognition.select),
      "the troublemakers never get a turn, so the block reads as placid")

# ── feuds ────────────────────────────────────────────────────────────────────────
_w9 = copy.deepcopy(_w7)
_a9 = copy.deepcopy(_a7)
# Start from no feuds: the live save carries whatever the city is currently arguing about,
# and this checks that a feud ENDS, which cannot be observed with other feuds still standing.
_w9["feuds"] = []
_a9["dez"]["relationships"]["malik"] = {"affinity": -80, "opinion": "done talking"}
drama.open_feud(_w9, _a9["dez"], _a9["malik"], _day7, "refused me")
check("a bad enough falling-out becomes a feud", bool(_w9.get("feuds")))
_a9["dez"]["relationships"]["malik"]["affinity"] = 40
for _f in _w9["feuds"]:
    _f["heat"] = 0
drama.tick_feuds(_w9, _a9, _day7 + 1)
check("feuds end when nothing feeds them", not _w9["feuds"])

# Enforcement has to look at the most chargeable thing in the city.
check("a violent confrontation is something the law can see",
      '"confrontation"' in inspect.getsource(law.detect),
      "only narrated `act` records were scanned, so assaults were never chargeable")


# ── what the player says has to travel ───────────────────────────────────────────
# Talking to people used to leave a memory and nothing else. If you tell somebody that Malik
# has been talking to police, that has to be able to move through the city — otherwise the
# conversation is a novelty act rather than a way of affecting anything.

_w10 = copy.deepcopy(w)
_a10 = copy.deepcopy(a)
_w10["buildings"] = [dict(b) for b in city.BASE_BUILDINGS]
city.rebuild(_w10["buildings"])
mortality.ensure_fields(_a10)
drama.ensure(_w10, _a10)
_day10 = clock.day_of(_w10["beat"])

drama.open_lead(_a10["dez"], "malik", "Malik torched the cannery himself", _day10)
check("something the player says becomes a lead the character carries",
      bool(_a10["dez"].get("leads")))
# The live save may already have him chasing a debt, which correctly outranks gossip.
_a10["dez"]["chasing"] = None
drama.press_leads(_w10, mortality.living(_a10), _day10)
# The Worker asks its brain to extract the claim in the same call as the reply, which only
# works when that brain returns JSON. Cloudflare's free fallback answers in prose, so the
# claim vanished exactly when Groq was out of tokens. This scan works with any brain.
check("a claim is found even when the brain answers in prose",
      (player._claim_from_line("Wes has been skimming off your counter.", _a10, "booker")
       .get("about") == "wes")
      and (player._claim_from_line("Malik has been talking to police.", _a10, "dez")
           .get("about") == "malik"),
      "player claims only work when the reply happens to be JSON")
check("an ordinary remark is not treated as an accusation",
      not player._claim_from_line("Cold one tonight. Quiet on the block?",
                                  _a10, "tee").get("about"))

check("carrying an unchecked rumour sends them to find the person it is about",
      _a10["dez"].get("checking") == "malik")
check("a debt outranks a rumour",
      inspect.getsource(tick.target_location).index('agent.get("chasing")')
      < inspect.getsource(tick.target_location).index('agent.get("checking")'),
      "gossip would pull people off collecting money they are owed")

# The claim is checked against the city's own record, not a coin flip.
_a10["malik"]["at"] = _a10["dez"]["at"]
_g10 = tick.colocation(mortality.living(_a10))
_false = drama.check_leads(_w10, mortality.living(_a10), _g10, _w10["beat"], _day10)
check("an invented rumour does not stick",
      _false and _false[0]["verdict"] in ("false", "believed anyway"),
      f'{_false[0]["verdict"] if _false else "unresolved"} — nothing in the record supports it')

_a11 = copy.deepcopy(_a10)
for _x in _a11.values():
    _x["leads"] = []
_a11["malik"]["memories"].append({"day": _day10 - 1, "beat": _w10["beat"],
                                  "what": "I torched the cannery and nobody knows it was me.",
                                  "importance": 8})
drama.open_lead(_a11["dez"], "malik", "Malik torched the cannery himself", _day10)
_a11["malik"]["at"] = _a11["dez"]["at"]
_true = drama.check_leads(_w10, mortality.living(_a11), tick.colocation(mortality.living(_a11)),
                          _w10["beat"], _day10)
check("a rumour that happens to be true finds its evidence",
      _true and _true[0]["verdict"] == "true",
      "the city's own record should corroborate it")

# Plain word overlap corroborated an invented rumour instantly, because "police" and
# "talking" appear in half the memories in a city about police and talk.
check("corroboration weighs how rare a word is, not just whether it matches",
      "_document_frequency" in inspect.getsource(drama.check_leads),
      "common vocabulary will corroborate anything")

_stale = {"about": "malik", "what": "x", "day": _day10 - 99, "checked": False}
_a10["dez"]["leads"] = [_stale]
drama.press_leads(_w10, mortality.living(_a10), _day10)
check("people stop caring about an old rumour eventually", _stale["checked"] == "gave up")


# ── the silent-death invariants ──────────────────────────────────────────────────
# Groq retired both Llama models and the city ran on for 85 city-days: green runs, a
# perfect clock, committed state, and 30 people frozen mid-stride. Every check below
# exists because nothing existing caught that.

RETIRED = {"llama-3.1-8b-instant", "llama-3.3-70b-versatile", "llama3-8b-8192",
           "llama3-70b-8192", "mixtral-8x7b-32768"}
_all_models = {m for p in llm.PROVIDERS for ms in p["models"].values() for m in ms}
check("the city is not pointed at a decommissioned model",
      not (_all_models & RETIRED),
      f"{sorted(_all_models & RETIRED)} are retired — those calls will 404")

# The whole outage happened because a tier WAS a model id. Now it is a tier, and each
# provider offers several candidates so one retirement demotes an entry instead of
# stopping the city.
check("a tier is not a single model id",
      llm.FAST not in _all_models and llm.DEEP not in _all_models,
      "FAST/DEEP are literal model names again — one retirement kills the city")
check("every tier has more than one candidate model per provider",
      all(len(p["models"][t]) >= 2 for p in llm.PROVIDERS for t in (llm.FAST, llm.DEEP)))
check("there is more than one provider to fall back to",
      len(llm.PROVIDERS) >= 3,
      "one provider means one daily cap between the city and silence")
check("a provider with no key configured is skipped, not attempted",
      all(p["key"] is None or "os.environ" in inspect.getsource(llm.providers_available)
          for p in llm.PROVIDERS))
# Gemini's OpenAI-compatibility endpoint demands `Authorization: Bearer` and rejects real
# AI Studio keys with a 403; the native endpoint takes the same key in a header and works.
# So one provider speaks its own dialect, and the translation has to keep working.
_gp = next(p for p in llm.PROVIDERS if p["name"] == "gemini")
check("gemini uses its native endpoint, not the OpenAI shim that rejects its keys",
      _gp.get("dialect") == "gemini" and "openai" not in _gp["url"],
      "the compatibility endpoint 403s perfectly good keys")
_probe = llm._gemini_payload(
    [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
     {"role": "assistant", "content": "A"}], 300, 0.5, True)
check("openai-shaped messages translate into gemini's request shape",
      _probe["systemInstruction"]["parts"][0]["text"] == "S"
      and [c["role"] for c in _probe["contents"]] == ["user", "model"]
      and _probe["generationConfig"]["maxOutputTokens"] == 300
      and _probe["generationConfig"]["responseMimeType"] == "application/json",
      f"{_probe}")
check("a gemini response is read back correctly",
      llm._gemini_read({"candidates": [{"content": {"parts": [{"text": " hi "}]},
                                        "finishReason": "STOP"}],
                        "usageMetadata": {"totalTokenCount": 42}}) == ("hi", 42, "STOP"))

check("a model that no longer exists is demoted, not retried forever",
      "_dead_models" in inspect.getsource(llm.chat)
      and "_ModelGone" in inspect.getsource(llm._call))
check("a local model is never relied on by the cloud cron",
      all(not p.get("local") or "THE_CUT_ALLOW_LOCAL" in inspect.getsource(llm.providers_available)
          for p in llm.PROVIDERS),
      "the city runs on a cron; a model on somebody's desktop cannot serve it")

# A reasoning model that spends its whole allowance thinking returns HTTP 200 with an
# empty body. Returning "" to the caller reads as "the model had nothing to say" and the
# beat is quietly dropped — indistinguishable from a healthy quiet beat. It must raise.
chat_src = inspect.getsource(llm._call)
check("an empty model reply is an error, never an empty string",
      "raise RuntimeError" in chat_src.split("if not content:")[-1],
      "the transport can hand back empty content and the city dies quietly again")

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

# Running out of the day's tokens is the budget working. Before this, quota exhaustion
# counted as "attempted and narrated nobody", so the run went red every single day the
# moment the cap was hit — the canary crying wolf at exactly the wrong time.
check("running out of quota is a skip, not an outage",
      issubclass(llm.QuotaExhausted, Exception)
      and "QuotaExhausted" in inspect.getsource(cognition.make_cognition)
      and "skipped_budget" in inspect.getsource(cognition.make_cognition),
      "hitting the daily cap would fail the run every day")
check("once the cap is hit the city stops re-discovering it every beat",
      "quota_exhausted_on" in inspect.getsource(cognition.make_cognition),
      "every remaining beat burns three doomed requests finding out the same thing")

check("the alarm is raised only after state is safely written",
      main_src.index("state.save_world") < main_src.index("::error::"),
      "failing the run before the save would cost the city its beats")


print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
    sys.exit(1)
print("All invariants hold.")
