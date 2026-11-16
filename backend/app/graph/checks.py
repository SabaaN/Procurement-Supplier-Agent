"""Requirement checks for camera products: pure Python, no LLM.

Each check returns True (met), False (missed) or None (the page had no data, so unknown).
"""
from typing import Callable

# criteria field -> (product spec field, how to compare wanted vs actual, label)
# Numeric minimums: actual >= wanted. Single values: actual == wanted.
# Lists: the wanted list is "any of these", so actual must be in it.
# For interface the product has a list, so any overlap counts.


def _min(wanted, actual):
    return None if actual is None else actual >= wanted


def _equals(wanted, actual):
    return None if actual is None else actual == wanted


def _one_of(wanted, actual):
    return None if actual is None else actual in wanted


def _any_overlap(wanted, actual):
    return None if not actual else bool(set(wanted) & set(actual))


CAMERA_CHECKS: dict[str, tuple[str, Callable, str]] = {
    "min_megapixels": ("megapixels", _min, "Resolution"),
    "min_fps": ("fps", _min, "Frame rate"),
    "shutter": ("shutter", _equals, "Shutter type"),
    "colour": ("colour", _equals, "Colour"),
    "scan_type": ("scan_type", _equals, "Scan type"),
    "sensor_format": ("sensor_format", _one_of, "Sensor format"),
    "interface": ("interface", _any_overlap, "Interface"),
    "lens_mount": ("lens_mount", _one_of, "Lens mount"),
    "min_bit_depth": ("bit_depth", _min, "Bit depth"),
    "hardware_trigger": ("hardware_trigger", _equals, "Hardware trigger"),
}


CAMERA_UNITS = {"min_megapixels": "MP", "min_fps": "fps", "min_bit_depth": "bit"}


def _show(value) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return " / ".join(map(str, value))
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
        wanted, actual = req["value"], product.get(spec_name)
        flexible, required = bool(req.get("flexible")), bool(req["required"]) and not req.get("flexible")
        result = compare(wanted, actual)
        unit = f" {units[crit_name]}" if crit_name in units else ""
        if result is True:
            met.append(label)
        elif result is None:  # not on the page
            unknown.append(label)
            if required and strict:
                dropped_for.append(f"{label}: not found on page")
        elif flexible and compare is _min:
            if actual >= wanted * (1 - tolerance):
                close.append(label)
                close_notes.append(f"{label}: {_show(actual)}{unit}, close to your {_show(wanted)}{unit}")
            else:
                missed.append(label)
                dropped_for.append(f"{label}: {_show(actual)}{unit}, too far below {_show(wanted)}{unit}")
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
