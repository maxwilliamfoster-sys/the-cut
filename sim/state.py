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
    }

    _write(os.path.join(STATE, "map.json"), city.export_map())
    save_world(world)
    save_agents(agents)
    os.makedirs(GAZETTE_DIR, exist_ok=True)
    return world, agents
