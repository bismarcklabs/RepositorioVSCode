"""Outcome tracker: evalúa alertas abiertas contra precios posteriores.

Anti-lookahead bias:
- La alerta se registra en t0 con sus niveles (entry, SL, TP1, TP2).
- El outcome se calcula SOLO con velas cuyo open_time > t0.
- No se usa ninguna vela que incluya el momento de la alerta.

Horizontes: configurados en OUTCOME_HORIZONS_MINUTES (15, 60, 240, 1440 min).
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.config import OUTCOME_HORIZONS_MINUTES
from app import database
from app.market_data import get_klines

logger = logging.getLogger("outcome_tracker")

# Mapping horizonte → intervalo de kline y límite de velas a pedir
_HORIZON_KLINE: Dict[int, tuple] = {
    15:   ("1m",  20),
    60:   ("5m",  20),
    240:  ("15m", 20),
    1440: ("1h",  30),
}


def _kline_interval_for_horizon(horizon_minutes: int) -> tuple:
    for h, cfg in sorted(_HORIZON_KLINE.items()):
        if horizon_minutes <= h:
            return cfg
    return ("1h", 30)


def _alert_epoch(alert: Dict[str, Any]) -> float:
    """Convierte el timestamp ISO (UTC sin zona) de la alerta a epoch."""
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(alert["timestamp"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _evaluate_alert(alert: Dict[str, Any], horizon_minutes: int) -> Optional[Dict[str, Any]]:
    """Evalúa un horizonte para una alerta. Retorna el outcome dict o None si no hay datos."""
    symbol = alert["symbol"]
    action = alert["action"]
    entry = float(alert.get("entry") or 0.0)
    stop = float(alert.get("stop_loss") or 0.0)
    tp1 = float(alert.get("take_profit_1") or 0.0)
    tp2 = float(alert.get("take_profit_2") or 0.0)
    alert_ts = _alert_epoch(alert)

    if entry <= 0.0 or stop <= 0.0 or alert_ts <= 0.0:
        return None

    now = time.time()
    elapsed_minutes = (now - alert_ts) / 60.0
    if elapsed_minutes < horizon_minutes:
        return None  # Aún no ha transcurrido el horizonte

    interval, limit = _kline_interval_for_horizon(horizon_minutes)
    # Solicitar la ventana exacta del horizonte en vez de las últimas N velas.
    # Esto permite evaluar alertas antiguas correctamente aunque el sistema
    # haya estado offline: las últimas N velas no cubrirían el rango correcto.
    horizon_end_ts = alert_ts + horizon_minutes * 60.0
    start_ms = int(alert_ts * 1000)
    end_ms   = int(horizon_end_ts * 1000)
    klines   = get_klines(symbol, interval=interval, limit=limit,
                          start_time_ms=start_ms, end_time_ms=end_ms)
    if not klines:
        return None

    # Filtrar velas estrictamente posteriores al momento de la alerta (anti-lookahead)
    future_klines = [
        k for k in klines
        if int(k[0]) / 1000.0 > alert_ts  # k[0] = open_time en ms
    ]
    if not future_klines:
        return None

    window_klines = [
        k for k in future_klines
        if int(k[0]) / 1000.0 <= horizon_end_ts
    ]
    if not window_klines:
        window_klines = future_klines[:1]

    highs  = [float(k[2]) for k in window_klines]
    lows   = [float(k[3]) for k in window_klines]
    closes = [float(k[4]) for k in window_klines]

    max_high = max(highs)
    min_low  = min(lows)
    price_at_check = closes[-1]

    is_long = action in ("LONG_FUTURES", "BUY_SPOT")

    if is_long:
        hit_tp1 = tp1 > 0.0 and max_high >= tp1
        hit_tp2 = tp2 > 0.0 and max_high >= tp2
        hit_stop = stop > 0.0 and min_low <= stop
        future_return_pct = (price_at_check - entry) / entry * 100.0 if entry > 0 else 0.0
        max_favorable = (max_high - entry) / entry * 100.0 if entry > 0 else 0.0
        max_adverse   = (entry - min_low) / entry * 100.0 if entry > 0 else 0.0
    else:  # SHORT
        hit_tp1 = tp1 > 0.0 and min_low <= tp1
        hit_tp2 = tp2 > 0.0 and min_low <= tp2
        hit_stop = stop > 0.0 and max_high >= stop
        future_return_pct = (entry - price_at_check) / entry * 100.0 if entry > 0 else 0.0
        max_favorable = (entry - min_low) / entry * 100.0 if entry > 0 else 0.0
        max_adverse   = (max_high - entry) / entry * 100.0 if entry > 0 else 0.0

    if hit_tp2:
        outcome = "win"
    elif hit_tp1 and not hit_stop:
        outcome = "partial"
    elif hit_stop and not hit_tp1:
        outcome = "loss"
    elif hit_tp1 and hit_stop:
        # Ambos tocados — determinar cuál fue primero aproximando por vela
        outcome = "partial"  # conservador
    else:
        outcome = "neutral"

    return {
        "alert_id":               alert["id"],
        "checked_at":             time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "horizon_minutes":        horizon_minutes,
        "price_at_check":         round(price_at_check, 8),
        "future_return_pct":      round(future_return_pct, 4),
        "max_favorable_excursion": round(max_favorable, 4),
        "max_adverse_excursion":   round(max_adverse, 4),
        "hit_tp1":                hit_tp1,
        "hit_tp2":                hit_tp2,
        "hit_stop":               hit_stop,
        "outcome":                outcome,
    }


def _update_alert_status_from_outcomes(alert_id: int) -> None:
    """Si el horizonte 1h ya tiene resultado definitivo, actualiza el status de la alerta."""
    try:
        conn_rows = database.get_evaluated_horizons(alert_id)
        # Horizonte 60 min es el primer horizonte de cierre
        if 60 not in conn_rows:
            return
        # Buscar el outcome del horizonte 1h
        from app.database import _get_conn
        conn = _get_conn()
        row = conn.execute(
            "SELECT outcome FROM alert_outcomes WHERE alert_id=? AND horizon_minutes=60",
            (alert_id,),
        ).fetchone()
        if row and row[0] in ("win", "partial", "loss"):
            database.update_alert_status(alert_id, row[0])
    except Exception:
        logger.exception("Error actualizando status de alerta %d", alert_id)


def run_outcome_tracker() -> None:
    """Evalúa todas las alertas abiertas en todos los horizontes configurados.

    Diseñado para ejecutarse una vez por ciclo de Streamlit (cada 15s).
    Es rápido cuando no hay horizonte cumplido — solo hace la comprobación de tiempo.
    """
    open_alerts = database.get_open_alerts()
    if not open_alerts:
        return

    for alert in open_alerts:
        already_evaluated = database.get_evaluated_horizons(alert["id"])
        for horizon in OUTCOME_HORIZONS_MINUTES:
            if horizon in already_evaluated:
                continue
            try:
                result = _evaluate_alert(alert, horizon)
                if result:
                    database.insert_alert_outcome(result)
                    logger.info(
                        "Outcome [%s %s] %dmin → %s (TP1=%s TP2=%s SL=%s)",
                        alert["symbol"], alert["action"], horizon,
                        result["outcome"],
                        result["hit_tp1"], result["hit_tp2"], result["hit_stop"],
                    )
            except Exception:
                logger.exception(
                    "Error evaluando outcome alerta=%d horizonte=%d", alert["id"], horizon
                )

        _update_alert_status_from_outcomes(alert["id"])
