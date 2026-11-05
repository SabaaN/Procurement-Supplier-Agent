"""SQLite storage for searches, their products and their progress events.

This is what the API reads from. Progress events are stored so a browser that connects late
(or reconnects) can replay them, instead of relying on in-memory state.
"""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import cache  # shares the same database file (and the tests' temp path)

_SCHEMAS = [
    """
    CREATE TABLE IF NOT EXISTS searches (
        id TEXT PRIMARY KEY,
        device_type TEXT NOT NULL,
        criteria TEXT NOT NULL,
        status TEXT NOT NULL,          -- queued | running | done | failed
        error TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        search_id TEXT NOT NULL,
        rank INTEGER NOT NULL,
        data TEXT NOT NULL,            -- the product as JSON
        shortlisted INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_products_search ON products (search_id)",
    """
    CREATE TABLE IF NOT EXISTS search_events (
        search_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        event TEXT NOT NULL,
        PRIMARY KEY (search_id, seq)
    )
    """,
]

_SELECT_SEARCH = """
    SELECT s.id, s.device_type, s.criteria, s.status, s.error, s.created_at, s.finished_at,
           (SELECT COUNT(*) FROM products p WHERE p.search_id = s.id)
    FROM searches s
"""


@contextmanager
def _connect():
    path = cache._db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        # WAL lets the API read while the background job writes
        conn.execute("PRAGMA journal_mode=WAL")
        for schema in _SCHEMAS:
            conn.execute(schema)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _search_dict(row) -> dict:
    return {
        "id": row[0], "device_type": row[1], "criteria": json.loads(row[2]), "status": row[3],
        "error": row[4], "created_at": row[5], "finished_at": row[6], "product_count": row[7],
    }


# ---- searches ----

def create_search(device_type: str, criteria: dict) -> str:
    search_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            "INSERT INTO searches (id, device_type, criteria, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
            (search_id, device_type, json.dumps(criteria), _now()),
        )
    return search_id


def set_status(search_id: str, status: str, error: str | None = None) -> None:
    finished = _now() if status in ("done", "failed") else None
    with _connect() as conn:
        conn.execute(
            "UPDATE searches SET status = ?, error = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, error, finished, search_id),
        )


def get_search(search_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(_SELECT_SEARCH + " WHERE s.id = ?", (search_id,)).fetchone()
    return _search_dict(row) if row else None


def list_searches(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(_SELECT_SEARCH + " ORDER BY s.created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_search_dict(r) for r in rows]


def fail_interrupted() -> int:
    """Mark searches left queued/running by a crash or restart as failed. Returns how many."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE searches SET status = 'failed', error = 'Interrupted by a server restart', finished_at = ? "
            "WHERE status IN ('queued', 'running')",
            (_now(),),
        )
        return cur.rowcount


# ---- progress events ----

def add_event(search_id: str, event: dict) -> int:
    with _connect() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM search_events WHERE search_id = ?", (search_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO search_events (search_id, seq, event) VALUES (?, ?, ?)",
            (search_id, seq, json.dumps(event)),
        )
    return seq


def get_events(search_id: str, after: int = 0) -> list[tuple[int, dict]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT seq, event FROM search_events WHERE search_id = ? AND seq > ? ORDER BY seq",
            (search_id, after),
        ).fetchall()
    return [(seq, json.loads(event)) for seq, event in rows]


# ---- products ----

def save_products(search_id: str, products: list[dict]) -> None:
    """Replace the search's products with this ranked list (rank = position, starting at 1)."""
    with _connect() as conn:
        conn.execute("DELETE FROM products WHERE search_id = ?", (search_id,))
        conn.executemany(
            "INSERT INTO products (search_id, rank, data) VALUES (?, ?, ?)",
            [(search_id, i + 1, json.dumps(p, default=str)) for i, p in enumerate(products)],
        )


def get_products(search_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, rank, data, shortlisted FROM products WHERE search_id = ? ORDER BY rank", (search_id,)
        ).fetchall()
    return [{**json.loads(data), "id": pid, "rank": rank, "shortlisted": bool(star)} for pid, rank, data, star in rows]


def set_shortlisted(search_id: str, product_id: int, shortlisted: bool) -> bool:
    """Star or unstar a product. False if it doesn't belong to this search."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE products SET shortlisted = ? WHERE id = ? AND search_id = ?",
            (int(shortlisted), product_id, search_id),
        )
        return cur.rowcount > 0