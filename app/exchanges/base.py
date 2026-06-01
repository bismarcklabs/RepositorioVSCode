"""Tipos comunes e interfaz de provider para todos los exchanges."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore


@dataclass
class ExchangeTicker:
    exchange: str
    symbol: str             # símbolo específico del exchange: "BTCUSDT", "BTC-USD", "XBT/USD"
    normalized_symbol: str  # base normalizado: "BTC"
    price: Optional[float]
    volume_24h: Optional[float]
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_pct: Optional[float] = None
    timestamp: Optional[str] = None
    ok: bool = True
    error: Optional[str] = None


@dataclass
class ExchangeOrderBook:
    exchange: str
    symbol: str
    normalized_symbol: str
    bids: List[Tuple[float, float]] = field(default_factory=list)  # (price, size)
    asks: List[Tuple[float, float]] = field(default_factory=list)
    timestamp: Optional[str] = None
    ok: bool = True
    error: Optional[str] = None


@dataclass
class ExchangeKline:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _failed_ticker(exchange: str, symbol: str, normalized: str, error: str) -> ExchangeTicker:
    return ExchangeTicker(
        exchange=exchange,
        symbol=symbol,
        normalized_symbol=normalized,
        price=None,
        volume_24h=None,
        ok=False,
        error=error,
    )


def _failed_orderbook(exchange: str, symbol: str, normalized: str, error: str) -> ExchangeOrderBook:
    return ExchangeOrderBook(
        exchange=exchange,
        symbol=symbol,
        normalized_symbol=normalized,
        ok=False,
        error=error,
    )


@runtime_checkable
class ExchangeProvider(Protocol):
    name: str

    def get_ticker(self, symbol: str, normalized_symbol: str) -> ExchangeTicker: ...

    def get_orderbook(self, symbol: str, normalized_symbol: str,
                      limit: int = 50) -> ExchangeOrderBook: ...

    def get_klines(self, symbol: str, interval: str = "1m",
                   limit: int = 100) -> List[ExchangeKline]: ...
