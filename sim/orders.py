"""
The Cut — the things a leader can actually do.

The player is not a character and does not get a sprite. They run the place: they set the
tax rate, they commission buildings, they fund services, they can put money into somebody's
hands. Everything else — who takes the jobs, who falls out with whom, who is born, what the
block decides to make illegal — stays outside their control, because a city where the
player decides everything is a spreadsheet and a city where they decide nothing is a
screensaver.

**Orders are advisory to the world, not commands to people.** You can build a clinic. You
cannot make anybody go to it, like it, or stop feuding with the person who runs it. What you
get is a changed set of conditions, and the simulation does what it does with them.

Orders arrive the same way conversation does: posted to the Worker, parked in KV, drained at
the start of a tick — and carried out immediately, before the tick pays out any beats. They
were once held back to a day-end boundary so that cost, effect and score moved together; but
the cost is already atomic with the effect (`_build` spends as it builds), and the delay only
meant a player could click Build and see nothing for an hour or more.
"""

from . import city, construction, economy, scores

# What a leader can commission, what it costs, and how big it is. Costs are set against a
# treasury that nets a couple of hundred a day, so a civic building is a real decision.
BUILDABLE = {
    "housing":    {"cost": 2600, "kind": "home",       "style": "brownstone",
                   "w": 8, "h": 6, "floors": 3, "name": "{street} Housing"},
    "shop":       {"cost": 2100, "kind": "business",   "style": "shopfront",
                   "w": 9, "h": 5, "floors": 1, "name": "{street} Market"},
    "workshop":   {"cost": 3400, "kind": "industrial", "style": "metal",
                   "w": 10, "h": 6, "floors": 2, "name": "{street} Works"},
    "bar":        {"cost": 2300, "kind": "social",     "style": "brick",
                   "w": 8, "h": 5, "floors": 2, "name": "The {street} Rooms"},
    "clinic":     {"cost": 4200, "kind": "civic",      "style": "concrete",
                   "w": 9, "h": 6, "floors": 2, "name": "{street} Clinic"},
    "school":     {"cost": 4600, "kind": "civic",      "style": "brick",
                   "w": 11, "h": 6, "floors": 2, "name": "{street} School"},
    "park":       {"cost": 1200, "kind": "outdoor",    "style": "none",
                   "w": 10, "h": 7, "floors": 1, "name": "{street} Green", "open": True},
}

# Money spent on people rather than bricks. One city-day of effect, so it is a lever you
# pull repeatedly rather than a switch you flip once.
PROGRAMMES = {
    "policing":  {"cost": 900,  "heat": -14,
                  "text": "The city puts more officers on the street."},
    "outreach":  {"cost": 800,  "mood": {"stress": -8, "fear": -6},
                  "text": "Outreach workers are on the block all day."},
    "amnesty":   {"cost": 1500, "debts": True,
                  "text": "The city clears what people owe each other."},
    "festival":  {"cost": 1100, "mood": {"happiness": 14, "social_need": -18},
                  "text": "The city throws a street party and pays for it."},
}

MAX_PENDING = 12


def ensure(world):
    world.setdefault("orders", [])
    world.setdefault("order_log", [])


def queue(world, order):
    """Park an order for the next city-day. Called when the tick drains the Worker."""
    ensure(world)
    world["orders"] = (world["orders"] + [order])[-MAX_PENDING:]
    return order


def apply_all(world, agents, day, beat):
    """Carry out everything the leader asked for. Returns records."""
    ensure(world)
    pending, world["orders"] = world.get("orders", []), []
    out = []
    for o in pending:
        try:
            rec = _apply(world, agents, o, day, beat)
        except Exception as e:
            rec = {"kind": "order", "ok": False, "day": day,
                   "text": f'That order could not be carried out ({type(e).__name__}).'}
        if rec:
            out.append(rec)
            world["order_log"] = ([rec] + world.get("order_log", []))[:40]
    return out


def _apply(world, agents, o, day, beat):
    kind = (o or {}).get("kind")

    if kind == "build":
        return _build(world, agents, o, day, beat)

    if kind == "tax":
        try:
            rate = max(0.0, min(economy.MAX_TAX, float(o.get("rate", 0.18))))
        except (TypeError, ValueError):
            return None
        before = world.get("tax_rate", economy.DEFAULT_TAX)
        world["tax_rate"] = rate
        # Nobody enjoys a tax rise, and the block notices immediately.
        shift = rate - before
        for a in agents.values():
            if a.get("alive", True) and economy.working_age(a):
                a["mood"]["happiness"] = max(0, min(100, a["mood"].get("happiness", 50)
                                                    - int(shift * 90)))
        return {"kind": "order", "order": "tax", "ok": True, "day": day,
                "text": f'Tax set to {rate * 100:.0f}% (was {before * 100:.0f}%).'}

    if kind == "assign":
        # Directing somebody into a public role is an instruction, not a posting — it goes
        # through the same refusal that everything else the mayor says does.
        from . import directives
        aid, role = o.get("who"), o.get("role")
        a = agents.get(aid)
        if not a or role not in economy.ROLES:
            return {"kind": "order", "ok": False, "day": day,
                    "text": "Nobody by that name, or no such job."}
        told = directives.give(world, agents, aid,
                               f"I need you to take work as a {role}.", day, beat)
        if told and not told.get("ok"):
            return {"kind": "order", "ok": False, "day": day, "order": "assign",
                    "text": told["text"]}
        return dict(economy.assign_role(world, agents, aid, role, day) or
                    {"kind": "order", "ok": False, "day": day,
                     "text": "That did not work."}, order="assign")

    if kind == "direct":
        # The Sims-shaped part of this: pick somebody, tell them to do a thing. It goes
        # through exactly the same refusal roll as anything else said to them, because a
        # city where forty people always do as they are told is an org chart, not a place —
        # and being told no by somebody you are trying to govern is most of the game.
        from . import directives
        aid = o.get("who")
        line = str(o.get("line") or "").strip()[:140]
        a = agents.get(aid)
        if not a or not a.get("alive", True):
            return {"kind": "order", "ok": False, "day": day, "order": "direct",
                    "text": "There is nobody by that name to tell."}
        told = directives.give(world, agents, aid, line, day, beat)
        if not told:
            return {"kind": "order", "ok": False, "day": day, "order": "direct",
                    "text": f'{a["name"]} did not take that as an instruction.'}
        return {"kind": "order", "order": "direct", "ok": bool(told.get("ok")),
                "day": day, "beat": beat, "who": aid, "name": a["name"],
                "text": told["text"]}

    if kind == "programme":
        return _programme(world, agents, o, day, beat)

    return None


def _build(world, agents, o, day, beat):
    spec = BUILDABLE.get(o.get("what"))
    if not spec:
        return {"kind": "order", "ok": False, "day": day,
                "text": f'Nobody knows how to build a {o.get("what")!r}.'}
    if not economy.can_afford(world, spec["cost"]):
        return {"kind": "order", "ok": False, "day": day, "order": "build",
                "text": f'Not enough in the treasury for a {o["what"]} '
                        f'(${spec["cost"]:,} needed, ${world.get("treasury", 0):,} held).'}

    import random
    rng = random.Random(f'order:{day}:{o.get("what")}')

    # A spot the mayor picked on the map, if they picked one. Checked here rather than
    # trusted: the page is public, and "build me a clinic on top of the church" should be
    # refused with a reason rather than quietly relocated somewhere else.
    plot, land = None, 0
    if o.get("x") is not None and o.get("y") is not None:
        try:
            px, py = int(o["x"]), int(o["y"])
        except (TypeError, ValueError):
            px = py = None
        if px is not None:
            if not city.can_reach(px, py, spec["w"], spec["h"]):
                return {"kind": "order", "ok": False, "day": day, "order": "build",
                        "text": 'That is beyond anywhere this city could ever reach.'}
            # Ground outside the current limits is bought, not assumed. Pointing past the
            # edge is how the city expands — but the bill arrives with the building, so
            # sprawl competes with everything else the treasury is for.
            land = city.expansion_cost(px, py, spec["w"], spec["h"])
            if not economy.can_afford(world, spec["cost"] + land):
                return {"kind": "order", "ok": False, "day": day, "order": "build",
                        "text": f'Not enough for that: ${spec["cost"]:,} to build and '
                                f'${land:,} to bring the ground inside the city '
                                f'(${world.get("treasury", 0):,} held).'}
            snap = city.dims_snapshot() if land else None
            if land:
                city.ensure_covers(world, world["buildings"], px, py,
                                   spec["w"], spec["h"])
            if construction.plot_free(world["buildings"], px, py, spec["w"], spec["h"]):
                plot = (px, py, city.district_at(py))
            else:
                # Hand the surveyed ground back. Growing the map is how we find out whether
                # the plot is clear, so a refusal has to undo it or a refused build quietly
                # becomes free expansion.
                if snap:
                    city.dims_restore(snap, world, world["buildings"])
                return {"kind": "order", "ok": False, "day": day, "order": "build",
                        "text": f'A {o["what"]} will not fit there — something is in the '
                                f'way, or it is on a road.'}

    if plot is None:
        plot = construction.find_plot(world["buildings"], spec["w"], spec["h"], rng)
    if not plot:
        # A mayor who has paid for a building should not be told there is no room while
        # there is still map to survey.
        if city.grow_if_needed(world, world["buildings"]):
            plot = construction.find_plot(world["buildings"], spec["w"], spec["h"], rng)
    if not plot:
        return {"kind": "order", "ok": False, "day": day, "order": "build",
                "text": 'There is nowhere left to put it.'}

    x, y, district = plot
    economy.spend(world, spec["cost"] + land, f'built a {o["what"]}', day)
    name = spec["name"].format(street=rng.choice(construction.STREET_NAMES))
    bid = f'civic_{o["what"]}_{day}'
    if any(b["id"] == bid for b in world["buildings"]):
        bid += "b"
    world["buildings"].append(city._b(
        bid, name, district, x, y, spec["w"], spec["h"],
        "N" if district == "civic" else "S", spec["kind"], spec["style"],
        is_open=spec.get("open", False), floors=spec.get("floors", 1)))
    world["buildings"][-1]["since_day"] = day
    world["buildings"][-1]["built_by"] = "the city"

    city.rebuild(world["buildings"])
    where = f'in {city.DISTRICTS[district]["name"]}'
    bill = (f'${spec["cost"]:,} to build, ${land:,} for the ground' if land
            else f'${spec["cost"]:,}')
    if land:
        where = f'on new ground {where}'
    return {"kind": "order", "ok": True, "day": day, "beat": beat, "order": "build",
            "building": bid, "what": o["what"], "cost": spec["cost"] + land,
            "land": land,
            "text": f'{name} is commissioned {where} ({bill}).'}


def _programme(world, agents, o, day, beat):
    spec = PROGRAMMES.get(o.get("what"))
    if not spec:
        return None
    if not economy.can_afford(world, spec["cost"]):
        return {"kind": "order", "ok": False, "day": day, "order": "programme",
                "text": f'Not enough in the treasury for that (${spec["cost"]:,} needed).'}
    economy.spend(world, spec["cost"], o["what"], day)

    if "heat" in spec:
        for d in world.get("heat", {}):
            world["heat"][d] = max(0, min(100, world["heat"][d] + spec["heat"]))
    if "mood" in spec:
        for a in agents.values():
            if a.get("alive", True):
                for k, v in spec["mood"].items():
                    a["mood"][k] = max(0, min(100, a["mood"].get(k, 50) + v))
    if spec.get("debts"):
        cleared = 0
        for d in world.get("debts", []):
            if not d.get("settled") and d.get("to") != "the block":
                d["settled"] = True
                cleared += 1
        return {"kind": "order", "ok": True, "day": day, "order": "programme",
                "text": f'{spec["text"]} {cleared} debts written off.'}

    return {"kind": "order", "ok": True, "day": day, "order": "programme",
            "what": o["what"], "text": spec["text"]}


def status(world, agents, day):
    """Everything the browser needs to draw the leader's dashboard."""
    ensure(world)
    snap = world.get("scores") or scores.snapshot(world, agents, day)
    return {
        "treasury": int(world.get("treasury", 0)),
        "tax_rate": world.get("tax_rate", economy.DEFAULT_TAX),
        "scores": snap,
        "grade": scores.grade(snap.get("overall", 0)),
        "buildable": {k: v["cost"] for k, v in BUILDABLE.items()},
        "programmes": {k: v["cost"] for k, v in PROGRAMMES.items()},
        "pending": len(world.get("orders", [])),
        "recent": world.get("order_log", [])[:6],
    }
