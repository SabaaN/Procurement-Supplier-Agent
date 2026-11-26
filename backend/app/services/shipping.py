"""Shipping / delivery time read from a page's raw HTML, in Python: no model call, no tokens.

Looks for a delivery phrase with a duration, e.g. "Delivery: 3-5 working days", "Ships in 2 weeks",
"Lead time 4-6 weeks", "Dispatched within 24 hours", "Same day delivery in Karachi". The phrase is kept
short and as written. Returns None when the page states no delivery time.

Not counted: return, refund, warranty and replacement periods ("7 days return policy").
Shipping times that a site works out in the browser (e.g. from your location) are not in the downloaded
page, so those stay empty.
"""
import re

from bs4 import BeautifulSoup

MAX_LEN = 90

_DURATION = (
    r"(?:\d+(?:\.\d+)?\s*(?:-|–|to|~)\s*)?\d+(?:\.\d+)?\s*\+?\s*"
    r"(?:working\s+|business\s+)?(?:days?|weeks?|wks?|hours?|hrs?|months?)\b"
    r"|same[\s-]day|next[\s-]day|overnight"
)
# (keyword pattern, weight): a product's own lead time beats a store-wide delivery promise
_KEYWORDS = [
    (r"lead[\s-]?time", 3),
    (r"ships?\s+(?:with)?in|ready\s+to\s+ship|dispatch(?:ed|es)?|ships?\s+out", 2),
    (r"estimated\s+delivery|delivery\s+time|delivery\s+(?:with)?in|delivered\s+(?:with)?in|delivery", 1),
    (r"shipping\s+time|shipping", 1),
]
_KEY = re.compile("|".join(f"(?:{k})" for k, _ in _KEYWORDS), re.I)
_DURATION_FIRST = re.compile(
    rf"(?:{_DURATION})\s+(?:[\w-]+\s+){{0,2}}?(?:delivery|shipping|dispatch)", re.I
)
_NOT_SHIPPING = re.compile(r"return|refund|warrant|replace|exchange|guarantee|trial|support|ago\b", re.I)


def _weight(text: str) -> int:
    return max((w for k, w in _KEYWORDS if re.search(k, text, re.I)), default=0)


def find(html: str) -> str | None:
    """The best delivery-time phrase on the page, as written, or None."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    lines = [" ".join(t.split()) for t in soup.get_text("\n").split("\n")]
    lines = [t for t in lines if t]

    best, best_score = None, 0
    for i, line in enumerate(lines):
        if not _KEY.search(line):
            continue
        # the duration is often in the next line: "Delivery time" / "3-5 working days"
        for text in (line, f"{line} {lines[i + 1]}" if i + 1 < len(lines) else None):
            if not text:
                continue
            key = _KEY.search(text)
            dur = re.search(_DURATION, text[key.start():], re.I)
            if not dur or dur.start() > 60:  # keyword and duration must be close together
                continue
            phrase = text[key.start(): key.start() + dur.end()]
            if _NOT_SHIPPING.search(phrase):
                continue
            phrase = phrase.strip(" :-–|")
            score = _weight(phrase) * 10 - len(phrase) / 100  # stronger keyword first, then the shorter phrase
            if len(phrase) <= MAX_LEN and score > best_score:
                best, best_score = phrase, score
            break
    for line in lines:  # the duration first: "Same day delivery", "2-3 days delivery"
        m = _DURATION_FIRST.search(line)
        if m and not _NOT_SHIPPING.search(m.group(0)):
            phrase = m.group(0).strip(" :-–|")
            score = _weight(phrase) * 10 - len(phrase) / 100
            if len(phrase) <= MAX_LEN and score > best_score:
                best, best_score = phrase, score
    return best[0].upper() + best[1:] if best else None
