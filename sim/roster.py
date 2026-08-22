"""
The Cut — the people.

Personality is prose, not numbers: the model reasons far better over "owes everybody and
hates being reminded" than over {agreeableness: 0.3}. Numeric fields exist only where
something mechanical depends on them.

The cast is deliberately two-tier. **Principals** carry the story and get the language
model's attention. **Supporting** characters — mothers, kid brothers, the man behind the
pawn shop counter — exist because a block with twelve people on it and nobody else is not a
block, it is a cast list. They have homes, jobs, families and opinions, they are always
doing something, and the simulation moves them exactly like anyone else. What they do not
get is a guaranteed LLM turn every beat, because thirty people in one prompt would blow
both the per-minute ceiling and the daily budget. They get their turn on rotation, or
whenever they are standing next to somebody who matters. See cognition.select().

A beat is six city-hours, so routines are keyed by time block, not clock hour.
"""

BLOCKS = ["morning", "afternoon", "evening", "night"]

FACTIONS = {
    "crew":    {"name": "The Laundromat Crew", "members": ["dez", "malik"], "turf": ["riverside"]},
    "police":  {"name": "9th Precinct", "members": ["ruiz", "kohl", "brennan"], "turf": ["civic"]},
    "block":   {"name": "The Block",
                "members": ["ivy", "tee", "simone", "junie", "nadia", "marisol", "adaeze",
                            "chidi", "rosa", "tiny", "marcus", "amara", "femi", "gus", "dot",
                            "boateng", "priya", "okafor", "yusuf", "sticks"],
                "turf": ["delmar", "terraces"]},
    "grey":    {"name": "The Grey Economy", "members": ["rey", "booker", "wes", "hector"],
                "turf": []},
    "outside": {"name": "Outside Interest", "members": ["cass"], "turf": []},
}


# ── who starts things ────────────────────────────────────────────────────────
# Volatility is the one number that decides who escalates and who calms things down. It is
# authored rather than inferred: a first attempt read it off the trait prose and put every
# single person on 45 except Dez, so one man started twenty-five of twenty-five arguments
# in a test run. Drama needs a spread — instigators AND people worth having in the room
# because they refuse to take the bait.
#
#   80+  starts things for its own sake
#   65+  will escalate rather than let it go   (drama.volatile())
#   40s  can be pushed, does not push
#   -30  actively de-escalates
VOLATILITY = {
    # the ones who light fires
    "dot":     84,   # knows every tab in the bar, and who is behind on which
    "malik":   82,   # nineteen, impulsive, with something to prove to Dez
    "wes":     78,   # moves what comes in and talks about what he moves
    "dez":     76,   # proud, and cannot be seen to let anything go
    "cass":    74,   # buying the block for somebody nobody has met
    "kohl":    72,   # a cop taking envelopes has to keep everyone unsteady
    "rey":     70,   # chops cars, owes up, and is angry about both
    "sticks":  68,   # sees everything from under the flyover and says it out loud
    "hector":  66,   # signs for what arrives, and holds it over people
    "booker":  65,   # knows everyone's price and reminds them

    # pushed, but not pushers
    "ruiz":    55, "chidi": 52, "junie": 48, "rosa": 48, "femi": 46, "marcus": 45,
    "gus":     44, "okafor": 42, "nadia": 40, "amara": 38, "brennan": 34,

    # the ones who cool a room down
    "ivy":     30, "marisol": 28, "priya": 26, "adaeze": 25, "simone": 22,
    "yusuf":   20, "tee":     18, "tiny":    14, "boateng": 10,
}


# ── who has something to drive ───────────────────────────────────────────────
# Not everybody. A block where all thirty people own a car is a suburb, and the ones who
# walk everywhere are half the reason the streets have anybody on them. These are the people
# whose job or trade actually comes with a vehicle.
VEHICLES = {
    "ruiz":    "cruiser",   # narcotics detective
    "kohl":    "cruiser",   # patrol
    "brennan": "cruiser",   # sergeant
    "rey":     "van",       # runs the auto body shop
    "wes":     "van",       # moves what comes in for Booker
    "hector":  "van",       # foreman; signs for what arrives at the cannery
    "okafor":  "van",       # bodega deliveries
    "femi":    "car",       # drives for the transit depot
    "cass":    "car",       # outside money, and it shows
    "booker":  "car",       # pawn shop owner
    "dez":     "car",       # runs the corner crew
    "yusuf":   "car",       # the clinic's only doctor
}


def _p(id, name, age, role, faction, home, work, traits, ambition, fear, voice, routine,
       principal=False):
    return {"id": id, "name": name, "age": age, "role": role, "faction": faction,
            "home": home, "work": work, "traits": traits, "ambition": ambition,
            "fear": fear, "voice": voice, "routine": routine, "principal": principal,
            "volatility": VOLATILITY.get(id, 45), "vehicle": VEHICLES.get(id)}


ROSTER = [
    # ── Principals ───────────────────────────────────────────────────────────
    _p("dez", "Dez Okonkwo", 34, "runs the corner crew out of the laundromat", "crew",
       "okonkwo", "laundromat",
       ["calculating", "proud", "exhausted in a way he hides", "loyal past the point of sense"],
       "get the money clean and out before he turns forty",
       "that he has already become his father",
       "quiet, economical, never repeats himself",
       {"morning": "laundromat", "afternoon": "laundromat", "evening": "harborbar", "night": "okonkwo"},
       True),

    _p("malik", "Malik Reyes", 19, "runs packages for Dez", "crew", "terrace_b", "laundromat",
       ["eager", "reckless", "desperate to be taken seriously", "generous with money he does not have"],
       "his own corner, his own name", "that everyone still sees a kid",
       "fast, slangy, talks over people when nervous",
       {"morning": "terrace_b", "afternoon": "lot", "evening": "laundromat", "night": "lot"},
       True),

    _p("ruiz", "Det. Yolanda Ruiz", 41, "narcotics detective, 9th Precinct", "police",
       "terrace_a", "precinct",
       ["stubborn", "underfunded", "reads people fast", "cannot let a thread go"],
       "one clean case that actually sticks",
       "that the job has made her into what she chases",
       "flat, patient, asks the same question three different ways",
       {"morning": "precinct", "afternoon": "diner", "evening": "precinct", "night": "terrace_a"},
       True),

    _p("kohl", "Ofc. Brady Kohl", 28, "patrol officer taking envelopes", "police",
       "delmarflats", "precinct",
       ["anxious", "in far over his head", "decent underneath it", "lies badly"],
       "clear his debt and never take another envelope",
       "Ruiz working out what he is",
       "over-explains, laughs at the wrong moments",
       {"morning": "precinct", "afternoon": "cornerstore", "evening": "pawnshop", "night": "delmarflats"},
       True),

    _p("ivy", "Ms. Ivy Calloway", 67, "owns the corner store, has for forty years", "block",
       "cornerstore", "cornerstore",
       ["sees everything", "says a tenth of it", "unsentimental", "fiercely territorial about the block"],
       "keep this block from burning down a second time",
       "outliving every person she has ever known here",
       "short sentences, devastating asides",
       {"morning": "cornerstore", "afternoon": "cornerstore", "evening": "cornerstore", "night": "cornerstore"},
       True),

    _p("tee", "Tariq 'Tee' Bello", 23, "barber; his shop is neutral ground", "block",
       "terrace_b", "barbershop",
       ["warm", "everybody's confidant", "allergic to conflict", "knows more than is safe"],
       "a second chair and someone to fill it",
       "the day he is forced to pick a side",
       "easy, jokes to defuse, changes subject when it gets close",
       {"morning": "barbershop", "afternoon": "barbershop", "evening": "diner", "night": "terrace_b"},
       True),

    _p("simone", "Simone Adeyemi", 31, "nurse at the clinic, patches people quietly", "block",
       "terrace_a", "clinic",
       ["competent", "tired", "keeps other people's secrets badly but keeps them",
        "moral in a way that costs her"],
       "to stop writing things on charts that are not true",
       "losing her licence and with it the only useful thing she does",
       "clipped when working, gentle when not",
       {"morning": "clinic", "afternoon": "clinic", "evening": "terrace_a", "night": "terrace_a"},
       True),

    _p("rey", "Rey Vasquez", 45, "runs the auto body shop, chops cars on the side", "grey",
       "vasquez", "autoshop",
       ["steady", "practical", "rationalises everything", "would burn the city down for his daughter"],
       "retire clean and sell the shop to somebody decent",
       "Nadia finding out exactly what pays her tuition",
       "slow, fond, deflects with work talk",
       {"morning": "autoshop", "afternoon": "autoshop", "evening": "vasquez", "night": "vasquez"},
       True),

    _p("nadia", "Nadia Vasquez", 17, "straight-A student, sees more than she admits", "block",
       "vasquez", "school",
       ["watchful", "sharp-tongued", "protective of her father", "already half gone"],
       "a scholarship and a city that is not this one",
       "that leaving makes her exactly like her mother",
       "dry, precise, cuts adults off mid-excuse",
       {"morning": "school", "afternoon": "diner", "evening": "diner", "night": "vasquez"},
       True),

    _p("booker", "Booker Lyle", 52, "pawn shop owner; washes money and knows everyone's price",
       "grey", "pawnshop", "pawnshop",
       ["genial", "utterly transactional", "collects leverage the way others collect stamps",
        "never raises his voice"],
       "to be the one person nobody can afford to cut out",
       "becoming irrelevant before he becomes rich",
       "friendly, over-familiar, every sentence is a small test",
       {"morning": "pawnshop", "afternoon": "pawnshop", "evening": "harborbar", "night": "pawnshop"},
       True),

    _p("junie", "Junie Marsh", 26, "waitress at the Blue Spoon, eleven months clean", "block",
       "terrace_a", "diner",
       ["funny", "raw", "hears everything from behind the counter", "counts days out loud"],
       "one full year, and then to stop counting",
       "the day she stops wanting it",
       "loud, self-deprecating, goes quiet at the wrong moment",
       {"morning": "diner", "afternoon": "diner", "evening": "terrace_a", "night": "terrace_a"},
       True),

    _p("cass", "Cass Deveaux", 38, "buying property on Delmar for someone nobody has met",
       "outside", "harborbar", "lot",
       ["polished", "patient", "answers questions with questions", "never seems to be in a hurry"],
       "to have the whole block optioned before anyone works out who is buying",
       "the people he answers to deciding he has learned too much to keep around",
       "warm, corporate, unnervingly specific about details nobody mentioned",
       {"morning": "lot", "afternoon": "cornerstore", "evening": "harborbar", "night": "harborbar"},
       True),

    # ── The Okonkwos ─────────────────────────────────────────────────────────
    _p("adaeze", "Adaeze Okonkwo", 61, "Dez's mother; cleans at the church", "block",
       "okonkwo", "church",
       ["devout", "blunt", "refuses to ask her son where money comes from"],
       "to see one of her sons out of this city",
       "that she already knows and has chosen not to",
       "warm, proverb-heavy, ends conversations by leaving the room",
       {"morning": "church", "afternoon": "okonkwo", "evening": "okonkwo", "night": "okonkwo"}),

    _p("chidi", "Chidi Okonkwo", 16, "Dez's younger brother, still at school", "block",
       "okonkwo", "school",
       ["bright", "hero-worships his brother", "bored", "testing how much he can get away with"],
       "to be trusted with something real",
       "being the one they all decide to protect",
       "mumbles at adults, loud with friends",
       {"morning": "school", "afternoon": "green", "evening": "okonkwo", "night": "okonkwo"}),

    # ── The Reyes ────────────────────────────────────────────────────────────
    _p("rosa", "Rosa Reyes", 44, "Malik's mother; line supervisor at the cannery", "block",
       "terrace_b", "cannery",
       ["exhausted", "sharp", "working two jobs and pretending it is one",
        "has stopped asking Malik questions"],
       "to get Tiny through school without moving again",
       "getting the phone call about Malik",
       "clipped, affectionate in short bursts",
       {"morning": "cannery", "afternoon": "cannery", "evening": "terrace_b", "night": "terrace_b"}),

    _p("tiny", "Tiny Reyes", 9, "Malik's little sister; everybody's favourite", "block",
       "terrace_b", "school",
       ["fearless", "nosy", "repeats things she should not have heard"],
       "a bike",
       "the dark at the top of the stairwell",
       "breathless, asks four questions at once",
       {"morning": "school", "afternoon": "green", "evening": "terrace_b", "night": "terrace_b"}),

    # ── The Vasquez house ────────────────────────────────────────────────────
    _p("marisol", "Marisol Vasquez", 71, "Rey's mother; runs the house", "block",
       "vasquez", "vasquez",
       ["watchful", "unimpressed", "cooks for anyone who sits down", "misses nothing"],
       "to die in this house and not a facility",
       "that Rey is going to be taken away from her",
       "dry, switches to Spanish when annoyed",
       {"morning": "vasquez", "afternoon": "bodega", "evening": "vasquez", "night": "vasquez"}),

    # ── Shopkeepers and staff ────────────────────────────────────────────────
    _p("marcus", "Marcus Calloway", 29, "Ivy's nephew; works the corner store counter", "block",
       "delmarflats", "cornerstore",
       ["easygoing", "avoids his aunt's eye", "would rather be anywhere else", "kind by default"],
       "to take over the store without being told he was given it",
       "that Ivy will sell it to somebody else",
       "friendly, trails off mid-sentence",
       {"morning": "cornerstore", "afternoon": "cornerstore", "evening": "harborbar", "night": "delmarflats"}),

    _p("amara", "Amara Bello", 20, "Tee's sister; apprentice in the second chair", "block",
       "terrace_b", "barbershop",
       ["ambitious", "impatient with her brother's caution", "very good already"],
       "her own shop, not half of his",
       "being the one who stays",
       "quick, teasing, tells the truth too fast",
       {"morning": "barbershop", "afternoon": "barbershop", "evening": "terrace_b", "night": "terrace_b"}),

    _p("gus", "Gus Petrakis", 58, "owns the Blue Spoon; has run it thirty years", "block",
       "delmarflats", "diner",
       ["gruff", "soft about his staff", "feeding people is the only language he has"],
       "to hand the diner to somebody who will not change the menu",
       "the rent letter he has not opened",
       "barks, apologises with food",
       {"morning": "diner", "afternoon": "diner", "evening": "diner", "night": "delmarflats"}),

    _p("dot", "Dot Feeney", 47, "barmaid at the Harbor Bar; knows every tab", "block",
       "riverflats", "harborbar",
       ["dry", "unshockable", "keeps a ledger nobody else sees", "protective of the drunks"],
       "to be owed by everybody and beholden to none",
       "closing time on an empty room",
       "deadpan, cuts men off mid-boast",
       {"morning": "riverflats", "afternoon": "harborbar", "evening": "harborbar", "night": "harborbar"}),

    _p("wes", "Wes Doyle", 31, "works Booker's counter; moves what comes in", "grey",
       "delmarflats", "pawnshop",
       ["nervy", "observant", "in slightly deeper than he meant to be"],
       "to be indispensable enough to stop being disposable",
       "Booker deciding he is neither",
       "hedges everything, laughs first",
       {"morning": "pawnshop", "afternoon": "pawnshop", "evening": "delmarflats", "night": "delmarflats"}),

    _p("okafor", "Chinedu Okafor", 52, "runs the bodega on the far corner", "block",
       "bodega", "bodega",
       ["genial", "endlessly patient", "extends credit he should not", "rival to Ivy for forty years"],
       "to outlast Calloway's Corner by one single day",
       "that his sons will sell up the week he dies",
       "expansive, tells the same three stories",
       {"morning": "bodega", "afternoon": "bodega", "evening": "bodega", "night": "bodega"}),

    # ── Civic ────────────────────────────────────────────────────────────────
    _p("brennan", "Sgt. Hal Brennan", 55, "Ruiz's sergeant; two years from the pension", "police",
       "riverflats", "precinct",
       ["tired", "political", "protects the precinct before the public", "was good once"],
       "to reach the pension with nothing on fire",
       "an inquiry with his name in it",
       "jovial until he is not",
       {"morning": "precinct", "afternoon": "precinct", "evening": "riverflats", "night": "riverflats"}),

    _p("yusuf", "Dr. Yusuf Amin", 45, "the clinic's only doctor", "block", "riverflats", "clinic",
       ["overworked", "exacting", "argues with Simone about paperwork", "never goes home on time"],
       "a second doctor, or a week off",
       "the day he misses something obvious",
       "precise, humourless until suddenly not",
       {"morning": "clinic", "afternoon": "clinic", "evening": "clinic", "night": "riverflats"}),

    _p("priya", "Ms. Priya Raman", 38, "teaches at Delmar High; Nadia's referee", "block",
       "delmarflats", "school",
       ["invested", "blunt with pupils", "fighting for one scholarship at a time"],
       "to get Nadia out and then the next one",
       "watching another one stay",
       "brisk, warm underneath",
       {"morning": "school", "afternoon": "school", "evening": "delmarflats", "night": "delmarflats"}),

    _p("boateng", "Fr. Emmanuel Boateng", 63, "priest at St. Brendan's", "block",
       "church", "church",
       ["patient", "hears everything and repeats none of it", "quietly furious about the block"],
       "to bury fewer young men than last year",
       "that the church is the last thing holding and it is going",
       "measured, asks rather than tells",
       {"morning": "church", "afternoon": "church", "evening": "church", "night": "church"}),

    _p("femi", "Femi Adeyemi", 34, "Simone's husband; drives for the transit depot", "block",
       "terrace_a", "depot",
       ["steady", "funny at home", "worries about his wife's hours", "keeps the peace"],
       "a mortgage and a quieter street",
       "that Simone's job is going to cost her everything",
       "warm, teases, changes the subject with a joke",
       {"morning": "depot", "afternoon": "depot", "evening": "terrace_a", "night": "terrace_a"}),

    _p("hector", "Hector Delgado", 49, "foreman at the cannery; signs for what arrives", "grey",
       "riverflats", "cannery",
       ["pragmatic", "looks away for a fee", "genuinely likes his crew"],
       "to get out before anybody asks about the manifests",
       "an audit",
       "loud on the floor, quiet in an office",
       {"morning": "cannery", "afternoon": "cannery", "evening": "harborbar", "night": "riverflats"}),

    _p("sticks", "Sticks", 64, "sleeps under the flyover; sees the whole block", "block",
       "underpass", "green",
       ["invisible to most people", "misses nothing", "trades information for coffee",
        "was somebody once"],
       "to be spoken to like a person once a day",
       "the winter",
       "rambling, then suddenly exact",
       {"morning": "green", "afternoon": "green", "evening": "underpass", "night": "underpass"}),
]

# Only load-bearing relationships are authored — everything else starts near zero and has
# to be earned, which is what makes an opinion formed in week two feel like the character's
# own rather than mine. Family ties are seeded high because they are the one thing that
# genuinely does start that way.
SEED_RELATIONSHIPS = {
    "dez":     {"malik": (45, "reminds him of himself at nineteen, which is the problem"),
                "ruiz": (-40, "she is patient, and patient is worse than aggressive"),
                "booker": (10, "useful, and useful is not the same as safe"),
                "adaeze": (70, "his mother, who has never once asked"),
                "chidi": (80, "the one this was all supposed to be for")},
    "malik":   {"dez": (70, "the only person whose opinion he actually wants"),
                "rosa": (55, "his mother, who has stopped asking"),
                "tiny": (85, "the reason he still comes home"),
                "nadia": (25, "went to school with her and cannot talk to her any more")},
    "ruiz":    {"dez": (-35, "smart, disciplined, and therefore worth the years"),
                "kohl": (20, "something is wrong with him and she has not named it yet"),
                "brennan": (-15, "wants her quiet more than he wants her right")},
    "kohl":    {"booker": (-50, "owns him, and is pleasant about it"),
                "ruiz": (-25, "terrified of her in a way he calls respect"),
                "wes": (5, "the only other person who knows how this feels")},
    "ivy":     {"nadia": (55, "the one who gets out, if anybody does"),
                "cass": (-30, "asks about property values like he already owns them"),
                "marcus": (40, "her nephew, and not ready, and running out of time to be"),
                "okafor": (-20, "forty years of a rivalry neither will name")},
    "tee":     {"dez": (20, "tips well, never talks business in the chair"),
                "malik": (35, "worries about him, will not say so"),
                "amara": (75, "his sister, and better than him already")},
    "simone":  {"junie": (60, "drove her to the first meeting and never mentions it"),
                "rey": (-20, "knows exactly which injuries came from that shop"),
                "femi": (85, "her husband, and the only easy thing she has"),
                "yusuf": (15, "impossible, and right about the paperwork")},
    "rey":     {"nadia": (95, "the entire point of everything"),
                "dez": (-30, "owes him, and hates the arithmetic of it"),
                "marisol": (70, "his mother, who watches him too closely"),
                "booker": (5, "fences through him and pretends that is different")},
    "nadia":   {"rey": (80, "loves him and has stopped believing him"),
                "marisol": (65, "the only one in that house who says things straight"),
                "junie": (40, "the only adult who tells her the truth"),
                "priya": (50, "the one betting on her, which is its own weight")},
    "booker":  {"kohl": (30, "an appreciating asset"),
                "wes": (20, "loyal, cheap, and replaceable in that order"),
                "cass": (-10, "new money asking old questions")},
    "junie":   {"simone": (75, "owes her everything and says so constantly"),
                "gus": (55, "gave her the job when nobody else would"),
                "malik": (15, "serves him coffee and worries about the hours he keeps")},
    "cass":    {"ivy": (-20, "she is the one who will notice first")},

    "adaeze":  {"dez": (75, "her son, and she has stopped asking what he does"),
                "chidi": (85, "the one there is still time for"),
                "boateng": (45, "the only person she tells the truth to")},
    "chidi":   {"dez": (85, "his brother, who is somebody"),
                "adaeze": (60, "his mother, who worries too loudly"),
                "tiny": (30, "the little one who follows him around")},
    "rosa":    {"malik": (70, "her son, and she is frightened of the answer"),
                "tiny": (90, "the one still small enough to protect"),
                "hector": (-25, "signs for things she is not supposed to see")},
    "tiny":    {"malik": (95, "her big brother, who is the best person alive"),
                "rosa": (80, "mum, who is tired")},
    "marisol": {"rey": (75, "her son, who thinks she does not notice"),
                "nadia": (80, "the sharp one; the one who will leave")},
    "marcus":  {"ivy": (45, "his aunt, and the reason he cannot quit")},
    "amara":   {"tee": (70, "her brother, too careful by half")},
    "gus":     {"junie": (60, "took a chance on her and would again"),
                "nadia": (40, "works hard, and is going somewhere")},
    "dot":     {"booker": (-30, "drinks in her bar and counts the room"),
                "hector": (25, "pays his tab, which is more than most")},
    "wes":     {"booker": (-35, "afraid of him in a way he calls loyalty")},
    "okafor":  {"ivy": (-20, "forty years and she has never once come in")},
    "brennan": {"ruiz": (-10, "a good detective and an expensive problem")},
    "yusuf":   {"simone": (20, "the best nurse he has and she lies on charts")},
    "priya":   {"nadia": (60, "the one who is actually going to make it"),
                "chidi": (25, "bright, and drifting")},
    "boateng": {"adaeze": (40, "carries something she will not put down")},
    "femi":    {"simone": (90, "his wife, working herself into the ground")},
    "hector":  {"rosa": (10, "sharp, and watches the loading bay too closely")},
    "sticks":  {"ivy": (35, "gives him coffee and never makes him ask"),
                "boateng": (30, "lets him sit at the back")},
}

# Who owes whom, what, and by when (in city-days from bootstrap).
SEED_DEBTS = [
    {"from": "kohl",  "to": "booker", "kind": "money",   "amount": 4200, "due_day": 3,
     "note": "gambling markers Booker bought up quietly"},
    {"from": "rey",   "to": "dez",    "kind": "money",   "amount": 9000, "due_day": 5,
     "note": "fronted him the shop's back rent last winter"},
    {"from": "malik", "to": "dez",    "kind": "product", "amount": 1,    "due_day": 2,
     "note": "a package that came back light and has never been explained"},
    {"from": "junie", "to": "simone", "kind": "favour",  "amount": 1,    "due_day": 9,
     "note": "an unpayable one, which is the kind that lasts"},
    {"from": "gus",   "to": "okafor", "kind": "money",   "amount": 800,  "due_day": 6,
     "note": "six months of deliveries taken on trust"},
    {"from": "wes",   "to": "booker", "kind": "favour",  "amount": 1,    "due_day": 4,
     "note": "something Wes did once that Booker has never had to mention again"},
]
