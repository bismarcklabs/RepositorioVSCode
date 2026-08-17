"""Outcome tracker para micro-scalp alerts."""
import datetime
import logging
import time
from typing import Any, Dict, List, Optional

from app import database
from app.market_data import get_klines
from app.config import MICRO_SCALP_FORCE_CLOSE_AFTER_MINUTES, MICRO_SCALP_TRADE_SIZE_USDT

logger = logging.getLogger("micro_outcome_tracker")


def _alert_epoch(alert: Dict[str, Any]) -> float:
    try:
        dt = datetime.datetime.fromisoformat(alert["timestamp"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _evaluate_micro_alert(alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    alert_ts = _alert_epoch(alert)
    timeout_minutes = int(alert.get("timeout_minutes") or 10)
    elapsed_minutes = (time.time() - alert_ts) / 60.0
    if alert_ts <= 0:
        return None

    if elapsed_minutes < timeout_minutes:
        return None

    symbol = alert["symbol"]
    action = alert["action"]
    entry = float(alert.get("entry") or 0.0)
    tp1 = float(alert.get("take_profit_1") or 0.0)
    tp2 = float(alert.get("take_profit_2") or 0.0)
    sl = float(alert.get("stop_loss") or 0.0)
    if entry <= 0 or sl <= 0:
        return None

    limit = max(5, min(1500, timeout_minutes + 2))
    start_ms = int(alert_ts * 1000)
    end_ms = int((alert_ts + timeout_minutes * 60.0) * 1000)
    klines = get_klines(
        symbol,
        interval="1m",
        limit=limit,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
    )
    future_klines: List[Any] = [
        k for k in (klines or [])
        if int(k[0]) / 1000.0 > alert_ts
        and int(k[0]) / 1000.0 <= alert_ts + timeout_minutes * 60.0
    ]
    if not future_klines:
        force_after = timeout_minutes + max(0, MICRO_SCALP_FORCE_CLOSE_AFTER_MINUTES)
        if elapsed_minutes >= force_after:
            return {
                "id": alert["id"],
                "outcome": "expired",
                "exit_price": round(entry, 8),
                "hit_tp1": False,
                "hit_tp2": False,
                "hit_stop": False,
                "pnl_pct": 0.0,
                "max_favorable_pct": 0.0,
                "max_adverse_pct": 0.0,
            }
        return None

    highs = [float(k[2]) for k in future_klines]
    lows = [float(k[3]) for k in future_klines]
    closes = [float(k[4]) for k in future_klines]
    max_high = max(highs)
    min_low = min(lows)

    is_long = action == "MICRO_LONG_SCALP"
    if is_long:
        max_favorable = (max_high - entry) / entry * 100.0
        max_adverse = (entry - min_low) / entry * 100.0
    else:
        max_favorable = (entry - min_low) / entry * 100.0
        max_adverse = (max_high - entry) / entry * 100.0

    # Simulacion secuencial: la salida es el primer nivel (SL o TP2) tocado
    # cronologicamente, en vez de mantener la posicion hasta el cierre del
    # timeout sin importar si ya se rompio el SL/TP. TP2 implica TP1 al ser
    # mas lejano en la misma direccion, por lo que no requiere desempate.
    hit_tp1 = False
    hit_tp2 = False
    hit_stop = False
    exit_price: Optional[float] = None
    outcome = ""
    for high, low in zip(highs, lows):
        if is_long:
            sl_touched = sl > 0 and low <= sl
            tp2_touched = tp2 > 0 and high >= tp2
            tp1_touched = tp1 > 0 and high >= tp1
        else:
            sl_touched = sl > 0 and high >= sl
            tp2_touched = tp2 > 0 and low <= tp2
            tp1_touched = tp1 > 0 and low <= tp1

        if sl_touched:
            hit_stop = True
            hit_tp1 = hit_tp1 or tp1_touched
            exit_price = sl
            outcome = "loss"
            break
        if tp2_touched:
            hit_tp1 = True
            hit_tp2 = True
            exit_price = tp2
            outcome = "win"
            break
        if tp1_touched:
            hit_tp1 = True

    if exit_price is None:
        exit_price = closes[-1]
        outcome = "partial" if hit_tp1 else "neutral"

    if is_long:
        pnl_pct = (exit_price - entry) / entry * 100.0
    else:
        pnl_pct = (entry - exit_price) / entry * 100.0

    # trade_size_usdt por alerta (metodo "nivel" usa un multiplicador mayor,
    # ver micro_scalper.py) — cae al tamano fijo historico si la fila es
    # anterior a la migracion 006 (columna vacia/0).
    trade_size = float(alert.get("trade_size_usdt") or 0.0) or MICRO_SCALP_TRADE_SIZE_USDT
    pnl_usdt = round(pnl_pct / 100.0 * trade_size, 4)

    return {
        "id": alert["id"],
        "outcome": outcome,
        "exit_price": round(exit_price, 8),
        "hit_tp1": hit_tp1,
        "hit_tp2": hit_tp2,
        "hit_stop": hit_stop,
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usdt": pnl_usdt,
        "max_favorable_pct": round(max_favorable, 4),
        "max_adverse_pct": round(max_adverse, 4),
    }


def run_micro_outcome_tracker() -> None:
    alerts = database.get_open_micro_scalp_alerts()
    if not alerts:
        return

    for alert in alerts:
        try:
            result = _evaluate_micro_alert(alert)
            if not result:
                continue
            database.close_micro_scalp_alert(
                result["id"],
                result["outcome"],
                result["exit_price"],
                result["hit_tp1"],
                result["hit_tp2"],
                result["hit_stop"],
                result["pnl_pct"],
                result["max_favorable_pct"],
                result["max_adverse_pct"],
                result["pnl_usdt"],
            )
            logger.info(
                "Micro outcome [%s %s] -> %s (TP1=%s TP2=%s SL=%s)",
                alert["symbol"], alert["action"], result["outcome"],
                result["hit_tp1"], result["hit_tp2"], result["hit_stop"],
            )
        except Exception:
            logger.exception("Error evaluando micro scalp id=%s", alert.get("id"))
