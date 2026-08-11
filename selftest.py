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

from sim import city, clock, events, state, tick

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

    check("relationships are symmetric in coverage",
          all(set(x["relationships"]) == set(a.keys()) - {aid} for aid, x in a.items()))

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
    check("the cast actually spreads across the map", len(visited) >= 5, f"only {visited}")

    ev_count = sum(1 for _ in range(400)
                   if events.roll_event(__import__("random").Random(_), a3, w3["factions"]))
    check("event table fires sometimes but not constantly",
          80 < ev_count < 340, f"{ev_count}/400 beats had an event")


print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
    sys.exit(1)
print("All invariants hold.")
