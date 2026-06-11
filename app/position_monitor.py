"""Monitor de posiciones de auto-trading.

Dos responsabilidades:
  1. check_positions()      — verifica TP1/TP2/SL/timeout en cada ciclo del scanner.
  2. send_positions_report() — envía resumen a Telegram cada 10 minutos.

Se llama desde run_scanner.py en el loop principal, sin hilo separado.
"""
import datetime
import json as _json
import logging
import time
import urllib.request
from typing import Any, Dict, List, Optional

from app import database, market_data
from app.auto_trader import calc_pnl, _DIRECTION
from app.config import (
    AUTO_TRADING_ENABLED,
    AUTO_TRADING_MODE,
    AUTO_TRADING_CAPITAL_USDT,
    AUTO_TRADING_MAX_POSITIONS,
    AUTO_TRADING_TIMEOUT_HOURS,
    AUTO_TRADING_RISK_CUT_ENABLED,
    AUTO_TRADING_RISK_CUT_MIN_HOURS,
    AUTO_TRADING_RISK_CUT_LOSS_PCT,
    AUTO_TRADING_PAPER_MAX_LOSS_PCT,
    ENABLE_TELEGRAM_ALERTS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    POSITION_REPORT_INTERVAL_SECONDS,
)

logger = logging.getLogger("position_monitor")

_ACTION_EMOJI = {
    "LONG_FUTURES":  "\U0001f4c8",   # 📈
    "SHORT_FUTURES": "\U0001f4c9",   # 📉
    "BUY_SPOT":      "\U0001f7e2",   # 🟢
    "SELL_SPOT":     "\U0001f534",   # 🔴
}

_CLOSE_REASON_LABEL = {
    "tp2":          "TP2 ✅",
    "tp1_only":     "TP1 \U0001f7e0",
    "sl":           "SL ❌",
    "sl_breakeven": "SL breakeven \U0001f7e1",
    "timeout":      "Timeout ⏱",
    "manual":       "Manual",
}

# ── helpers ───────────────────────────────────────────────────────────────

def _elapsed_str(open_time_iso: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(open_time_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
        h = int(elapsed // 3600)
        m = int((elapsed % 3600) // 60)
        return f"{h}h {m}m" if h else f"{m}m"
    except Exception:
        return "?"


def _elapsed_hours(open_time_iso: str) -> float:
    try:
        dt = datetime.datetime.fromisoformat(open_time_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 0.0


def _fetch_prices(positions: List[Dict]) -> Dict[str, float]:
    """Obtiene el precio actual de cada símbolo en batch."""
    prices: Dict[str, float] = {}
    for pos in positions:
        sym = pos["symbol"]
        if sym in prices:
            continue
        try:
            p = (market_data.get_futures_price(sym)
                 if "FUTURES" in pos["action"]
                 else market_data.get_spot_price(sym))
            if p:
                prices[sym] = p
        except Exception:
            pass
    return prices


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


# ── TP/SL checker ─────────────────────────────────────────────────────────

def check_positions() -> None:
    """Verifica TP1/TP2/SL/timeout para todas las posiciones abiertas."""
    if not AUTO_TRADING_ENABLED:
        return

    positions = database.get_open_auto_positions()
    if not positions:
        return

    prices = _fetch_prices(positions)

    for pos in positions:
        sym   = pos["symbol"]
        price = prices.get(sym)
        if not price:
            continue

        action    = pos["action"]
        direction = _DIRECTION.get(action, 1)
        entry     = pos["entry_price"]
        size      = pos["size_usdt"]
        leverage  = pos.get("leverage") or 1
        tp1       = pos.get("tp1")
        tp2       = pos.get("tp2")
        sl        = pos.get("sl_current") or pos.get("sl")
        tp1_hit   = bool(pos.get("tp1_hit"))

        pnl = calc_pnl(pos, price)
        elapsed_hours = _elapsed_hours(pos["open_time"])

        # ── SL ─────────────────────────────────────────────────────────────
        sl_triggered = (direction == 1 and price <= sl) or (direction == -1 and price >= sl)
        if sl_triggered:
            reason = "sl_breakeven" if tp1_hit else "sl"
            # En paper se simula ejecucion en el stop configurado. Usar el ultimo
            # precio observado convierte un gap del monitor en una perdida ficticia.
            exit_price = sl if AUTO_TRADING_MODE == "paper" else price
            exit_pnl = calc_pnl(pos, exit_price)
            database.close_auto_position(
                pos["id"], exit_price, reason,
                exit_pnl["open_pnl_usdt"], exit_pnl["total_pnl_usdt"], exit_pnl["total_pnl_pct"],
            )
            logger.info("AUTO SL%s %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                        "(BE)" if tp1_hit else "", action, sym,
                        exit_price, exit_pnl["total_pnl_usdt"], exit_pnl["total_pnl_pct"])
            _notify_close(pos, exit_price, reason, exit_pnl)
            continue

        # ── TP2 (solo si TP1 ya fue tocado) ───────────────────────────────
        # Hard cap adicional para paper si faltara o fallara el stop.
        if AUTO_TRADING_MODE == "paper" and pnl["total_pnl_pct"] <= -abs(AUTO_TRADING_PAPER_MAX_LOSS_PCT):
            max_move = abs(AUTO_TRADING_PAPER_MAX_LOSS_PCT) / (100.0 * leverage)
            cap_price = entry * (1.0 - direction * max_move)
            cap_pnl = calc_pnl(pos, cap_price)
            database.close_auto_position(
                pos["id"], cap_price, "paper_hard_cap",
                cap_pnl["open_pnl_usdt"], cap_pnl["total_pnl_usdt"], cap_pnl["total_pnl_pct"],
            )
            logger.warning("AUTO PAPER HARD CAP %s %s | P&L %.2f%%", action, sym, cap_pnl["total_pnl_pct"])
            _notify_close(pos, cap_price, "paper_hard_cap", cap_pnl)
            continue

        if (
            AUTO_TRADING_RISK_CUT_ENABLED
            and not tp1_hit
            and elapsed_hours >= AUTO_TRADING_RISK_CUT_MIN_HOURS
            and pnl["total_pnl_pct"] <= -abs(AUTO_TRADING_RISK_CUT_LOSS_PCT)
        ):
            database.close_auto_position(
                pos["id"], price, "risk_cut",
                pnl["open_pnl_usdt"], pnl["total_pnl_usdt"], pnl["total_pnl_pct"],
            )
            logger.info(
                "AUTO RISK CUT %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                action, sym, price, pnl["total_pnl_usdt"], pnl["total_pnl_pct"],
            )
            _notify_close(pos, price, "risk_cut", pnl)
            continue

        if tp1_hit and tp2:
            tp2_hit = (direction == 1 and price >= tp2) or (direction == -1 and price <= tp2)
            if tp2_hit:
                database.close_auto_position(
                    pos["id"], price, "tp2",
                    pnl["open_pnl_usdt"], pnl["total_pnl_usdt"], pnl["total_pnl_pct"],
                )
                logger.info("AUTO TP2 %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                            action, sym, price, pnl["total_pnl_usdt"], pnl["total_pnl_pct"])
                _notify_close(pos, price, "tp2", pnl)
                continue

        # ── TP1 (solo si aún no fue tocado) ───────────────────────────────
        if not tp1_hit and tp1:
            tp1_reached = (direction == 1 and price >= tp1) or (direction == -1 and price <= tp1)
            if tp1_reached:
                # Cerrar 50% y mover SL a breakeven (entrada)
                half_pnl_pct  = direction * (tp1 - entry) / entry * leverage * 100
                tp1_pnl_usdt  = round(size * 0.5 * half_pnl_pct / 100, 4)
                database.update_auto_position_tp1(pos["id"], tp1_pnl_usdt, entry)
                logger.info("AUTO TP1 %s %s | tp1=%.6g | pnl_parcial=$%.2f | SL→BE",
                            action, sym, tp1, tp1_pnl_usdt)
                _notify_tp1(pos, tp1, tp1_pnl_usdt)

                # Si no hay TP2, cerrar la posición completa aquí
                if not tp2:
                    # Recalcular pnl con la posición ya actualizada como tp1_hit
                    pos_updated = {**pos, "tp1_hit": 1, "tp1_pnl_usdt": tp1_pnl_usdt, "sl_current": entry}
                    pnl2 = calc_pnl(pos_updated, price)
                    database.close_auto_position(
                        pos["id"], price, "tp1_only",
                        pnl2["open_pnl_usdt"], tp1_pnl_usdt, round(tp1_pnl_usdt / size * 100, 2),
                    )
                    logger.info("AUTO TP1_ONLY %s %s | sin TP2 → cerrado", action, sym)

        if elapsed_hours >= AUTO_TRADING_TIMEOUT_HOURS:
            database.close_auto_position(
                pos["id"], price, "timeout",
                pnl["open_pnl_usdt"], pnl["total_pnl_usdt"], pnl["total_pnl_pct"],
            )
            logger.info("AUTO TIMEOUT %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                        action, sym, price, pnl["total_pnl_usdt"], pnl["total_pnl_pct"])
            _notify_close(pos, price, "timeout", pnl)
            continue


def _notify_close(pos: Dict, exit_price: float, reason: str, pnl: Dict) -> None:
    """Envía notificación Telegram al cerrar posición."""
    emoji  = _ACTION_EMOJI.get(pos["action"], "⚠️")
    label  = _CLOSE_REASON_LABEL.get(reason, reason)
    sign   = "+" if pnl["total_pnl_usdt"] >= 0 else ""
    mode   = "📄" if pos.get("mode") == "paper" else "🔴"
    msg = (
        f"{mode} <b>AUTO-TRADE CERRADO</b>\n"
        f"{emoji} {pos['action'].replace('_',' ')} — {pos['symbol']}\n"
        f"Razón: {label}\n"
        f"Entrada: <code>{pos['entry_price']:.6g}</code>  →  Salida: <code>{exit_price:.6g}</code>\n"
        f"P&amp;L: <b><code>{sign}{pnl['total_pnl_usdt']:.2f}$</code> ({sign}{pnl['total_pnl_pct']:.2f}%)</b>\n"
        f"Tiempo: {_elapsed_str(pos['open_time'])}"
    )
    try:
        _post_telegram(msg)
    except Exception as exc:
        logger.warning("Error notificando cierre: %s", exc)


def _notify_tp1(pos: Dict, tp1_price: float, tp1_pnl: float) -> None:
    """Notifica TP1 parcial alcanzado."""
    emoji = _ACTION_EMOJI.get(pos["action"], "⚠️")
    mode  = "📄" if pos.get("mode") == "paper" else "🔴"
    sign  = "+" if tp1_pnl >= 0 else ""
    msg = (
        f"{mode} <b>TP1 ALCANZADO</b> — {pos['symbol']}\n"
        f"{emoji} {pos['action'].replace('_',' ')}\n"
        f"TP1: <code>{tp1_price:.6g}</code>  |  50% cerrado\n"
        f"Ganancia parcial: <b><code>{sign}{tp1_pnl:.2f}$</code></b>\n"
        f"SL movido a breakeven (<code>{pos['entry_price']:.6g}</code>)\n"
        f"Esperando TP2..."
    )
    try:
        _post_telegram(msg)
    except Exception as exc:
        logger.warning("Error notificando TP1: %s", exc)


# ── Reporte periódico (cada 10 min) ──────────────────────────────────────

def build_report(positions: List[Dict], prices: Dict[str, float]) -> str:
    """Construye el mensaje Telegram con estado de posiciones y P&L del día."""
    now_str    = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    mode_label = "PAPER \U0001f4c4" if AUTO_TRADING_MODE == "paper" else "REAL \U0001f534"
    lines = [
        f"\U0001f916 <b>Auto-Trading {mode_label}</b>",
        f"<i>{now_str}</i>",
        "",
    ]

    # ── Posiciones abiertas ────────────────────────────────────────────────
    if not positions:
        lines.append("\U0001f4c2 <b>Sin posiciones abiertas</b>")
    else:
        lines.append(f"\U0001f4c2 <b>Posiciones abiertas ({len(positions)}/{AUTO_TRADING_MAX_POSITIONS}):</b>")
        total_unrealized = 0.0

        for pos in positions:
            sym    = pos["symbol"]
            action = pos["action"]
            entry  = pos["entry_price"]
            price  = prices.get(sym, entry)
            tp1    = pos.get("tp1")
            tp2    = pos.get("tp2")
            sl_cur = pos.get("sl_current") or pos.get("sl")
            lev    = pos.get("leverage") or 1
            emoji  = _ACTION_EMOJI.get(action, "")
            tp1_hit = bool(pos.get("tp1_hit"))

            pnl = calc_pnl(pos, price)
            total_unrealized += pnl["total_pnl_usdt"]
            pnl_sign = "+" if pnl["total_pnl_usdt"] >= 0 else ""

            lev_str = f" ⚡{lev}x" if lev > 1 else ""
            tp1_str = "\U0001f535 BE" if tp1_hit else (f"TP1:<code>{tp1:.6g}</code>" if tp1 else "")
            tp2_str = f"TP2:<code>{tp2:.6g}</code>" if tp2 else ""

            lines += [
                "",
                f"{emoji} <b>{action.replace('_',' ')} — {sym}</b>{lev_str}  ⏱ {_elapsed_str(pos['open_time'])}",
                f"  Entrada:<code>{entry:.6g}</code>  Actual:<code>{price:.6g}</code>",
                f"  P&amp;L: <b><code>{pnl_sign}{pnl['total_pnl_usdt']:.2f}$</code> ({pnl_sign}{pnl['total_pnl_pct']:.2f}%)</b>",
                f"  {tp1_str}  {tp2_str}  SL:<code>{sl_cur:.6g}</code>",
            ]

        no_sign = "+" if total_unrealized >= 0 else ""
        lines += [
            "",
            f"\U0001f4b0 No realizado: <b><code>{no_sign}{total_unrealized:.2f}$</code></b>",
        ]

    # ── Resumen del día ────────────────────────────────────────────────────
    try:
        s = database.get_auto_positions_summary(since_hours=24)
        if s["total"] > 0:
            pnl_sign = "+" if s["total_pnl_usdt"] >= 0 else ""
            roi = s["total_pnl_usdt"] / AUTO_TRADING_CAPITAL_USDT * 100
            roi_sign = "+" if roi >= 0 else ""
            lines += [
                "",
                "─" * 21,
                f"\U0001f4ca <b>ltimas 24h ({s['total']} cerradas):</b>",
                f"  ✅{s['tp2_count']}TP2  \U0001f7e0{s['tp1_count']}TP1  ❌{s['sl_count']}SL  ⏱{s['timeout_count']}TO",
                f"  P&amp;L realizado: <b><code>{pnl_sign}{s['total_pnl_usdt']:.2f}$</code></b>",
                f"  ROI sobre capital: <code>{roi_sign}{roi:.2f}%</code>",
            ]
    except Exception:
        pass

    return "\n".join(lines)


def send_positions_report() -> None:
    """Obtiene posiciones actuales, construye y envía el reporte a Telegram."""
    if not AUTO_TRADING_ENABLED:
        return
    try:
        positions = database.get_open_auto_positions()
        prices    = _fetch_prices(positions)
        msg       = build_report(positions, prices)
        _post_telegram(msg)
        logger.info("[auto-trading] Reporte de posiciones enviado")
    except Exception as exc:
        logger.warning("[auto-trading] Error en reporte de posiciones: %s", exc)


def log_pnl_overview() -> None:
    """Registra en el log el PnL acumulado realizado por categoría: futures, spot y micro-scalping."""
    try:
        pnl = database.get_pnl_overview()
        f, s, m = pnl["futures"], pnl["spot"], pnl["micro_scalp"]
        logger.info(
            "[pnl] Futures: %+.2f$ (%d cerradas, %d abiertas, WR %.1f%%) | "
            "Spot: %+.2f$ (%d cerradas, %d abiertas, WR %.1f%%) | "
            "Micro-scalp: %+.2f%% acum (%d cerradas, %d abiertas, WR %.1f%%)",
            f["pnl_usdt"], f["closed"], f["open"], f["winrate_pct"],
            s["pnl_usdt"], s["closed"], s["open"], s["winrate_pct"],
            m["pnl_pct_total"], m["closed"], m["open"], m["winrate_pct"],
        )
    except Exception:
        logger.exception("Error en log_pnl_overview")
