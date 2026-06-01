"""Modelo de datos para alertas de trading."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TradeAlert:
    symbol: str
    action: str           # LONG_FUTURES, SHORT_FUTURES, BUY_SPOT, SELL_SPOT
    market: str           # FUTURES | SPOT
    confidence: int       # 0-100
    price: float
    confluence_score: int

    # Niveles operables
    timing: str           # NOW | WAIT_FOR_PULLBACK | WAIT_FOR_BREAKOUT
    entry: float
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward_1: float
    risk_reward_2: float

    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    invalidation: List[str] = field(default_factory=list)
    position_note: str = ""

    @classmethod
    def from_row(cls, row: dict) -> Optional["TradeAlert"]:
        """Construye un TradeAlert desde una fila del scanner.

        Retorna None si la acción es WAIT o si no hay setup operable.
        """
        if row.get("action") == "WAIT":
            return None
        setup = row.get("setup")
        if not setup:
            return None
        rec = row  # row ya tiene todos los campos necesarios

        return cls(
            symbol=rec["symbol"],
            action=rec["action"],
            market=rec["market"],
            confidence=rec["confidence"],
            price=rec["price"],
            confluence_score=rec["score"],
            timing=setup["timing"],
            entry=setup["entry"],
            entry_zone_low=setup["entry_zone_low"],
            entry_zone_high=setup["entry_zone_high"],
            stop_loss=setup["stop_loss"],
            take_profit_1=setup["take_profit_1"],
            take_profit_2=setup["take_profit_2"],
            risk_reward_1=setup["risk_reward_1"],
            risk_reward_2=setup["risk_reward_2"],
            reasons=rec.get("reasons", []),
            warnings=rec.get("warnings", []),
            invalidation=rec.get("invalidation", []),
            position_note=setup.get("position_note", ""),
        )

    @property
    def subject(self) -> str:
        return f"[Crypto Scanner] {self.action} {self.symbol} | {self.confidence}%"

    def is_valid(self) -> bool:
        return (
            self.entry > 0.0
            and self.stop_loss > 0.0
            and self.take_profit_1 > 0.0
            and self.stop_loss != self.entry
        )
