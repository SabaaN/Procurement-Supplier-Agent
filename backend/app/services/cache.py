"""SQLite cache: a URL is never fetched or extracted twice within the TTL."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import settings

_SCHEMAS = [
    """
    CREATE TABLE IF NOT EXISTS page_cache (
        url TEXT PRIMARY KEY,
        ok INTEGER NOT NULL,
        text TEXT,
        error TEXT,
        fetched_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS extraction_cache (
        url TEXT NOT NULL,
        device_type TEXT NOT NULL,
        product TEXT,            -- JSON, or NULL when the page is not a product page
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (url, device_type)
    )
    """,
        """
    CREATE TABLE IF NOT EXISTS fx_cache (
        base TEXT PRIMARY KEY,
        rates TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )
    """,
]


def _db_path() -> Path:  # a function so tests can point it at a temp file
    return settings.db_path


@contextmanager
def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        for schema in _SCHEMAS:
            conn.execute(schema)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _fresh(fetched_at: str, max_age_hours: float | None) -> bool:
    max_age = settings.cache_ttl_hours if max_age_hours is None else max_age_hours
    return datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at) <= timedelta(hours=max_age)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- fetched pages ----

def get_page(url: str, max_age_hours: float | None = None) -> dict | None:
    """Cached fetch result, or None if missing or older than the TTL."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT ok, text, error, fetched_at FROM page_cache WHERE url = ?", (url,)
        ).fetchone()
    if row is None or not _fresh(row[3], max_age_hours):
        return None
    ok, text, error, _ = row
    return {"url": url, "ok": bool(ok), "text": text or "", "error": error}


def put_page(url: str, ok: bool, text: str, error: str | None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO page_cache (url, ok, text, error, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (url, int(ok), text, error, _now()),
        )


# ---- extraction results ----

def get_extraction(url: str, device_type: str, max_age_hours: float | None = None) -> dict | None:
    """{'product': dict | None} if this page was extracted before (None product = not a product page),
    or None if it was never extracted or the entry is stale."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT product, fetched_at FROM extraction_cache WHERE url = ? AND device_type = ?",
            (url, device_type),
        ).fetchone()
    if row is None or not _fresh(row[1], max_age_hours):
        return None
    return {"product": json.loads(row[0]) if row[0] else None}


def put_extraction(url: str, device_type: str, product: dict | None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO extraction_cache (url, device_type, product, fetched_at) VALUES (?, ?, ?, ?)",
            (url, device_type, json.dumps(product) if product is not None else None, _now()),
        )

# ---- exchange rates ----

def get_fx(base: str = "USD", max_age_hours: float | None = None) -> dict | None:
    """Cached rates relative to `base`, or None if missing or older than max_age_hours."""
    with _connect() as conn:
        row = conn.execute("SELECT rates, fetched_at FROM fx_cache WHERE base = ?", (base,)).fetchone()
    if row is None or not _fresh(row[1], max_age_hours):
        return None
    return json.loads(row[0])


def put_fx(rates: dict, base: str = "USD") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fx_cache (base, rates, fetched_at) VALUES (?, ?, ?)",
            (base, json.dumps(rates), _now()),
        )