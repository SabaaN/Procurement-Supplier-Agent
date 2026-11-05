import dataclasses

from app.graph import nodes
from app.services import explainer

CRIT = {"currency": "PKR", "quantity": 4}


def ranked_products():
    return [
        {"title": "Acme AC-500", "supplier": "Acme", "price": 1299.0, "currency": "USD",
         "price_buyer": 363720.0, "fx_rate": 280.0, "total_cost": 1454880.0, "match_score": 85.0,
         "requirements_met": ["Resolution", "Shutter type"], "requirements_missed": ["Frame rate"],
         "flags": [], "megapixels": 5.0, "fps": 20.0, "shutter": "global", "interface": ["GigE"],
         "score_breakdown": {"preferences": 0.5, "price": 0.0, "confidence": 1.0}},
        {"title": "Beta B-200", "supplier": "Beta", "price": 90000.0, "currency": "PKR",
         "price_buyer": 90000.0, "total_cost": 360000.0, "match_score": 60.0,
         "requirements_met": ["Resolution"], "requirements_missed": [],
         "flags": ["Shutter type: not found on page"], "megapixels": 5.0,
         "score_breakdown": {"preferences": 0.0, "price": 1.0, "confidence": 0.75}},
    ]


# ---- facts and template ----

def test_facts_include_specs_money_and_quantity():
    p = ranked_products()[0]
    facts = explainer.facts_for("camera", p, 1, 2, CRIT)
    assert facts["specs"]["megapixels"] == 5.0 and facts["specs"]["interface"] == ["GigE"]
    assert facts["price_on_page"] == "1,299.00 USD"
    assert facts["total_for_quantity"] == "1,454,880 PKR"
    assert facts["quantity"] == 4 and "supplier" in facts


def test_template_mentions_rank_matches_misses_total_and_issues():
    p = ranked_products()[1]
    text = explainer.template_explanation(p, 2, 2, CRIT)
    assert "#2 of 2" in text and "60/100" in text
    assert "Meets: Resolution" in text and "360,000 PKR" in text and "Shutter type: not found" in text


def test_number_extraction():
    assert explainer._numbers("Costs 1,454,880 PKR, 5.0 MP, #1.") == {1454880.0, 5.0, 1.0}


# ---- explain() ----

def test_llm_text_is_used_when_every_number_is_in_the_facts(monkeypatch):
    monkeypatch.setattr(explainer, "_llm_explanations", lambda facts: {
        1: "Best match: 5 MP, global shutter, 1,454,880 PKR for 4 units.",
        2: "Second at 60 of 100: cheaper, but check the shutter type.",
    })
    texts, source = explainer.explain("camera", CRIT, ranked_products())
    assert source == "llm" and texts[0].startswith("Best match")


def test_explanation_with_an_invented_number_is_replaced_by_the_template(monkeypatch):
    monkeypatch.setattr(explainer, "_llm_explanations", lambda facts: {
        1: "A 12 MP camera with great value.",  # 12 is not in the facts
        2: "Second at 60 of 100: cheaper, but check the shutter type.",
    })
    texts, source = explainer.explain("camera", CRIT, ranked_products())
    assert texts[0].startswith("Ranked #1 of 2")  # template
    assert texts[1].startswith("Second at 60")  # accepted
    assert source == "llm: 1/2 accepted, rest templates"


def test_missing_rank_from_the_model_uses_the_template(monkeypatch):
    monkeypatch.setattr(explainer, "_llm_explanations", lambda facts: {1: "Best match at 85 of 100."})
    texts, _ = explainer.explain("camera", CRIT, ranked_products())
    assert texts[0].startswith("Best match") and texts[1].startswith("Ranked #2 of 2")


def test_llm_failure_falls_back_to_templates():
    # conftest makes the LLM raise
    texts, source = explainer.explain("camera", CRIT, ranked_products())
    assert source.startswith("templates") and len(texts) == 2 and all(texts)


def test_only_the_top_n_are_sent_to_the_model(monkeypatch):
    monkeypatch.setattr(explainer, "settings", dataclasses.replace(explainer.settings, explain_top_n=1))
    sent = []
    monkeypatch.setattr(explainer, "_llm_explanations", lambda facts: sent.append(len(facts)) or {1: "Best at 85 of 100."})
    texts, _ = explainer.explain("camera", CRIT, ranked_products())
    assert sent == [1] and len(texts) == 2 and texts[1].startswith("Ranked #2")


def test_nothing_to_explain_makes_no_model_call():
    assert explainer.explain("camera", CRIT, []) == ([], "llm")


# ---- finalize ----

def test_finalize_attaches_an_explanation_to_every_product():
    state = {"device_type": "camera", "criteria": CRIT, "candidates": ranked_products()}
    ranked = nodes.finalize(state)["ranked"]
    assert [p["title"] for p in ranked] == ["Acme AC-500", "Beta B-200"]
    assert all(p["explanation"] for p in ranked)