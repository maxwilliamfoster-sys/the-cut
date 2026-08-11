"""
The Cut — the twelve.

Personality is stored as prose, not numbers, because the model reasons far better over
"owes everybody and hates being reminded" than over {agreeableness: 0.3}. The numeric
fields exist only where something mechanical depends on them: mood drives routine
deviation, affinity drives who talks to whom, debt drives deadlines.

Seeded relationships are deliberately sparse. Only the load-bearing ones are authored —
everything else starts near zero and has to be earned, which is what makes an opinion
formed in week two feel like it belongs to the character rather than to me.

A beat is six city-hours, so routines are keyed by time block, not by clock hour.
"""

BLOCKS = ["morning", "afternoon", "evening", "night"]

FACTIONS = {
    "crew":     {"name": "The Laundromat Crew", "members": ["dez", "malik"],            "turf": ["riverside"]},
    "police":   {"name": "9th Precinct",        "members": ["ruiz", "kohl"],            "turf": ["civic"]},
    "block":    {"name": "The Block",           "members": ["ivy", "tee", "simone", "junie", "nadia"], "turf": ["delmar"]},
    "grey":     {"name": "The Grey Economy",    "members": ["rey", "booker"],           "turf": ["terraces"]},
    "outside":  {"name": "Outside Interest",    "members": ["cass"],                    "turf": []},
}

ROSTER = [
    {
        "id": "dez", "name": "Dez Okonkwo", "age": 34, "role": "runs the corner crew out of the laundromat",
        "faction": "crew", "home": "terrace_a", "work": "laundromat",
        "traits": ["calculating", "proud", "exhausted in a way he hides", "loyal past the point of sense"],
        "ambition": "get the money clean and out before he turns forty",
        "fear": "that he has already become his father",
        "voice": "quiet, economical, never repeats himself",
        "routine": {"morning": "laundromat", "afternoon": "laundromat", "evening": "harborbar", "night": "terrace_a"},
    },
    {
        "id": "malik", "name": "Malik Reyes", "age": 19, "role": "runs packages for Dez",
        "faction": "crew", "home": "terrace_b", "work": "laundromat",
        "traits": ["eager", "reckless", "desperate to be taken seriously", "generous with money he does not have"],
        "ambition": "his own corner, his own name",
        "fear": "that everyone still sees a kid",
        "voice": "fast, slangy, talks over people when nervous",
        "routine": {"morning": "terrace_b", "afternoon": "lot", "evening": "laundromat", "night": "lot"},
    },
    {
        "id": "ruiz", "name": "Det. Yolanda Ruiz", "age": 41, "role": "narcotics detective, 9th Precinct",
        "faction": "police", "home": "terrace_a", "work": "precinct",
        "traits": ["stubborn", "underfunded", "reads people fast", "cannot let a thread go"],
        "ambition": "one clean case that actually sticks",
        "fear": "that the job has made her into what she chases",
        "voice": "flat, patient, asks the same question three different ways",
        "routine": {"morning": "precinct", "afternoon": "diner", "evening": "precinct", "night": "terrace_a"},
    },
    {
        "id": "kohl", "name": "Ofc. Brady Kohl", "age": 28, "role": "patrol officer taking envelopes",
        "faction": "police", "home": "terrace_b", "work": "precinct",
        "traits": ["anxious", "in far over his head", "decent underneath it", "lies badly"],
        "ambition": "clear his debt and never take another envelope",
        "fear": "Ruiz working out what he is",
        "voice": "over-explains, laughs at the wrong moments",
        "routine": {"morning": "precinct", "afternoon": "cornerstore", "evening": "pawnshop", "night": "terrace_b"},
    },
    {
        "id": "ivy", "name": "Ms. Ivy Calloway", "age": 67, "role": "owns the corner store, has for forty years",
        "faction": "block", "home": "cornerstore", "work": "cornerstore",
        "traits": ["sees everything", "says a tenth of it", "unsentimental", "fiercely territorial about the block"],
        "ambition": "keep this block from burning down a second time",
        "fear": "outliving every person she has ever known here",
        "voice": "short sentences, devastating asides",
        "routine": {"morning": "cornerstore", "afternoon": "cornerstore", "evening": "cornerstore", "night": "cornerstore"},
    },
    {
        "id": "tee", "name": "Tariq 'Tee' Bello", "age": 23, "role": "barber; his shop is neutral ground",
        "faction": "block", "home": "terrace_b", "work": "barbershop",
        "traits": ["warm", "everybody's confidant", "allergic to conflict", "knows more than is safe"],
        "ambition": "a second chair and someone to fill it",
        "fear": "the day he is forced to pick a side",
        "voice": "easy, jokes to defuse, changes subject when it gets close",
        "routine": {"morning": "barbershop", "afternoon": "barbershop", "evening": "diner", "night": "terrace_b"},
    },
    {
        "id": "simone", "name": "Simone Adeyemi", "age": 31, "role": "nurse at the clinic, patches people quietly",
        "faction": "block", "home": "terrace_a", "work": "clinic",
        "traits": ["competent", "tired", "keeps other people's secrets badly but keeps them", "moral in a way that costs her"],
        "ambition": "to stop writing things on charts that are not true",
        "fear": "losing her licence and with it the only useful thing she does",
        "voice": "clipped when working, gentle when not",
        "routine": {"morning": "clinic", "afternoon": "clinic", "evening": "terrace_a", "night": "terrace_a"},
    },
    {
        "id": "rey", "name": "Rey Vasquez", "age": 45, "role": "runs the auto body shop, chops cars on the side",
        "faction": "grey", "home": "vasquez", "work": "autoshop",
        "traits": ["steady", "practical", "rationalises everything", "would burn the city down for his daughter"],
        "ambition": "retire clean and sell the shop to somebody decent",
        "fear": "Nadia finding out exactly what pays her tuition",
        "voice": "slow, fond, deflects with work talk",
        "routine": {"morning": "autoshop", "afternoon": "autoshop", "evening": "vasquez", "night": "vasquez"},
    },
    {
        "id": "nadia", "name": "Nadia Vasquez", "age": 17, "role": "straight-A student, sees more than she admits",
        "faction": "block", "home": "vasquez", "work": "diner",
        "traits": ["watchful", "sharp-tongued", "protective of her father", "already half gone"],
        "ambition": "a scholarship and a city that is not this one",
        "fear": "that leaving makes her exactly like her mother",
        "voice": "dry, precise, cuts adults off mid-excuse",
        "routine": {"morning": "vasquez", "afternoon": "diner", "evening": "diner", "night": "vasquez"},
    },
    {
        "id": "booker", "name": "Booker Lyle", "age": 52, "role": "pawn shop owner; washes money and knows everyone's price",
        "faction": "grey", "home": "pawnshop", "work": "pawnshop",
        "traits": ["genial", "utterly transactional", "collects leverage the way others collect stamps", "never raises his voice"],
        "ambition": "to be the one person nobody can afford to cut out",
        "fear": "becoming irrelevant before he becomes rich",
        "voice": "friendly, over-familiar, every sentence is a small test",
        "routine": {"morning": "pawnshop", "afternoon": "pawnshop", "evening": "harborbar", "night": "pawnshop"},
    },
    {
        "id": "junie", "name": "Junie Marsh", "age": 26, "role": "waitress at the Blue Spoon, eleven months clean",
        "faction": "block", "home": "terrace_a", "work": "diner",
        "traits": ["funny", "raw", "hears everything from behind the counter", "counts days out loud"],
        "ambition": "one full year, and then to stop counting",
        "fear": "the day she stops wanting it",
        "voice": "loud, self-deprecating, goes quiet at the wrong moment",
        "routine": {"morning": "diner", "afternoon": "diner", "evening": "terrace_a", "night": "terrace_a"},
    },
    {
        "id": "cass", "name": "Cass Deveaux", "age": 38, "role": "buying property on Delmar for someone nobody has met",
        "faction": "outside", "home": "harborbar", "work": "lot",
        "traits": ["polished", "patient", "answers questions with questions", "never seems to be in a hurry"],
        "ambition": "[hidden — the model may invent and must stay consistent]",
        "fear": "[hidden — the model may invent and must stay consistent]",
        "voice": "warm, corporate, unnervingly specific about details nobody mentioned",
        "routine": {"morning": "lot", "afternoon": "cornerstore", "evening": "harborbar", "night": "harborbar"},
    },
]

# Only load-bearing relationships are authored. affinity: -100..100.
SEED_RELATIONSHIPS = {
    "dez":    {"malik": (45, "reminds him of himself at nineteen, which is the problem"),
               "ruiz":  (-40, "she is patient, and patient is worse than aggressive"),
               "booker": (10, "useful, and useful is not the same as safe"),
               "ivy":   (30, "she knew his mother; that still means something")},
    "malik":  {"dez":   (70, "the only person whose opinion he actually wants"),
               "nadia": (25, "went to school with her and cannot talk to her any more"),
               "kohl":  (-15, "a cop who takes money is still a cop")},
    "ruiz":   {"dez":   (-35, "smart, disciplined, and therefore worth the years"),
               "kohl":  (20, "something is wrong with him and she has not named it yet"),
               "ivy":   (15, "the only person on Delmar who does not lie to her, exactly")},
    "kohl":   {"booker": (-50, "owns him, and is pleasant about it"),
               "ruiz":  (-25, "terrified of her in a way he calls respect")},
    "ivy":    {"nadia": (55, "the one who gets out, if anybody does"),
               "cass":  (-30, "asks about property values like he already owns them")},
    "tee":    {"dez":   (20, "tips well, never talks business in the chair"),
               "malik": (35, "worries about him, will not say so")},
    "simone": {"junie": (60, "drove her to the first meeting and never mentions it"),
               "rey":   (-20, "knows exactly which injuries came from that shop")},
    "rey":    {"nadia": (95, "the entire point of everything"),
               "dez":   (-30, "owes him, and hates the arithmetic of it"),
               "booker": (5, "fences through him and pretends that is different")},
    "nadia":  {"rey":   (80, "loves him and has stopped believing him"),
               "junie": (40, "the only adult who tells her the truth")},
    "booker": {"kohl":  (30, "an appreciating asset"),
               "cass":  (-10, "new money asking old questions")},
    "junie":  {"simone": (75, "owes her everything and says so constantly"),
               "malik":  (15, "serves him coffee and worries about the hours he keeps")},
    "cass":   {"ivy":   (-20, "she is the one who will notice first")},
}

# who owes whom, what, and by when (in city-days from bootstrap)
SEED_DEBTS = [
    {"from": "kohl",  "to": "booker", "kind": "money",  "amount": 4200, "due_day": 3,
     "note": "gambling markers Booker bought up quietly"},
    {"from": "rey",   "to": "dez",    "kind": "money",  "amount": 9000, "due_day": 5,
     "note": "fronted him the shop's back rent last winter"},
    {"from": "malik", "to": "dez",    "kind": "product","amount": 1,    "due_day": 2,
     "note": "a package that came back light and has never been explained"},
    {"from": "junie", "to": "simone", "kind": "favour", "amount": 1,    "due_day": 9,
     "note": "an unpayable one, which is the kind that lasts"},
]
