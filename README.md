# THE CUT

A pixel-art American city with thirty people in it — families, shop staff, the priest, the
man who sleeps under the flyover. They have names, memories, personalities, routines and
moods, and they are always doing something specific: asleep in a bed, washing up, restocking
shelves, watching television. Nobody wrote the story.

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

### Thirty people on a fixed token budget

The cast is two-tier, and the reason is arithmetic. Groq reserves `prompt + max_tokens`
against a 6,000-per-minute ceiling; twelve people cost ~2,000 prompt tokens, so thirty would
need roughly 8,000 — over the per-minute limit *and* about double the daily cap.

So attention is rationed rather than the cast being capped:

- **Everyone** gets a deterministic activity every beat from `sim/activities.py`, chosen
  from where they are, the time of day, and whether they are at work, at home or visiting.
  A background character loading a dishwasher does not need a language model to decide that.
- **Eleven people per beat** get actual cognition, picked by `cognition.select()`: the
  principals, whoever the event landed on, anyone the player spoke to, anyone with an overdue
  debt, anyone standing in a room with other people — plus a rotation term so nobody goes
  unheard for long.

Cost is therefore flat at ~3,500 tokens a beat whether the city holds twelve people or
thirty. An unselected character is not idle; they are just not being narrated.

Activities also *place* people: an activity names the furniture it happens at, so somebody
asleep is drawn in a bed and somebody washing up is at the sink, rather than the whole
household standing on one anchor tile.

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
- **cognition** — one batched LLM call per beat decides what the selected cast do about the
  above, what they think, what they say to whoever is standing next to them, and what they
  will still be turning over tomorrow.
- **mortality** — people die, rarely, of things the city already tracks: age, sustained
  stress, the heat on their district, a building coming down on them. Everyone who knew
  them reacts in the direction they actually felt — grief scaled by affinity, so somebody
  who hated the deceased gets relief and the fear that comes with it. Grief persists for
  days and shows in what people get wrong. Two city-days later there is a funeral, and the
  whole block turns out for it.
- **the city itself** — buildings burn, are condemned, stand as walkable rubble for days,
  go behind scaffolding, and reopen — sometimes as something else entirely, so the block's
  character drifts over months without anybody authoring it. When homes get tight or the
  city has been static too long, a new building goes up on empty ground.
- **law** — see below. The block writes its own.

### Law nobody wrote

There is no statute book in this repo. The block accumulates incidents, and when enough of
them are things no existing rule covers, the model is asked **once** to write a single
ordinance in response to what actually happened. The result is a legal code that reads as a
history of the city's worst weeks.

Only the drafting costs tokens. Everything downstream is plain Python:

```
propose  ── LLM, rare, budget-capped ──> a law, with keywords
detect   ── keyword scan on narrated actions
arrest   ── caught or not, by district heat and how many people saw
trial     ── a jury of nine actual characters
sentence ── a fine, days in a cell, days of service, or acquittal
```

The jury is the interesting part. Verdicts are voted by real characters weighted by how
they actually feel about the accused, so a popular defendant walks and somebody the block
has turned on does not. That is the social graph deciding the outcome, and it costs
nothing — no model call could produce a more grounded answer than the affinities the city
has spent weeks building. Detection uses keywords the model supplies **when it writes the
law**, so the expensive judgement happens once and the machine applies it ten thousand
times.

### The token constraint that shapes the whole design

Groq's free tier is bound by tokens per *day*, and reserves `prompt + max_tokens` against a
per-*minute* ceiling as a single booking — exceed it and the request is refused outright
(413), not truncated. So:

- **one batched call per beat for the entire cast**, never one per character, which would
  spend a day's allowance in about an hour
- the reply allowance is sized against the prompt at call time, not chosen freely
- beats cannot be narrated faster than roughly one a minute, so catch-up paces itself and
  caps at 12 narrated beats; anything older is fast-forwarded quietly

Cost lands around 3,400 tokens a beat, ~320K a day against a 450K self-imposed budget, with
automatic failover to OpenRouter if Groq's daily cap is ever hit.

## Running it locally

```bash
py -m sim.tick --bootstrap     # create a fresh city
py -m sim.tick --owe 20        # pretend 20 beats are owed (catch-up testing)
py -m sim.tick --dry-run       # simulate, write nothing
py selftest.py                 # 25 invariants — run before touching the clock
py -m http.server 8777         # then open http://localhost:8777
```

## Walking in

Press **WASD** on the live page and you drop into the city as a sprite. Stand next to
somebody and press **E** to talk to them.

You are not simulated. Between beats the cloud has no idea you exist, and if you never
speak to anyone you leave no trace. The only thing that crosses from the browser into the
city is a line you actually said:

```
browser  ──POST /talk──▶  Cloudflare Worker  ──▶ Groq   (replies in character)
                                │
                                └──▶ KV queue ──▶ next cron beat ──▶ their memory stream
```

The Worker exists because the browser can hold neither of the two things needed to make
someone remember you: the Groq key (the page is public) and a write path into the repo.

Two details that matter:

- The Worker fetches the character's persona from the **published state, server-side**. If
  the client supplied it, anyone could POST an invented "character", have the endpoint
  speak in the city's voice, and get it written into the city's memory as fact.
- The memory is written in plain Python on drain, not left to the model to volunteer. If
  "they remember you" depended on the model choosing to emit a memory object, it would work
  nearly always — and the one time it quietly didn't would be the exact moment the whole
  premise stopped being true.

`/talk` is gated by a player key and rate-limited per IP, so a public URL cannot burn the
token budget.

## State

```
state/map.json       the city as it currently stands — re-exported whenever it changes
state/world.json     clock, weather, heat, turf, debts, events, buildings, laws, charges, dead
state/agents.json    the cast: mood, relationships, memories, who is alive, who is inside
state/log-wNNN.jsonl append-only event log, rotated per city-week
```

## Status

- [x] **Phase 1** — the city breathes: routines, needs, heat, debts, events, renderer, cron
- [x] **Phase 2** — the city thinks: batched cognition, memory streams, opinions, dialogue
- [x] **Phase 3** — you exist: a player sprite, and characters who remember meeting you
- [x] **Phase 4** — the city narrates itself: nightly reflection, a daily newspaper
- [x] **Phase 5** — the city can be lost: death and grief, buildings that burn and are
      rebuilt, growth onto empty land, and law the block writes and enforces on itself

## The end of a day

Two things happen when a city-day closes.

**Reflection** turns incidents into a character. During the day people record what happened;
at night they decide what it *meant*. "Ruiz asked about my father twice" is a memory;
"somebody is building a case against Dad" is a belief — and beliefs are what change how a
person behaves next week. Beliefs are allowed to be wrong: people draw the conclusion their
fears point at. Junie has decided Booker is the only one who genuinely wants to help her,
which is the opposite of true.

**The Gazette** is the same day written from outside — a short front page in
`state/gazette/day-NNN.md`. Coming back to the city gives you that paper plus everything
that happened since your last visit, rather than a diff.

The model split is forced, not chosen: 70b gets 100K tokens a day against 8b's 500K, and
there are 24 city-days in a real day. Reflection on 70b would eat the entire 70b allowance,
so reflection (a summarising job) runs on 8b and the scarce budget goes where prose quality
is the whole point. The Gazette falls back to 8b rather than skipping if 70b is spent.

Sprites are drawn procedurally in `index.html` — no asset packs, no licences, nothing to
download.
