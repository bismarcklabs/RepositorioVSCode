"""Motor del framework multi-estrategia: evaluacion por ciclo y lifecycle
de posiciones paper (SL / TP1 parcial+breakeven / TP2 / timeout).

Generalizacion MINIMA de auto_trader.py/position_monitor.py: sin
risk_cut ni paper_hard_cap (esos existen alli por la friccion de trading
real/apalancado) y sin recover_gap_positions (tolerable en paper — en el
peor caso una posicion se resuelve un ciclo tarde). Se puede agregar por
estrategia puntual mas adelante si hace falta.

100% aditivo: no toca trade_alerts/auto_positions/micro_scalp_alerts ni
los modulos auto_trader.py/position_monitor.py/trade_advisor.py.
"""
import datetime
import logging
from typing import Any, Dict, List, Optional

from app import database, market_data
from app.config import AUTO_TRADING_FEE_RATE, MULTI_STRATEGY_ENABLED
from app.strategies.base import Strategy, StrategyContext, StrategySignal
from app.strategies.registry import get_enabled_strategies

logger = logging.getLogger("strategy_engine")


def _direction_sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1


def _levels_are_valid(direction: str, entry: float,
                      tp1: Optional[float], tp2: Optional[float],
                      sl: float) -> bool:
    if entry <= 0 or sl <= 0:
        return False
    if direction == "LONG":
        if sl >= entry:
            return False
        if tp1 is not None and tp1 <= entry:
            return False
        if tp2 is not None and tp2 < (tp1 or entry):
            return False
    else:
        if sl <= entry:
            return False
        if tp1 is not None and tp1 >= entry:
            return False
        if tp2 is not None and tp2 > (tp1 or entry):
            return False
    return True


def calc_pnl(position: Dict[str, Any], current_price: float) -> Dict[str, float]:
    """Calcula P&L de una posicion de estrategia (misma mecanica que
    auto_trader.calc_pnl, pero usando direction explicito en vez de
    inferirlo de un string de action)."""
    entry     = position["entry_price"]
    size      = position["size_usdt"]
    leverage  = position.get("leverage") or 1
    direction = _direction_sign(position["direction"])
    tp1_hit   = bool(position.get("tp1_hit"))
    tp1_pnl   = position.get("tp1_pnl_usdt") or 0.0

    open_size = size * 0.5 if tp1_hit else size
    pct = direction * (current_price - entry) / entry * leverage * 100
    open_pnl_usdt = open_size * pct / 100

    notional = size * leverage
    fees_usdt = notional * AUTO_TRADING_FEE_RATE
    if tp1_hit:
        fees_usdt += notional * 0.5 * AUTO_TRADING_FEE_RATE
    fees_usdt += open_size * leverage * AUTO_TRADING_FEE_RATE

    total_pnl_usdt = round(tp1_pnl + open_pnl_usdt - fees_usdt, 4)
    total_pnl_pct  = round(total_pnl_usdt / size * 100, 2) if size else 0.0

    return {
        "pnl_pct":        round(pct, 2),
        "open_pnl_usdt":  round(open_pnl_usdt, 4),
        "fees_usdt":      round(fees_usdt, 4),
        "total_pnl_usdt": total_pnl_usdt,
        "total_pnl_pct":  total_pnl_pct,
    }


def _process_signal(strategy: Strategy, ctx: StrategyContext, signal: StrategySignal) -> None:
    if not _levels_are_valid(signal.direction, signal.entry, signal.take_profit_1,
                             signal.take_profit_2, signal.stop_loss):
        logger.debug("STRATEGY SKIP %s %s: niveles incoherentes", strategy.id, ctx.symbol)
        return

    open_positions = database.get_open_strategy_positions(strategy.id)

    if len(open_positions) >= strategy.max_open_positions:
        logger.debug("STRATEGY SKIP %s %s: limite %d posiciones abiertas",
                     strategy.id, ctx.symbol, strategy.max_open_positions)
        return

    if any(p["symbol"] == ctx.symbol for p in open_positions):
        logger.debug("STRATEGY SKIP %s %s: posicion ya abierta", strategy.id, ctx.symbol)
        return

    if database.count_recent_strategy_losses(
        strategy.id, ctx.symbol, signal.direction, strategy.loss_cooldown_hours
    ) >= strategy.loss_cooldown_count:
        logger.debug("STRATEGY SKIP %s %s: cooldown por perdidas recientes", strategy.id, ctx.symbol)
        return

    size_usdt = strategy.capital_usdt * strategy.position_size_pct
    if size_usdt <= 0:
        return

    timeout_hours = signal.timeout_hours if signal.timeout_hours is not None else strategy.timeout_hours

    alert_id = database.insert_strategy_alert({
        "timestamp":     ctx.timestamp,
        "strategy_id":   strategy.id,
        "symbol":        ctx.symbol,
        "direction":     signal.direction,
        "score":         signal.score,
        "confidence":    signal.confidence,
        "entry":         signal.entry,
        "take_profit_1": signal.take_profit_1,
        "take_profit_2": signal.take_profit_2,
        "stop_loss":     signal.stop_loss,
        "leverage":      signal.leverage,
        "timeout_hours": timeout_hours,
        "reasons":       signal.reasons,
        "warnings":      signal.warnings,
    })

    position_id = database.insert_strategy_position({
        "alert_id":      alert_id,
        "strategy_id":   strategy.id,
        "symbol":        ctx.symbol,
        "direction":     signal.direction,
        "mode":          "paper",
        "open_time":     ctx.timestamp,
        "entry_price":   signal.entry,
        "size_usdt":     size_usdt,
        "leverage":      signal.leverage,
        "timeout_hours": timeout_hours,
        "tp1":           signal.take_profit_1,
        "tp2":           signal.take_profit_2,
        "sl":            signal.stop_loss,
        "sl_current":    signal.stop_loss,
    })

    logger.info(
        "STRATEGY ABRIR %s %s %s | entry=%.6g | $%.2f | lev=%dx | TP1=%s TP2=%s SL=%.6g | pos_id=%d",
        strategy.id, signal.direction, ctx.symbol, signal.entry, size_usdt, signal.leverage,
        f"{signal.take_profit_1:.6g}" if signal.take_profit_1 else "—",
        f"{signal.take_profit_2:.6g}" if signal.take_profit_2 else "—",
        signal.stop_loss, position_id,
    )


def evaluate_all(result: Dict[str, Any]) -> None:
    """Evalua todas las estrategias habilitadas contra un result ya
    computado por _scan_symbol. Solo lectura sobre result/ctx."""
    if not MULTI_STRATEGY_ENABLED:
        return

    strategies = get_enabled_strategies()
    if not strategies:
        return

    ctx = StrategyContext.from_result(result)

    for strategy in strategies:
        try:
            signal = strategy.evaluate(ctx)
        except Exception:
            logger.exception("Error evaluando estrategia %s para %s", strategy.id, ctx.symbol)
            continue
        if signal is None:
            continue
        try:
            _process_signal(strategy, ctx, signal)
        except Exception:
            logger.exception("Error procesando señal de %s para %s", strategy.id, ctx.symbol)


def _elapsed_hours(open_time_iso: str) -> float:
    try:
        dt = datetime.datetime.fromisoformat(open_time_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 0.0


def _fetch_prices(
    positions: List[Dict[str, Any]],
    scanned_prices: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    """Precio actual por simbolo. Intenta futuros primero (soporta LONG y
    SHORT); si no hay mercado de futuros para el simbolo, usa spot.

    Reusa scanned_prices (ya calculados por _scan_symbol en este ciclo) cuando
    el simbolo esta entre los candidatos escaneados, evitando refetch."""
    prices: Dict[str, float] = {}
    for pos in positions:
        sym = pos["symbol"]
        if sym in prices:
            continue
        if scanned_prices and sym in scanned_prices:
            p = scanned_prices[sym].get("futures") or scanned_prices[sym].get("spot")
            if p:
                prices[sym] = p
                continue
        try:
            p = market_data.get_futures_price(sym) or market_data.get_spot_price(sym)
            if p:
                prices[sym] = p
        except Exception:
            pass
    return prices


def check_positions(scanned_prices: Optional[Dict[str, Dict[str, float]]] = None) -> None:
    """Verifica SL / TP1 parcial+breakeven / TP2 / timeout para todas las
    posiciones paper abiertas de todas las estrategias."""
    if not MULTI_STRATEGY_ENABLED:
        return

    positions = database.get_open_strategy_positions()
    if not positions:
        return

    prices = _fetch_prices(positions, scanned_prices)

    for pos in positions:
        sym = pos["symbol"]
        price = prices.get(sym)
        if not price:
            continue

        direction = pos["direction"]
        sign      = _direction_sign(direction)
        entry     = pos["entry_price"]
        size      = pos["size_usdt"]
        leverage  = pos.get("leverage") or 1
        tp1       = pos.get("tp1")
        tp2       = pos.get("tp2")
        sl        = pos.get("sl_current") or pos.get("sl")
        tp1_hit   = bool(pos.get("tp1_hit"))
        timeout_hours = pos.get("timeout_hours") or 4.0

        pnl = calc_pnl(pos, price)
        elapsed_hours = _elapsed_hours(pos["open_time"])

        # ── SL ──────────────────────────────────────────────────────────
        sl_triggered = (sign == 1 and price <= sl) or (sign == -1 and price >= sl)
        if sl_triggered:
            reason = "sl_breakeven" if tp1_hit else "sl"
            exit_price = sl  # paper: simular ejecucion exacta en el stop
            exit_pnl = calc_pnl(pos, exit_price)
            database.close_strategy_position(
                pos["id"], exit_price, reason,
                exit_pnl["open_pnl_usdt"], exit_pnl["total_pnl_usdt"], exit_pnl["total_pnl_pct"],
            )
            logger.info("STRATEGY SL%s %s %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                        "(BE)" if tp1_hit else "", pos["strategy_id"], direction, sym,
                        exit_price, exit_pnl["total_pnl_usdt"], exit_pnl["total_pnl_pct"])
            continue

        # ── TP2 (solo si TP1 ya fue tocado) ──────────────────────────────
        if tp1_hit and tp2:
            tp2_hit = (sign == 1 and price >= tp2) or (sign == -1 and price <= tp2)
            if tp2_hit:
                database.close_strategy_position(
                    pos["id"], price, "tp2",
                    pnl["open_pnl_usdt"], pnl["total_pnl_usdt"], pnl["total_pnl_pct"],
                )
                logger.info("STRATEGY TP2 %s %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                            pos["strategy_id"], direction, sym, price,
                            pnl["total_pnl_usdt"], pnl["total_pnl_pct"])
                continue

        # ── TP1 (solo si aun no fue tocado) ──────────────────────────────
        if not tp1_hit and tp1:
            tp1_reached = (sign == 1 and price >= tp1) or (sign == -1 and price <= tp1)
            if tp1_reached:
                half_pnl_pct = sign * (tp1 - entry) / entry * leverage * 100
                tp1_pnl_usdt = round(size * 0.5 * half_pnl_pct / 100, 4)
                database.update_strategy_position_tp1(pos["id"], tp1_pnl_usdt, entry)
                logger.info("STRATEGY TP1 %s %s %s | tp1=%.6g | parcial=$%.2f | SL->BE",
                            pos["strategy_id"], direction, sym, tp1, tp1_pnl_usdt)

                if not tp2:
                    pos_updated = {**pos, "tp1_hit": 1, "tp1_pnl_usdt": tp1_pnl_usdt, "sl_current": entry}
                    pnl2 = calc_pnl(pos_updated, price)
                    database.close_strategy_position(
                        pos["id"], price, "tp1_only",
                        pnl2["open_pnl_usdt"], pnl2["total_pnl_usdt"], pnl2["total_pnl_pct"],
                    )
                    logger.info("STRATEGY TP1_ONLY %s %s %s | sin TP2 -> cerrado",
                                pos["strategy_id"], direction, sym)
                continue

        # ── Timeout ───────────────────────────────────────────────────────
        if elapsed_hours >= timeout_hours:
            database.close_strategy_position(
                pos["id"], price, "timeout",
                pnl["open_pnl_usdt"], pnl["total_pnl_usdt"], pnl["total_pnl_pct"],
            )
            logger.info("STRATEGY TIMEOUT %s %s %s | exit=%.6g | P&L $%.2f (%.2f%%)",
                        pos["strategy_id"], direction, sym, price,
                        pnl["total_pnl_usdt"], pnl["total_pnl_pct"])
            continue
