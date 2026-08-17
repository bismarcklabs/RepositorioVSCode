"""Registro explicito de estrategias del framework multi-estrategia.

Sin auto-discovery: agregar una estrategia nueva es instanciarla aqui.
"""
from typing import List

from app.strategies.agile_futures import AgileFuturesStrategy
from app.strategies.base import Strategy
from app.strategies.example_strategy import ExampleRsiVwapStrategy
from app.strategies.value_area_strategies import (
    ValueAreaRangeStrategy,
    ValueAreaVolume70Strategy,
)

STRATEGIES: List[Strategy] = [
    ExampleRsiVwapStrategy(),
    ValueAreaRangeStrategy(),
    ValueAreaVolume70Strategy(),
    AgileFuturesStrategy(),
]


def get_enabled_strategies() -> List[Strategy]:
    return [s for s in STRATEGIES if s.enabled]
