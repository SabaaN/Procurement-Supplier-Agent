"""Groq's daily limit: switch to the backup model, then stop cleanly; low reasoning effort for gpt-oss."""
import time

import pytest
from pydantic import BaseModel

from app.graph import nodes
from app.services import cache, extractor, llm, page_fetcher
from app.services.llm import DailyLimitReached
from .conftest import PRODUCT_TEXT

# Groq's own wording, from a real run
TPD = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-20b` in organization "
       "`org_x` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 198410, Requested 1835. "
       "Please try again in 1m45.84s. Need more tokens?', 'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
TPM = ("Error code: 429 - Rate limit reached for model `openai/gpt-oss-20b` on tokens per minute (TPM): "
       "Limit 8000, Used 7900, Requested 900. Please try again in 6.5s.")

real_extract_page = extractor.extract_page


class RateLimited(Exception):
    status_code = 429


class Answer(BaseModel):
    ok: bool


class Client:
    """Fake model: raises the queued error, or answers."""

    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def with_structured_output(self, schema, **kw):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.error:
            raise self.error
        return Answer(ok=True)


@pytest.fixture
def two_models(monkeypatch):
    monkeypatch.setattr(llm.settings.__class__, "groq_fallback_model", property(lambda s: "backup"))


def test_wait_times_and_limit_kinds_are_read_from_the_message():
    assert llm._seconds("Please try again in 1m45.84s.") == pytest.approx(105.84)
    assert llm._seconds("try again in 2h3m") == 7380
    assert llm._limit(RateLimited(TPD)) == ("day", pytest.approx(105.84))
    assert llm._limit(RateLimited(TPM))[0] == "minute"
    assert llm._limit(ValueError("bad tool output")) is None
    assert llm.per_minute_wait(RateLimited(TPM)) == pytest.approx(6.5)
    assert llm.per_minute_wait(RateLimited(TPD)) is None


def test_daily_limit_switches_to_the_backup_and_remembers(two_models):
    main, backup = Client(RateLimited(TPD)), Client()
    clients = {"main": main, "backup": backup}
    assert llm.call("main", Answer, [], client_for=clients.get).ok
    assert (main.calls, backup.calls) == (1, 1)
    llm.call("main", Answer, [], client_for=clients.get)
    assert main.calls == 1  # known to be out: not asked again until it is back


def test_all_models_out_raises_once_with_the_wait(two_models):
    clients = {"main": Client(RateLimited(TPD)), "backup": Client(RateLimited(TPD))}
    with pytest.raises(DailyLimitReached) as e:
        llm.call("main", Answer, [], client_for=clients.get)
    assert 100 < e.value.retry_after <= 106 and "about 2 minutes" in str(e.value)
    with pytest.raises(DailyLimitReached):  # no calls at all now
        llm.call("main", Answer, [], client_for=lambda m: pytest.fail("should not call"))


def test_a_model_comes_back_when_its_wait_is_over(two_models):
    llm._exhausted["main"] = time.time() - 1
    main = Client()
    llm.call("main", Answer, [], client_for={"main": main, "backup": Client()}.get)
    assert main.calls == 1


def test_per_minute_limits_and_other_errors_are_not_treated_as_daily(two_models):
    main, backup = Client(RateLimited(TPM)), Client()
    assert llm.call("main", Answer, [], client_for={"main": main, "backup": backup}.get).ok  # the backup answers
    assert "main" not in llm._exhausted and backup.calls == 1
    with pytest.raises(ValueError):  # anything else is raised as it is
        llm.call("main", Answer, [], client_for=lambda m: Client(ValueError("bad tool output")))


def test_no_backup_when_turned_off(monkeypatch):
    monkeypatch.setattr(llm.settings.__class__, "groq_fallback_model", property(lambda s: ""))
    assert llm.model_chain("openai/gpt-oss-20b") == ["openai/gpt-oss-20b"]
    with pytest.raises(DailyLimitReached):
        llm.call("m", Answer, [], client_for=lambda m: Client(RateLimited(TPD)))


def test_reasoning_effort_only_for_gpt_oss(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    llm.chat.cache_clear()
    assert llm.chat("openai/gpt-oss-20b").reasoning_effort == "low"
    assert llm.chat("qwen/qwen3.6-27b").reasoning_effort is None
    llm.chat.cache_clear()


def test_extraction_does_not_retry_a_daily_limit(monkeypatch, two_models):
    monkeypatch.setattr(llm.settings.__class__, "groq_api_key", property(lambda s: "k"))
    client = Client(RateLimited(TPD))
    monkeypatch.setattr(extractor, "_llm", lambda *a: client)
    monkeypatch.setattr(extractor.time, "sleep", lambda s: pytest.fail("should not wait"))
    with pytest.raises(DailyLimitReached):
        real_extract_page("camera", "https://s.test/p", "", "page")
    assert client.calls == 2  # once on the main model, once on the backup: then stop


def test_pipeline_stops_reading_and_keeps_what_it_has(monkeypatch):
    urls = [f"https://s.test/{i}" for i in range(5)]
    cache.put_extraction(urls[4], extractor.cache_key("camera"),
                         {"title": "seen before", "source_url": urls[4]}, "product")
    calls = []

    def page(device_key, url, title, text):
        calls.append(url)
        if len(calls) > 2:
            raise DailyLimitReached(3600)
        return "product", {"title": url, "source_url": url}

    monkeypatch.setattr(page_fetcher, "fetch_page",
                        lambda url, client=None: page_fetcher.FetchResult(url, True, text=PRODUCT_TEXT))
    monkeypatch.setattr(extractor, "extract_page", page)
    state = {"device_type": "camera", "urls": urls, "hits": []}
    state.update(nodes.fetch_clean(state))
    out = nodes.extract(state)
    assert [p["title"] for p in out["products"]] == [urls[0], urls[1], "seen before"]  # cached page still read
    assert len(calls) == 3  # one failed call, then no more model calls
    assert "daily token limit" in out["llm_limited"]
    state.update(out, candidates=[], attempts=1)
    assert nodes.route_after_filter(state) == "score"  # no widening: it couldn't be read either


def test_pipeline_reports_the_limit_when_nothing_could_be_read(monkeypatch):
    def page(*a):
        raise DailyLimitReached(1800)

    monkeypatch.setattr(extractor, "extract_page", page)
    out = nodes.extract({"device_type": "camera", "pages": [
        {"url": "https://s.test/a", "ok": True, "text": PRODUCT_TEXT}], "urls": []})
    assert out["products"] == [] and out["error"] == "Groq daily token limit reached; try again in about 30 minutes"
