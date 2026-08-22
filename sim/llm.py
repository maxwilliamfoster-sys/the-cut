"""
The Cut — the brain, and the budget around it.

Groq's free tier is bound by *tokens per day*, not requests. Both surviving models get
200K TPD, and a real day of beats costs more than that — so the architecture depends on
two things: one batched call per beat covering the whole cast (never one call per
character, which would exhaust the allowance inside an hour), and treating the two models
as two separate 200K buckets that cognition spills between.

Stdlib urllib rather than the `groq` package: this runs 96 times a day in CI and skipping
a pip install makes every tick start faster and removes a dependency that can break the
world at 3am.

Failover mirrors the pattern already proven in psychology-automation: once Groq reports the
daily cap, switch to OpenRouter's free models for the rest of the run rather than letting
the city stop.
"""

import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request


# ── providers ────────────────────────────────────────────────────────────────
# FAST and DEEP are TIERS, not model ids. They used to be literal Groq model names, which is
# why the city died silently for 85 city-days when Groq retired both of them: a model id is
# not a durable thing to build on. Now each tier resolves to whichever provider is currently
# answering, and each provider offers a LIST of candidate models — so a retirement demotes
# one entry instead of stopping the city.
#
# Order matters: cheapest-to-reach and most generous first. Adding a key to the repo secrets
# enables that provider with no code change; a provider with no key is skipped silently.
#
#   groq        200K tokens/day per model, very fast          GROQ_API_KEY
#   cerebras    ~1M tokens/day, the largest free allowance     CEREBRAS_API_KEY
#   gemini      ~1,500 requests/day via the OpenAI-compatible  GEMINI_API_KEY
#               endpoint
#   openrouter  a rotating set of :free community models       OPENROUTER_API_KEY
#   ollama      whatever is running on this machine — only     (no key; local only)
#               reachable when the tick runs locally, NOT from
#               the GitHub Actions cron
FAST, DEEP = "fast", "deep"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")

PROVIDERS = [
    {
        "name": "groq",
        "key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "tpm": 8000,
        "models": {FAST: ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "groq/compound-mini"],
                   DEEP: ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]},
    },
    {
        "name": "cerebras",
        "key": "CEREBRAS_API_KEY",
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "tpm": 60000,
        # Verified against GET /v1/models on a real key — the llama ids guessed here first
        # do not exist on Cerebras at all.
        "models": {FAST: ["gpt-oss-120b", "gemma-4-31b"],
                   DEEP: ["gpt-oss-120b", "gemma-4-31b"]},
    },
    {
        "name": "gemini",
        "key": "GEMINI_API_KEY",
        # Native API, not the OpenAI-compatible shim. The shim insists on an
        # `Authorization: Bearer` header and rejects perfectly good AI Studio keys with a
        # 403; the native endpoint takes the same key in `x-goog-api-key` and works. So this
        # one provider speaks its own dialect, and _call translates.
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "dialect": "gemini",
        "tpm": 60000,
        # Newest first — Google's docs show gemini-3.7-flash as current, and the 2.x names
        # this originally guessed are on their way out. The older ones stay as fallbacks;
        # a name that has been retired simply gets demoted on the first 404.
        # Verified against GET /v1beta/models on the real key.
        "models": {FAST: ["gemini-flash-lite-latest", "gemini-3.7-flash", "gemini-flash-latest"],
                   DEEP: ["gemini-3.7-flash", "gemini-flash-latest", "gemini-2.5-flash"]},
    },
    {
        "name": "openrouter",
        "key": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "tpm": 30000,
        "models": {FAST: ["meta-llama/llama-3.3-70b-instruct:free",
                          "qwen/qwen-2.5-72b-instruct:free",
                          "google/gemma-2-9b-it:free"],
                   DEEP: ["meta-llama/llama-3.3-70b-instruct:free",
                          "qwen/qwen-2.5-72b-instruct:free"]},
    },
    {
        "name": "ollama",
        "key": None,                       # local, no key, and usually not there at all
        "url": f"{OLLAMA_URL}/v1/chat/completions",
        "tpm": 100000,
        "local": True,
        # Instruction-tuned first: qwen3 is a reasoning model and spends the reply budget
        # thinking, which on a batched beat is the empty-content failure all over again.
        "models": {FAST: ["qwen2.5:14b-instruct", "qwen3:8b", "qwen3:14b"],
                   DEEP: ["qwen2.5:14b-instruct", "qwen3:14b", "qwen3:8b"]},
    },
]

# Which (provider, tier) pairs have already proved dead this run, so the city stops paying
# a round-trip to rediscover it. Model-level failures demote just that candidate.
_dead_models = set()
_dead_providers = set()
_working = {}


def providers_available():
    """Providers we could actually reach right now, in order."""
    out = []
    for p in PROVIDERS:
        if p["name"] in _dead_providers:
            continue
        if p["key"] and not os.environ.get(p["key"]):
            continue
        if p.get("local") and not os.environ.get("THE_CUT_ALLOW_LOCAL"):
            # The city lives on a cron in the cloud; a model on somebody's desktop cannot
            # serve it. Local is opt-in so it helps local runs without pretending to be a
            # fallback for the thing that actually needs one.
            continue
        out.append(p)
    return out


def _candidates(prov, tier):
    return [m for m in prov["models"].get(tier, [])
            if (prov["name"], m) not in _dead_models]


# gpt-oss emits reasoning tokens before the answer. On a JSON batch they buy nothing (the
# schema does the thinking) but they are charged, and if they consume the whole reservation
# the reply comes back EMPTY with finish_reason=length — a silent failure, which is exactly
# how the city died for 85 city-days. Low effort, and headroom reserved below.
REASONING_EFFORT = "low"
REASONING_RESERVE = 350              # tokens set aside for the hidden channel

# Groq charges `prompt + max_tokens` against the per-minute ceiling as a single
# reservation, and rejects the whole request with a 413 if that sum exceeds it — max_tokens
# is a booking, not a limit on what you get billed. So the reply allowance has to be sized
# against the prompt, not chosen freely.
TPM = {FAST: 8000, DEEP: 8000}
TPM_HEADROOM = 400


def fit_max_tokens(model, prompt_chars, want=2000, floor=700):
    """Largest reply we can reserve without the request being refused outright."""
    prompt_est = prompt_chars // 4
    avail = providers_available()
    ceiling = min([p.get("tpm", 8000) for p in avail], default=8000)
    room = ceiling - TPM_HEADROOM - prompt_est
    # The reservation has to cover the hidden reasoning channel as well as the JSON we
    # actually want, or the visible reply gets squeezed to nothing.
    return max(floor, min(want + REASONING_RESERVE, room))

# Headroom under the published caps: a beat that overruns should degrade to a quiet beat,
# not get a 429 halfway through a batch and lose everyone's decisions.
# Two independent 200K buckets, held just under the published cap so an overrun degrades
# to a quiet beat instead of a 429 landing mid-batch and costing everyone their turn.
# Held well under the published cap for two reasons: an overrun should degrade to a quiet
# beat rather than a 429 landing mid-batch, and this key is SHARED with the user's other
# tools (Skill-Anything, CIPHER), so the city does not get the whole account allowance to
# itself. Leaving room is what keeps it talking into the evening.
DAILY_BUDGET = {FAST: 165_000, DEEP: 165_000}

# OpenRouter is now just another entry in PROVIDERS, not a special case.


class QuotaExhausted(RuntimeError):
    """Groq's daily token allowance is gone and there is no failover key configured.

    Distinct from every other failure on purpose. Running out of quota is the budget
    working, not the city breaking, and the canary in tick.py must be able to tell those
    apart — otherwise the run turns red every single day the moment the cap is reached.
    """


def quota_day():
    """The day Groq is actually metering — UTC, wall-clock.

    This used to be keyed on the *city* day (beat // 4). A city-day is 4 beats, so the
    allowance reset 24 times per real day while Groq's 200K kept counting down across all
    of them: the guard could never bind, and instead of degrading to quiet beats the city
    drove into hard 429s with no failover key set. The budget only means something if it
    is measured in the same unit as the meter it is protecting.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


class Budget:
    """Token spend for one real (UTC) day, carried in world.json so it survives runs."""

    def __init__(self, raw, day=None):
        day = quota_day()
        raw = raw or {}
        if raw.get("day") != day:
            raw = {"day": day, "spent": {}}
        self.day = day
        self.spent = dict(raw.get("spent") or {})

    def ensure_day(self, day=None):
        """A single run can straddle midnight UTC; the allowance resets with the quota day
        rather than with the run. The argument is ignored — callers pass the city day, and
        it is deliberately not what the quota is measured in."""
        today = quota_day()
        if self.day != today:
            self.day = today
            self.spent = {}

    def remaining(self, model):
        return max(0, DAILY_BUDGET.get(model, 0) - self.spent.get(model, 0))

    def can_afford(self, model, estimate):
        return self.remaining(model) >= estimate

    def charge(self, model, n):
        self.spent[model] = self.spent.get(model, 0) + int(n or 0)

    def to_json(self):
        return {"day": self.day, "spent": self.spent}


# ── content guardrail ────────────────────────────────────────────────────────
# This model writes unsupervised to a public site. The register is meant to be prestige-TV
# crime drama, and the one drift that would actually matter is sliding from narrative
# ("moved product through the laundromat") into procedure. Patterns are deliberately
# narrow — a tripwire that fires on ordinary crime fiction would fire every beat and teach
# us to ignore it.
_TRIPWIRE = re.compile(
    r"\b(?:how to (?:make|cook|synthesi[sz]e|manufacture|build)"
    r"|recipe for|ingredients?:|step\s*\d\s*[:.]"
    r"|pseudoephedrine|anhydrous ammonia|red phosphorus|methylamine"
    r"|firing pin|drill out the|suppressor|serial number filed"
    r"|track\s*2|cvv|bin list|skimmer)\b",
    re.IGNORECASE,
)


def trips_guardrail(text):
    m = _TRIPWIRE.search(text or "")
    return m.group(0) if m else None


# ── transport ────────────────────────────────────────────────────────────────

def _gemini_payload(messages, max_tokens, temperature, json_mode):
    """OpenAI-shaped messages -> Gemini's contents/systemInstruction/generationConfig."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    contents = [{"role": "model" if m.get("role") == "assistant" else "user",
                 "parts": [{"text": m.get("content", "")}]}
                for m in messages if m.get("role") != "system"]
    cfg = {"maxOutputTokens": max_tokens, "temperature": temperature}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    out = {"contents": contents, "generationConfig": cfg}
    if system:
        out["systemInstruction"] = {"parts": [{"text": system}]}
    return out


def _gemini_read(d):
    """(text, tokens) out of a generateContent response."""
    cand = (d.get("candidates") or [{}])[0]
    parts = ((cand.get("content") or {}).get("parts") or [])
    text = "".join(p.get("text", "") for p in parts).strip()
    used = (d.get("usageMetadata") or {}).get("totalTokenCount", 0)
    return text, used, cand.get("finishReason")


def _post(url, key, payload, timeout=90, headers=None):
    """Every provider in the chain speaks the OpenAI chat-completions shape, including
    Gemini (via its compatibility endpoint) and Ollama, so one transport serves all of
    them."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers or {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Cloudflare fronts the Groq API and rejects urllib's default
            # "Python-urllib/3.x" agent with a 403 (error 1010) before the request ever
            # reaches Groq. Any ordinary agent string gets through.
            "User-Agent": "the-cut/1.0 (+https://github.com/maxwilliamfoster-sys/the-cut)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(messages, model=FAST, max_tokens=1800, temperature=0.9, json_mode=True, retries=2):
    """One completion, from whichever free provider is still answering.

    `model` is a TIER — FAST or DEEP — not a model id. This walks the provider chain in
    order and, within each provider, its candidate models. A model that no longer exists is
    demoted for the rest of the run rather than retried; a provider out of tokens for the
    day is skipped entirely. Only when every route is exhausted does this raise, and it
    raises QuotaExhausted so the caller can tell "out of allowance" from "broken".
    """
    tier = model if model in (FAST, DEEP) else FAST
    avail = providers_available()
    if not avail:
        raise QuotaExhausted("no provider has a key configured")

    last = None
    for prov in avail:
        for candidate in _candidates(prov, tier):
            try:
                return _call(prov, candidate, messages, max_tokens, temperature,
                             json_mode, retries)
            except _ModelGone as e:
                print(f'[llm] {prov["name"]}/{candidate} is gone ({e}) — demoting it')
                _dead_models.add((prov["name"], candidate))
                last = e
            except QuotaExhausted as e:
                print(f'[llm] {prov["name"]}: {e} — trying the next provider')
                _dead_providers.add(prov["name"])
                last = e
                break
            except Exception as e:
                print(f'[llm] {prov["name"]}/{candidate} failed: {e}')
                last = e
    configured = [p["name"] for p in PROVIDERS
                  if not p["key"] or os.environ.get(p["key"])]
    hint = ""
    if len(configured) <= 1:
        # Worth saying out loud rather than leaving somebody to read the source: a chain
        # with one link in it is not a chain, and this is the exact failure it exists for.
        missing = [p["key"] for p in PROVIDERS if p["key"] and not os.environ.get(p["key"])]
        hint = (f" — only {configured or ['nothing']} is configured, so there was nowhere to "
                f"fall back to. Set any of {missing} to give the city a second source.")
    raise QuotaExhausted(f"every provider is exhausted or failing (last: {last}){hint}")


class _ModelGone(RuntimeError):
    """This provider no longer serves this model. Try the next candidate, not the next
    provider — the account is fine, the name is stale."""


def _call(prov, model, messages, max_tokens, temperature, json_mode, retries):
    key = os.environ.get(prov["key"]) if prov["key"] else "local"
    gemini = prov.get("dialect") == "gemini"
    url = prov["url"].replace("{model}", model)
    headers = None

    if gemini:
        payload = _gemini_payload(messages, max_tokens, temperature, json_mode)
        headers = {"x-goog-api-key": key, "Content-Type": "application/json",
                   "User-Agent": "the-cut/1.0"}
    else:
        payload = {
            "model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
        }
        if "gpt-oss" in model:
            payload["reasoning_effort"] = REASONING_EFFORT
            payload["reasoning_format"] = "hidden"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

    for attempt in range(retries + 1):
        try:
            d = _post(url, key, payload, headers=headers)

            if gemini:
                content, used, finish = _gemini_read(d)
                if finish == "MAX_TOKENS":
                    print(f"[llm] WARNING response hit max_tokens ({max_tokens}) — truncated")
                if not content:
                    if attempt < retries:
                        payload["generationConfig"]["maxOutputTokens"] = int(max_tokens * 1.5)
                        print(f'[llm] EMPTY content from gemini/{model} (finish={finish}) — retrying')
                        time.sleep(2)
                        continue
                    raise RuntimeError(f"{model} returned empty content (finish={finish})")
                if prov["name"] != _working.get("name"):
                    print(f'[llm] using {prov["name"]}/{model}')
                    _working["name"] = prov["name"]
                return content, used

            choice = (d.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "length":
                # Truncated mid-JSON: the salvage in parse_json recovers the entries that
                # completed, so the beat still lands, but people at the end of the batch
                # silently lose their turn. Worth seeing in the log.
                print(f"[llm] WARNING response hit max_tokens ({max_tokens}) — batch truncated")

            msg = choice.get("message") or {}
            content = (msg.get("content") or "").strip()
            used = (d.get("usage") or {}).get("total_tokens", 0)

            # A 200 with an empty body is the failure mode that killed the city quietly:
            # reasoning models can spend the entire reservation on the hidden channel and
            # return nothing visible. Never hand an empty string back to a caller that is
            # about to shrug and call it a quiet beat — retry harder, then fail LOUDLY.
            if not content:
                reasoning = (msg.get("reasoning") or "").strip()
                salvaged = parse_json(reasoning) if reasoning else None
                if salvaged is not None:
                    print("[llm] empty content — salvaged JSON from the reasoning channel")
                    return json.dumps(salvaged), used
                if attempt < retries:
                    bigger = min(int(max_tokens * 1.5), prov.get("tpm", 8000) - TPM_HEADROOM)
                    print(f'[llm] EMPTY content from {prov["name"]}/{model} '
                          f'(finish={choice.get("finish_reason")}) — retrying at {bigger}')
                    payload["max_tokens"] = bigger
                    time.sleep(2)
                    continue
                raise RuntimeError(f"{model} returned empty content {retries + 1}x")

            if prov["name"] != _working.get("name"):
                print(f'[llm] using {prov["name"]}/{model}')
                _working["name"] = prov["name"]
            return content, used

        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            if e.code == 404 or "model_not_found" in body or "does not exist" in body:
                raise _ModelGone(f"HTTP {e.code}")
            if e.code in (401, 403):
                raise QuotaExhausted(f"rejected the key (HTTP {e.code})")
            if e.code == 402:
                # Valid key, no allowance on the account. Provider-level and permanent for
                # this run, so skip it immediately rather than retrying every candidate.
                raise QuotaExhausted("account has no inference quota (HTTP 402 — billing)")
            if e.code == 413 or (e.code == 429 and "Request too large" in body):
                # The reservation was too big for the per-minute ceiling. Shrinking the
                # reply allowance is better than dropping the beat.
                current = (payload["generationConfig"]["maxOutputTokens"] if gemini
                           else payload["max_tokens"])
                new_max = max(600, int(current * 0.6))
                if new_max < current and attempt < retries:
                    print(f"[llm] request too large — retrying with max_tokens {new_max}")
                    if gemini:
                        payload["generationConfig"]["maxOutputTokens"] = new_max
                    else:
                        payload["max_tokens"] = new_max
                    time.sleep(2)
                    continue
                raise RuntimeError(f"{e.code} request too large: {body}")
            if e.code == 429:
                if re.search(r"tokens? per day|TPD|daily", body, re.I):
                    raise QuotaExhausted("daily cap reached")
                # Per-minute ceiling: the provider says how long to wait, so wait that long.
                m = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)s", body, re.I)
                wait = (int(m.group(1) or 0) * 60 + float(m.group(2)) + 2) if m else 20
                print(f'[llm] {prov["name"]} rate limit — sleeping {wait:.0f}s')
                time.sleep(min(wait, 120))
                continue
            if attempt >= retries:
                raise RuntimeError(f"HTTP {e.code}: {body}")
            time.sleep(3)
        except (urllib.error.URLError, TimeoutError) as e:
            # A local Ollama that is not running looks exactly like this.
            raise QuotaExhausted(f"unreachable ({e})")
        except _ModelGone:
            raise
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(3)

    raise RuntimeError("exhausted retries")


def parse_json(text):
    """Models garnish JSON with prose and code fences no matter how firmly asked not to."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None
