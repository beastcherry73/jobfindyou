"""AI client with quota-aware dynamic routing.

Rather than a fixed priority chain, every request picks the model with the most
estimated headroom RIGHT NOW, so concurrent users naturally land on different
models and one saturated bucket does not stall everyone. When a model nears or
trips its limit the router moves on - sometimes to another Groq model,
sometimes to a different provider entirely.

What the providers actually give us (measured 2026-08-28, not assumed)
----------------------------------------------------------------------
* There is NO pre-flight quota endpoint anywhere. Groq reports quota in
  RESPONSE headers (`x-ratelimit-remaining-requests` / `-tokens`, plus reset
  intervals); Gemini and NVIDIA NIM report nothing at all. So headroom is
  *learned from the last response*, never queried up front, and estimated
  locally for the providers that stay silent. Groq's headers are account-wide
  truth, so one instance's observations are authoritative even though other
  instances share the account.
* TPM is the binding constraint, not RPM. gpt-oss reports 1000 requests/min but
  only 8000 tokens/min, and one analysis call requests 6000 max_tokens - so
  roughly ONE analysis saturates a minute of that bucket. Scoring is therefore
  token-first.
* Buckets are PER MODEL, and their sizes differ a lot: gpt-oss models sit at
  8000 TPM, groq/compound-mini at 70000, allam-2-7b at 6000, Gemini around
  250000. Under load the three gpt-oss models drift apart independently
  (6921 / 7093 / 7867 observed), confirming they are metered separately - so
  spreading across models really does multiply capacity. Nothing is hardcoded
  regardless: state is keyed per model and driven by observed headers, so if a
  family ever did share a bucket the router would simply see low headroom on
  all its members and move on.

State lives in memory, per process. Vercel instances are stateless and scale
horizontally, so this is per-instance and approximate - but because Groq's
headers report ACCOUNT-wide remaining quota, each instance corrects itself on
every response it sees. Persisting to Postgres was rejected for now: the shared
connection is lock-serialized (see CLAUDE.md), and a read+write per AI call
would add contention to every request in the app.

JSON mode
---------
`json_mode=True` sends `response_format={"type":"json_object"}` AND restricts
routing to models verified to honour it. It is opt-in, never global, because
`call_groq` also serves generate.py, whose SCRATCH_PROMPT asks for a Markdown
resume - forcing json_object there would corrupt that output.

Every model carries `json_ok` / `text_ok` flags recording the shapes it was
actually tested to honour, and routing only considers models proven for the
shape a call needs. Silent shape violations are the reason: they are worse than
errors, because json.loads blows up on valid-looking prose and a resume would
ship with the model's reasoning stapled to the top. Observed offenders:
  * qwen/qwen3.6-27b  - 400 in JSON mode AND leaks a <think> block in text.
                        Dropped entirely.
  * groq/compound     - 200 with PROSE in JSON mode, "**Reasoning**" prefix in
                        text mode. Dropped entirely.
  * allam-2-7b        - JSON only; drops markdown ("# Hello" -> "Hello").
  * nemotron-3-nano   - text only; answers JSON mode in prose.

Provider notes
--------------
Cerebras was REMOVED (2026-08-29): its free tier now requires a payment method
on file, so every key returns 402. JobSpike runs card-free.
Google limits are per Cloud PROJECT, not per key, and the flash models share
one ~250k TPM pool - extra Gemini entries buy requests-per-day, not TPM.
NVIDIA NIM is card-free (email signup); most models in its /models listing 404
on this tier, so entries here were verified by real completions.
"""

import os
import re
import threading
import time

import requests as http_requests
from flask import current_app


class GroqError(Exception):
    """Raised when the AI service cannot produce a response.

    Named for Groq historically; every route already catches it, so the name
    is kept to avoid a wide rename. `AIError` is the forward-looking alias.
    """


AIError = GroqError


class ProviderError(Exception):
    """One model attempt failed. Carries the HTTP status and body so the
    router can classify the failure instead of guessing."""

    def __init__(self, message, status=None, body="", headers=None):
        super().__init__(message)
        self.status = status
        self.body = body or ""
        # Kept so back-off can honour Retry-After / reset hints from the
        # response that actually failed.
        self.headers = headers or {}

    @property
    def kind(self):
        return _classify(self.status, self.body or str(self))


# Cerebras was removed on 2026-08-29. Its free tier began requiring a payment
# method on file (provider policy change, 2026-08-17), so every key returned
# HTTP 402 payment_required - it could never serve a request, and left in the
# table it cost a wasted round trip on every cold instance before being parked.
# JobSpike runs card-free, so it is not coming back.
_PROVIDER_CONF = {
    "groq": {"env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1"},
    "gemini": {"env": "GEMINI_API_KEY",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "nvidia": {"env": "NVIDIA_API_KEY",
               "base_url": "https://integrate.api.nvidia.com/v1"},
}

# Routable models. `json_ok` gates membership of the JSON pool; `tpm_hint` is
# only a cold-start prior for models we have not yet heard headers from, and is
# replaced by observed values on the first response.
#
# `reasoning_effort` is a gpt-oss extension - those models return EMPTY content
# without it - and must not be sent to providers that do not understand it.
def _m(provider, model, json_ok=True, text_ok=True, extra=None, tpm_hint=8000,
       min_budget=0, max_budget=None):
    """One routable model.

    `json_ok` / `text_ok` record the OUTPUT SHAPES this model was actually
    verified to honour - routing only considers models proven for the shape a
    call needs, so the contract holds whichever model wins.
    `min_budget` excludes models that need a large max_tokens to produce any
    content at all (reasoning models spend the budget thinking first).
    `max_budget` excludes models too SLOW to finish a large request inside
    `_TIMEOUT`. Offering one a job it cannot finish is worse than skipping it:
    the attempt burns the full timeout and the request fails anyway, having
    spent the budget the next candidate needed.
    """
    return {"provider": provider, "model": model, "json_ok": json_ok,
            "text_ok": text_ok, "extra": extra or {}, "tpm_hint": tpm_hint,
            "min_budget": min_budget, "max_budget": max_budget}


# `reasoning_effort` is a gpt-oss extension - those models return EMPTY content
# without it - and must not be sent to providers that do not understand it.
_OSS = {"reasoning_effort": "low"}

_MODELS = [
    # --- Groq: separate per-model buckets, so spreading multiplies capacity ---
    _m("groq", "openai/gpt-oss-120b", extra=_OSS, tpm_hint=8000),
    _m("groq", "openai/gpt-oss-20b", extra=_OSS, tpm_hint=8000),
    _m("groq", "openai/gpt-oss-safeguard-20b", extra=_OSS, tpm_hint=8000),
    # Much the largest Groq bucket, and it honours both shapes.
    _m("groq", "groq/compound-mini", tpm_hint=70000),
    _m("groq", "qwen/qwen3.8-27b", tpm_hint=8000),
    # JSON only: asked for "# Hello" it returned "Hello", dropping the markdown.
    _m("groq", "allam-2-7b", text_ok=False, tpm_hint=6000),

    # --- Google AI Studio. NOTE: limits are per Cloud PROJECT, not per key,
    # and the flash models SHARE one ~250k TPM pool - so extra entries here buy
    # request-per-day headroom, not more tokens per minute.
    # gemini-2.5-flash / 2.0-flash / 2.5-pro are RETIRED: still listed by
    # /models, but every completion returns 404 "no longer available".
    _m("gemini", "gemini-3.1-flash-lite", tpm_hint=250000),
    _m("gemini", "gemini-flash-lite-latest", tpm_hint=250000),
    _m("gemini", "gemini-3.1-flash-lite-preview", tpm_hint=250000),
    # Spends a small budget on reasoning tokens and can return
    # finish_reason=length with NO content, so it is only offered a real one.
    _m("gemini", "gemini-3-flash-preview", tpm_hint=250000, min_budget=400),

    # --- NVIDIA NIM (card-free, email signup). Sends no rate-limit headers,
    # so its headroom is estimated locally like Gemini's. Most models in its
    # /models listing 404 on this tier; these were verified to actually serve.
    #
    # SLOW. Measured 2026-08-29 on this tier: the full resume-analysis prompt
    # (max_tokens=6000) took 58.4s -- past our 40s timeout and past the Vercel
    # function budget, so it could never have completed in production. The same
    # model answers the 1500-token job-match prompt in 10.4s. So it stays in
    # the pool for the small calls (job match, digest scoring, builder polish)
    # and is not offered the big one.
    _m("nvidia", "nvidia/nemotron-3-super-120b-a12b", tpm_hint=8000,
       max_budget=2000),
    # mistralai/mistral-nemotron was REMOVED (2026-08-29): measured HTTP 500 on
    # the small prompt and no response at all on the large one (still hanging
    # at 180s). It could not serve either shape, and left in the table it cost
    # a full 40s timeout on every failover before the next candidate was tried.
    # Text only: in JSON mode it answers in prose ("We are to return a JSON
    # object..."), silently ignoring response_format.
    _m("nvidia", "nvidia/nemotron-3-nano-30b-a3b", json_ok=False, tpm_hint=8000),
]

_TIMEOUT = 40.0
_TEMPERATURE = 0.4

# Failure classes; they differ in how far the router should back off.
_RATE_LIMIT = "rate_limit"
_AUTH = "auth"
_ACCOUNT = "account"          # payment/plan problem - condemns a whole provider
_MODEL_MISSING = "model_missing"
_TRANSIENT = "transient"
_OTHER = "other"

_PROVIDER_FATAL = (_AUTH, _ACCOUNT)

_QUOTA_MARKERS = (
    "rate limit", "rate_limit", "ratelimit", "quota", "insufficient_quota",
    "resource_exhausted", "too many requests",
)
_MODEL_MISSING_MARKERS = (
    "model_not_found", "does not exist", "no longer available", "not found",
    "decommissioned", "unsupported model", "invalid model",
)

# Back-off windows.
_RATE_LIMIT_COOLDOWN = 60.0     # fallback when no reset header is supplied
_TRANSIENT_COOLDOWN = 20.0
_MODEL_DEAD_COOLDOWN = 3600.0   # a retired model will not return within the hour
_PROVIDER_FATAL_COOLDOWN = 900.0

_lock = threading.Lock()
# key -> observed quota + back-off state
_state = {}


def _classify(status, body):
    """Map an HTTP status + body onto a failure class.

    Deliberately not a blanket `except Exception`: routing only works if a rate
    limit is distinguishable from a dead model or a bad key, and the body must
    be consulted because providers disagree about which status carries what.
    """
    text = (body or "").lower()
    # Before the quota markers: Cerebras answers 402 with `"param":"quota"`,
    # which reads as a rate limit but is an account-level plan problem - no
    # sibling model will succeed either.
    if status == 402 or "payment_required" in text or "payment required" in text:
        return _ACCOUNT
    if status == 429 or any(m in text for m in _QUOTA_MARKERS):
        return _RATE_LIMIT
    if status == 404 or any(m in text for m in _MODEL_MISSING_MARKERS):
        return _MODEL_MISSING
    if status in (401, 403):
        return _AUTH
    if status is None or status >= 500:
        return _TRANSIENT
    return _OTHER


def _log():
    """App logger inside a request, module logger otherwise (the digest and
    cron paths run without an application context)."""
    try:
        return current_app.logger
    except RuntimeError:
        import logging
        return logging.getLogger(__name__)


_DURATION_RE = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?"
                          r"(?:(\d+(?:\.\d+)?)m?s)?")


def _parse_reset(value):
    """Groq reset intervals look like '1m26.4s', '3.045s', '2h1m'. Returns
    seconds, or None when unparseable."""
    if not value:
        return None
    v = str(value).strip()
    try:
        return float(v)          # some providers send bare seconds
    except ValueError:
        pass
    m = _DURATION_RE.fullmatch(v)
    if not m or not any(m.groups()):
        return None
    h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def _key(provider, model):
    return f"{provider}/{model}"


def _entry(key, tpm_hint):
    """Fetch-or-create mutable state for one model. Caller holds `_lock`."""
    st = _state.get(key)
    if st is None:
        st = {
            "remaining_tokens": None, "limit_tokens": tpm_hint,
            "remaining_requests": None, "limit_requests": None,
            "quota_expires_at": 0.0,   # after this, observations are stale
            "cooldown_until": 0.0,
            "reserved_tokens": 0,      # in-flight, not yet reflected in headers
        }
        _state[key] = st
    return st


def _headroom(st, want_tokens, now):
    """Fraction of the token bucket believed free, 0..1.

    Token-first because TPM binds long before RPM. An unobserved model scores
    optimistically (1.0) so it gets tried and teaches us its real numbers -
    otherwise the router would never discover a fresh bucket.
    """
    if st["cooldown_until"] > now:
        return -1.0
    remaining = st["remaining_tokens"]
    if remaining is None or now >= st["quota_expires_at"]:
        return 1.0                      # unknown or window rolled over
    remaining = max(0, remaining - st["reserved_tokens"])
    limit = st["limit_tokens"] or 1
    if remaining < want_tokens:
        return 0.0                      # cannot fit this request right now
    return min(1.0, remaining / float(limit))


def _estimate_tokens(prompt, max_tokens):
    """Rough budget for one call: prompt plus the completion we asked for.
    ~4 chars/token is crude but only needs to rank models, not bill them."""
    return int(len(prompt) / 4) + int(max_tokens)


def _select(prompt, max_tokens, json_mode):
    """Models ordered by current headroom, best first.

    Candidates are filtered to those whose provider has a key, that are not in
    back-off, and - when json_mode is on - that are verified to honour
    response_format.
    """
    now = time.time()
    want = _estimate_tokens(prompt, max_tokens)
    scored = []
    with _lock:
        for spec in _MODELS:
            provider, model = spec["provider"], spec["model"]
            # A model must be verified for the OUTPUT SHAPE this call needs.
            if not (spec["json_ok"] if json_mode else spec["text_ok"]):
                continue
            # ...and be given enough budget to produce content at all.
            if max_tokens < spec["min_budget"]:
                continue
            # ...and be fast enough to finish a request this size in time.
            if spec["max_budget"] is not None and max_tokens > spec["max_budget"]:
                continue
            conf = _PROVIDER_CONF[provider]
            if not os.environ.get(conf["env"], ""):
                continue
            st = _entry(_key(provider, model), spec["tpm_hint"])
            score = _headroom(st, want, now)
            if score < 0:
                continue                # cooling down
            scored.append((score, provider, model, spec["extra"], conf))
    # Highest headroom first; ties keep _MODELS order, which puts the models we
    # trust most for quality first.
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored, want


def _note_success(key, headers, want_tokens):
    """Fold a provider's rate-limit headers into state. Authoritative for Groq;
    for providers that send nothing we decrement our own estimate instead."""
    now = time.time()
    with _lock:
        st = _state.get(key)
        if st is None:
            return
        st["reserved_tokens"] = max(0, st["reserved_tokens"] - want_tokens)

        rem_t = headers.get("x-ratelimit-remaining-tokens")
        lim_t = headers.get("x-ratelimit-limit-tokens")
        rem_r = headers.get("x-ratelimit-remaining-requests")
        lim_r = headers.get("x-ratelimit-limit-requests")
        reset_t = _parse_reset(headers.get("x-ratelimit-reset-tokens"))

        if rem_t is not None:
            try:
                st["remaining_tokens"] = int(float(rem_t))
                if lim_t:
                    st["limit_tokens"] = int(float(lim_t))
                if rem_r:
                    st["remaining_requests"] = int(float(rem_r))
                if lim_r:
                    st["limit_requests"] = int(float(lim_r))
                # Trust an observation until its window resets.
                st["quota_expires_at"] = now + (reset_t if reset_t else 60.0)
            except (TypeError, ValueError):
                pass
        else:
            # No headers (Gemini): decrement our own running estimate.
            if st["remaining_tokens"] is None or now >= st["quota_expires_at"]:
                st["remaining_tokens"] = st["limit_tokens"]
                st["quota_expires_at"] = now + 60.0
            st["remaining_tokens"] = max(0, st["remaining_tokens"] - want_tokens)


def _note_failure(key, kind, headers, want_tokens):
    """Apply back-off for a failed attempt."""
    now = time.time()
    with _lock:
        st = _state.get(key)
        if st is None:
            return
        st["reserved_tokens"] = max(0, st["reserved_tokens"] - want_tokens)
        if kind == _RATE_LIMIT:
            wait = (_parse_reset((headers or {}).get("retry-after"))
                    or _parse_reset((headers or {}).get("x-ratelimit-reset-tokens"))
                    or _RATE_LIMIT_COOLDOWN)
            st["cooldown_until"] = now + wait
            st["remaining_tokens"] = 0
            st["quota_expires_at"] = now + wait
        elif kind == _MODEL_MISSING:
            st["cooldown_until"] = now + _MODEL_DEAD_COOLDOWN
        elif kind == _TRANSIENT:
            st["cooldown_until"] = now + _TRANSIENT_COOLDOWN


def _cooldown_provider(provider, seconds):
    """Park every model behind a provider - used when a key or plan is refused,
    where trying siblings only burns latency."""
    now = time.time()
    with _lock:
        for spec in _MODELS:
            if spec["provider"] == provider:
                _entry(_key(provider, spec["model"]),
                       spec["tpm_hint"])["cooldown_until"] = now + seconds


def _chat_completion(conf, provider, model, extra, prompt, max_tokens,
                     api_key, json_mode):
    """One OpenAI-compatible chat-completions call.

    Returns (content, headers). Raises ProviderError - including for a 200
    whose content is empty, which is useless to every caller.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": _TEMPERATURE,
        "max_tokens": max_tokens,
    }
    payload.update(extra or {})
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = http_requests.post(
            f"{conf['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload, timeout=_TIMEOUT,
        )
    except http_requests.RequestException as e:
        # Never let the exception text carry the key.
        raise ProviderError(f"{provider}/{model} request failed: {type(e).__name__}")

    if resp.status_code != 200:
        raise ProviderError(
            f"{provider}/{model} HTTP {resp.status_code}: {resp.text[:160]}",
            status=resp.status_code, body=resp.text, headers=resp.headers,
        )

    try:
        content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"{provider}/{model} unreadable response: {e}",
                            status=resp.status_code)
    if not content:
        raise ProviderError(f"{provider}/{model} returned an empty response",
                            status=resp.status_code)
    return content, resp.headers


def call_groq(prompt, max_tokens=6000, json_mode=False):
    """Call the AI service and return the raw model output.

    Routes to whichever configured model currently has the most token headroom,
    then walks down the ranking on failure. `json_mode=True` additionally
    restricts routing to models verified to honour response_format, so the
    output contract holds no matter which model is picked.

    Signature stays backward compatible: every route calls
    `call_groq(prompt, max_tokens=...)` and catches GroqError, and the
    production test suite patches this name directly.

    Raises GroqError only once every candidate is exhausted.
    """
    log = _log()
    candidates, want = _select(prompt, max_tokens, json_mode)

    if not candidates:
        # Distinguish "nothing configured" from "everything is rate-limited".
        # Reporting a missing key when the key is fine sends whoever reads the
        # log after the wrong problem entirely.
        any_configured = any(
            os.environ.get(_PROVIDER_CONF[spec["provider"]]["env"], "")
            for spec in _MODELS
        )
        if not any_configured:
            log.warning("No AI provider key is set (GROQ_API_KEY / "
                        "GEMINI_API_KEY / NVIDIA_API_KEY).")
            raise GroqError("GROQ_API_KEY is not set. "
                            "Configure it before using AI features.")
        log.error("Every configured AI model is rate-limited or cooling down.")
        raise GroqError("All AI models are rate-limited right now. "
                        "Please try again in a minute.")

    last_err = None
    attempted = 0
    for score, provider, model, extra, conf in candidates:
        key = _key(provider, model)
        with _lock:
            _state[key]["reserved_tokens"] += want
        attempted += 1
        try:
            content, headers = _chat_completion(
                conf, provider, model, extra, prompt, max_tokens,
                os.environ.get(conf["env"], ""), json_mode)
            _note_success(key, headers, want)
            if attempted > 1:
                log.warning(f"AI routed to {key} after {attempted - 1} failed "
                            f"attempt(s); last error: {last_err}")
            return content
        except ProviderError as e:
            kind = e.kind
            _note_failure(key, kind, e.headers, want)
            last_err = e
            if kind == _MODEL_MISSING:
                log.error(f"AI model may have been retired: {e}")
            elif kind == _RATE_LIMIT:
                log.warning(f"AI model rate-limited, rerouting: {e}")
            else:
                log.warning(f"AI model failed ({kind}), rerouting: {e}")
            if kind in _PROVIDER_FATAL:
                log.error(f"{provider} unusable ({kind}); parking its models.")
                _cooldown_provider(provider, _PROVIDER_FATAL_COOLDOWN)
            continue

    log.error(f"Every AI model in the routing table failed. Last: {last_err}")
    raise GroqError(f"All Groq models are unavailable: {last_err}")


def routing_snapshot():
    """Current per-model view, for diagnostics and the step-4 health check.

    Read-only; never exposes keys.
    """
    now = time.time()
    out = []
    with _lock:
        for spec in _MODELS:
            provider = spec["provider"]
            key = _key(provider, spec["model"])
            st = _state.get(key)
            out.append({
                "model": key,
                "json_ok": spec["json_ok"],
                "text_ok": spec["text_ok"],
                "configured": bool(os.environ.get(_PROVIDER_CONF[provider]["env"], "")),
                "remaining_tokens": (st or {}).get("remaining_tokens"),
                "limit_tokens": (st or {}).get("limit_tokens", spec["tpm_hint"]),
                "cooling_down_for": max(0.0, round((st or {}).get("cooldown_until", 0) - now, 1)),
            })
    return out
