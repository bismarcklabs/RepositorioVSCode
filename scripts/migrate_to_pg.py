"""
migrate_to_pg.py — Copia los datos de data/crypto_dashboard.sqlite3 a PostgreSQL.

Requisitos:
    - PostgreSQL corriendo (docker compose up -d)
    - Variables PG_* en .env apuntando al contenedor
    - Schema ya desplegado en PostgreSQL (python scripts/init_db.py)

No modifica ni borra el archivo SQLite original.

Uso:
    set USE_POSTGRESQL=true
    python scripts/migrate_to_pg.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATABASE_PATH
from app.db.postgres import connect as pg_connect

SQLITE_DB = Path(DATABASE_PATH)
if not SQLITE_DB.is_absolute():
    SQLITE_DB = ROOT / SQLITE_DB


def get_sqlite_tables(sconn: sqlite3.Connection) -> list[str]:
    rows = sconn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations'"
    ).fetchall()
    return [r[0] for r in rows]


def migrate() -> None:
    if not SQLITE_DB.exists():
        print(f"No se encontro {SQLITE_DB}, nada que migrar.")
        return

    sconn = sqlite3.connect(str(SQLITE_DB))
    sconn.row_factory = sqlite3.Row

    pconn = pg_connect()
    pcur = pconn.cursor()

    tables = get_sqlite_tables(sconn)
    print(f"Tablas a migrar: {len(tables)}")

    # Desactivar FKs durante la carga (permite insertar sin orden topológico)
    pcur.execute("SET session_replication_role = 'replica'")
    for table in tables:
        pcur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
    pconn.commit()

    for table in tables:
        rows = sconn.execute(f'SELECT * FROM "{table}"').fetchall()
        if not rows:
            continue
        columns = rows[0].keys()
        col_list = ", ".join(f'"{c}"' for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'
        values = [tuple(row[c] for c in columns) for row in rows]
        pcur.executemany(insert_sql, values)
        print(f"  {table}: {len(rows)} filas copiadas")

    pconn.commit()
    pcur.execute("SET session_replication_role = 'origin'")
    pconn.commit()

    print("\nVerificacion de conteos (SQLite -> Postgres):")
    mismatches = []
    for table in tables:
        sq_count = sconn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        verify_cur = pconn.cursor()
        verify_cur.execute(f'SELECT COUNT(*) AS n FROM "{table}"')
        pg_count = verify_cur.fetchone()["n"]
        status = "OK" if sq_count == pg_count else "MISMATCH"
        if sq_count != pg_count:
            mismatches.append(table)
        print(f"  {table:35s} sqlite={sq_count:6d}  postgres={pg_count:6d}  {status}")

    sconn.close()
    pconn.close()

    if mismatches:
        print(f"\nATENCION: {len(mismatches)} tabla(s) con conteos distintos: {', '.join(mismatches)}")
        sys.exit(1)
    print("\nMigracion completa. Todos los conteos coinciden.")


if __name__ == "__main__":
    migrate()