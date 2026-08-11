"""
The Cut — time.

The single rule that makes this survive GitHub Actions: **city time is derived from real
elapsed time, never from how many times the cron actually fired.** Actions is documented
to delay scheduled runs by 5-30 minutes and to drop them outright under load. If one run
meant one beat, the city's clock would quietly desynchronise from reality and every
"a day has passed" promise would break.

Instead each run asks "how many beats does the world owe?" and pays all of them. A run
that arrives 40 minutes late simulates three beats. A run after a six-hour outage
simulates twenty-four. The same code path covers both, so the outage case is exercised
every single time the cron is merely late.

`last_beat_at` advances by exactly `beats_paid * BEAT_SECONDS` rather than jumping to
`now`, so the sub-beat remainder carries into the next run and the clock cannot drift.
"""

from datetime import datetime, timedelta, timezone

BEAT_SECONDS = 15 * 60          # one beat per 15 real minutes
BEATS_PER_DAY = 4               # => 1 real hour == 1 city day
BLOCKS = ["morning", "afternoon", "evening", "night"]

# A beat with cognition costs an LLM call. A very long outage is paid off with cheap
# deterministic beats for the backlog and full cognition only for the recent tail, so a
# two-day Actions failure cannot detonate the daily token budget in a single run.
# Beats cannot be narrated faster than about one a minute (Groq's per-minute ceiling), so
# this is also a wall-clock budget for the job: 12 beats is roughly 13 minutes of catch-up,
# comfortably inside the workflow timeout, and three city-days of narrated backlog is far
# more than anyone returning to the city will read.
MAX_COGNITION_BEATS = 12


def now_utc():
    return datetime.now(timezone.utc)


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def beats_owed(last_beat_at, now=None):
    """How many whole beats have elapsed since the last one was paid."""
    now = now or now_utc()
    elapsed = (now - parse(last_beat_at)).total_seconds()
    return max(0, int(elapsed // BEAT_SECONDS))


def advance(last_beat_at, beats):
    return iso(parse(last_beat_at) + timedelta(seconds=beats * BEAT_SECONDS))


def split(beats):
    """Given the backlog, decide how many beats get cognition and how many are fast-forwarded.

    Returns (quiet_beats, thinking_beats). Quiet beats still move people, decay needs and
    tick debts — the city keeps living, it just does not narrate that stretch.
    """
    if beats <= MAX_COGNITION_BEATS:
        return 0, beats
    return beats - MAX_COGNITION_BEATS, MAX_COGNITION_BEATS


def day_of(beat):
    return beat // BEATS_PER_DAY


def block_of(beat):
    return BLOCKS[beat % BEATS_PER_DAY]


def is_day_end(beat):
    """True on the last beat of a city day — when reflection and the Gazette run."""
    return beat % BEATS_PER_DAY == BEATS_PER_DAY - 1


def describe(beat):
    return f"Day {day_of(beat)}, {block_of(beat)}"
