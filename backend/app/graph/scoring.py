"""Match score from 0 to 100 in plain Python: reproducible and explainable, no LLM."""
from ..devices.camera import CAMERA_CHECKS

WEIGHTS = {"preferences": 50, "price": 30, "confidence": 20}
FLAG_PENALTY = 0.25  # each data-quality flag removes this share of the confidence component


CLOSE_CREDIT = 0.5  # a flexible spec that is close counts half


def preference_share(criteria: dict, product: dict, checks=CAMERA_CHECKS) -> float | None:
    """Share of the buyer's flexible and nice-to-have specs that the page verifiably meets
    (a close flexible spec counts half). None when the buyer set none."""
    labels = [
        label
        for name, (_spec, _compare, label) in checks.items()
        if (req := criteria.get(name)) and (req.get("flexible") or not req.get("required"))
    ]
    if not labels:
        return None
    met = set(product.get("requirements_met", []))
    close = set(product.get("requirements_close", []))
    return sum(1 if label in met else CLOSE_CREDIT if label in close else 0 for label in labels) / len(labels)


def score_products(criteria: dict, products: list[dict], checks=CAMERA_CHECKS) -> list[dict]:
    """Adds match_score and score_breakdown to each product. Price is scored relative to the others.
    Prices under the buyer's minimum budget count as the minimum: cheaper than the floor earns nothing extra."""
    floor = criteria.get("budget_min") or 0

    def priced(p):
        return None if p.get("price_buyer") is None else max(p["price_buyer"], floor)

    prices = [priced(p) for p in products if priced(p) is not None]
    lo, hi = (min(prices), max(prices)) if prices else (0, 0)

    scored = []
    for p in products:
        parts = {"preferences": preference_share(criteria, p, checks)}
        price = priced(p)
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