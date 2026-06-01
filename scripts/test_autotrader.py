import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auto_trader import evaluate_alert, get_position_size_usdt, calc_pnl
from app.position_monitor import check_positions, send_positions_report, build_report
from app.database import (
    insert_auto_position, get_open_auto_positions, close_auto_position,
    update_auto_position_tp1, get_auto_positions_summary, init_db,
)
from app.config import (
    AUTO_TRADING_ENABLED, AUTO_TRADING_MODE,
    AUTO_TRADING_CAPITAL_USDT, POSITION_REPORT_INTERVAL_SECONDS,
)

init_db()

print("Imports OK")
print(f"AUTO_TRADING_ENABLED:           {AUTO_TRADING_ENABLED}")
print(f"AUTO_TRADING_MODE:              {AUTO_TRADING_MODE}")
print(f"AUTO_TRADING_CAPITAL_USDT:      {AUTO_TRADING_CAPITAL_USDT}")
print(f"POSITION_REPORT_INTERVAL_SECS:  {POSITION_REPORT_INTERVAL_SECONDS}")
print()

print("Sizing por score:")
for score in [69, 70, 75, 80, 85]:
    print(f"  Score {score} -> USD {get_position_size_usdt(score):.0f}")

print()
positions = get_open_auto_positions()
print(f"Posiciones abiertas actualmente: {len(positions)}")

s = get_auto_positions_summary(since_hours=24)
print(f"Resumen 24h: total={s['total']} pnl={s['total_pnl_usdt']}")

print()
msg = build_report(positions, {})
print("Reporte preview:")
print(msg.encode("ascii", errors="replace").decode("ascii"))
