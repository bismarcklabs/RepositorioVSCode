"""Herramienta de administración de la base de datos.

Uso:
    python scripts/manage_db.py status
    python scripts/manage_db.py purge --older-than 24   # elimina snapshots > 24h
    python scripts/manage_db.py purge --all              # elimina TODOS los snapshots
    python scripts/manage_db.py vacuum                   # compacta el archivo SQLite
"""
import argparse
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import DATABASE_PATH
from app.database import _get_conn, _ts_to_iso, init_db


def cmd_status() -> None:
    init_db()
    conn = _get_conn()

    total = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    symbols = conn.execute("SELECT COUNT(DISTINCT symbol) FROM market_snapshots").fetchone()[0]
    oldest = conn.execute("SELECT MIN(timestamp) FROM market_snapshots").fetchone()[0]
    newest = conn.execute("SELECT MAX(timestamp) FROM market_snapshots").fetchone()[0]
    alerts = conn.execute("SELECT COUNT(*) FROM trade_alerts").fetchone()[0]

    db_size_mb = os.path.getsize(DATABASE_PATH) / 1_048_576 if os.path.exists(DATABASE_PATH) else 0

    print(f"\n{'='*50}")
    print(f"  Base de datos: {DATABASE_PATH}")
    print(f"  Tamaño:        {db_size_mb:.2f} MB")
    print(f"{'='*50}")
    print(f"  Snapshots:     {total:,}")
    print(f"  Símbolos:      {symbols}")
    print(f"  Más antiguo:   {oldest or '—'}")
    print(f"  Más reciente:  {newest or '—'}")
    print(f"  Alertas:       {alerts:,}")
    print(f"{'='*50}\n")

    # Últimos 5 snapshots por símbolo más activo
    recent = conn.execute(
        """
        SELECT symbol, COUNT(*) as cnt, MAX(timestamp) as last_ts, AVG(score) as avg_score
        FROM market_snapshots
        WHERE timestamp >= ?
        GROUP BY symbol
        ORDER BY cnt DESC
        LIMIT 10
        """,
        (_ts_to_iso(time.time() - 3600),),
    ).fetchall()

    if recent:
        print("  Top 10 símbolos (última hora):")
        print(f"  {'Símbolo':<14} {'Snapshots':>10} {'Score prom':>11} {'Último':>20}")
        print(f"  {'-'*57}")
        for row in recent:
            print(f"  {row[0]:<14} {row[1]:>10} {row[3]:>11.1f} {row[2]:>20}")
        print()


def cmd_purge(older_than_hours: float, all_records: bool, dry_run: bool) -> None:
    init_db()
    conn = _get_conn()

    if all_records:
        count = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        alerts = conn.execute("SELECT COUNT(*) FROM trade_alerts").fetchone()[0]
        outcomes = conn.execute("SELECT COUNT(*) FROM alert_outcomes").fetchone()[0]
        print(f"\n  SOLO se borrará market_snapshots ({count:,} filas).")
        print(f"  Se conservan: trade_alerts ({alerts:,}), alert_outcomes ({outcomes:,}), notification_log.")
        if dry_run:
            print(f"\n[DRY RUN] Se eliminarían {count:,} snapshots (TODOS)\n")
            return
        confirm = input(f"\n¿Eliminar TODOS los {count:,} snapshots? Escribe 'SI' para confirmar: ")
        if confirm.strip() != "SI":
            print("Cancelado.")
            return
        conn.execute("DELETE FROM market_snapshots")
        conn.commit()
        print(f"Eliminados {count:,} snapshots. El scanner los reconstruye en el próximo ciclo.\n")
    else:
        cutoff = _ts_to_iso(time.time() - older_than_hours * 3600)
        count = conn.execute(
            "SELECT COUNT(*) FROM market_snapshots WHERE timestamp < ?", (cutoff,)
        ).fetchone()[0]
        if dry_run:
            print(f"\n[DRY RUN] Se eliminarían {count:,} snapshots anteriores a {cutoff}\n")
            return
        if count == 0:
            print(f"\nNo hay snapshots anteriores a {cutoff}.\n")
            return
        confirm = input(f"\n¿Eliminar {count:,} snapshots anteriores a {cutoff}? Escribe 'SI': ")
        if confirm.strip() != "SI":
            print("Cancelado.")
            return
        conn.execute("DELETE FROM market_snapshots WHERE timestamp < ?", (cutoff,))
        conn.commit()
        print(f"Eliminados {count:,} snapshots.\n")


def cmd_vacuum() -> None:
    init_db()
    conn = _get_conn()
    before = os.path.getsize(DATABASE_PATH) / 1_048_576 if os.path.exists(DATABASE_PATH) else 0
    print(f"\nVACUUM en progreso... (tamaño actual: {before:.2f} MB)")
    conn.execute("VACUUM")
    after = os.path.getsize(DATABASE_PATH) / 1_048_576 if os.path.exists(DATABASE_PATH) else 0
    print(f"Completado. Tamaño final: {after:.2f} MB (ahorrado: {before - after:.2f} MB)\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Administración de la DB del crypto dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Muestra estadísticas de la DB")

    p_purge = sub.add_parser("purge", help="Elimina snapshots")
    p_purge.add_argument(
        "--older-than", type=float, default=24, metavar="HORAS",
        help="Elimina snapshots más viejos que N horas (default: 24)",
    )
    p_purge.add_argument(
        "--all", action="store_true", dest="all_records",
        help="Elimina TODOS los snapshots (pide confirmación)",
    )
    p_purge.add_argument(
        "--dry-run", action="store_true",
        help="Muestra qué se eliminaría sin borrar nada",
    )

    sub.add_parser("vacuum", help="Compacta el archivo SQLite liberando espacio")

    args = parser.parse_args()

    if args.cmd == "status":
        cmd_status()
    elif args.cmd == "purge":
        cmd_purge(args.older_than, args.all_records, args.dry_run)
    elif args.cmd == "vacuum":
        cmd_vacuum()


if __name__ == "__main__":
    main()
