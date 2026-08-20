"""
The Cut — persistence.

Everything the city is lives in `state/` as plain JSON, committed back to the repo by the
cron. That is a deliberate choice over a database: it costs nothing, it needs no server,
and it makes the git history a literal, scrubbable record of the city. Every commit is a
beat; `git log` is the chronicle.

`log.jsonl` is append-only and rotates per city-week so the repo does not grow without
bound at ~96 beats a day.
"""

import json
import os

from . import city, clock
from .roster import ROSTER, FACTIONS, SEED_RELATIONSHIPS, SEED_DEBTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
GAZETTE_DIR = os.path.join(STATE, "gazette")

MOOD_KEYS = ["energy", "happiness", "stress", "social_need", "fear"]
BASE_MOOD = {"energy": 70, "happiness": 55, "stress": 30, "social_need": 40, "fear": 20}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)   # atomic: a killed run never leaves half a world behind


def _read(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── world ────────────────────────────────────────────────────────────────────

def world_path():
    return os.path.join(STATE, "world.json")


def load_world():
    return _read(world_path())


def save_world(w):
    _write(world_path(), w)


# ── agents ───────────────────────────────────────────────────────────────────

def agents_path():
    return os.path.join(STATE, "agents.json")


def load_agents():
    """One file rather than twelve: the front-end needs a single fetch, and a 12-key JSON
    written with indent=2 still diffs line-by-line in git, so the per-character history
    stays just as readable in `git log -p`."""
    return _read(agents_path(), {}) or {}


def save_agents(agents):
    _write(agents_path(), agents)


# ── the city itself ──────────────────────────────────────────────────────────
# The map used to be a constant compiled into city.py and written to map.json exactly once,
# at bootstrap. It is now mutable state: buildings burn down, stand as ruins, get rebuilt,
# and new ones go up on empty land.
#
# The live building list lives in world.json and nowhere else. An earlier version also kept
# a copy in city.json, which is exactly the sort of second source of truth that is right
# until the day it silently is not.

def map_path():
    return os.path.join(STATE, "map.json")


def merge_base(existing):
    """Fold the seed city in code together with the city as it has actually turned out.

    Geometry comes from source, so a layout fix reaches a city that has been running for
    weeks. Everything the city earned — whether a place is a ruin, what it was renamed to
    when it reopened — comes from the save. Buildings the city invented at runtime are not
    in the seed at all and are carried through untouched.
    """
    saved = {b["id"]: b for b in (existing or [])}
    out = []
    for base in city.BASE_BUILDINGS:
        b = dict(base)
        keep = saved.get(base["id"])
        if keep:
            for k in ("condition", "since_day", "generation", "name", "kind", "style"):
                if k in keep:
                    b[k] = keep[k]
        out.append(b)
    known = {b["id"] for b in out}
    out += [dict(b) for b in (existing or []) if b["id"] not in known]
    return out


def sync_city(world):
    """Reconcile the world's buildings with the seed, then point the city module at them."""
    merged = merge_base(world.get("buildings"))
    if merged != world.get("buildings"):
        world["buildings"] = merged
    point_city(world)
    return world["buildings"]


def point_city(world):
    """Cheap per-beat re-point: only rebuilds the grid if this world's city is not the one
    the module is currently showing. Two simulations in one process each keep their own.

    A world saved before the city became mutable has no buildings at all, so it is seeded
    here rather than crashing — the live city is upgraded by being run, not by a migration.
    """
    if not world.get("buildings"):
        return sync_city(world)
    if city.BUILDINGS is not world["buildings"]:
        city.rebuild(world["buildings"])
    return world["buildings"]


def save_map():
    _write(map_path(), city.export_map())


# ── log ──────────────────────────────────────────────────────────────────────

def log_path(day):
    return os.path.join(STATE, f"log-w{day // 7:03d}.jsonl")


def append_log(day, records):
    if not records:
        return
    path = log_path(day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_day(day):
    """Every record already written for a city-day.

    A day is four beats and a run normally pays one, so the day's history is spread across
    four separate cron runs. The Gazette reading only the current run's in-memory records
    saw a quarter of the day and duly reported that 'details are scarce'.
    """
    return [r for r in read_log_tail(day, limit=20000) if r.get("day") == day]


def read_log_tail(day, limit=200):
    """Most recent records, newest last. Reads the current week and the one before it so a
    week boundary does not blank the front-end's 'while you were away' diff."""
    paths = []
    for d in (max(0, day - 7), day):
        p = log_path(d)
        if p not in paths:
            paths.append(p)

    records = []
    for p in paths:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                records.extend(json.loads(line) for line in f if line.strip())
    return records[-limit:]


# ── bootstrap ────────────────────────────────────────────────────────────────

def bootstrap(seed="the-cut-001", start_at=None):
    """Create a fresh city. Safe to re-run only on an empty state/ — it will refuse otherwise."""
    if os.path.exists(world_path()):
        raise SystemExit("state/world.json already exists — refusing to overwrite a living city.")

    start = start_at or clock.iso(clock.now_utc())

    agents = {}
    for spec in ROSTER:
        loc = city.LOCATIONS[spec["routine"]["morning"]]
        anchor = list(loc["anchor"])
        agents[spec["id"]] = {
            "id": spec["id"], "name": spec["name"], "age": spec["age"], "role": spec["role"],
            "faction": spec["faction"], "home": spec["home"], "work": spec["work"],
            "principal": bool(spec.get("principal")),
            "traits": spec["traits"], "ambition": spec["ambition"], "private_fear": spec["fear"],
            "voice": spec["voice"], "routine": spec["routine"],
            "pos": anchor, "dest": anchor, "at": spec["routine"]["morning"], "spot": None,
            "mood": dict(BASE_MOOD),
            "relationships": {},
            "memories": [],
            "action": "starting the day", "activity": "starting the day",
            "thought": "", "speech": None,
        }

    # Relationships are SPARSE. Filling every pair would be 30x29 = 870 entries of "knows
    # the face, not much else" — most of agents.json, and most of every git diff, saying
    # nothing. Opinions are created the moment two people actually interact.
    for aid, rels in SEED_RELATIONSHIPS.items():
        if aid not in agents:
            continue
        for other, (aff, opinion) in rels.items():
            if other in agents:
                agents[aid]["relationships"][other] = {"affinity": aff, "opinion": opinion}

    turf = {}
    for fid, f in FACTIONS.items():
        for d in f["turf"]:
            turf[d] = fid

    world = {
        "version": 1,
        "seed": seed,
        "beat": 0,
        "last_beat_at": start,
        "started_at": start,
        "weather": "clear",
        "heat": {d: 5 for d in city.DISTRICTS},
        "turf": turf,
        "factions": FACTIONS,
        "debts": [dict(d, id=f"debt{i}", settled=False) for i, d in enumerate(SEED_DEBTS)],
        "events": [],
        "player_queue": [],
        "last_gazette_day": -1,
        "buildings": [dict(b) for b in city.BASE_BUILDINGS],
    }

    save_map()
    save_world(world)
    save_agents(agents)
    os.makedirs(GAZETTE_DIR, exist_ok=True)
    return world, agents
