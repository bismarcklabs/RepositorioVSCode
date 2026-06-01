"""Auto-trading module — paper y real.

Evalúa alertas del scanner contra gates de seguridad y abre posiciones
simuladas (paper) o reales (Binance API). Sizing variable por score.

Paper mode: sin llamadas a Binance, todo en DB.
Real mode:  llama Binance Futures API (requiere API key con permiso trading).
"""
import json as _json
import logging
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from app import database
from app.config import (
    AUTO_TRADING_ENABLED,
    AUTO_TRADING_MODE,
    AUTO_TRADING_CAPITAL_USDT,
    AUTO_TRADING_MAX_POSITIONS,
    AUTO_TRADING_MARKETS,
    AUTO_TRADING_MIN_SCORE,
    AUTO_TRADING_TIER1_SCORE,
    AUTO_TRADING_TIER2_SCORE,
    AUTO_TRADING_TIER3_SCORE,
    ENABLE_TELEGRAM_ALERTS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

logger = logging.getLogger("auto_trader")

_ACTION_EMOJI = {
    "LONG_FUTURES":  "\U0001f4c8",
    "SHORT_FUTURES": "\U0001f4c9",
    "BUY_SPOT":      "\U0001f7e2",
    "SELL_SPOT":     "\U0001f534",
}


def _post_telegram(message: str) -> None:
    if not ENABLE_TELEGRAM_ALERTS or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = _json.dumps({
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8):
        pass


# Acciones elegibles por mercado
_ELIGIBLE_ACTIONS: Dict[str, set] = {
    "futures": {"LONG_FUTURES", "SHORT_FUTURES"},
    "spot":    {"BUY_SPOT", "SELL_SPOT"},
    "both":    {"LONG_FUTURES", "SHORT_FUTURES", "BUY_SPOT", "SELL_SPOT"},
}

# Dirección del trade (+1 long, -1 short)
_DIRECTION = {
    "LONG_FUTURES":  1,
    "SHORT_FUTURES": -1,
    "BUY_SPOT":      1,
    "SELL_SPOT":    -1,
}


def get_position_size_usdt(score: int) -> float:
    """Sizing variable según score: 80+→3%, 75-79→2%, 70-74→1%."""
    if score >= AUTO_TRADING_TIER1_SCORE:
        return AUTO_TRADING_CAPITAL_USDT * 0.03
    if score >= AUTO_TRADING_TIER2_SCORE:
        return AUTO_TRADING_CAPITAL_USDT * 0.02
    if score >= AUTO_TRADING_TIER3_SCORE:
        return AUTO_TRADING_CAPITAL_USDT * 0.01
    return 0.0


def _passes_gates(result: Dict[str, Any],
                  open_positions: List[Dict]) -> Tuple[bool, str]:
    """Verifica todas las condiciones antes de abrir posición."""
    rec    = result.get("recommendation", {})
    action = rec.get("action", "WAIT")
    score  = result.get("score_data", {}).get("score", 0)
    conf   = rec.get("confidence", 0)
    setup  = rec.get("setup") or {}

    if action == "WAIT":
        return False, "action=WAIT"

    eligible = _ELIGIBLE_ACTIONS.get(AUTO_TRADING_MARKETS, set())
    if action not in eligible:
        return False, f"accion {action} no habilitada"

    if score < AUTO_TRADING_MIN_SCORE:
        return False, f"score {score} < min {AUTO_TRADING_MIN_SCORE}"

    if conf < 60:
        return False, f"confianza {conf}% < 60%"

    if not setup.get("stop_loss"):
        return False, "setup sin stop_loss"

    if len(open_positions) >= AUTO_TRADING_MAX_POSITIONS:
        return False, f"limite {AUTO_TRADING_MAX_POSITIONS} posiciones abiertas"

    symbol = result["symbol"]
    for p in open_positions:
        if p["symbol"] == symbol:
            return False, f"posicion abierta ya existe para {symbol}"

    size = get_position_size_usdt(score)
    if size <= 0:
        return False, f"score {score} no alcanza ningun tier de sizing"

    return True, ""


def evaluate_alert(result: Dict[str, Any],
                   alert_id: Optional[int] = None) -> Optional[int]:
    """Evalúa una alerta y abre posición si pasa los gates.

    Retorna position_id si se abrió, None si no.
    """
    if not AUTO_TRADING_ENABLED:
        return None

    try:
        open_positions = database.get_open_auto_positions()
        passed, reason = _passes_gates(result, open_positions)
        if not passed:
            logger.debug("AUTO SKIP %s: %s", result.get("symbol"), reason)
            return None

        rec      = result["recommendation"]
        action   = rec["action"]
        score    = result["score_data"]["score"]
        setup    = rec.get("setup") or {}
        price    = result.get("price", 0.0)

        entry_price = (result.get("futures_price") or price) if "FUTURES" in action else price
        if not entry_price:
            return None

        size_usdt = get_position_size_usdt(score)
        leverage  = int(setup.get("suggested_leverage") or 1)
        tp1       = setup.get("take_profit_1") or None
        tp2       = setup.get("take_profit_2") or None
        sl        = float(setup["stop_loss"])

        position_id = database.insert_auto_position({
            "alert_id":    alert_id,
            "symbol":      result["symbol"],
            "action":      action,
            "mode":        AUTO_TRADING_MODE,
            "open_time":   result.get("timestamp", ""),
            "entry_price": entry_price,
            "size_usdt":   size_usdt,
            "leverage":    leverage,
            "tp1":         tp1,
            "tp2":         tp2,
            "sl":          sl,
            "sl_current":  sl,
        })

        tier = "3%" if score >= AUTO_TRADING_TIER1_SCORE else "2%" if score >= AUTO_TRADING_TIER2_SCORE else "1%"
        logger.info(
            "AUTO ABRIR %s %s | entry=%.6g | $%.0f (%s) | lev=%dx | "
            "TP1=%s TP2=%s SL=%.6g | mode=%s | pos_id=%d",
            action, result["symbol"], entry_price, size_usdt, tier, leverage,
            f"{tp1:.6g}" if tp1 else "—",
            f"{tp2:.6g}" if tp2 else "—",
            sl, AUTO_TRADING_MODE, position_id,
        )
        try:
            _notify_open(result["symbol"], action, entry_price, size_usdt,
                         leverage, tp1, tp2, sl, score, tier)
        except Exception:
            logger.warning("Error notificando apertura de posicion")
        return position_id

    except Exception:
        logger.exception("Error en evaluate_alert para %s", result.get("symbol"))
        return None


def _notify_open(symbol: str, action: str, entry: float, size_usdt: float,
                  leverage: int, tp1: Optional[float], tp2: Optional[float],
                  sl: float, score: int, tier: str) -> None:
    emoji     = _ACTION_EMOJI.get(action, "⚠️")
    mode_tag  = "📄 PAPER" if AUTO_TRADING_MODE == "paper" else "🔴 REAL"
    lev_str   = f"  ⚡ Apalancamiento: <b>{leverage}x</b>" if leverage > 1 else ""
    tp1_str   = f"\n✅ TP1: <code>{tp1:.6g}</code>" if tp1 else ""
    tp2_str   = f"\n✅ TP2: <code>{tp2:.6g}</code>" if tp2 else ""
    msg = (
        f"{emoji} <b>POSICIÓN ABIERTA</b> — {mode_tag}\n"
        f"{action.replace('_', ' ')} — <b>{symbol}</b>\n"
        f"\n"
        f"💰 Entrada: <code>{entry:.6g}</code>\n"
        f"📦 Tamaño: <b>${size_usdt:.0f}</b> ({tier} capital){lev_str}\n"
        f"📊 Score: {score}"
        f"{tp1_str}{tp2_str}\n"
        f"🛑 SL: <code>{sl:.6g}</code>"
    )
    try:
        _post_telegram(msg)
    except Exception as exc:
        logger.warning("Error enviando notificacion de apertura: %s", exc)


def calc_pnl(position: Dict[str, Any], current_price: float) -> Dict[str, float]:
    """Calcula P&L actual de una posición (incluyendo TP1 parcial ya realizado)."""
    action    = position["action"]
    entry     = position["entry_price"]
    size      = position["size_usdt"]
    leverage  = position.get("leverage") or 1
    direction = _DIRECTION.get(action, 1)
    tp1_hit   = bool(position.get("tp1_hit"))
    tp1_pnl   = position.get("tp1_pnl_usdt") or 0.0

    # Porción abierta: 50% si TP1 ya fue tocado, 100% si no
    open_size = size * 0.5 if tp1_hit else size
    pct = direction * (current_price - entry) / entry * leverage * 100
    open_pnl_usdt = open_size * pct / 100

    total_pnl_usdt = round(tp1_pnl + open_pnl_usdt, 4)
    total_pnl_pct  = round(total_pnl_usdt / size * 100, 2)

    return {
        "pnl_pct":       round(pct, 2),           # % del precio desde entrada
        "open_pnl_usdt": round(open_pnl_usdt, 4), # P&L de la porción abierta
        "total_pnl_usdt": total_pnl_usdt,         # tp1 realizado + abierto
        "total_pnl_pct":  total_pnl_pct,          # % sobre size_usdt total
    }
