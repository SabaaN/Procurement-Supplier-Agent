"""Groq calls: one place for clients, structured answers, daily limits and the backup model.

Two Groq quirks are handled here:

1. Models sometimes name their answer "functions.CameraExtraction" instead of "CameraExtraction"
   (copying the OpenAI-style prefix). LangChain then rejects a perfectly good answer with
   "Unknown tool type". The raw answer is kept, the prefix stripped, and the arguments validated.

2. The free tier has a daily token allowance per model (e.g. 200,000 for gpt-oss-20b). When a
   model runs out, it is remembered as exhausted until Groq says it is back, and the call moves to
   GROQ_FALLBACK_MODEL, which has its own allowance. When every model is out, DailyLimitReached is
   raised once, so the caller can stop instead of failing page after page.
"""
import logging
import re
import time
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


def model_chain(primary: str) -> list[str]:
    """The primary model, then the backup if it is a different one."""
    backup = settings.groq_fallback_model
    return [primary] + ([backup] if backup and backup != primary else [])


def call(primary: str, schema: type[BaseModel], messages, client_for=None, temperature: float = 0.0):
    """A structured answer from the first model in the chain that still has daily allowance.

    client_for(model) builds the client (tests pass a fake). Raises DailyLimitReached when every
    model is out for the day; other errors are raised as they are."""
    client_for = client_for or (lambda model: chat(model, temperature))
    chain = model_chain(primary)
    for model in chain:
        if _exhausted.get(model, 0) > time.time():
            continue
        try:
            return structured_invoke(client_for(model), schema, messages)
        except Exception as e:
            limit = _limit(e)
            if not limit or limit[0] != "day":
                raise
            wait = limit[1] if limit[1] is not None else 600.0
            _exhausted[model] = time.time() + wait
            nxt = next((m for m in chain[chain.index(model) + 1:] if _exhausted.get(m, 0) <= time.time()), None)
            log.warning("Groq daily limit reached for %s (back in %s)%s", model, human_wait(wait),
                        f"; switching to {nxt}" if nxt else "")
    raise DailyLimitReached(min(_exhausted[m] for m in chain) - time.time())


def structured_invoke(llm, schema: type[BaseModel], messages):
    """llm.with_structured_output(schema).invoke(messages), tolerating a prefixed tool name.

    Raises the original parsing error (or a ValidationError) if the answer really is unusable."""
    out = llm.with_structured_output(schema, include_raw=True).invoke(messages)
    if not isinstance(out, dict):  # a client that ignores include_raw (e.g. a test fake)
        return out
    if out.get("parsed") is not None:
        return out["parsed"]

    raw = out.get("raw")
    for call_ in getattr(raw, "tool_calls", None) or []:
        name = str(call_.get("name") or "").rsplit(".", 1)[-1]  # "functions.CameraExtraction" -> "CameraExtraction"
        if name == schema.__name__:
            return schema.model_validate(call_.get("args") or {})
    raise out.get("parsing_error") or ValueError("The model returned no structured answer")


def reset_limits() -> None:
    """Forget which models are out for the day (tests)."""
    _exhausted.clear()
