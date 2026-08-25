/**
 * THE CUT — dialogue proxy.
 *
 * The browser cannot hold the Groq key (the page is public) and cannot write to the repo,
 * so it cannot make anyone remember anything. This Worker is the only thing that can do
 * both: it talks to Groq with a key the client never sees, and it parks the exchange in KV
 * for the next cron beat to fold into that character's memory.
 *
 * The persona is fetched from the published state server-side and never taken from the
 * request body. If the client supplied it, anyone could POST an arbitrary "character" and
 * have this endpoint say whatever they wanted in the city's voice — and it would then be
 * written into the city's memory as fact.
 *
 * Endpoints
 *   POST /talk    { agent, line }   header X-Player-Key   -> { reply }
 *   GET  /drain                     header X-Drain-Key    -> [ exchanges ], and clears them
 */

const PAGES = "https://maxwilliamfoster-sys.github.io/the-cut";
const GROQ = "https://api.groq.com/openai/v1/chat/completions";
// Groq retired llama-3.1-8b-instant in Aug 2026 (404). gpt-oss is a reasoning model:
// reasoning_format "hidden" keeps the trace out of the reply, and "low" effort keeps it
// from eating max_tokens — without both, a short reply budget is spent thinking and the
// character answers with nothing but a 502 "they said nothing".
const MODEL = "openai/gpt-oss-20b";

const RATE_LIMIT = 40;          // talk requests
const RATE_WINDOW = 3600;       // per hour, per IP
const MAX_LINE = 180;

// The site key travels in a public page, so it is a speed bump, not a lock. These are the
// controls that actually bound the damage: browsers refuse a cross-origin fetch that is not
// allowed here, and the per-IP limit caps what any single caller can spend of the token
// budget even if they skip the browser entirely.
const ALLOWED_ORIGINS = [
  "https://maxwilliamfoster-sys.github.io",
  "http://localhost:8777",
];

// Same register and the same hard line as the simulation's own prompt: this output is
// written into the city's memory and shown on a public page.
const GUARD =
  /\b(?:how to (?:make|cook|synthesi[sz]e|manufacture|build)|recipe for|ingredients?:|step\s*\d\s*[:.]|pseudoephedrine|anhydrous ammonia|red phosphorus|methylamine|firing pin|drill out the|suppressor|track\s*2|cvv|bin list|skimmer)\b/i;

function cors(res, origin) {
  const h = new Headers(res.headers);
  h.set("Access-Control-Allow-Origin",
        ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0]);
  h.set("Vary", "Origin");
  h.set("Access-Control-Allow-Headers", "Content-Type, X-Player-Key");
  h.set("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  return new Response(res.body, { status: res.status, headers: h });
}

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });

async function rateLimited(env, ip, bucket = "rl", limit = RATE_LIMIT) {
  const key = `${bucket}:${ip}`;
  const now = Math.floor(Date.now() / 1000);
  const raw = await env.CUT_KV.get(key, "json");
  if (raw && now - raw.start < RATE_WINDOW) {
    if (raw.n >= limit) return true;
    await env.CUT_KV.put(key, JSON.stringify({ start: raw.start, n: raw.n + 1 }),
                         { expirationTtl: RATE_WINDOW });
    return false;
  }
  await env.CUT_KV.put(key, JSON.stringify({ start: now, n: 1 }), { expirationTtl: RATE_WINDOW });
  return false;
}

// Beats are fifteen minutes apart, so refetching the whole city on every message is pure
// waste — and the extra pair of subrequests is what produced an intermittent Cloudflare
// 1042 during rapid-fire testing. A few seconds of staleness costs nothing here.
let cityCache = { at: 0, data: null };
const CITY_TTL_MS = 20_000;

async function getJSON(url, tries = 2) {
  for (let i = 0; i <= tries; i++) {
    try {
      const r = await fetch(url, { cf: { cacheTtl: 0 } });
      if (r.ok) return await r.json();
    } catch (_) { /* fall through to retry */ }
  }
  throw new Error(`could not load ${url}`);
}

async function loadCity() {
  if (cityCache.data && Date.now() - cityCache.at < CITY_TTL_MS) return cityCache.data;
  const bust = `?t=${Date.now()}`;
  const [agents, world] = await Promise.all([
    getJSON(`${PAGES}/state/agents.json${bust}`),
    getJSON(`${PAGES}/state/world.json${bust}`),
  ]);
  cityCache = { at: Date.now(), data: { agents, world } };
  return cityCache.data;
}

// Conversations are remembered for this long, so a back-and-forth actually holds together.
// Keyed by caller IP + character: the browser is never trusted to supply the history, for
// the same reason it is never trusted to supply the persona.
const HIST_TURNS = 8;
const HIST_TTL = 60 * 60 * 2;

function histKey(ip, agentId) { return `hist:${ip}:${agentId}`; }

async function loadHistory(env, ip, agentId) {
  const raw = await env.CUT_KV.get(histKey(ip, agentId), "json");
  return Array.isArray(raw) ? raw.slice(-HIST_TURNS) : [];
}

async function saveHistory(env, ip, agentId, newTurns, prior = []) {
  const turns = [...prior, ...newTurns].slice(-HIST_TURNS);
  await env.CUT_KV.put(histKey(ip, agentId), JSON.stringify(turns),
                       { expirationTtl: HIST_TTL });
}

// Everything this person is currently living through. The old prompt gave the model a name,
// some traits and four memories, which produced a character who sounded right but had no
// stake in anything. These are the same facts the simulation's own cognition prompt uses.
function situation(a, world, agents) {
  const bits = [];
  const nameOf = id => (agents[id] || {}).name || id;

  for (const d of (world.debts || [])) {
    if (d.settled) continue;
    const day = Math.floor(world.beat / 4);
    const over = day - d.due_day;
    if (over < 0) continue;
    const what = d.kind === "money" ? `$${d.amount}` : d.kind === "favour" ? "a favour" : "a package";
    if (d.to === a.id)
      bits.push(`${nameOf(d.from)} owes you ${what} and is ${over} days late` +
                (d.asked ? `; you have asked ${d.asked} times` : "") + ". You are sick of it.");
    if (d.from === a.id)
      bits.push(`You owe ${nameOf(d.to)} ${what} and you are ${over} days late. You are avoiding it.`);
  }

  for (const f of (world.feuds || [])) {
    if (f.a === a.id || f.b === a.id)
      bits.push(`You are feuding with ${nameOf(f.a === a.id ? f.b : f.a)} — ${f.cause}.`);
  }

  if (a.grief >= 40) bits.push("Somebody you were close to has died recently. You are not over it.");
  else if (a.grief >= 15) bits.push("There has been a death on the block and it is still sitting with you.");
  if (a.detained_until) bits.push(`You are being held at the 9th Precinct over ${a.charged_with || "a charge"}.`);

  const laws = (world.laws || []).filter(l => l.status === "enacted").slice(-3);
  if (laws.length)
    bits.push(`Rules this block passed recently: ${laws.map(l => l.title).join("; ")}.`);

  return bits.length ? bits.join("\n") : "Nothing much is hanging over you right now.";
}

function personaPrompt(a, world, agents) {
  const block = ["morning", "afternoon", "evening", "night"][world.beat % 4];
  const mems = (a.memories || []).slice(-5).map(m => `d${m.day}: ${m.what}`).join(" | ") || "nothing much";
  const rels = Object.entries(a.relationships || {})
    .sort((x, y) => Math.abs(y[1].affinity) - Math.abs(x[1].affinity)).slice(0, 4)
    .map(([id, v]) => `${(agents[id] || {}).name || id}: ${v.opinion}`).join("; ");

  const temper = a.volatility >= 75 ? "You do not let things go, and you start them."
               : a.volatility <= 25 ? "You calm rooms down rather than lighting them."
               : "";

  return `You are ${a.name}, ${a.age}. ${a.role}.
You are: ${(a.traits || []).join("; ")}. ${temper}
You want: ${a.ambition}. You dread: ${a.private_fear}.
You speak like this: ${a.voice}.
It is day ${Math.floor(world.beat / 4)}, ${block}, weather ${world.weather}.
You are ${a.action || "here"}. Privately: ${a.thought || "not much"}.
You remember: ${mems}
Your read on people: ${rels || "no strong views"}

WHAT IS ON YOUR PLATE
${situation(a, world, agents)}

A stranger is talking to you in the street. You do not know them and you have no reason to
trust them. Reply IN CHARACTER as ${a.name} — one or two short sentences, the words you say
out loud and nothing else. No narration, no asterisks, no explaining yourself. Be guarded,
funny, rude, evasive or curious, whatever THIS person would actually be.

Give them something to push against — a question back, a denial with an edge, a piece of
what you actually think, a demand. Never a bare "is that so" or "sounds like a lie" and
nothing else; that ends the conversation and wastes both your time. If you have spoken to
this stranger already, answer what they ACTUALLY just said and remember what was said
before — do not reintroduce yourself or start the conversation over.

Never describe how anything illegal is actually done. No sexual content. No slurs.

Reply with the spoken words ONLY — no JSON, no braces, no quotes around it, no label, no
narration. Just what ${a.name} says out loud.`;
}

async function talk(req, env) {
  if (req.headers.get("X-Player-Key") !== env.PLAYER_KEY)
    return json({ error: "bad player key" }, 401);

  const ip = req.headers.get("CF-Connecting-IP") || "anon";
  if (await rateLimited(env, ip)) return json({ error: "slow down" }, 429);

  let body;
  try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }

  const line = String(body.line || "").trim().slice(0, MAX_LINE);
  if (!line) return json({ error: "say something" }, 400);
  if (GUARD.test(line)) return json({ error: "not that" }, 400);

  const { agents, world } = await loadCity();
  const a = agents[body.agent];
  if (!a) return json({ error: "no such person" }, 404);

  const history = await loadHistory(env, ip, body.agent);
  const messages = [
    { role: "system", content: personaPrompt(a, world, agents) },
    ...history,
    { role: "user", content: line },
  ];

  const raw = await think(env, messages);
  if (!raw.ok) return json({ error: `brain unavailable (${raw.status})`, detail: raw.detail }, 502);
  return await finish(env, ip, body, a, agents, line, raw.text);
}

// Cloudflare's own inference FIRST, Groq second.
//
// Both used to share one Groq key with the simulation's cron, which burns the entire
// 8,000-token-per-minute ceiling every time it thinks. So a player got two or three replies
// and then "brain unavailable" as the city stole the budget mid-conversation. Workers AI is
// a separate allowance that nothing else touches, it needs no key, and it runs on the
// machine this Worker is already on — which makes it the right primary for the one part of
// the system a human is sitting in front of. Groq stays as backup, and the city keeps its
// tokens for thinking.
//
// Model ids verified against developers.cloudflare.com — the first set here was guessed and
// two of the three did not exist, which is what produced "every brain is unavailable".
const CF_MODELS = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/meta/llama-3.1-8b-instruct-fast",
  "@cf/openai/gpt-oss-20b",
];

async function think(env, messages) {
  const tried = [];

  if (env.AI) {
    for (const m of CF_MODELS) {
      try {
        const out = await env.AI.run(m, { messages, max_tokens: 420, temperature: 0.95 });
        const text = (out?.response || out?.result?.response || "").trim();
        if (text) return { ok: true, text, via: m };
        tried.push(`${m}: empty`);
      } catch (e) {
        tried.push(`${m}: ${e}`);
      }
    }
  } else {
    tried.push("no AI binding");
  }

  if (env.GROQ_API_KEY) {
    try {
      const r = await groqCall(env, messages);
      if (r.ok) return r;
      tried.push(`groq: ${r.status} ${r.detail || ""}`);
    } catch (e) {
      tried.push(`groq threw: ${e}`);
    }
  } else {
    tried.push("no groq key");
  }

  // Say WHY, not just that. The first version returned a bare "every brain is unavailable",
  // which is exactly as useful as it sounds when the cause is a mistyped model id.
  return { ok: false, status: 502, detail: tried.join(" | ").slice(0, 400) };
}


async function groqCall(env, messages) {
  const res = await fetch(GROQ, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GROQ_API_KEY}`,
      "Content-Type": "application/json",
      "User-Agent": "the-cut-talk/1.0",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 420,
      temperature: 0.95,
      reasoning_format: "hidden",
      reasoning_effort: "low",
      response_format: { type: "json_object" },
      messages,
    }),
  });
  if (!res.ok) return { ok: false, status: res.status, detail: (await res.text()).slice(0, 200) };
  const d = await res.json();
  const text = (d.choices?.[0]?.message?.content || "").trim();
  if (!text) return { ok: false, status: 502, detail: "empty content" };
  return { ok: true, text, via: MODEL };
}

// Turn whatever the brain said into a reply plus, if there was one, a claim about somebody
// else. Groq is asked for JSON so the claim comes out of the SAME call that writes the
// reply — a second request per message would double what a conversation costs. Workers AI
// often answers in prose regardless, and that is fine: the reply still works, only the
// claim is lost.
// Deliberately dumb, and brain-independent: if the player named somebody else on the block,
// that is a claim about them. sim/player.py does the same scan server-side; this copy exists
// only so the reply can tell the player it landed.
const NOT_A_NAME = new Set(["det", "ofc", "sgt", "dr", "ms", "fr", "the", "and", "his", "her"]);

function claimFrom(line, agents, speakerId) {
  const low = ` ${line.toLowerCase()} `;
  let best = null;
  for (const id in agents) {
    const o = agents[id];
    if (id === speakerId || o.alive === false) continue;
    const parts = String(o.name).split(/\s+/).map(p => p.replace(/[.,']/g, "").toLowerCase());
    const names = [String(o.name).toLowerCase(),
                   ...parts.filter(p => p.length >= 3 && !NOT_A_NAME.has(p))];
    for (const n of names) {
      if (low.includes(` ${n} `) || low.includes(` ${n}'`) ||
          low.includes(` ${n}.`) || low.includes(` ${n},`)) {
        if (!best || n.length > best.len) best = { about: id, len: n.length };
      }
    }
  }
  return best ? { about: best.about, what: line.trim().slice(0, 120) } : null;
}


async function finish(env, ip, body, a, agents, line, raw) {
  let reply = raw;

  // The prompt no longer asks for JSON — Python extracts claims now — but an older cached
  // prompt or a helpful brain can still volunteer a schema. Anything that looks like one is
  // stripped rather than spoken: {"claim":null} came out of a character's mouth once, and
  // once is too often.
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && parsed.say) reply = String(parsed.say);
  } catch (_) { /* prose, which is what we now ask for */ }
  reply = reply
    .replace(/\{[^{}]*\}/g, " ")               // stray JSON objects
    .replace(/^\s*(claim|say|reply)\s*:\s*/i, "")  // stray labels
    .replace(/\s+/g, " ");

  // Who did the player name? The same plain scan sim/player.py does, so the browser can
  // honestly report that a rumour landed whichever brain answered.
  let claim = claimFrom(line, agents, body.agent);

  // Trim BEFORE stripping the wrapping quotes: collapsing whitespace first leaves a leading
  // space, and then ^["'] no longer matches, so every quoted reply kept its quotes.
  reply = reply.trim().replace(/^["']+|["']+$/g, "").replace(/\*/g, "").trim().slice(0, 300);
  if (!reply) return json({ error: "they said nothing" }, 502);
  if (GUARD.test(reply)) { reply = "They look at you for a second and change the subject."; claim = null; }
  if (claim && GUARD.test(claim.what)) claim = null;

  await saveHistory(env, ip, body.agent,
                    [{ role: "user", content: line }, { role: "assistant", content: reply }],
                    await loadHistory(env, ip, body.agent));

  // Queued under a unique key rather than appended to one blob — two people talking at
  // once would otherwise read-modify-write over each other and silently lose a line.
  await env.CUT_KV.put(
    `q:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
    JSON.stringify({ agent: body.agent, line, reply, claim, at: new Date().toISOString() }),
    { expirationTtl: 60 * 60 * 24 * 7 },
  );

  // Telling the player their rumour landed is the difference between talking at the city
  // and talking to it: they can watch the person walk off to go and check.
  return json({
    reply,
    asked_about: claim ? ((agents[claim.about] || {}).name || null) : null,
  });
}


// ── the leader's orders ─────────────────────────────────────────────────────
// The browser cannot write to the repo, so an order takes the same route a conversation
// does: posted here, parked in KV, drained by the next tick and carried out at the end of
// that city-day. That delay is a feature — you are a mayor, not a god, and the gap between
// signing something and seeing it is what a term of office feels like.
//
// Validation is deliberately paranoid: the page is public and the site key is a speed bump,
// not a lock. Anything not on these lists is refused here rather than trusted to the
// simulation, and a rate limit stops one caller filling the queue.
const BUILDABLE = ["housing", "shop", "workshop", "bar", "clinic", "school", "park"];
const PROGRAMMES = ["policing", "outreach", "amnesty", "festival"];
const ORDER_LIMIT = 20;        // per IP per hour — a leader does not sign 200 things an hour

async function order(req, env) {
  if (req.headers.get("X-Player-Key") !== env.PLAYER_KEY)
    return json({ error: "bad player key" }, 401);

  const ip = req.headers.get("CF-Connecting-IP") || "anon";
  if (await rateLimited(env, ip, "ol", ORDER_LIMIT)) return json({ error: "slow down" }, 429);

  let body;
  try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }

  const kind = String(body.kind || "");
  let out = null;

  if (kind === "build") {
    if (!BUILDABLE.includes(body.what)) return json({ error: "cannot build that" }, 400);
    out = { kind: "build", what: body.what };
  } else if (kind === "programme") {
    if (!PROGRAMMES.includes(body.what)) return json({ error: "no such programme" }, 400);
    out = { kind: "programme", what: body.what };
  } else if (kind === "tax") {
    const rate = Number(body.rate);
    if (!isFinite(rate) || rate < 0 || rate > 0.45) return json({ error: "rate out of range" }, 400);
    out = { kind: "tax", rate: Math.round(rate * 100) / 100 };
  } else {
    return json({ error: "unknown order" }, 400);
  }

  await env.CUT_KV.put(
    `o:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
    JSON.stringify({ ...out, at: new Date().toISOString() }),
    { expirationTtl: 60 * 60 * 24 * 7 },
  );
  return json({ ok: true, queued: out });
}

async function drain(req, env) {
  if (req.headers.get("X-Drain-Key") !== env.DRAIN_KEY)
    return json({ error: "nope" }, 401);

  // Both queues in one round trip. A second endpoint would mean a second subrequest on
  // every tick for something that is usually empty.
  const take = async (prefix) => {
    const list = await env.CUT_KV.list({ prefix });
    const out = [];
    for (const k of list.keys) {
      const v = await env.CUT_KV.get(k.name, "json");
      if (v) out.push(v);
      await env.CUT_KV.delete(k.name);
    }
    return out.sort((a, b) => (a.at < b.at ? -1 : 1));
  };
  return json({ exchanges: await take("q:"), orders: await take("o:") });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = req.headers.get("Origin") || "";
    if (req.method === "OPTIONS") return cors(new Response(null, { status: 204 }), origin);
    if (url.pathname === "/talk" && req.method === "POST")
      return cors(await talk(req, env), origin);
    if (url.pathname === "/order" && req.method === "POST")
      return cors(await order(req, env), origin);
    if (url.pathname === "/drain") return drain(req, env);   // server-to-server, no CORS
    // A real 404 for anything unrecognised. The catch-all used to answer every unknown
    // path with a cheerful 200, so a client posting to an endpoint that did not exist yet
    // was told everything was fine.
    if (url.pathname === "/" || url.pathname === "")
      return cors(json({ ok: "the cut — dialogue and orders" }), origin);
    return cors(json({ error: "no such endpoint" }, 404), origin);
  },
};
