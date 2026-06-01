"""Mantenimiento programado de la base de datos SQLite.

Diseñado para ejecutarse como tarea programada (Windows Task Scheduler o cron).
No requiere interacción — sale con código 0 si todo OK, 1 si hubo error.

Operaciones:
  - Purga snapshots más viejos que SNAPSHOT_RETENTION_DAYS (config/.env)
  - Purga completa de alertas, outcomes y logs (--alerts)
  - WAL checkpoint para compactar el archivo WAL
  - VACUUM opcional (--vacuum) para recuperar espacio en disco

Uso:
    python scripts/purge_db.py                  # solo purga snapshots
    python scripts/purge_db.py --alerts         # purga alertas + outcomes + logs
    python scripts/purge_db.py --vacuum         # purga + vacuum (semanal recomendado)
    python scripts/purge_db.py --dry-run        # solo muestra qué haría, no borra nada

IMPORTANTE: detener el scanner antes de ejecutar --alerts.

Configurar en Windows Task Scheduler:
    Programa:   C:\\ruta\\al\\venv\\Scripts\\python.exe
    Argumentos: scripts\\purge_db.py
    Directorio: C:\\Users\\pedro\\crypto-dashboard
    Frecuencia: Diario, a las 03:00 AM
    (Agregar tarea semanal con --vacuum para el VACUUM)
"""
import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.log_setup import setup_logging

setup_logging()
logger = logging.getLogger("purge_db")

from app.config import DATABASE_PATH, SNAPSHOT_RETENTION_DAYS


def _get_conn() -> sqlite3.Connection:
    db_path = Path(DATABASE_PATH)
    if not db_path.exists():
        raise FileNotFoundError(f"Base de datos no encontrada: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _db_size_mb() -> float:
    path = Path(DATABASE_PATH)
    if not path.exists():
        return 0.0
    wal = path.with_suffix(".sqlite3-wal")
    total = path.stat().st_size + (wal.stat().st_size if wal.exists() else 0)
    return total / 1_048_576


def run_purge(dry_run: bool = False) -> int:
    """Elimina snapshots más viejos que SNAPSHOT_RETENTION_DAYS. Retorna filas eliminadas."""
    conn = _get_conn()
    cutoff_epoch = time.time() - SNAPSHOT_RETENTION_DAYS * 86400
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(cutoff_epoch))

    count = conn.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE timestamp < ?",
        (cutoff_iso,),
    ).fetchone()[0]

    total = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]

    logger.info(
        "Snapshots totales: %d | A eliminar (>%dd): %d | Cutoff: %s",
        total, SNAPSHOT_RETENTION_DAYS, count, cutoff_iso,
    )

    if count == 0:
        logger.info("Nada que purgar en snapshots.")
        conn.close()
        return 0

    if dry_run:
        logger.info("[DRY RUN] Se eliminarían %d snapshots.", count)
        conn.close()
        return count

    conn.execute("DELETE FROM market_snapshots WHERE timestamp < ?", (cutoff_iso,))
    conn.commit()
    logger.info("Purgados %d snapshots.", count)

    conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
    conn.close()
    return count


def run_purge_alerts(dry_run: bool = False) -> dict:
    """Elimina TODAS las alertas, outcomes y logs de notificación.

    El orden de borrado es importante: primero tablas hijas, luego padre.
    Retorna dict con conteo de filas eliminadas por tabla.
    """
    conn = _get_conn()

    counts = {
        "alert_outcomes":   conn.execute("SELECT COUNT(*) FROM alert_outcomes").fetchone()[0],
        "notification_log": conn.execute("SELECT COUNT(*) FROM notification_log").fetchone()[0],
        "trade_alerts":     conn.execute("SELECT COUNT(*) FROM trade_alerts").fetchone()[0],
    }

    logger.info(
        "Alertas a purgar — trade_alerts: %d | alert_outcomes: %d | notification_log: %d",
        counts["trade_alerts"], counts["alert_outcomes"], counts["notification_log"],
    )

    if all(v == 0 for v in counts.values()):
        logger.info("Tablas de alertas ya vacías.")
        conn.close()
        return counts

    if dry_run:
        logger.info("[DRY RUN] Se eliminarían %d alertas, %d outcomes, %d logs.",
                    counts["trade_alerts"], counts["alert_outcomes"], counts["notification_log"])
        conn.close()
        return counts

    conn.execute("DELETE FROM alert_outcomes")
    conn.execute("DELETE FROM notification_log")
    conn.execute("DELETE FROM trade_alerts")
    # Resetear el autoincrement para que los IDs comiencen desde 1
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('trade_alerts','alert_outcomes','notification_log')")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
    conn.close()

    logger.info(
        "Purgadas — trade_alerts: %d | alert_outcomes: %d | notification_log: %d",
        counts["trade_alerts"], counts["alert_outcomes"], counts["notification_log"],
    )
    return counts


def run_vacuum() -> None:
    """VACUUM + WAL truncate — recupera espacio en disco. Puede tardar varios minutos."""
    conn = _get_conn()
    before_mb = _db_size_mb()
    logger.info("Iniciando VACUUM (tamaño actual: %.2f MB)...", before_mb)

    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.commit()
    conn.close()

    after_mb = _db_size_mb()
    logger.info(
        "VACUUM completado — antes: %.2f MB | despues: %.2f MB | ahorrado: %.2f MB",
        before_mb, after_mb, before_mb - after_mb,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mantenimiento programado de la DB del crypto dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--alerts", action="store_true",
        help="Purgar TODAS las alertas, outcomes y logs (reset limpio)",
    )
    parser.add_argument(
        "--vacuum", action="store_true",
        help="Ejecutar VACUUM despues de la purga (recomendado 1 vez/semana)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Muestra que se eliminaria sin borrar nada",
    )
    args = parser.parse_args()

    logger.info(
        "Inicio de mantenimiento — retention=%dd alerts=%s vacuum=%s dry_run=%s",
        SNAPSHOT_RETENTION_DAYS, args.alerts, args.vacuum, args.dry_run,
    )

    t0 = time.monotonic()
    try:
        deleted_snapshots = run_purge(dry_run=args.dry_run)

        deleted_alerts = {}
        if args.alerts:
            deleted_alerts = run_purge_alerts(dry_run=args.dry_run)

        if args.vacuum and not args.dry_run:
            run_vacuum()

        elapsed = time.monotonic() - t0
        logger.info(
            "Mantenimiento completado en %.1fs — snapshots: %d | alertas: %s",
            elapsed, deleted_snapshots,
            deleted_alerts.get("trade_alerts", 0) if deleted_alerts else "no purgadas",
        )
        sys.exit(0)
    except FileNotFoundError as exc:
        logger.error("DB no encontrada: %s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("Error durante el mantenimiento")
        sys.exit(1)


if __name__ == "__main__":
    main()
