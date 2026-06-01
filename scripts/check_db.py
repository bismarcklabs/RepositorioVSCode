"""
Script de verificación rápida de la base de datos.
Uso: python scripts/check_db.py
"""
import sqlite3
import sys
import io
from pathlib import Path

# Forzar UTF-8 en stdout para caracteres especiales en Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).parent.parent / "data" / "crypto_dashboard.sqlite3"

if not DB_PATH.exists():
    print(f"[!] Base de datos no encontrada en: {DB_PATH}")
    print("    Asegúrate de que Streamlit haya corrido al menos un ciclo.")
    sys.exit(1)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

print(f"\n{'='*55}")
print(f"  Base de datos: {DB_PATH}")
print(f"  Tamaño: {DB_PATH.stat().st_size / 1024:.1f} KB")
print(f"{'='*55}\n")

# ── Conteos por tabla ──────────────────────────────────────────────────────
tables = ["market_snapshots", "trade_alerts", "notification_log", "alert_outcomes"]
for t in tables:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<25} {n:>8,} filas")
    except Exception as e:
        print(f"  {t:<25} ERROR: {e}")

# ── Últimos 5 snapshots ────────────────────────────────────────────────────
print(f"\n{'─'*55}")
print("  Últimos 5 snapshots guardados:")
print(f"{'─'*55}")
rows = conn.execute("""
    SELECT timestamp, symbol, price, action, score, signal
    FROM market_snapshots
    ORDER BY timestamp DESC LIMIT 5
""").fetchall()
if rows:
    print(f"  {'Timestamp':<20} {'Símbolo':<12} {'Precio':>10} {'Acción':<16} {'Score':>5} {'Señal'}")
    print(f"  {'─'*20} {'─'*12} {'─'*10} {'─'*16} {'─'*5} {'─'*20}")
    for r in rows:
        print(f"  {r['timestamp']:<20} {r['symbol']:<12} {r['price']:>10.2f} {r['action']:<16} {r['score']:>5} {r['signal']}")
else:
    print("  (sin datos aún)")

# ── Últimas alertas ────────────────────────────────────────────────────────
print(f"\n{'─'*55}")
print("  Últimas 5 alertas registradas:")
print(f"{'─'*55}")
alerts = conn.execute("""
    SELECT timestamp, symbol, action, confidence, score, status, entry, stop_loss, take_profit_1
    FROM trade_alerts
    ORDER BY timestamp DESC LIMIT 5
""").fetchall()
if alerts:
    for a in alerts:
        print(f"  [{a['timestamp'][:16]}] {a['symbol']} {a['action']} "
              f"conf={a['confidence']}% score={a['score']} status={a['status']}")
        print(f"    Entry={a['entry']:.4f}  SL={a['stop_loss']:.4f}  TP1={a['take_profit_1']:.4f}")
else:
    print("  (sin alertas aún — necesita señal accionable + ciclos de scan)")

# ── Outcomes ───────────────────────────────────────────────────────────────
n_outcomes = conn.execute("SELECT COUNT(*) FROM alert_outcomes").fetchone()[0]
if n_outcomes > 0:
    print(f"\n{'─'*55}")
    print(f"  Outcomes evaluados: {n_outcomes}")
    wins = conn.execute(
        "SELECT COUNT(*) FROM alert_outcomes WHERE outcome='win'"
    ).fetchone()[0]
    partial = conn.execute(
        "SELECT COUNT(*) FROM alert_outcomes WHERE outcome='partial'"
    ).fetchone()[0]
    losses = conn.execute(
        "SELECT COUNT(*) FROM alert_outcomes WHERE outcome='loss'"
    ).fetchone()[0]
    print(f"  Win={wins}  Partial={partial}  Loss={losses}  Neutral/Unknown={n_outcomes-wins-partial-losses}")

# ── Rango de tiempo ────────────────────────────────────────────────────────
ts_range = conn.execute("""
    SELECT MIN(timestamp), MAX(timestamp) FROM market_snapshots
""").fetchone()
if ts_range[0]:
    print(f"\n{'─'*55}")
    print(f"  Rango de datos: {ts_range[0][:16]} → {ts_range[1][:16]} UTC")

print(f"\n{'='*55}\n")
conn.close()
