"""Detección de estructura de mercado: soportes, resistencias y breakouts.

Construye niveles horizontales a partir de pivots (swing highs/lows) de velas
15m y detecta rupturas confirmadas de esos niveles. Es la base "chartista" del
sistema: los niveles alimentan a setup_rules (gatillo level_breakout para
futuros) y a micro_scalper (rebotes en soporte/resistencia con TP ajustado).

Diseño:
- Pivot = máximo/mínimo local con `window` velas menores a cada lado.
- Nivel = clúster de pivots cuyo precio difiere menos que `tolerance_pct`.
  Fuerza del nivel = número de toques + recencia.
- Breakout = el cierre anterior estaba de un lado del nivel y el cierre actual
  lo supera con margen (buffer ATR); confirmado si además hay volumen relativo.
"""
from typing import Any, Dict, List, Optional

from app.config import (
    STRUCTURE_PIVOT_WINDOW,
    STRUCTURE_LEVEL_TOLERANCE_PCT,
    STRUCTURE_MIN_TOUCHES,
    STRUCTURE_MAX_LEVELS,
    STRUCTURE_BREAKOUT_MIN_RVOL,
    STRUCTURE_BREAKOUT_LOOKBACK,
)


def _row(k: Any) -> Dict[str, float]:
    """Normaliza vela en dict (formato dict o lista Binance)."""
    if isinstance(k, dict):
        return {
            "open":   float(k.get("open",   k.get("o", 0))),
            "high":   float(k.get("high",   k.get("h", 0))),
            "low":    float(k.get("low",    k.get("l", 0))),
            "close":  float(k.get("close",  k.get("c", 0))),
            "volume": float(k.get("volume", k.get("v", 0))),
        }
    return {
        "open":   float(k[1]),
        "high":   float(k[2]),
        "low":    float(k[3]),
        "close":  float(k[4]),
        "volume": float(k[5]) if len(k) > 5 else 0.0,
    }


def find_pivots(klines: List[Any], window: int = STRUCTURE_PIVOT_WINDOW) -> List[Dict[str, Any]]:
    """Detecta swing highs/lows: extremo local con `window` velas a cada lado.

    Retorna lista cronológica de {index, price, kind} con kind='high'|'low'.
    Las últimas `window` velas no pueden confirmar pivot (aún sin lado derecho).
    """
    if not klines or len(klines) < 2 * window + 1:
        return []

    rows = [_row(k) for k in klines]
    pivots: List[Dict[str, Any]] = []

    for i in range(window, len(rows) - window):
        hi = rows[i]["high"]
        lo = rows[i]["low"]
        left  = rows[i - window:i]
        right = rows[i + 1:i + 1 + window]

        if all(hi >= r["high"] for r in left) and all(hi > r["high"] for r in right):
            pivots.append({"index": i, "price": hi, "kind": "high"})
        if all(lo <= r["low"] for r in left) and all(lo < r["low"] for r in right):
            pivots.append({"index": i, "price": lo, "kind": "low"})

    return pivots


def build_levels(
    klines: List[Any],
    *,
    window: int = STRUCTURE_PIVOT_WINDOW,
    tolerance_pct: float = STRUCTURE_LEVEL_TOLERANCE_PCT,
    min_touches: int = STRUCTURE_MIN_TOUCHES,
    max_levels: int = STRUCTURE_MAX_LEVELS,
) -> List[Dict[str, Any]]:
    """Agrupa pivots en niveles horizontales por proximidad de precio.

    Retorna niveles ordenados por fuerza descendente:
    {price, touches, kinds, first_index, last_index, strength}.
    `price` es el promedio de los toques del clúster.
    """
    pivots = find_pivots(klines, window)
    if not pivots:
        return []

    n_candles = len(klines)
    clusters: List[List[Dict[str, Any]]] = []

    for piv in sorted(pivots, key=lambda p: p["price"]):
        placed = False
        for cluster in clusters:
            ref = sum(p["price"] for p in cluster) / len(cluster)
            if ref > 0 and abs(piv["price"] - ref) / ref * 100.0 <= tolerance_pct:
                cluster.append(piv)
                placed = True
                break
        if not placed:
            clusters.append([piv])

    levels: List[Dict[str, Any]] = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        price = sum(p["price"] for p in cluster) / len(cluster)
        last_index = max(p["index"] for p in cluster)
        # Fuerza: toques (peso principal) + recencia del último toque
        recency = last_index / max(n_candles - 1, 1)
        strength = len(cluster) * 10.0 + recency * 10.0
        levels.append({
            "price":       price,
            "touches":     len(cluster),
            "kinds":       sorted({p["kind"] for p in cluster}),
            "first_index": min(p["index"] for p in cluster),
            "last_index":  last_index,
            "strength":    round(strength, 1),
        })

    levels.sort(key=lambda lv: lv["strength"], reverse=True)
    return levels[:max_levels]


def _nearest(levels: List[Dict[str, Any]], price: float, side: str) -> Optional[Dict[str, Any]]:
    """Nivel más cercano por debajo (side='support') o por encima (side='resistance')."""
    if side == "support":
        candidates = [lv for lv in levels if lv["price"] < price]
        best = max(candidates, key=lambda lv: lv["price"], default=None)
    else:
        candidates = [lv for lv in levels if lv["price"] > price]
        best = min(candidates, key=lambda lv: lv["price"], default=None)
    if best is None or price <= 0:
        return None
    return {
        "price":        best["price"],
        "touches":      best["touches"],
        "strength":     best["strength"],
        "distance_pct": round(abs(price - best["price"]) / price * 100.0, 4),
    }


def _detect_breakout(
    levels: List[Dict[str, Any]],
    rows: List[Dict[str, float]],
    atr: float,
    relative_volume: float,
) -> Optional[Dict[str, Any]]:
    """Busca la ruptura más reciente de un nivel en las últimas velas.

    Ruptura alcista: algún cierre de las últimas `lookback` velas quedó por
    encima de un nivel + buffer cuando el cierre previo estaba por debajo.
    Confirmada = margen >= buffer y volumen relativo >= mínimo.
    """
    if not levels or len(rows) < 2:
        return None

    close = rows[-1]["close"]
    if close <= 0:
        return None
    buffer = max(atr * 0.15, close * 0.0005)

    lookback = min(STRUCTURE_BREAKOUT_LOOKBACK, len(rows) - 1)
    for back in range(lookback):
        idx = len(rows) - 1 - back
        cur, prev = rows[idx]["close"], rows[idx - 1]["close"]
        for lv in levels:
            lp = lv["price"]
            # El nivel debe haberse formado antes de la vela que lo rompe
            if lv["last_index"] >= idx:
                continue
            if prev <= lp and cur > lp + buffer and close > lp:
                direction = "up"
            elif prev >= lp and cur < lp - buffer and close < lp:
                direction = "down"
            else:
                continue
            margin_pct = abs(close - lp) / lp * 100.0
            confirmed = relative_volume >= STRUCTURE_BREAKOUT_MIN_RVOL
            return {
                "direction":    direction,
                "level":        lp,
                "touches":      lv["touches"],
                "strength":     lv["strength"],
                "candles_ago":  back,
                "margin_pct":   round(margin_pct, 4),
                "confirmed":    confirmed,
                "rvol":         round(relative_volume, 2),
            }
    return None


def analyze_structure(
    klines: List[Any],
    *,
    atr: float = 0.0,
    relative_volume: float = 1.0,
) -> Optional[Dict[str, Any]]:
    """API principal: niveles S/R + breakout sobre las velas dadas (típicamente 15m).

    Retorna None si no hay velas suficientes. Estructura:
    {
      "levels": [...],
      "nearest_support":    {price, touches, strength, distance_pct} | None,
      "nearest_resistance": {...} | None,
      "breakout": {direction, level, touches, margin_pct, confirmed, ...} | None,
      "range": {"high": ..., "low": ..., "width_pct": ...} | None,
    }
    """
    if not klines or len(klines) < 2 * STRUCTURE_PIVOT_WINDOW + 5:
        return None

    rows = [_row(k) for k in klines]
    price = rows[-1]["close"]
    atr = max(float(atr or 0.0), 0.0)
    relative_volume = float(relative_volume or 1.0)

    levels = build_levels(klines)
    breakout = _detect_breakout(levels, rows, atr, relative_volume)

    range_info = None
    if levels and price > 0:
        highs = [lv["price"] for lv in levels]
        lo, hi = min(highs), max(highs)
        if hi > lo:
            range_info = {
                "high": hi,
                "low": lo,
                "width_pct": round((hi - lo) / price * 100.0, 4),
            }

    return {
        "levels":             levels,
        "nearest_support":    _nearest(levels, price, "support"),
        "nearest_resistance": _nearest(levels, price, "resistance"),
        "breakout":           breakout,
        "range":              range_info,
    }
