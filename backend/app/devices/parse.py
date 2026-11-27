"""Small, shared helpers for turning the model's loose text into exact values. Pure Python.

The model copies what a page says ("2 m", "≤ 500 μs", "IP67 / IP65", "NPN/PNP switchable");
these helpers do the matching and the unit arithmetic, so the model never converts anything.
"""
import re


def pick(value, rules):
    """The first canonical value whose words appear in the text (rules are ordered), else None."""
    s = (value or "").lower()
    return next((canon for needles, canon in rules if any(n in s for n in needles)), None)


def pick_all(items, patterns) -> list:
    """Every canonical value whose regex matches any of the texts, in rule order, no duplicates."""
    found = []
    for item in items if isinstance(items, list) else [items]:
        s = str(item or "").lower()
        for pattern, canon in patterns:
            if re.search(pattern, s) and canon not in found:
                found.append(canon)
    return found


def number(value, low, high):
    """value if it is a real number in (low, high], else None."""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low < value <= high
    return value if ok else None


def ip_rating(value) -> int | None:
    """'IP67 / IP65' -> 67 (the first rating written)."""
    m = re.search(r"ip\s*-?\s*(\d)\s*(\d)", (value or "").lower())
    return int(m.group(1) + m.group(2)) if m else None


_NUM = r"(\d+(?:[.,]\d+)?)"


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def length_mm(value) -> float | None:
    """The largest distance written, in mm: '0.1–2 m' -> 2000, '300mm' -> 300, '20 cm' -> 200.
    A bare number with no unit is not guessed."""
    s = str(value or "").lower().replace("~", "-").replace("–", "-")
    best = None
    # "0.1-2 m": the unit after a range applies to both ends
    for m in re.finditer(rf"{_NUM}\s*(?:-\s*{_NUM}\s*)?(mm|cm|m)\b", s):
        scale = {"mm": 1, "cm": 10, "m": 1000}[m.group(3)]
        for part in (m.group(1), m.group(2)):
            if part:
                mm = _to_float(part) * scale
                best = mm if best is None else max(best, mm)
    return best if best and 0 < best <= 1_000_000 else None


def time_ms(value) -> float | None:
    """The longest time written, in ms: '≤ 1 ms' -> 1, '500 μs' -> 0.5, '0.5ms max' -> 0.5."""
    s = str(value or "").lower().replace("µ", "μ")
    best = None
    for m in re.finditer(rf"{_NUM}\s*(ms|μs|us|s)\b", s):
        scale = {"ms": 1, "μs": 0.001, "us": 0.001, "s": 1000}[m.group(2)]
        ms = _to_float(m.group(1)) * scale
        best = ms if best is None else max(best, ms)
    return best if best and 0 < best <= 60_000 else None


def voltage_range(low, high) -> tuple[float | None, float | None]:
    """A tidy (min, max) supply range in volts: swapped if reversed, None if out of range."""
    lo, hi = number(low, 0, 400), number(high, 0, 400)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def frequency_khz(value) -> float | None:
    """The highest frequency written, in kHz: '6 x 100 kHz' -> 100, '1 MHz' -> 1000, '60kHz (2 ch)' -> 60."""
    s = str(value or "").lower()
    best = None
    for m in re.finditer(rf"{_NUM}\s*(mhz|khz|hz)\b", s):
        khz = _to_float(m.group(1)) * {"mhz": 1000, "khz": 1, "hz": 0.001}[m.group(2)]
        best = khz if best is None else max(best, khz)
    return best if best and 0 < best <= 100_000 else None


def code_size_mil(value) -> float | None:
    """The finest (smallest) code size written, in mil: '≥3 mil (1D), 5 mil (2D)' -> 3, '4mil' -> 4."""
    sizes = [_to_float(m.group(1)) for m in re.finditer(rf"{_NUM}\s*mils?\b", str(value or "").lower())]
    sizes = [s for s in sizes if 0 < s <= 100]
    return min(sizes) if sizes else None
