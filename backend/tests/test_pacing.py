"""Speed under Groq's free tier: per-minute pacing, both models in turn, parallel searches, short waits."""
import threading
import time

import pytest
from pydantic import BaseModel

from app.graph import nodes
from app.services import extractor, llm, web_search

from .test_extraction import TEXT, FakeLLM, good_extraction
from .test_quota import TPM, Answer, Client, RateLimited

real_extract_product = extractor.extract_product


@pytest.fixture
def paced(monkeypatch):
    """A 1,000 tokens-a-minute limit, a backup model, and sleeps that are recorded instead of slept.
    A recorded sleep empties the minute, as real waiting would."""
    monkeypatch.setattr(llm.PACER, "limit", 1000)
    monkeypatch.setattr(llm.settings.__class__, "groq_fallback_model", property(lambda s: "backup"))
    slept = []
    monkeypatch.setattr(llm, "_sleep", lambda s: (slept.append(s), llm.PACER.reset()))
    return slept


def test_a_model_has_room_until_its_minute_is_full(paced):
    llm.PACER.reserve("main", 800)
    now = time.time()
    assert llm.PACER.wait_for("main", 100, now) == 0  # 900 fits under 1,000 x 0.9
    assert llm.PACER.wait_for("main", 200, now) == pytest.approx(60, abs=1)  # waits for the 800 to age out
    assert llm.PACER.wait_for("main", 200, now + 30) == pytest.approx(30, abs=1)
    assert llm.PACER.wait_for("main", 200, now + 61) == 0
    assert llm.PACER.wait_for("other", 200, now) == 0  # each model has its own minute


def test_a_call_bigger_than_the_budget_still_goes_in_an_empty_minute(paced):
    assert llm.PACER.wait_for("main", 5000) == 0


def test_groqs_own_count_replaces_the_estimate(paced):
    entry = llm.PACER.reserve("main", 900)
    llm.PACER.settle(entry, 300)
    assert llm.PACER.wait_for("main", 500) == 0


def test_the_main_model_is_preferred_then_the_backup_then_the_soonest(paced):
    assert llm.PACER.pick(["main", "backup"], 100) == ("main", 0)
    llm.PACER.reserve("main", 850)
    assert llm.PACER.pick(["main", "backup"], 100) == ("backup", 0)
    llm.PACER.reserve("backup", 850)
    model, wait = llm.PACER.pick(["main", "backup"], 100)
    assert model == "main" and 55 < wait <= 60  # main's tokens leave the window first


def test_calls_move_to_the_backup_instead_of_waiting(paced):
    main, backup = Client(), Client()
    llm.PACER.reserve("main", 880)
    assert llm.call("main", Answer, [("human", "hi")], client_for={"main": main, "backup": backup}.get).ok
    assert (main.calls, backup.calls, paced) == (0, 1, [])


def test_without_spreading_the_call_waits_for_the_main_model(paced, monkeypatch):
    monkeypatch.setattr(llm.settings.__class__, "groq_spread_models", property(lambda s: False))
    main, backup = Client(), Client()
    llm.PACER.reserve("main", 880)
    llm.call("main", Answer, [("human", "hi")], client_for={"main": main, "backup": backup}.get)
    assert (main.calls, backup.calls) == (1, 0) and len(paced) == 1 and paced[0] > 50


def test_a_per_minute_error_rests_that_model_and_the_other_answers(paced, monkeypatch):
    monkeypatch.setattr(llm.PACER, "limit", 100_000)  # room for several calls: only Groq's error rests a model
    main, backup = Client(RateLimited(TPM)), Client()
    clients = {"main": main, "backup": backup}
    assert llm.call("main", Answer, [], client_for=clients.get).ok
    assert llm.PACER.wait_for("main", 1) == pytest.approx(6.5, abs=1)  # Groq said "try again in 6.5s"
    llm.call("main", Answer, [], client_for=clients.get)
    assert (main.calls, backup.calls) == (1, 2)  # main is resting: not asked again yet
    assert "main" not in llm._exhausted


def test_per_minute_errors_everywhere_give_up_after_a_few_tries(paced):
    client = Client(RateLimited(TPM))
    with pytest.raises(RateLimited):
        llm.call("main", Answer, [], client_for=lambda m: client)
    assert client.calls == llm.MAX_MINUTE_RETRIES + 1


def test_the_estimate_counts_the_prompt_and_the_schema():
    class Small(BaseModel):
        x: int

    est = llm.estimate_tokens([("system", "a" * 4000), ("human", "b" * 4000)], Small)
    assert 2000 + llm.ANSWER_ALLOWANCE < est < 2100 + llm.ANSWER_ALLOWANCE


def test_usage_is_read_from_groqs_answer():
    class Raw:
        usage_metadata = {"input_tokens": 2000, "output_tokens": 300, "total_tokens": 2300}

    class Groq:
        def with_structured_output(self, schema, include_raw=False):
            return self

        def invoke(self, messages):
            return {"parsed": Answer(ok=True), "raw": Raw(), "parsing_error": None}

    usage = {}
    assert llm.structured_invoke(Groq(), Answer, [], usage).ok and usage["total_tokens"] == 2300


def test_a_bad_answer_is_retried_without_waiting(monkeypatch):
    fake = FakeLLM([ValueError("bad tool output"), good_extraction()])
    monkeypatch.setattr(extractor, "_llm", lambda *a: fake)
    monkeypatch.setattr(extractor.time, "sleep", lambda s: pytest.fail("should not wait"))
    assert real_extract_product("camera", "https://a.test/p", "", TEXT)["title"] == "Acme AC-500"


def test_queries_are_searched_at_the_same_time_and_merged_in_order(monkeypatch):
    running, peak, lock = [0], [0], threading.Lock()

    def slow_search(query, max_results=None, country=None):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.2)
        with lock:
            running[0] -= 1
        if query == "q2":
            raise web_search.SearchError("quota")
        return [{"url": f"https://s.test/{query}", "title": query, "snippet": "", "score": 1.0}]

    monkeypatch.setattr(web_search, "search_web", slow_search)
    start = time.time()
    out = nodes.search({"queries": ["q1", "q2", "q3", "q4"], "criteria": {}})
    assert time.time() - start < 0.6 and peak[0] == 4
    assert out["urls"] == ["https://s.test/q1", "https://s.test/q3", "https://s.test/q4"]  # q2 failed alone
    assert "error" not in out
