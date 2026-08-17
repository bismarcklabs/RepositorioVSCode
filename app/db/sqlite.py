"""SQLite connection and migration helpers.

Extracted from the original app/database.py — same PRAGMAs, same behaviour.
"""

import calendar
import logging
from pathlib import Path
import sqlite3
import time
from typing import Iterable

from app.config import DATABASE_PATH

logger = logging.getLogger("database")

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "migrations" / "sqlite"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open (or create) the SQLite database with production-safe PRAGMAs."""
    path = Path(db_path or DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA wal_autocheckpoint=200;")
    conn.execute("PRAGMA cache_size=-32000;")
    return conn


def apply_migrations(
    conn: sqlite3.Connection, migrations: Iterable[Path] | None = None
) -> None:
    """Run all .sql files in migrations/sqlite/ (idempotent)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    files = list(migrations or sorted(MIGRATIONS_DIR.glob("*.sql")))
    for migration in files:
        version = migration.name
        exists = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        if exists:
            continue
        conn.executescript(migration.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
        )
    conn.commit()


# ── Timestamp helpers (kept here for backward compat) ──────────────────────

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _ts_to_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))


def _iso_to_ts(value: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        return time.time()