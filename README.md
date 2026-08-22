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
- **debts** — an explicit ledger of who owes whom and by when, and the block's main engine.
  When somebody is late, the person who is *owed* loses patience, gets angry rather than
  sad, and goes looking for them; routing overrides their whole day to do it. When the two
  end up in a room it resolves — paid, promised, refused, or it turns physical — and new
  obligations keep forming so the city is never square for long.
- **volatility** — an authored number per character for who starts things. The block has
  about ten people who escalate rather than let something go, and a handful who calm a room
  down, and the difference is what makes a scene rather than a conversation.
- **feuds** — what is left after a confrontation goes badly. They persist, they pull two
  people toward each other, and they fade only if nothing feeds them.
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

## Things you can stand and watch

Every dramatic event used to resolve inside one beat and leave nothing but a line of text —
so on the map a beating looked exactly like a quiet afternoon. `sim/incidents.py` gives an
event a **place and a lifespan**, and a beat is fifteen real minutes, so a two-beat fight is
half an hour of trouble on a street corner you can actually catch.

Fires, fights, public rows, shots fired, police raids, arrests, vigils, building work and
openings. It is deliberately not graphic: shapes, flashes and drifting smoke, the register
of a police report seen from across the street. Nothing is depicted.

Because the map is 128 tiles wide, an incident is a few pixels at fit-zoom — so each one
also gets a pulsing ring drawn in screen space, and appears at the top of the panel with
how long it has left. Clicking takes you there to watch before it stops.

Costs nothing: the simulation only records where the beat's events happened.

## Driving

Twelve people have something to drive, chosen by what they actually do: three police
cruisers, vans for the auto shop and the cannery foreman and whoever is moving Booker's
stock, cars for the doctor, the outside money, and the man who runs the corner. Not
everybody — a block where all thirty own a car is a suburb, and the people who walk are half
the reason the streets have anybody on them.

Anything more than about twenty tiles gets driven, so crossing districts is a journey and
nobody drives to the shop at the end of their own street. A driven trip is routed by
`city.road_path` — Dijkstra weighted so tarmac is cheap and everything else is only worth
crossing to reach it — which keeps cars on the streets instead of cutting across Marrow
Green. The same trip: 75% on road walking, 96% driving.

They travel at 15 tiles a second against a walking 3.5, so a cross-town run takes about
three seconds and you can watch it take the corners. The sprite is the vehicle while they
are in it and the person again when they get out.

There is also thin ambient traffic so the streets are not dead between journeys — but the
cars worth watching are the ones with somebody from the cast at the wheel. Corridors are
read off the map itself, so a street the city builds gets traffic with no other change.

## Room to grow

The map was 96x72 and effectively full: one 8x6 plot left and nothing bigger, so the
expansion system had nowhere to put anything. It is now **128x104** — the original blocks
keep their exact coordinates, and the extra ground is open land to the south and east, with
a fifth district, **The Flats**, that starts completely empty.

Growth was throttled hard when there was nowhere to build. Now it runs at roughly a building
every couple of real hours, and `find_plot` prefers whichever district is thinnest, so the
city spreads into open ground instead of thickening one corner. Over a simulated week: nine
new buildings, six of them in The Flats, including a library and a social club.

## Staying alive on a free allowance

The city used to think brilliantly until early afternoon and then go silent for the rest of
the day — and a silent city has no dialogue, which means no speech bubbles, which is the
thing a visitor actually notices. Three changes so it lasts the whole day:

- **The instruction prompt was 1,388 tokens, re-sent every beat** — 133K a day, a third of
  the entire allowance, spent restating the same rules. Compressed to 931 without dropping
  a single rule.
- **Attention now narrows as the allowance runs down** (`cognition.SLOT_LADDER`): eleven
  people early, down to four when it is nearly gone. A narrower beat is enormously better
  than no beat.
- **The mechanical drama speaks.** Confrontations and instigations already produced events;
  they now put words in people's mouths too, so there are speech bubbles even on a beat that
  spends nothing. Cognition overwrites them with better lines for whoever it narrates, so a
  real line always wins over a canned one.

Together: ~84 of 96 beats narrated per day inside a budget deliberately held below the cap
(the key is shared with other tools), and visible speech on the rest.

## Never running out of tokens

A tier (`FAST` / `DEEP`) is not a model id. It used to be, which is exactly why the city
died silently for eighty-five city-days when Groq retired both of them. `sim/llm.py` now
walks a chain of free providers, and within each one a list of candidate models, so a
retirement demotes an entry instead of stopping the city:

| provider | free allowance | secret to set |
|---|---|---|
| Groq | ~200K tokens/day per model | `GROQ_API_KEY` |
| Cerebras | ~1M tokens/day — the largest | `CEREBRAS_API_KEY` |
| Google Gemini | ~1,500 requests/day | `GEMINI_API_KEY` |
| OpenRouter | rotating `:free` models | `OPENROUTER_API_KEY` |
| Ollama | whatever is on this machine | none — local only |

Adding a repo secret is the entire job of enabling a provider; the workflow already passes
all of them and a provider with no key is skipped silently. Ordered most-generous-first,
and each one is only abandoned for the day when it actually says it is out.

**Local models are deliberately opt-in** (`THE_CUT_ALLOW_LOCAL=1`). The city lives on a
cron in the cloud, so a model on somebody's desktop cannot serve it — treating Ollama as a
fallback for the thing that actually needs one would be a lie. It is there for local runs,
where it works well: a full beat, eleven people narrated, on `qwen2.5:14b-instruct`.

The dialogue Worker has its own chain — Groq, then **Cloudflare Workers AI**, which needs no
key and no second account because the Worker is already running on Cloudflare. The one part
of this a player actually touches cannot be taken out by a token cap somewhere else.

## Running it locally

```bash
py -m sim.tick --bootstrap     # create a fresh city
py -m sim.tick --owe 20        # pretend 20 beats are owed (catch-up testing)
py -m sim.tick --dry-run       # simulate, write nothing
py selftest.py                 # 25 invariants — run before touching the clock
py -m http.server 8777         # then open http://localhost:8777
```

## Talking to them

Walk up to somebody and press E. The Cloudflare Worker in `worker/` is the only thing that
can hold the Groq key *and* write into the city, so it answers in character and queues the
exchange for the next beat to absorb.

Three things make it a conversation rather than a vending machine:

- **They remember the conversation.** History is kept per caller per character in KV for two
  hours, so a back-and-forth holds together and they answer what you actually just said.
- **They know what they are living through.** The persona is built from the same facts the
  simulation's own prompt uses — who owes them money and how late it is, who they are
  feuding with, whether they are grieving, whether they are in a cell, what laws the block
  has passed. Not just a name and some adjectives.
- **What you tell them travels.** If you say something about somebody else, the same call
  that writes the reply extracts it as a *claim*. That becomes an unverified **lead**: they
  go and find the person it is about, and when they do it resolves against the city's own
  record — the subject's actual memories — rather than a coin flip. A true rumour finds its
  evidence and costs somebody a friendship. An invented one usually gets dropped, unless the
  person you told is volatile or frightened enough to believe it anyway.

You are the only source of information in this city that did not come from inside it.

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
