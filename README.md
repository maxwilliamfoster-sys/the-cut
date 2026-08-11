# THE CUT

A pixel-art American city with twelve people in it. They have names, memories,
personalities, routines and moods. Nobody wrote the story.

**It keeps running when you close the tab.** The city's heartbeat is a GitHub Actions
cron, not your computer — one beat every fifteen real minutes, four beats to a city day,
so roughly one city day passes every real hour whether anyone is watching or not.

Every beat is a commit. `git log` is the chronicle of the city.

---

## How it works

```
GitHub Actions (every ~15 min)          Your browser (whenever)
  sim/tick.py                             index.html
    how many beats are owed?                fetches state/*.json
    move everyone along their routine       walks everyone along their path
    decay needs, tick heat and debts        night wash, ambient drift
    roll the event table                    click anyone to read their mind
    commit state/ back to the repo
```

### Time

A **beat** is six city-hours — morning, afternoon, evening, night. City time is derived
from *real elapsed time*, never from how many times the cron actually fired. GitHub delays
scheduled runs by 5–30 minutes routinely and drops them under load; a run that arrives
late simply pays several beats at once. After a long outage the backlog is fast-forwarded
quietly and only the recent tail is narrated in full.

### What generates the story

There is no script and no story state machine. Narrative falls out of:

- **routines** — everyone has somewhere they are supposed to be
- **needs** — energy, happiness, stress, social need, fear, all relaxing toward a personal
  resting level, all pushed around by what happens
- **heat** — police attention per district, which rises with visible crime and takes about
  six city-days to bleed off. People in the wrong line of work avoid hot districts.
- **debts** — an explicit ledger of who owes whom and by when. Deadlines force decisions,
  and decisions are where drama comes from.
- **the event table** — a weighted, seeded roll each beat. Reproducible, so an interesting
  week can be replayed and a bug can be caught.

## Running it locally

```bash
py -m sim.tick --bootstrap     # create a fresh city
py -m sim.tick --owe 20        # pretend 20 beats are owed (catch-up testing)
py -m sim.tick --dry-run       # simulate, write nothing
py selftest.py                 # 25 invariants — run before touching the clock
py -m http.server 8777         # then open http://localhost:8777
```

## State

```
state/map.json       the city, generated once from sim/city.py
state/world.json     clock, weather, heat, turf, debts, recent events
state/agents.json    twelve people: mood, relationships, memories
state/log-wNNN.jsonl append-only event log, rotated per city-week
```

## Status

- [x] **Phase 1** — the city breathes: routines, needs, heat, debts, events, renderer, cron
- [ ] **Phase 2** — the city thinks: batched LLM cognition, memory streams, opinions
- [ ] **Phase 3** — you exist: a player sprite, and characters who remember meeting you
- [ ] **Phase 4** — the city narrates itself: nightly reflection, a daily newspaper

Sprites are drawn procedurally in `index.html` — no asset packs, no licences, nothing to
download.
