"""Fetches a product page and cleans it to plain text.

fetch_page never raises: every failure comes back as FetchResult(ok=False, error=...),
so one bad site can't break a search.
"""
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ..config import settings

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    ok: bool
    text: str = ""
    error: str | None = None


_client: httpx.Client | None = None
_client_lock = threading.Lock()
_ROBOTS: dict[str, RobotFileParser | None] = {}  # one robots.txt per site, per run

_NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "form", "svg", "iframe"]

def _spec_rows(html: str) -> list[list[str]]:
    """Table rows and definition lists as [label, value, ...] cells.

    trafilatura often drops spec tables as boilerplate, but this is where the specs live.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        # very long "cells" are layout tables wrapping the whole page, not spec values
        if len(cells) >= 2 and all(len(c) <= 200 for c in cells):
            rows.append(cells)
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd and dt.get_text(strip=True) and dd.get_text(strip=True):
                rows.append([dt.get_text(" ", strip=True), dd.get_text(" ", strip=True)])
    return rows

def _get_client() -> httpx.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                timeout=settings.fetch_timeout,
                follow_redirects=True,
                headers={"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml"},
            )
        return _client


def _bs4_text(html: str) -> str:
    """Fallback cleaner: drop obvious noise, keep all other text (including table cells)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)

@lru_cache(maxsize=1)
def _trafilatura():
    """Import trafilatura on first use. If it is broken, warn once and return None."""
    try:
        import trafilatura

        return trafilatura
    except Exception as e:
        log.warning("trafilatura unavailable (%s: %s); using the BeautifulSoup fallback only", type(e).__name__, e)
        return None

def clean_html(html: str) -> str:
    """HTML -> plain text. trafilatura for the main content, plus spec tables it dropped."""
    limit = settings.max_page_chars
    text = None
    lib = _trafilatura()
    if lib is not None:
        try:
            text = lib.extract(html, include_tables=True, include_comments=False, favor_recall=True)
        except Exception:
            text = None

    if not text or len(text) < settings.min_page_chars:
        return _bs4_text(html)[:limit]  # keeps everything, including table cells

    # Add back table rows and definition lists that trafilatura left out.
    missing = [" | ".join(cells) for cells in _spec_rows(html) if not all(c in text for c in cells)]
    tables = "\n".join(missing)[: int(limit * 0.4)]
    if not tables:
        return text[:limit]
    header = "\n\nSpecification tables:\n"
    room = max(limit - len(tables) - len(header), 0)
    return (text[:room] + header + tables)[:limit]


def _robots_allowed(url: str, client: httpx.Client) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _ROBOTS:
        parser = None
        try:
            resp = client.get(f"{origin}/robots.txt")
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
        except httpx.HTTPError:
            pass  # can't read robots.txt -> treat as allowed
        _ROBOTS[origin] = parser
    parser = _ROBOTS[origin]
    return True if parser is None else parser.can_fetch(settings.user_agent, url)


def fetch_page(url: str, client: httpx.Client | None = None) -> FetchResult:
    client = client or _get_client()
    try:
        if settings.respect_robots and not _robots_allowed(url, client):
            return FetchResult(url, False, error="blocked by robots.txt")

        with client.stream("GET", url) as resp:
            if resp.status_code != 200:
                return FetchResult(url, False, error=f"HTTP {resp.status_code}")
            ctype = resp.headers.get("content-type", "").lower()
            if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
                return FetchResult(url, False, error="PDF (not supported yet)")
            if ctype and "html" not in ctype and "text" not in ctype:
                return FetchResult(url, False, error=f"unsupported content type: {ctype.split(';')[0]}")
            raw = bytearray()
            for chunk in resp.iter_bytes():
                raw.extend(chunk)
                if len(raw) >= settings.max_page_bytes:
                    break
            encoding = resp.encoding or "utf-8"

        text = clean_html(raw.decode(encoding, errors="replace"))
        if len(text) < settings.min_page_chars:
            return FetchResult(url, False, error="too little text (page may need JavaScript)")
        return FetchResult(url, True, text=text)
    except httpx.TimeoutException:
        return FetchResult(url, False, error="timeout")
    except Exception as e:  # network errors, bad encodings, parser errors...
        return FetchResult(url, False, error=f"{type(e).__name__}: {e}")