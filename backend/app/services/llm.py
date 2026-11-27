"""Groq calls: one place for clients, structured answers, daily limits and the backup model.

Two Groq quirks are handled here:

1. Models sometimes name their answer "functions.CameraExtraction" instead of "CameraExtraction"
   (copying the OpenAI-style prefix). LangChain then rejects a perfectly good answer with
   "Unknown tool type". The raw answer is kept, the prefix stripped, and the arguments validated.

2. The free tier has a daily token allowance per model (e.g. 200,000 for gpt-oss-20b). When a
   model runs out, it is remembered as exhausted until Groq says it is back, and the call moves to
   GROQ_FALLBACK_MODEL, which has its own allowance. When every model is out, DailyLimitReached is
   raised once, so the caller can stop instead of failing page after page.

Speed on the free tier is set by the per-minute token limit (8,000 per model): about 2-3 page readings
a minute. Two things keep calls moving under it:

- Pacing: the tokens each model used in the last minute are counted, and a call waits just long enough
  for room instead of hitting the limit, sleeping, and often failing the page anyway.
- Spreading (GROQ_SPREAD_MODELS): when the main model has no room, the call goes to the backup model,
  which has its own per-minute allowance. Pages are read about twice as fast for the same tokens.
"""
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from functools import lru_cache

from pydantic import BaseModel

from ..config import settings

log = logging.getLogger(__name__)

_exhausted: dict[str, float] = {}  # model -> time.time() when its daily allowance is back


class DailyLimitReached(RuntimeError):
    """Every model we may use has hit Groq's daily limit."""

    def __init__(self, retry_after: float):
        self.retry_after = max(0.0, retry_after)
        super().__init__(f"Groq daily token limit reached; try again in about {human_wait(self.retry_after)}")


def human_wait(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "a minute"
    if minutes < 90:
        return f"{minutes} minutes"
    return f"{round(minutes / 60)} hours"


_WAIT = re.compile(r"try again in ((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", re.I)


def _seconds(text: str) -> float | None:
    """'1m45.84s' / '2h3m' / '12.5s' -> seconds."""
    m = _WAIT.search(text)
    if not m or not m.group(1):
        return None
    parts = {unit: value for value, unit in re.findall(r"([\d.]+)([hms])", m.group(1))}
    return float(parts.get("h", 0)) * 3600 + float(parts.get("m", 0)) * 60 + float(parts.get("s", 0))


def _limit(error: Exception) -> tuple[str, float | None] | None:
    """('day' | 'minute', seconds to wait) for a Groq rate-limit error, else None."""
    text = str(error)
    if getattr(error, "status_code", None) != 429 and "rate_limit" not in text and "Rate limit" not in text:
        return None
    period = "day" if re.search(r"per day|\((TPD|RPD)\)", text) else "minute"
    return period, _seconds(text)


def per_minute_wait(error: Exception) -> float | None:
    """Seconds to wait for a per-minute rate limit (capped), else None."""
    limit = _limit(error)
    if limit and limit[0] == "minute":
        return min(limit[1] or settings.extract_retry_wait, 30.0)
    return None


@lru_cache(maxsize=8)
def chat(model: str, temperature: float = 0.0):
    """A ChatGroq client. Reasoning models (gpt-oss) get GROQ_REASONING_EFFORT: pulling facts off a
    page needs little reasoning, and hidden reasoning tokens count towards the daily limit."""
    from langchain_groq import ChatGroq

    extra = {}
    if settings.groq_reasoning_effort and model.startswith("openai/gpt-oss"):
        extra["reasoning_effort"] = settings.groq_reasoning_effort
    # one retry for network blips; rate limits are handled here, not by sleeping in the SDK
    return ChatGroq(model=model, temperature=temperature, max_retries=1, **extra)


# ---- per-minute pacing ----

WINDOW = 60.0  # seconds: Groq's per-minute limits count tokens over the last minute
SAFETY = 0.9  # stay a little under the limit: token counts are estimates until the answer arrives
ANSWER_ALLOWANCE = 700  # tokens for the hidden reasoning and the answer, before the real count is known
MAX_MINUTE_RETRIES = 4  # per-minute limit errors in one call before giving up on it


def _sleep(seconds: float) -> None:  # tests replace this
    time.sleep(seconds)


class Pacer:
    """Tokens each model used in the last minute; tells a call how long to wait for room."""

    def __init__(self):
        self.limit: int | None = None  # tokens per minute; None: GROQ_TOKENS_PER_MINUTE (tests set 0)
        self._used: dict[str, deque] = defaultdict(deque)  # model -> [time, tokens] entries
        self._blocked: dict[str, float] = {}  # model -> time Groq said to wait until
        self._lock = threading.Lock()

    def wait_for(self, model: str, tokens: int, now: float | None = None) -> float:
        """Seconds until `tokens` more fit under this model's per-minute limit (0: now)."""
        now = time.time() if now is None else now
        with self._lock:
            blocked = max(0.0, self._blocked.get(model, 0) - now)
            limit = settings.groq_tokens_per_minute if self.limit is None else self.limit
            if not limit:
                return blocked
            used = self._used[model]
            while used and used[0][0] <= now - WINDOW:
                used.popleft()
            over = sum(t for _, t in used) + tokens - limit * SAFETY
            if over <= 0 or not used:  # a call bigger than the whole budget still goes when the minute is empty
                return blocked
            for at, t in used:  # wait until enough of the oldest calls leave the window
                over -= t
                if over <= 0:
                    return max(blocked, at + WINDOW - now)
            return max(blocked, used[-1][0] + WINDOW - now)

    def reserve(self, model: str, tokens: int) -> list:
        """Count a call that is about to start; settle() replaces the estimate with Groq's count."""
        entry = [time.time(), tokens]
        with self._lock:
            self._used[model].append(entry)
        return entry

    def settle(self, entry: list, tokens: int | None) -> None:
        if tokens:
            with self._lock:
                entry[1] = tokens

    def block(self, model: str, seconds: float) -> None:
        """Groq said this model is at its limit: don't use it for this long."""
        with self._lock:
            self._blocked[model] = max(self._blocked.get(model, 0), time.time() + seconds)

    def pick(self, models: list[str], tokens: int) -> tuple[str, float]:
        """The first model with room now, else the one with room soonest, and the wait for it."""
        waits = [(self.wait_for(m, tokens), i, m) for i, m in enumerate(models)]
        ready = [w for w in waits if w[0] <= 0]
        wait, _, model = ready[0] if ready else min(waits)
        return model, max(0.0, wait)

    def reset(self) -> None:
        with self._lock:
            self._used.clear()
            self._blocked.clear()


PACER = Pacer()


def estimate_tokens(messages, schema: type[BaseModel] | None = None) -> int:
    """About 4 characters per token, for the prompt and the answer schema, plus the answer."""
    chars = sum(len(str(m[1] if isinstance(m, (tuple, list)) else getattr(m, "content", m))) for m in messages)
    if schema is not None:
        chars += len(json.dumps(schema.model_json_schema()))
    return chars // 4 + ANSWER_ALLOWANCE


def model_chain(primary: str) -> list[str]:
    """The primary model, then the backup if it is a different one."""
    backup = settings.groq_fallback_model
    return [primary] + ([backup] if backup and backup != primary else [])


def call(primary: str, schema: type[BaseModel], messages, client_for=None, temperature: float = 0.0):
    """A structured answer from a model that still has daily allowance and room this minute.

    The main model is used while it has room. With GROQ_SPREAD_MODELS, the backup takes the call when
    the main model is at its per-minute limit; otherwise the backup is used only once the main model is
    out for the day. When no model has room, the call waits for the first one that will.

    client_for(model) builds the client (tests pass a fake). Raises DailyLimitReached when every
    model is out for the day; other errors are raised as they are."""
    client_for = client_for or (lambda model: chat(model, temperature))
    chain = model_chain(primary)
    tokens = estimate_tokens(messages, schema)
    minute_errors = 0
    while True:
        live = [m for m in chain if _exhausted.get(m, 0) <= time.time()]
        if not live:
            raise DailyLimitReached(min(_exhausted[m] for m in chain) - time.time())
        model, wait = PACER.pick(live if settings.groq_spread_models else live[:1], tokens)
        if wait > 0:
            log.info("Waiting %.0fs for room under Groq's per-minute limit (%s)", wait, model)
            _sleep(wait)
            continue  # another model may have room by now
        entry = PACER.reserve(model, tokens)
        usage: dict = {}
        try:
            result = structured_invoke(client_for(model), schema, messages, usage)
            PACER.settle(entry, usage.get("total_tokens"))
            return result
        except Exception as e:
            limit = _limit(e)
            if not limit:
                raise
            period, seconds = limit
            if period == "day":
                wait = seconds if seconds is not None else 600.0
                _exhausted[model] = time.time() + wait
                nxt = next((m for m in chain if _exhausted.get(m, 0) <= time.time()), None)
                log.warning("Groq daily limit reached for %s (back in %s)%s", model, human_wait(wait),
                            f"; switching to {nxt}" if nxt else "")
                continue
            # per-minute: our count was off (another app using the key, or a long answer). Rest this
            # model for as long as Groq says and carry on with another one, or wait for it.
            minute_errors += 1
            if minute_errors > MAX_MINUTE_RETRIES:
                raise
            PACER.block(model, min(seconds or settings.extract_retry_wait, WINDOW))
            log.info("Groq per-minute limit on %s; resting it %.0fs", model, seconds or settings.extract_retry_wait)


def structured_invoke(llm, schema: type[BaseModel], messages, usage: dict | None = None):
    """llm.with_structured_output(schema).invoke(messages), tolerating a prefixed tool name.

    usage, if given, is filled with Groq's token counts (total_tokens...) when the answer has them.
    Raises the original parsing error (or a ValidationError) if the answer really is unusable."""
    out = llm.with_structured_output(schema, include_raw=True).invoke(messages)
    if not isinstance(out, dict):  # a client that ignores include_raw (e.g. a test fake)
        return out
    if usage is not None:
        usage.update(getattr(out.get("raw"), "usage_metadata", None) or {})
    if out.get("parsed") is not None:
        return out["parsed"]

    raw = out.get("raw")
    for call_ in getattr(raw, "tool_calls", None) or []:
        name = str(call_.get("name") or "").rsplit(".", 1)[-1]  # "functions.CameraExtraction" -> "CameraExtraction"
        if name == schema.__name__:
            return schema.model_validate(call_.get("args") or {})
    raise out.get("parsing_error") or ValueError("The model returned no structured answer")


def reset_limits() -> None:
    """Forget which models are out for the day and what they used this minute (tests)."""
    _exhausted.clear()
    PACER.reset()
