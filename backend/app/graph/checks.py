"""Requirement checks: pure Python, no LLM. Each device lists its own checks (DeviceDefinition.checks);
the comparisons themselves live in devices/compare.py."""
from ..devices.camera import CAMERA_CHECKS, CAMERA_UNITS  # noqa: F401  (the default device, kept importable)
from ..devices.compare import any_overlap, at_least, at_most, equals, one_of  # noqa: F401

# the old private names, still used by older code and tests
_min, _equals, _one_of, _any_overlap = at_least, equals, one_of, any_overlap


def _show(value) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return " / ".join(map(str, value))
    if isinstance(value, tuple):  # a range
        return "–".join(_show(v) for v in value)
    return str(value)


def check_product(
    criteria: dict,
    product: dict,
    checks=CAMERA_CHECKS,
    strict: bool = False,
    tolerance: float = 0.2,
    units: dict = CAMERA_UNITS,
) -> dict:
    """Compare one product against the buyer's requirements.

    Returns lists of labels: met, missed, close (flexible specs that are near enough, or a
    compromise the buyer allowed), unknown; plus close_notes (readable lines for the close ones)
    and dropped_for (the reasons the product must go).

    must-have  fails -> dropped. Not on the page -> unknown (dropped only when strict).
    flexible   a number up to `tolerance` short -> close; further off -> dropped.
               another kind of value that differs -> close (a compromise the buyer allowed).
    nice       fails -> missed (ranked lower).
    """
    met, missed, close, close_notes, unknown, dropped_for = [], [], [], [], [], []
    for crit_name, (spec_name, compare, label) in checks.items():
        req = criteria.get(crit_name)
        if req is None:
            continue  # buyer didn't ask for this
        wanted = req["value"]
        if isinstance(spec_name, tuple):  # e.g. a supply-voltage range: (low, high)
            actual = tuple(product.get(n) for n in spec_name)
            actual = None if any(v is None for v in actual) else actual
        else:
            actual = product.get(spec_name)
        flexible, required = bool(req.get("flexible")), bool(req.get("required")) and not req.get("flexible")
        result = compare(wanted, actual)
        unit = f" {units[crit_name]}" if crit_name in units else ""
        if result is True:
            met.append(label)
        elif result is None:  # not on the page
            unknown.append(label)
            if required and strict:
                dropped_for.append(f"{label}: not found on page")
        elif flexible and compare in (at_least, at_most):
            near = actual >= wanted * (1 - tolerance) if compare is at_least else actual <= wanted * (1 + tolerance)
            if near:
                close.append(label)
                close_notes.append(f"{label}: {_show(actual)}{unit}, close to your {_show(wanted)}{unit}")
            else:
                side = "below" if compare is at_least else "above"
                missed.append(label)
                dropped_for.append(f"{label}: {_show(actual)}{unit}, too far {side} {_show(wanted)}{unit}")
        elif flexible:
            close.append(label)
            close_notes.append(f"{label}: {_show(actual)} instead of {_show(wanted)}")
        else:
            missed.append(label)
            if required:
                dropped_for.append(f"{label}: does not meet requirement")
    return {
        "met": met, "missed": missed, "close": close, "close_notes": close_notes,
        "unknown": unknown, "dropped_for": dropped_for,
    }
