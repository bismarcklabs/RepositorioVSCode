"""Estrategia de ejemplo — RSI extremo + reversion a VWAP.

Sirve unicamente para validar el framework multi-estrategia de punta a
punta (evaluate -> gates -> apertura paper -> lifecycle SL/TP/timeout)
antes de que existan criterios reales. Se puede desactivar o borrar sin
afectar nada mas.
"""
import os
from typing import Optional

from app.strategies.base import Strategy, StrategyContext, StrategySignal

_RSI_OVERSOLD = 25.0
_RSI_OVERBOUGHT = 75.0


class ExampleRsiVwapStrategy(Strategy):
    id = "example_rsi_vwap"

    def __init__(self) -> None:
        self.enabled = os.getenv("STRATEGY_EXAMPLE_RSI_VWAP_ENABLED", "false").lower() == "true"
        self.capital_usdt = float(os.getenv("STRATEGY_EXAMPLE_RSI_VWAP_CAPITAL_USDT", "100"))
        self.position_size_pct = float(os.getenv("STRATEGY_EXAMPLE_RSI_VWAP_POSITION_SIZE_PCT", "0.02"))
        self.timeout_hours = float(os.getenv("STRATEGY_EXAMPLE_RSI_VWAP_TIMEOUT_HOURS", "4"))
        self.max_open_positions = int(os.getenv("STRATEGY_EXAMPLE_RSI_VWAP_MAX_POSITIONS", "3"))

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignal]:
        technical = ctx.technical
        rsi = float(technical.get("rsi", 50.0) or 50.0)
        above_vwap = bool(technical.get("above_vwap", True))
        price = ctx.price
        if price <= 0:
            return None

        if rsi <= _RSI_OVERSOLD and not above_vwap:
            direction = "LONG"
            reasons = [f"RSI sobrevendido ({rsi:.1f}) bajo VWAP"]
        elif rsi >= _RSI_OVERBOUGHT and above_vwap:
            direction = "SHORT"
            reasons = [f"RSI sobrecomprado ({rsi:.1f}) sobre VWAP"]
        else:
            return None

        sl_pct = 0.02
        tp1_pct = 0.02
        tp2_pct = 0.04
        sign = 1 if direction == "LONG" else -1

        return StrategySignal(
            direction=direction,
            entry=price,
            stop_loss=round(price * (1 - sign * sl_pct), 8),
            take_profit_1=round(price * (1 + sign * tp1_pct), 8),
            take_profit_2=round(price * (1 + sign * tp2_pct), 8),
            leverage=1,
            confidence=60,
            score=60,
            reasons=reasons,
        )
