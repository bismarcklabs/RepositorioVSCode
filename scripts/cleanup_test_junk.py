# -*- coding: utf-8 -*-
"""Limpieza puntual de filas de prueba que los tests escribieron en la DB real.

Contexto (2026-07-17): tras el refactor a app/db/, el fixture fresh_db dejó de
redirigir la conexión y los tests escribieron en data/crypto_dashboard.sqlite3.
El fixture ya fue corregido (database._get_conn pasa DATABASE_PATH explícito);
este script borra las filas de prueba que quedaron, con respaldo JSON previo.

Criterios exactos (valores sintéticos de tests/test_database.py):
- trade_alerts:   price=100000.0 AND entry=100000.0 AND stop_loss=98500.0
- market_snapshots: price=100000.0 AND futures_price=100050.0
- micro_scalp_alerts: symbol='BTCUSDT' AND entry=100.0 AND stop_loss=99.75
- news_events:    event_id='dashboard-news-1'
- news_predictions: symbol='BTCUSDT' AND price_at_prediction=100.0
- security_event_alerts: fingerprint='zec-security-2026-06-02'
- accumulation_watch: symbol='ABCUSDT'
+ dependientes: alert_outcomes / notification_log / micro_notification_log

Uso:  python scripts/cleanup_test_junk.py            (dry-run: solo muestra)
      python scripts/cleanup_test_junk.py --apply    (borra, con respaldo)
"""
import io
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATABASE_PATH  # noqa: E402

APPLY = "--apply" in sys.argv


def main() -> None:
    conn = sqlite3.connect(str(ROOT / DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    backup = {}

    def grab(name, sql, params=()):
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]
        backup[name] = rows
        return rows

    alerts = grab("trade_alerts",
                  "SELECT * FROM trade_alerts WHERE price=100000.0 "
                  "AND entry=100000.0 AND stop_loss=98500.0")
    ids = [r["id"] for r in alerts]
    ph = ",".join("?" * len(ids)) or "NULL"
    grab("alert_outcomes", f"SELECT * FROM alert_outcomes WHERE alert_id IN ({ph})", ids)
    grab("notification_log", f"SELECT * FROM notification_log WHERE alert_id IN ({ph})", ids)
    grab("market_snapshots",
         "SELECT * FROM market_snapshots WHERE price=100000.0 AND futures_price=100050.0")
    micro = grab("micro_scalp_alerts",
                 "SELECT * FROM micro_scalp_alerts WHERE symbol='BTCUSDT' "
                 "AND entry=100.0 AND stop_loss=99.75")
    mids = [r["id"] for r in micro]
    mph = ",".join("?" * len(mids)) or "NULL"
    grab("micro_notification_log",
         f"SELECT * FROM micro_notification_log WHERE micro_alert_id IN ({mph})", mids)
    grab("news_events", "SELECT * FROM news_events WHERE event_id='dashboard-news-1'")
    grab("news_predictions",
         "SELECT * FROM news_predictions WHERE symbol='BTCUSDT' AND price_at_prediction=100.0")
    grab("security_event_alerts",
         "SELECT * FROM security_event_alerts WHERE fingerprint='zec-security-2026-06-02'")
    grab("accumulation_watch", "SELECT * FROM accumulation_watch WHERE symbol='ABCUSDT'")

    total = sum(len(v) for v in backup.values())
    for name, rows in backup.items():
        print(f"{name}: {len(rows)} filas")
    print(f"TOTAL: {total} filas de prueba")

    if not APPLY:
        print("\nDry-run — nada borrado. Ejecutar con --apply para limpiar.")
        return

    out = ROOT / "outputs" / f"db_test_junk_backup_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(backup, default=str), encoding="utf-8")
    print(f"\nRespaldo: {out}")

    c.execute(f"DELETE FROM alert_outcomes WHERE alert_id IN ({ph})", ids)
    c.execute(f"DELETE FROM notification_log WHERE alert_id IN ({ph})", ids)
    c.execute(f"DELETE FROM trade_alerts WHERE id IN ({ph})", ids)
    c.execute("DELETE FROM market_snapshots WHERE price=100000.0 AND futures_price=100050.0")
    c.execute(f"DELETE FROM micro_notification_log WHERE micro_alert_id IN ({mph})", mids)
    c.execute(f"DELETE FROM micro_scalp_alerts WHERE id IN ({mph})", mids)
    c.execute("DELETE FROM news_events WHERE event_id='dashboard-news-1'")
    c.execute("DELETE FROM news_predictions WHERE symbol='BTCUSDT' AND price_at_prediction=100.0")
    c.execute("DELETE FROM security_event_alerts WHERE fingerprint='zec-security-2026-06-02'")
    c.execute("DELETE FROM accumulation_watch WHERE symbol='ABCUSDT'")
    conn.commit()
    print("Limpieza aplicada.")
    conn.close()


if __name__ == "__main__":
    main()
