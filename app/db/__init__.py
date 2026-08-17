"""Database abstraction layer.

Use `USE_POSTGRESQL=true` in the environment to switch from SQLite to PostgreSQL.
Default is SQLite (backward-compatible, zero-config).
"""

import os

USE_POSTGRESQL = os.getenv("USE_POSTGRESQL", "false").lower() == "true"

if USE_POSTGRESQL:
    from app.db.postgres import connect, apply_migrations, _now_iso, _iso_to_ts, _ts_to_iso
else:
    from app.db.sqlite import connect, apply_migrations, _now_iso, _iso_to_ts, _ts_to_iso

__all__ = [
    "USE_POSTGRESQL",
    "connect",
    "apply_migrations",
    "_now_iso",
    "_iso_to_ts",
    "_ts_to_iso",
]