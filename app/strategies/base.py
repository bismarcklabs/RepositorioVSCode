"""Interfaces del framework multi-estrategia.

StrategyContext empaqueta todo lo que _scan_symbol ya calculo para un
simbolo (cero fetches nuevos). StrategySignal es lo que una estrategia
devuelve cuando quiere abrir una posicion paper — direction es siempre
explicito (LONG/SHORT), nunca inferido de un string de action arbitrario
(a diferencia de auto_trader._DIRECTION).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StrategyContext:
    symbol: str
    timestamp: str
    price: float
    futures_price: float
    technical: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    footprint: Dict[str, Any] = field(default_factory=dict)
    orderbook: Dict[str, Any] = field(default_factory=dict)
    funding: float = 0.0
    open_interest: float = 0.0
    oi_change_pct: float = 0.0
    structure: Optional[Dict[str, Any]] = None
    structure_micro: Optional[Dict[str, Any]] = None
    score_data: Dict[str, Any] = field(default_factory=dict)
    multi_exchange: Optional[Dict[str, Any]] = None
    market_regime: Dict[str, Any] = field(default_factory=dict)
    klines_1m: List[Any] = field(default_factory=list)
    klines_15m: List[Any] = field(default_factory=list)
    klines_3m: List[Any] = field(default_factory=list)
    # Escape hatch: el dict completo que produce _scan_symbol, por si una
    # estrategia necesita algo que aun no se promovio a un campo propio.
    raw_result: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_result(cls, result: Dict[str, Any]) -> "StrategyContext":
        return cls(
            symbol=result.get("symbol", ""),
            timestamp=result.get("timestamp", ""),
            price=result.get("price", 0.0) or 0.0,
            futures_price=result.get("futures_price", 0.0) or 0.0,
            technical=result.get("technical") or {},
            metrics=result.get("metrics") or {},
            footprint=result.get("footprint") or {},
            orderbook=result.get("orderbook") or {},
            funding=result.get("funding", 0.0) or 0.0,
            open_interest=result.get("open_interest", 0.0) or 0.0,
            oi_change_pct=result.get("oi_change_pct", 0.0) or 0.0,
            structure=result.get("structure"),
            structure_micro=result.get("structure_micro"),
            score_data=result.get("score_data") or {},
            multi_exchange=result.get("multi_exchange"),
            market_regime=result.get("market_regime") or {},
            klines_1m=result.get("klines_1m") or [],
            klines_15m=result.get("klines_15m") or [],
            klines_3m=result.get("klines_3m") or [],
            raw_result=result,
        )


@dataclass
class StrategySignal:
    direction: str                              # "LONG" | "SHORT" — explicito
    entry: float
    stop_loss: float
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    leverage: int = 1
    confidence: int = 0
    score: int = 0
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timeout_hours: Optional[float] = None       # override puntual; si None usa el de la estrategia


class Strategy(ABC):
    """Clase base de una estrategia del framework. Cada estrategia nueva es
    un archivo que subclasea esto y se registra en app/strategies/registry.py.
    """
    id: str = "base"
    enabled: bool = False

    # Parametros de riesgo/posicion — cada subclase los fija en __init__,
    # tipicamente leyendo sus propios env vars STRATEGY_<ID>_*.
    timeout_hours: float = 4.0
    capital_usdt: float = 100.0
    position_size_pct: float = 0.02
    max_open_positions: int = 3
    loss_cooldown_count: int = 2
    loss_cooldown_hours: float = 6.0

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignal]:
        """Evalua el contexto de un simbolo y retorna una señal, o None."""
        raise NotImplementedError
