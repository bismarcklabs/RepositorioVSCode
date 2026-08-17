"""Initialize the database (SQLite or PostgreSQL depending on USE_POSTGRESQL).

Usage:
    python scripts/init_db.py                         # SQLite (default)
    set USE_POSTGRESQL=true && python scripts/init_db.py  # PostgreSQL
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import USE_POSTGRESQL, connect, apply_migrations


def main() -> None:
    conn = connect()
    apply_migrations(conn)
    backend = "PostgreSQL" if USE_POSTGRESQL else "SQLite"
    print(f"Base de datos inicializada ({backend}).")


if __name__ == "__main__":
    main()