"""SQLite cache: a URL is never fetched twice within the TTL. Extraction results join it later."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY,
    ok INTEGER NOT NULL,
    text TEXT,
    error TEXT,
    fetched_at TEXT NOT NULL
)
"""


def _db_path() -> Path:  # a function so tests can point it at a temp file
    return settings.db_path


@contextmanager
def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_page(url: str, max_age_hours: float | None = None) -> dict | None:
    """Cached fetch result, or None if missing or older than the TTL."""
    max_age = settings.cache_ttl_hours if max_age_hours is None else max_age_hours
    with _connect() as conn:
        row = conn.execute(
            "SELECT ok, text, error, fetched_at FROM page_cache WHERE url = ?", (url,)
        ).fetchone()
    if row is None:
        return None
    ok, text, error, fetched_at = row
    if datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at) > timedelta(hours=max_age):
        return None
    return {"url": url, "ok": bool(ok), "text": text or "", "error": error}


def put_page(url: str, ok: bool, text: str, error: str | None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO page_cache (url, ok, text, error, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (url, int(ok), text, error, datetime.now(timezone.utc).isoformat()),
        )