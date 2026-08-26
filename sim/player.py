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

from . import directives, drama, memory, orders

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
        return [], []
    try:
        req = urllib.request.Request(
            f"{WORKER_URL}/drain",
            headers={"X-Drain-Key": key, "User-Agent": "the-cut/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode()) or {}
            return (d.get("exchanges") or []), (d.get("orders") or [])
    except urllib.error.HTTPError as e:
        print(f"[player] drain refused: HTTP {e.code}")
    except Exception as e:
        print(f"[player] drain unavailable: {e}")
    return [], []


# Titles, and words that happen to be somebody's name here.
_NOT_A_NAME = {"det", "ofc", "sgt", "dr", "ms", "fr", "the", "and", "his", "her", "she"}


def _claim_from_line(line, agents, speaker_id):
    """Did the player say something ABOUT somebody else on the block?

    Deliberately dumb: if the line names another living character, that is a claim about
    them. It over-triggers a little — mentioning somebody in passing counts — but a
    character going to ask a neighbour about something a stranger said is exactly the
    behaviour we want, and a false positive just produces a conversation.
    """
    low = f" {line.lower()} "
    best = None
    for aid, other in agents.items():
        if aid == speaker_id or not other.get("alive", True):
            continue
        # Three letters is the floor, not four: half this cast is Wes, Tee, Dot, Rey, Gus.
        # Titles and a couple of words that are also names are excluded so "the doc said"
        # does not become an accusation against Dr. Amin.
        parts = [p.strip(".,'").lower() for p in other["name"].split()]
        names = [other["name"].lower()] + [
            p for p in parts if len(p) >= 3 and p not in _NOT_A_NAME]
        for n in names:
            if f" {n} " in low or f" {n}'" in low or f" {n}." in low or f" {n}," in low:
                # Prefer the longest match, so "Rosa Reyes" beats "Reyes".
                if not best or len(n) > best[1]:
                    best = (aid, len(n))
    if not best:
        return {}
    return {"about": best[0], "what": line.strip()[:120]}


def absorb(world, agents, beat, day):
    """Fold queued conversations and orders into the city. Returns log records."""
    exchanges, pending = drain()

    # Orders are only queued here; the tick applies them the moment this returns, before it
    # pays out any beats. Keeping the two steps apart is what lets a failing order be
    # reported against the day it was received rather than swallowed inside the drain.
    records = []
    for o in pending:
        orders.queue(world, o)
        what = o.get("what") or (f'{round(float(o.get("rate", 0)) * 100)}%'
                                 if o.get("kind") == "tax" else "")
        print(f'[player] order received: {o.get("kind")} {what}')
        records.append({"beat": beat, "day": day, "kind": "order_in",
                        "order": o.get("kind"), "what": what,
                        "text": f'The city takes an instruction: {o.get("kind")} {what}.'})

    if not exchanges:
        return records

    kept = []
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
        if not claim.get("about"):
            # The Worker asks its brain to extract the claim in the same call that writes
            # the reply, which is free but only works when that brain returns the JSON it
            # was asked for. Cloudflare's fallback answers in prose, so the claim is lost
            # exactly when Groq is out of tokens — i.e. when it matters most. Falling back
            # to a plain scan of what the player actually typed works with any brain, and
            # costs nothing.
            claim = _claim_from_line(line, agents, a["id"])
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

        # Anything shaped like an instruction becomes a directive they may or may not
        # carry out. Ordinary conversation falls straight through this and stays talk.
        told = directives.give(world, agents, a["id"], line, day, beat)
        if told:
            records.append(told)
            print(f'[player] {a["name"]}: {"agreed to" if told.get("ok") else "REFUSED"} '
                  f'{told.get("what")}')

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
