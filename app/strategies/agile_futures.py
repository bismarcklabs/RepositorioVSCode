"""Estrategia "futuros agil": mismo espiritu reactivo de micro_scalper.py
(exigir que el movimiento ya este en marcha, no anticipar rupturas como
level_breakout/pattern_break) pero con apalancamiento moderado y fijo, SL/TP
conscientes de estructura, y un horizonte mas largo (>30 min, no el scalp de
~30 min de micro ni las 4h del pipeline principal de futuros).

Motivacion (ver plan aprobado / HANDOFF): el pipeline principal de futuros
tiene PnL historico negativo porque el apalancamiento (hasta 5x) amplifica el
SL minimo de 2% a perdidas de -8/-9%, mientras el movimiento real favorable en
4h rara vez alcanza el TP1 exigido (>=1.5R). Esta estrategia ataca la causa
raiz: apalancamiento fijo mas bajo, TP recortado contra el nivel S/R opuesto
(igual que ya hace micro_scalper._build_setup) en vez de un R:R fijo que casi
nunca se alcanza, y una entrada reactiva en vez de anticipatoria.

Cadencia: la deteccion de señal se evalua cada 3 minutos por simbolo (no cada
ciclo del scanner, ~60s) usando el CVD acumulado de esa ventana de 3 min —
mismo patron de throttle que el preview-window de value_area_core.py. El
chequeo de posiciones abiertas (SL/TP/timeout) lo sigue haciendo el motor
generico (engine.check_positions()) cada ciclo normal, sin relacion con este
throttle.
"""
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.strategies.base import Strategy, StrategyContext, StrategySignal

_EVAL_INTERVAL_SECONDS = float(os.getenv("STRATEGY_AGILE_FUTURES_EVAL_INTERVAL_SECONDS", "180"))


@dataclass
class _SymbolWindow:
    cvd_window: float = 0.0
    last_eval_ts: float = 0.0
    window_start_ts: float = field(default_factory=time.time)


def _nearest_opposing_level(structure: Optional[Dict], direction: str) -> Optional[float]:
    struct = structure or {}
    lvl = struct.get("nearest_resistance") if direction == "LONG" else struct.get("nearest_support")
    if lvl and lvl.get("price"):
        return float(lvl["price"])
    return None


def _build_signal(
    direction: str,
    price: float,
    atr: float,
    structure: Optional[Dict],
    reasons: List[str],
    *,
    sl_pct: float,
    tp1_r: float,
    tp2_r: float,
    leverage: int,
) -> StrategySignal:
    sign = 1 if direction == "LONG" else -1

    sl_dist = max(price * sl_pct, atr * 1.0) if atr > 0 else price * sl_pct
    sl = price - sign * sl_dist
    tp1_dist = sl_dist * tp1_r
    tp2_dist = sl_dist * tp2_r

    # Recortar el TP contra el nivel S/R opuesto mas cercano en vez de exigir
    # que el precio atraviese una pared — misma idea que micro_scalper.
    opposing = _nearest_opposing_level(structure, direction)
    if opposing and price > 0:
        opp_dist = abs(opposing - price)
        min_dist = price * (sl_pct * 0.6)   # piso: no degenerar el TP
        if opp_dist > min_dist:
            tp1_dist = min(tp1_dist, max(opp_dist * 0.85, min_dist))
            tp2_dist = min(tp2_dist, max(opp_dist * 0.95, tp1_dist))

    tp1 = price + sign * tp1_dist
    tp2 = price + sign * tp2_dist

    return StrategySignal(
        direction=direction,
        entry=round(price, 8),
        stop_loss=round(sl, 8),
        take_profit_1=round(tp1, 8),
        take_profit_2=round(tp2, 8),
        leverage=leverage,
        confidence=65,
        score=65,
        reasons=reasons,
    )


class AgileFuturesStrategy(Strategy):
    """Entrada reactiva (movimiento ya en marcha, como micro-scalp) con
    apalancamiento moderado y objetivo de >30 min — paper, capital propio."""
    id = "agile_futures"

    def __init__(self) -> None:
        self.enabled = os.getenv("STRATEGY_AGILE_FUTURES_ENABLED", "false").lower() == "true"
        self.capital_usdt = float(os.getenv("STRATEGY_AGILE_FUTURES_CAPITAL_USDT", "150"))
        self.position_size_pct = float(os.getenv("STRATEGY_AGILE_FUTURES_POSITION_SIZE_PCT", "0.02"))
        # Horizonte objetivo >30min (mas largo que micro), bastante mas corto
        # que las 4h del pipeline principal — timeout propio en horas.
        self.timeout_hours = float(os.getenv("STRATEGY_AGILE_FUTURES_TIMEOUT_MINUTES", "100")) / 60.0
        self.max_open_positions = int(os.getenv("STRATEGY_AGILE_FUTURES_MAX_POSITIONS", "4"))
        self.loss_cooldown_count = int(os.getenv("STRATEGY_AGILE_FUTURES_LOSS_COOLDOWN_COUNT", "2"))
        self.loss_cooldown_hours = float(os.getenv("STRATEGY_AGILE_FUTURES_LOSS_COOLDOWN_HOURS", "3"))

        # Apalancamiento moderado y FIJO — a diferencia de entry_exit.py, que
        # llega hasta 5x en los stops mas ajustados (causa raiz del R:R roto
        # del pipeline principal).
        self._leverage = int(os.getenv("STRATEGY_AGILE_FUTURES_LEVERAGE", "3"))
        self._sl_pct = float(os.getenv("STRATEGY_AGILE_FUTURES_SL_PCT", "0.008"))
        self._tp1_r = float(os.getenv("STRATEGY_AGILE_FUTURES_TP1_R", "1.3"))
        self._tp2_r = float(os.getenv("STRATEGY_AGILE_FUTURES_TP2_R", "2.2"))

        # Umbrales de entrada reactiva — exigir que el movimiento ya este en
        # marcha (igual que micro_scalper), no anticipar rupturas de nivel.
        self._min_rvol = float(os.getenv("STRATEGY_AGILE_FUTURES_MIN_RVOL", "1.8"))
        self._min_return_15m = float(os.getenv("STRATEGY_AGILE_FUTURES_MIN_RETURN_15M", "0.30"))

        self._windows: Dict[str, _SymbolWindow] = {}

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignal]:
        price = ctx.futures_price or ctx.price
        if price <= 0:
            return None

        win = self._windows.setdefault(ctx.symbol, _SymbolWindow())
        # El CVD de la ventana de 3 min se acumula CADA ciclo (gratis, ya viene
        # del websocket) — pero la señal solo se evalua cada 3 min, sincronizada
        # con esa ventana, no con el ciclo de 60s del scanner.
        win.cvd_window += float(ctx.metrics.get("delta", 0.0) or 0.0)

        now = time.time()
        if now - win.last_eval_ts < _EVAL_INTERVAL_SECONDS:
            return None

        cvd_window = win.cvd_window
        win.cvd_window = 0.0
        win.last_eval_ts = now

        technical = ctx.technical or {}
        rvol = float(technical.get("relative_volume", 1.0) or 1.0)
        return_15m = float(technical.get("return_15m", 0.0) or 0.0)
        cvd_15m = float(ctx.metrics.get("cvd_15m", 0.0) or 0.0)
        delta = float(ctx.metrics.get("delta", 0.0) or 0.0)
        atr = float(technical.get("atr", 0.0) or 0.0)

        if rvol < self._min_rvol:
            return None

        direction: Optional[str] = None
        if (return_15m >= self._min_return_15m and cvd_15m > 0 and delta > 0 and cvd_window > 0):
            direction = "LONG"
        elif (return_15m <= -self._min_return_15m and cvd_15m < 0 and delta < 0 and cvd_window < 0):
            direction = "SHORT"

        if direction is None:
            return None

        reasons = [
            f"Movimiento ya en marcha: return_15m={return_15m:+.2f}%, RVOL={rvol:.1f}x, "
            f"CVD 15m={cvd_15m:+.0f}, CVD ventana 3min={cvd_window:+.0f} — entrada reactiva, no anticipatoria.",
        ]
        return _build_signal(
            direction, price, atr, ctx.structure, reasons,
            sl_pct=self._sl_pct, tp1_r=self._tp1_r, tp2_r=self._tp2_r,
            leverage=self._leverage,
        )
