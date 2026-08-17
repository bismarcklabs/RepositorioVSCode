"""PostgreSQL connection and migration helpers.

Requires psycopg2-binary and the PG_* environment variables set in .env.
"""

import calendar
import logging
from pathlib import Path
import time
from typing import Iterable

import psycopg2
import psycopg2.extensions
from psycopg2.extras import RealDictCursor

from app.config import PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD

logger = logging.getLogger("database")

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "migrations" / "postgres"


def connect(
    host: str | None = None,
    port: int | None = None,
    dbname: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> psycopg2.extensions.connection:
    """Create a new PostgreSQL connection."""
    conn = psycopg2.connect(
        host=host or PG_HOST,
        port=port or PG_PORT,
        dbname=dbname or PG_DB,
        user=user or PG_USER,
        password=password or PG_PASSWORD,
        cursor_factory=RealDictCursor,
    )
    conn.autocommit = False
    return conn


def apply_migrations(
    conn: psycopg2.extensions.connection,
    migrations: Iterable[Path] | None = None,
) -> None:
    """Run all .sql files in migrations/postgres/ (idempotent)."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.commit()

    files = list(migrations or sorted(MIGRATIONS_DIR.glob("*.sql")))
    for migration in files:
        version = migration.name
        cur.execute(
            "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
        )
        if cur.fetchone():
            continue
        cur.execute(migration.read_text(encoding="utf-8"))
        cur.execute(
            "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
        )
        conn.commit()


# ── Timestamp helpers ──────────────────────────────────────────────────────

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _ts_to_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))


def _iso_to_ts(value: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        return time.time()