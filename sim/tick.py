"""
The Cut — the beat loop.

Run by the cron. Reads how much time the world owes, pays it beat by beat, writes state
back. Phase 1 is entirely deterministic: routines, needs, heat, debts and the event table.
Cognition (the LLM deciding what people actually *do* about all this) plugs into the
`cognition` seam at the bottom without the loop changing shape.

  py -m sim.tick --bootstrap        create a new city
  py -m sim.tick                    pay whatever beats are owed
  py -m sim.tick --owe 12           pretend 12 beats are owed (catch-up testing)
  py -m sim.tick --dry-run          simulate and report, write nothing
"""

import argparse
import random
import sys
import time

from . import activities, city, clock, cognition, events, llm, player, reflect, state

# Seconds between two thinking beats inside one run. A batched beat actually costs about
# 4,000 tokens against an 8,000-per-minute ceiling, so beats cannot run faster than roughly
# one a minute no matter how many are owed. Measured, not guessed: at 30s every catch-up
# spent most of its time inside the 429 handler being told to wait anyway.
BEAT_PACING_SECONDS = 62

# Consecutive thinking runs producing zero actions before the run is failed on purpose.
SILENT_RUNS_ALARM = 2

MOOD_MIN, MOOD_MAX = 0, 100


def clamp(v, lo=MOOD_MIN, hi=MOOD_MAX):
    return max(lo, min(hi, v))


def apply_mood(agent, deltas):
    for k, dv in (deltas or {}).items():
        if k in agent["mood"]:
            agent["mood"][k] = clamp(agent["mood"][k] + dv)


# ── deterministic systems ────────────────────────────────────────────────────

def target_location(agent, block, world):
    """Where routine says this person should be, before anyone decides otherwise.

    Exhaustion overrides work and high district heat pushes people off the street — two
    rules, both cheap, and between them the routine stops looking like a timetable.
    """
    loc = agent["routine"][block]
    if agent["mood"]["energy"] < 15 and block != "night":
        return agent["home"]
    dest_district = city.LOCATIONS[loc]["district"]
    if world["heat"].get(dest_district, 0) > 55 and agent["faction"] in ("crew", "grey"):
        return agent["home"]
    return loc


def move(agent, dest_id, block, weather, rng):
    """Resolve the beat's movement and settle on something to be doing when you get there.

    The simulation is authoritative about *where you end up*; the browser is authoritative
    about how that looks over the next fifteen real minutes.

    The destination is the activity's furniture, not the building's door anchor — somebody
    asleep should be drawn in a bed, and somebody washing up at the sink. Standing every
    resident on one anchor tile is what made a house of four look like a single person.
    """
    loc = city.LOCATIONS[dest_id]
    agent["at"] = dest_id

    text, spot = activities.choose(agent, loc, block, weather, rng)
    agent["activity"] = text
    agent["spot"] = spot

    target = tuple(spot) if spot and city.walkable(*spot) else tuple(loc["anchor"])
    p = city.path(tuple(agent["pos"]), target)
    agent["path"] = [list(t) for t in p[:600]]
    agent["pos"] = list(target)


#          stat        baseline  rate
MOOD_RELAX = {"stress": (18, 2), "fear": (10, 2), "happiness": (50, 3)}


def relax(value, baseline, rate):
    """Move a stat toward its resting level without overshooting it."""
    if value > baseline:
        return max(baseline, value - rate)
    if value < baseline:
        return min(baseline, value + rate)
    return value


def tick_needs(agent, block, alone):
    """Needs relax toward a resting level rather than decaying to zero.

    The first version subtracted a flat 6 stress and 5 fear per beat — 24 and 20 a city-day,
    which comfortably outran anything the event table could add. Both stats sat pinned at 0,
    so two of the five mood bars were permanently dead and nothing the model saw about a
    character's state ever reflected a bad week. Everyone now has a temperament to return
    to, and a shock takes several beats to work through.
    """
    m = agent["mood"]
    at_home = agent["at"] == agent["home"]
    working = agent["at"] == agent["work"] and block in ("morning", "afternoon")

    if block == "night" and at_home:
        m["energy"] = clamp(m["energy"] + 34)
    elif working:
        m["energy"] = clamp(m["energy"] - 14)
    else:
        m["energy"] = clamp(m["energy"] - 6)

    m["social_need"] = clamp(m["social_need"] + (12 if alone else -18))
    for stat, (baseline, rate) in MOOD_RELAX.items():
        m[stat] = clamp(relax(m[stat], baseline, rate))


HEAT_BASELINE = 5


def tick_heat(world):
    """Heat relaxes toward a baseline rather than to zero, by 1 a beat rather than 3.

    The first version decayed 12 points a city-day, which outran the event table: heat sat
    flat at 0, the panel was dead, and the "stay off a hot district" rule could never fire.
    At 1 a beat a raid (+25) stays felt for about six city-days, which is roughly how long
    a block actually stays careful.
    """
    for d, v in world["heat"].items():
        if v > HEAT_BASELINE:
            world["heat"][d] = clamp(v - 1)
        elif v < HEAT_BASELINE:
            world["heat"][d] = clamp(v + 1)


def tick_debts(world, agents, day):
    """Overdue debts are the most reliable story engine in the table: they impose a
    deadline, and a deadline forces somebody to choose badly."""
    pressures = []
    for d in world["debts"]:
        if d["settled"]:
            continue
        if day >= d["due_day"]:
            overdue = day - d["due_day"]
            debtor, creditor = agents.get(d["from"]), agents.get(d["to"])
            if not debtor or not creditor:
                continue
            apply_mood(debtor, {"stress": min(4 + overdue * 2, 18), "fear": min(2 + overdue * 2, 14)})
            pressures.append({
                "debt_id": d["id"], "from": debtor["name"], "to": creditor["name"],
                "from_id": debtor["id"], "to_id": creditor["id"],
                "kind": d["kind"], "amount": d["amount"], "days_overdue": overdue,
                "note": d["note"],
            })
    return pressures


def colocation(agents):
    groups = {}
    for a in agents.values():
        groups.setdefault(a["at"], []).append(a["id"])
    return groups


# ── one beat ─────────────────────────────────────────────────────────────────

def run_beat(world, agents, quiet=False, cognition=None):
    beat = world["beat"] + 1
    world["beat"] = beat
    day, block = clock.day_of(beat), clock.block_of(beat)

    rng = random.Random(f"{world['seed']}:{beat}")
    world["weather"] = events.roll_weather(rng)

    for a in agents.values():
        move(a, target_location(a, block, world), block, world["weather"], rng)

    groups = colocation(agents)
    for a in agents.values():
        tick_needs(a, block, alone=len(groups.get(a["at"], [])) <= 1)

    tick_heat(world)
    pressures = tick_debts(world, agents, day)

    ev = None if quiet else events.roll_event(rng, agents, world["factions"])
    if ev:
        for d, dv in ev.get("heat", {}).items():
            if d == "*":
                for k in world["heat"]:
                    world["heat"][k] = clamp(world["heat"][k] + dv)
            elif d in world["heat"]:
                world["heat"][d] = clamp(world["heat"][d] + dv)

        targets = ev.get("targets") or list(agents.keys())
        for aid in targets:
            if aid in agents:
                apply_mood(agents[aid], ev.get("mood", {}))
        world["events"] = ([ev] + world.get("events", []))[:20]

    records = [{
        "beat": beat, "day": day, "block": block, "kind": "beat",
        "weather": world["weather"], "quiet": quiet,
        "event": ev["text"] if ev else None,
        "heat": dict(world["heat"]),
    }]

    # Everyone's baseline is whatever the activity system decided. Cognition then overwrites
    # that for the handful of people it covers this beat, so nobody is ever left standing on
    # a tile with nothing to their name.
    for a in agents.values():
        a["action"] = a.get("activity") or "here"
        a["thought"] = ""
        a["speech"] = None

    if cognition and not quiet:
        # A malformed response must never take the city down with it. This exact path
        # crashed the live cron for two hours: the model returned a bare array instead of
        # an object and the traceback killed the whole run, so no beat was paid at all.
        # Everyone already has an activity, so the worst case here is a beat nobody
        # narrates — which is survivable, unlike a city that stops.
        try:
            records += cognition(world, agents, groups, pressures, ev, beat, day, block)
        except Exception as e:
            print(f"[tick] cognition failed on beat {beat} ({type(e).__name__}: {e}) — "
                  f"beat still paid, nobody narrated.")

    world["last_beat_at"] = clock.advance(world["last_beat_at"], 1)
    return records


# ── entry point ──────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="The Cut — advance the city")
    ap.add_argument("--bootstrap", action="store_true", help="create a fresh city")
    ap.add_argument("--seed", default="the-cut-001")
    ap.add_argument("--owe", type=int, default=None, help="force N beats owed (testing)")
    ap.add_argument("--dry-run", action="store_true", help="simulate but write nothing")
    ap.add_argument("--no-llm", action="store_true", help="deterministic only, no cognition")
    ap.add_argument("--no-pacing", action="store_true", help="skip the inter-beat TPM pause")
    ap.add_argument("--resync", action="store_true",
                    help="pull last_beat_at back to now (undo --owe testing)")
    args = ap.parse_args(argv)

    if args.bootstrap:
        world, agents = state.bootstrap(seed=args.seed)
        print(f"Bootstrapped '{args.seed}': {len(agents)} people, "
              f"{len(city.LOCATIONS)} locations, beat 0.")
        return 0

    world = state.load_world()
    if not world:
        print("No state/world.json — run with --bootstrap first.", file=sys.stderr)
        return 1
    agents = state.load_agents()

    # `--owe N` advances last_beat_at by N beats regardless of real time, so local testing
    # leaves the marker in the future — and beats_owed then returns 0 forever, freezing the
    # city until the wall clock catches up. It froze for two hours once, silently, which is
    # the worst way for this to fail. Detect it and pull the marker back.
    drift = (clock.parse(world["last_beat_at"]) - clock.now_utc()).total_seconds()
    ahead = drift > (clock.BEAT_SECONDS if not args.resync else 0)
    if ahead:
        world["last_beat_at"] = clock.iso(clock.now_utc())
        print(f"[clock] last_beat_at was {drift/60:.0f} min ahead of now — pulled back.")
    elif args.resync:
        # Only ever pulls the marker backwards. Moving it forward to "now" when it is
        # already behind would silently throw away beats the city genuinely owes.
        print(f"[clock] already {abs(drift)/60:.0f} min behind — nothing to resync.")

    if args.resync:
        state.save_world(world)
        return 0

    owed = args.owe if args.owe is not None else clock.beats_owed(world["last_beat_at"])
    if owed <= 0:
        print(f"Nothing owed. {clock.describe(world['beat'])}, last beat {world['last_beat_at']}.")
        return 0

    quiet_n, think_n = clock.split(owed)
    if quiet_n:
        print(f"Backlog of {owed} beats — fast-forwarding {quiet_n} quiet, "
              f"narrating the last {think_n}.")

    budget = llm.Budget(world.get("llm_budget"), clock.day_of(world["beat"]))
    cog = None if args.no_llm else cognition.make_cognition(budget)

    # Before any beat is paid, so anything said to the city while it was idle is already
    # in the right person's head when they next decide what to do.
    records = player.absorb(world, agents, world["beat"], clock.day_of(world["beat"]))

    # Beats already simulated must survive anything that goes wrong later in the run.
    # Before this, state was only written at the very end, so one unexpected exception
    # threw away every beat the run had paid and the city stopped dead — which is exactly
    # what a malformed model reply did for two hours. The `finally` means the worst case is
    # losing the narration of a single beat, never the run.
    paid = 0
    try:
        for _ in range(quiet_n):
            records += run_beat(world, agents, quiet=True)
            paid += 1
        for i in range(think_n):
            if i and cog and not args.no_pacing:
                time.sleep(BEAT_PACING_SECONDS)
            records += run_beat(world, agents, quiet=False, cognition=cog)
            paid += 1

            # A city-day just closed: work out what today meant to everybody, then write it
            # up. Reflection first — the Gazette should be able to report what people
            # concluded, not just what happened to them. Both are enrichment: if either
            # falls over, the day still happened.
            if cog and clock.is_day_end(world["beat"]):
                d = clock.day_of(world["beat"])
                try:
                    records += reflect.reflect(world, agents, budget, d, world["beat"])
                except Exception as e:
                    print(f"[tick] reflection failed for day {d} "
                          f"({type(e).__name__}: {e}) — no beliefs formed.")
                try:
                    # Earlier beats of this day were written by earlier cron runs and are
                    # already on disk; only the tail is still in memory. The Gazette needs both.
                    today = state.read_day(d) + [r for r in records if r.get("day") == d]
                    records += reflect.gazette(world, agents, budget, d, today,
                                               dry_run=args.dry_run)
                except Exception as e:
                    print(f"[tick] gazette failed for day {d} "
                          f"({type(e).__name__}: {e}) — no front page.")
    finally:
        world["llm_budget"] = budget.to_json()

        # ── the canary ───────────────────────────────────────────────────────────────
        # Cognition failures are deliberately non-fatal, so the city keeps its history
        # when the model has a bad night. The cost of that mercy is that a PERMANENT
        # breakage looks identical to a bad night: when Groq retired both models, every
        # run stayed green while 30 people stood frozen for 85 city-days. Nothing was
        # wrong with the clock, the commits, or the exit code — which is why nobody saw.
        # So: one silent run is weather, two in a row is an outage, and an outage has to
        # be able to turn the run red. This is recorded AFTER state is saved, so raising
        # the alarm never costs the city a beat.
        # Only genuine attempts count. Exhausting the day's token allowance is the budget
        # working as designed and must never raise the alarm; attempting to think and
        # producing nothing is the outage this canary exists to catch.
        st = getattr(cog, "stats", None) or {}
        attempted, narrated = st.get("attempted", 0), st.get("narrated", 0)
        if cog and attempted:
            world["silent_runs"] = 0 if narrated else int(world.get("silent_runs", 0)) + 1
            if not narrated:
                print(f"[canary] {attempted} thinking beat(s) attempted and NOBODY acted — "
                      f"{world['silent_runs']} silent run(s) in a row.")
        elif cog and st.get("skipped_budget"):
            print(f"[canary] {st['skipped_budget']} beat(s) skipped on budget, not broken "
                  f"— alarm not armed.")

        day = clock.day_of(world["beat"])
        print(f"Paid {paid}/{owed} beat(s) -> {clock.describe(world['beat'])}, "
              f"weather {world['weather']}.")
        if world.get("events"):
            print(f"Latest: {world['events'][0]['text']}")
        if not args.dry_run and paid:
            state.save_world(world)
            state.save_agents(agents)
            state.append_log(day, records)
            print(f"[tick] state written ({paid} beat(s) persisted).")

    if args.dry_run:
        print("--dry-run: nothing written.")

    # State is already safely on disk (the finally above). Only now is it safe to fail the
    # run — a red tick that has already committed its beats costs nothing but attention.
    silent = int(world.get("silent_runs", 0))
    if silent >= SILENT_RUNS_ALARM:
        print(f"::error::The city is ticking but nobody is thinking — {silent} consecutive "
              f"runs produced zero actions. The clock is fine; cognition is not. "
              f"Check the [cognition] lines above for the real error.")
        return 1
    return 0                      # state was already persisted in the finally above


if __name__ == "__main__":
    raise SystemExit(main())
