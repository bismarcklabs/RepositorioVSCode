"""Dos variantes de la estrategia Value Area + CVD, para comparar cual
metodo de calculo de value area rinde mejor (pedido explicito: correr
ambas en paralelo y comparar performance despues, ej. con /diagnostico-integral).

Comparten toda la logica de sesgo/breakout/divergencia en value_area_core.py
— solo difieren en como se calculan VAH/VAL.
"""
import os
from typing import Dict, Optional

from app.strategies.base import Strategy, StrategyContext, StrategySignal
from app.strategies.value_area_core import (
    _SymbolState,
    compute_value_area_range,
    compute_value_area_volume70,
    evaluate_value_area_cvd,
)


class ValueAreaRangeStrategy(Strategy):
    """Value area = high/low simple de la sesion overnight (4:30pm-9:30am NY)."""
    id = "value_area_range"

    def __init__(self) -> None:
        self.enabled = os.getenv("STRATEGY_VALUE_AREA_RANGE_ENABLED", "false").lower() == "true"
        self.capital_usdt = float(os.getenv("STRATEGY_VALUE_AREA_RANGE_CAPITAL_USDT", "100"))
        self.position_size_pct = float(os.getenv("STRATEGY_VALUE_AREA_RANGE_POSITION_SIZE_PCT", "0.02"))
        self.timeout_hours = float(os.getenv("STRATEGY_VALUE_AREA_RANGE_TIMEOUT_HOURS", "6"))
        self.max_open_positions = int(os.getenv("STRATEGY_VALUE_AREA_RANGE_MAX_POSITIONS", "3"))
        self._state: Dict[str, _SymbolState] = {}

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignal]:
        return evaluate_value_area_cvd(self.id, ctx, self._state, compute_value_area_range)


class ValueAreaVolume70Strategy(Strategy):
    """Value area = 70% del volumen alrededor del POC (auction market theory)."""
    id = "value_area_volume70"

    def __init__(self) -> None:
        self.enabled = os.getenv("STRATEGY_VALUE_AREA_VOLUME70_ENABLED", "false").lower() == "true"
        self.capital_usdt = float(os.getenv("STRATEGY_VALUE_AREA_VOLUME70_CAPITAL_USDT", "100"))
        self.position_size_pct = float(os.getenv("STRATEGY_VALUE_AREA_VOLUME70_POSITION_SIZE_PCT", "0.02"))
        self.timeout_hours = float(os.getenv("STRATEGY_VALUE_AREA_VOLUME70_TIMEOUT_HOURS", "6"))
        self.max_open_positions = int(os.getenv("STRATEGY_VALUE_AREA_VOLUME70_MAX_POSITIONS", "3"))
        self._state: Dict[str, _SymbolState] = {}

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignal]:
        return evaluate_value_area_cvd(self.id, ctx, self._state, compute_value_area_volume70)
