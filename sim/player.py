"""
The Cut — the player's mark on the city.

You are not simulated. Between beats the cloud has no idea you exist, and if you never
speak to anybody you leave no trace at all. The only thing that crosses from your browser
into the city is a line you actually said, and it crosses via the Worker's queue.

The memory is written here in plain Python rather than left to the model to record. If
"they remember you" depended on the model choosing to emit a memory object, it would work
most of the time — and the one time it silently didn't would be the exact moment the whole
premise stopped being true.
"""

import json
import os
import urllib.error
import urllib.request

from . import drama, memory

WORKER_URL = os.environ.get("THE_CUT_WORKER_URL",
                            "https://the-cut-talk.maxwilliamfoster.workers.dev")

# High enough that a conversation outranks a rainy afternoon for a long time. Being spoken
# to by a stranger who knows your name is genuinely notable in a place this small.
PLAYER_MEMORY_IMPORTANCE = 6
KEEP_IN_PROMPT = 3


def drain(timeout=20):
    """Pull everything said to the city since the last beat, and clear it.

    A failure here must never take the beat down with it — the city carrying on without
    your conversation is a much smaller loss than the city not carrying on.
    """
    key = os.environ.get("THE_CUT_DRAIN_KEY")
    if not key:
        return []
    try:
        req = urllib.request.Request(
            f"{WORKER_URL}/drain",
            headers={"X-Drain-Key": key, "User-Agent": "the-cut/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return (json.loads(r.read().decode()) or {}).get("exchanges", []) or []
    except urllib.error.HTTPError as e:
        print(f"[player] drain refused: HTTP {e.code}")
    except Exception as e:
        print(f"[player] drain unavailable: {e}")
    return []


def absorb(world, agents, beat, day):
    """Fold queued conversations into the people who had them. Returns log records."""
    exchanges = drain()
    if not exchanges:
        return []

    records, kept = [], []
    for ex in exchanges:
        a = agents.get(ex.get("agent"))
        if not a:
            continue
        line = str(ex.get("line", ""))[:200]
        reply = str(ex.get("reply", ""))[:200]

        memory.remember(
            a, beat, day,
            f'A stranger stopped me and said "{line}". I said "{reply}".',
            PLAYER_MEMORY_IMPORTANCE,
        )
        memory.prune(a)

        # If the stranger said something about somebody else, this person now carries it as
        # an unverified lead — and will go and ask. This is the only route by which
        # information from outside the simulation gets into it.
        claim = ex.get("claim") or {}
        lead = None
        if claim.get("about") in agents and claim.get("what"):
            lead = drama.open_lead(a, claim["about"], claim["what"], day)
            if lead:
                memory.remember(
                    a, beat, day,
                    f'A stranger told me {claim["what"]}. I have not checked it.', 7)
                memory.prune(a)
                print(f'[player] {a["name"]} is now carrying a rumour about '
                      f'{agents[claim["about"]]["name"]}')

        kept.append({"agent": a["id"], "name": a["name"], "line": line, "reply": reply})
        records.append({
            "beat": beat, "day": day, "kind": "player",
            "who": a["id"], "name": a["name"], "line": line, "reply": reply,
            "claim": (lead or {}).get("what"), "about": (lead or {}).get("about"),
        })
        print(f'[player] {a["name"]} remembers being spoken to: "{line[:60]}"')

    # Shown to the model on the next beat so the encounter colours what they do next,
    # not just what they can recall later.
    world["player_queue"] = (kept + (world.get("player_queue") or []))[:KEEP_IN_PROMPT]
    return records
