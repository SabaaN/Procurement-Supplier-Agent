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


def check_product(criteria: dict, product: dict, checks=CAMERA_CHECKS) -> dict:
    """Compare one product against the buyer's requirements.

    Returns the verdict lists plus 'dropped_for' (the reasons a required spec failed).
    """
    met, missed, unknown, dropped_for = [], [], [], []
    for crit_name, (spec_name, compare, label) in checks.items():
        req = criteria.get(crit_name)
        if req is None:
            continue  # buyer didn't ask for this
        result = compare(req["value"], product.get(spec_name))
        if result is True:
            met.append(label)
        elif result is False:
            missed.append(label)
            if req["required"]:
                dropped_for.append(f"{label}: does not meet requirement")
        else:  # None -> not on the page
            unknown.append(label)
            if req["required"]:
                dropped_for.append(f"{label}: not found on page")
    return {"met": met, "missed": missed, "unknown": unknown, "dropped_for": dropped_for}