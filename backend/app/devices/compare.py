"""How a wanted value is compared with what a product page states. Pure Python, no LLM.

Each comparison returns True (met), False (missed) or None (the page had no data, so unknown).
A device lists its checks as: criteria field -> (product spec field, comparison, label).
The spec field may be a tuple of fields (e.g. a supply-voltage range); it is then passed as a tuple,
and is unknown if any part is missing.
"""


def at_least(wanted, actual):
    """Numeric minimum: actual >= wanted."""
    return None if actual is None else actual >= wanted


def at_most(wanted, actual):
    """Numeric maximum: actual <= wanted (e.g. housing diameter that must fit a space)."""
    return None if actual is None else actual <= wanted


def equals(wanted, actual):
    return None if actual is None else actual == wanted


def same_number(wanted, actual):
    """Exact size, allowing for rounding (6 vs 6.0 mm)."""
    return None if actual is None else abs(actual - wanted) < 0.01


def one_of(wanted, actual):
    """The wanted list is "any of these"."""
    return None if actual is None else actual in wanted


def any_overlap(wanted, actual):
    """Both are lists (e.g. interfaces): any value in common counts."""
    return None if not actual else bool(set(wanted) & set(actual))


def within_range(wanted, actual):
    """actual is (low, high): wanted must fall inside it (e.g. your 24 V supply in a 10-30 V range)."""
    if actual is None or any(v is None for v in actual):
        return None
    low, high = actual
    return low <= wanted <= high


def contains(wanted, actual):
    """actual is a list of what the product supports (e.g. light-on and dark-on, selectable):
    the single wanted value must be in it."""
    return None if not actual else wanted in actual


def all_of(wanted, actual):
    """Both are lists (e.g. communication ports): the product must have every wanted value."""
    return None if not actual else set(wanted) <= set(actual)
