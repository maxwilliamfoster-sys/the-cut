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

async function rateLimited(env, ip) {
  const key = `rl:${ip}`;
  const now = Math.floor(Date.now() / 1000);
  const raw = await env.CUT_KV.get(key, "json");
  if (raw && now - raw.start < RATE_WINDOW) {
    if (raw.n >= RATE_LIMIT) return true;
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

function personaPrompt(a, world) {
  const block = ["morning", "afternoon", "evening", "night"][world.beat % 4];
  const mems = (a.memories || []).slice(-4).map(m => `d${m.day}: ${m.what}`).join(" | ") || "nothing much";
  const rels = Object.entries(a.relationships || {})
    .sort((x, y) => Math.abs(y[1].affinity) - Math.abs(x[1].affinity)).slice(0, 3)
    .map(([, v]) => v.opinion).join("; ");

  return `You are ${a.name}, ${a.age}. ${a.role}.
You are: ${(a.traits || []).join("; ")}.
You want: ${a.ambition}. You dread: ${a.private_fear}.
You speak like this: ${a.voice}.
Right now it is day ${Math.floor(world.beat / 4)}, ${block}, weather ${world.weather}.
You are ${a.action || "here"}. Privately you are thinking: ${a.thought || "not much"}.
You remember: ${mems}
Your read on people: ${rels}

A stranger has just spoken to you in the street. Reply IN CHARACTER, as ${a.name}, in ONE
or TWO short sentences. You do not know this person. Be guarded, or funny, or dismissive,
or curious - whatever this particular person would actually be. Do not narrate, do not use
asterisks, do not explain yourself. Just the words you say out loud.

Never describe how anything illegal is actually done. No sexual content. No slurs.`;
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

  const res = await fetch(GROQ, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GROQ_API_KEY}`,
      "Content-Type": "application/json",
      "User-Agent": "the-cut-talk/1.0",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 300,
      temperature: 0.95,
      reasoning_format: "hidden",
      reasoning_effort: "low",
      messages: [
        { role: "system", content: personaPrompt(a, world) },
        { role: "user", content: line },
      ],
    }),
  });

  if (!res.ok) return json({ error: `brain unavailable (${res.status})` }, 502);
  const d = await res.json();
  let reply = (d.choices?.[0]?.message?.content || "").trim()
    .replace(/^["']|["']$/g, "").replace(/\*/g, "").slice(0, 300);

  if (!reply) return json({ error: "they said nothing" }, 502);
  if (GUARD.test(reply)) reply = "They look at you for a second and change the subject.";

  // Queued under a unique key rather than appended to one blob — two people talking at
  // once would otherwise read-modify-write over each other and silently lose a line.
  await env.CUT_KV.put(
    `q:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
    JSON.stringify({ agent: body.agent, line, reply, at: new Date().toISOString() }),
    { expirationTtl: 60 * 60 * 24 * 7 },
  );

  return json({ reply });
}

async function drain(req, env) {
  if (req.headers.get("X-Drain-Key") !== env.DRAIN_KEY)
    return json({ error: "nope" }, 401);

  const list = await env.CUT_KV.list({ prefix: "q:" });
  const out = [];
  for (const k of list.keys) {
    const v = await env.CUT_KV.get(k.name, "json");
    if (v) out.push(v);
    await env.CUT_KV.delete(k.name);
  }
  out.sort((a, b) => (a.at < b.at ? -1 : 1));
  return json({ exchanges: out });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = req.headers.get("Origin") || "";
    if (req.method === "OPTIONS") return cors(new Response(null, { status: 204 }), origin);
    if (url.pathname === "/talk" && req.method === "POST")
      return cors(await talk(req, env), origin);
    if (url.pathname === "/drain") return drain(req, env);   // server-to-server, no CORS
    return cors(json({ ok: "the cut — dialogue proxy" }), origin);
  },
};
