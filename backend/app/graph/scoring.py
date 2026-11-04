"""Match score from 0 to 100 in plain Python: reproducible and explainable, no LLM."""
from .checks import CAMERA_CHECKS

WEIGHTS = {"preferences": 50, "price": 30, "confidence": 20}
FLAG_PENALTY = 0.25  # each data-quality flag removes this share of the confidence component


def preference_share(criteria: dict, product: dict, checks=CAMERA_CHECKS) -> float | None:
    """Share of the buyer's preferred (nice-to-have) specs that the page verifiably meets.
    None when the buyer set no preferences."""
    labels = [
        label
        for name, (_spec, _compare, label) in checks.items()
        if (req := criteria.get(name)) and not req["required"]
    ]
    if not labels:
        return None
    met = set(product.get("requirements_met", []))
    return sum(1 for label in labels if label in met) / len(labels)


def score_products(criteria: dict, products: list[dict], checks=CAMERA_CHECKS) -> list[dict]:
    """Adds match_score and score_breakdown to each product. Price is scored relative to the others."""
    prices = [p["price_buyer"] for p in products if p.get("price_buyer") is not None]
    lo, hi = (min(prices), max(prices)) if prices else (0, 0)

    scored = []
    for p in products:
        parts = {"preferences": preference_share(criteria, p, checks)}
        price = p.get("price_buyer")
        if price is None:
            parts["price"] = 0.0
        elif hi == lo:
            parts["price"] = 1.0
        else:
            parts["price"] = 1 - (price - lo) / (hi - lo)  # cheapest = 1, most expensive = 0
        parts["confidence"] = max(0.0, 1 - FLAG_PENALTY * len(p.get("flags", [])))

        used = {k: v for k, v in parts.items() if v is not None}  # skip components that don't apply
        total_weight = sum(WEIGHTS[k] for k in used)
        score = 100 * sum(WEIGHTS[k] * v for k, v in used.items()) / total_weight
        scored.append({
            **p,
            "match_score": round(score, 1),
            "score_breakdown": {k: None if v is None else round(v, 2) for k, v in parts.items()},
        })
    return scored