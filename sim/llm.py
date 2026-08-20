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

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Groq retired the whole Llama text line (both former models now 404). The replacements
# are gpt-oss, which changes two things that the rest of this file has to respect:
#   1. Both tiers get the SAME allowance — 8K TPM / 200K TPD each. The old design leaned on
#      FAST having 500K TPD; it no longer does. 200K does not cover a day of beats alone, so
#      the two models are treated as two *separate* 200K buckets and cognition spills from
#      one into the other rather than going quiet (see cognition.make_cognition).
#   2. They are reasoning models. Reasoning tokens are billed as completion tokens and eat
#      the same max_tokens reservation as the visible reply, so REASONING_EFFORT is pinned
#      low and fit_max_tokens() budgets for them explicitly.
FAST = "openai/gpt-oss-20b"          # 200K TPD — the workhorse, one call per beat
DEEP = "openai/gpt-oss-120b"         # 200K TPD — the Gazette, and cognition's spillover

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
    room = TPM.get(model, 8000) - TPM_HEADROOM - prompt_est
    # The reservation has to cover the hidden reasoning channel as well as the JSON we
    # actually want, or the visible reply gets squeezed to nothing.
    return max(floor, min(want + REASONING_RESERVE, room))

# Headroom under the published caps: a beat that overruns should degrade to a quiet beat,
# not get a 429 halfway through a batch and lose everyone's decisions.
# Two independent 200K buckets, held just under the published cap so an overrun degrades
# to a quiet beat instead of a 429 landing mid-batch and costing everyone their turn.
DAILY_BUDGET = {FAST: 188_000, DEEP: 188_000}

OPENROUTER_FALLBACKS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

_openrouter_only = False


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

def _post(url, key, payload, timeout=90):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
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


def _openrouter(messages, max_tokens, temperature):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Groq daily cap reached and OPENROUTER_API_KEY is not set.")
    last = None
    for model in OPENROUTER_FALLBACKS:
        try:
            d = _post(OPENROUTER_URL, key, {
                "model": model, "messages": messages,
                "max_tokens": max_tokens, "temperature": temperature,
            })
            text = (d["choices"][0]["message"].get("content") or "").strip()
            if not text:
                raise RuntimeError(f"{model} returned empty content")
            print(f"[llm] OpenRouter -> {model}")
            return text, 0
        except Exception as e:
            last = e
    raise RuntimeError(f"All OpenRouter fallbacks failed: {last}")


def chat(messages, model=FAST, max_tokens=1800, temperature=0.9, json_mode=True, retries=2):
    """One completion. Returns (text, tokens_used). Raises only if every route fails."""
    global _openrouter_only
    key = os.environ.get("GROQ_API_KEY")
    if not key or _openrouter_only:
        return _openrouter(messages, max_tokens, temperature)

    payload = {
        "model": model, "messages": messages,
        "max_tokens": max_tokens, "temperature": temperature,
    }
    if model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = REASONING_EFFORT
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    for attempt in range(retries + 1):
        try:
            d = _post(GROQ_URL, key, payload)
            choice = d["choices"][0]
            if choice.get("finish_reason") == "length":
                # Truncated mid-JSON: the salvage in parse_json will recover the entries
                # that completed, so the beat still lands, but people at the end of the
                # batch silently lose their turn. Worth seeing in the log.
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
                    bigger = min(int(max_tokens * 1.5), TPM.get(model, 8000) - TPM_HEADROOM)
                    print(f"[llm] EMPTY content (finish={choice.get('finish_reason')}, "
                          f"{used} tokens spent on reasoning) — retrying with "
                          f"max_tokens {bigger}")
                    payload["max_tokens"] = bigger
                    time.sleep(2)
                    continue
                raise RuntimeError(
                    f"{model} returned empty content {retries + 1}x "
                    f"(finish_reason={choice.get('finish_reason')}) — the model answered "
                    f"but said nothing usable.")

            return content, used
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            if e.code == 413 or (e.code == 429 and "Request too large" in body):
                # The reservation was too big for the per-minute ceiling. Shrinking the
                # reply allowance is better than dropping the beat: a slightly terser
                # batch still gives everyone a turn.
                new_max = max(600, int(payload["max_tokens"] * 0.6))
                if new_max < payload["max_tokens"] and attempt < retries:
                    print(f"[llm] request too large — retrying with max_tokens {new_max}")
                    payload["max_tokens"] = new_max
                    time.sleep(2)
                    continue
                raise RuntimeError(f"Groq {e.code} (request too large): {body}")
            if e.code == 429:
                if re.search(r"tokens? per day|TPD", body, re.I):
                    print("[llm] Groq daily token cap reached — failing over to OpenRouter.")
                    _openrouter_only = True
                    return _openrouter(messages, max_tokens, temperature)
                # Per-minute ceiling: Groq tells us how long to wait, so wait exactly that.
                m = re.search(r"try again in (?:(\d+)m)?\s*([\d.]+)s", body, re.I)
                wait = (int(m.group(1) or 0) * 60 + float(m.group(2)) + 2) if m else 20
                print(f"[llm] Groq rate limit — sleeping {wait:.0f}s")
                time.sleep(min(wait, 120))
                continue
            if attempt >= retries:
                raise RuntimeError(f"Groq HTTP {e.code}: {body}")
            time.sleep(3)
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(3)

    raise RuntimeError("Groq exhausted retries")


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
