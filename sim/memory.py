"""
The Cut — memory.

A character's memory stream is append-only. What matters is not storing it but *choosing
what to hand the model*: the whole stream will not fit in the token budget, and a stream
truncated to "most recent five" produces goldfish who forget every grudge by Tuesday.

Retrieval scores each memory on the Generative Agents formula — recency, importance and
relevance — and passes only the top few. This is the machinery behind "she brought up
something you said three days ago": an old memory with high importance can outrank five
recent trivial ones, so a betrayal keeps surfacing long after the weather stops.

Relevance is deliberately cheap. Proper semantic similarity needs embeddings, an API call
per memory per beat, and a vector store; word overlap against the current situation gets
most of the benefit for none of the budget. Worth revisiting only if characters start
missing obviously-relevant history.
"""

import re

RECENCY_HALF_LIFE = 40.0     # beats — ten city-days for a memory to lose half its recency
W_RECENCY, W_IMPORTANCE, W_RELEVANCE = 1.0, 1.2, 0.9

_STOP = {
    "the","a","an","and","or","but","is","are","was","were","to","of","in","on","at","for",
    "with","that","this","it","he","she","they","him","her","them","his","their","has","had",
    "have","been","be","as","from","by","not","no","who","what","about","into","over","up",
    "down","out","then","than","so","if","when","which","there","here","just","like","get",
    "got","one","two","some","said","says","say",
}


def tokens(text):
    return {w for w in re.findall(r"[a-z']+", (text or "").lower()) if w not in _STOP and len(w) > 2}


DUPLICATE_SIMILARITY = 0.7


def remember(agent, beat, day, what, importance):
    """Append a memory, unless this person already has essentially the same one.

    Retrieved memories are shown back to the model in the prompt, and it reliably echoes
    them straight out again as "new" — every character was re-recording the same line
    every beat, so a stream of a hundred memories held about four actual events. A repeat
    now reinforces the original's importance instead of duplicating it, which is closer to
    how remembering something again actually works.
    """
    what = (what or "").strip()
    if not what:
        return
    imp = max(1, min(10, int(importance or 3)))

    incoming = tokens(what)
    for m in agent.setdefault("memories", [])[-40:]:
        prior = tokens(m["what"])
        same = m["what"].strip().lower() == what.lower()
        overlap = (len(incoming & prior) / len(incoming | prior)) if (incoming | prior) else 0
        if same or overlap >= DUPLICATE_SIMILARITY:
            m["importance"] = max(m["importance"], imp)
            m["beat"] = beat            # recalled now, so it is fresh again
            m["day"] = day
            return

    agent["memories"].append({"beat": beat, "day": day, "what": what, "importance": imp})


def retrieve(agent, beat, query, k=5):
    """The top k memories for this character, given what is happening around them now."""
    mems = agent.get("memories") or []
    if not mems:
        return []

    q = tokens(query)
    scored = []
    for m in mems:
        age = max(0, beat - m.get("beat", 0))
        recency = 0.5 ** (age / RECENCY_HALF_LIFE)
        importance = m.get("importance", 3) / 10.0
        overlap = tokens(m.get("what"))
        relevance = (len(q & overlap) / len(q)) if q else 0.0
        scored.append((
            W_RECENCY * recency + W_IMPORTANCE * importance + W_RELEVANCE * relevance, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [m for _, m in scored[:k]]
    top.sort(key=lambda m: m.get("beat", 0))          # chronological reads better in a prompt
    return top


def prune(agent, keep=240):
    """Cap the stream so a long-running city cannot grow agents.json without bound.

    Drops the lowest-scoring old memories rather than the oldest, so the formative things —
    a death, a betrayal, the day someone was arrested — survive indefinitely while a
    thousand rainy afternoons do not.
    """
    mems = agent.get("memories") or []
    if len(mems) <= keep:
        return
    newest = max(m.get("beat", 0) for m in mems)
    ranked = sorted(
        mems,
        key=lambda m: (m.get("importance", 3) / 10.0)
        + 0.5 ** (max(0, newest - m.get("beat", 0)) / RECENCY_HALF_LIFE),
        reverse=True,
    )
    kept = ranked[:keep]
    kept.sort(key=lambda m: m.get("beat", 0))
    agent["memories"] = kept
