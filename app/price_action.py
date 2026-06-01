"""Detección de gatillos de price action para confirmación de entrada.

Analiza las últimas velas de 1m para identificar patrones de confirmación:
engulfing, rechazo de mecha, reclaim/pérdida de VWAP.

Se usa como filtro de gatillo en setup_rules.py — una señal fuerte de flujo
sin gatillo de vela es una señal prematura.
"""
from typing import Any, Dict, List, Optional


def _row(k: Any) -> Dict[str, float]:
    """Normaliza vela en dict independientemente del formato (dict o lista Binance)."""
    if isinstance(k, dict):
        return {
            "open":   float(k.get("open",   k.get("o", 0))),
            "high":   float(k.get("high",   k.get("h", 0))),
            "low":    float(k.get("low",    k.get("l", 0))),
            "close":  float(k.get("close",  k.get("c", 0))),
            "volume": float(k.get("volume", k.get("v", 0))),
        }
    # Lista Binance: [open_time, open, high, low, close, volume, ...]
    return {
        "open":   float(k[1]),
        "high":   float(k[2]),
        "low":    float(k[3]),
        "close":  float(k[4]),
        "volume": float(k[5]) if len(k) > 5 else 0.0,
    }


def detect_price_action_trigger(
    klines: List[Any],
    *,
    vwap: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Detecta el gatillo de price action más reciente.

    Retorna un dict con {type, direction, strength} o None si no hay gatillo.
    Prioridad: engulfing > VWAP event > rejection wick.

    Args:
        klines: Lista de velas (formato dict o lista Binance), al menos 3.
        vwap:   VWAP de la sesión actual (opcional — habilita detección VWAP events).
    """
    if not klines or len(klines) < 3:
        return None

    prev = _row(klines[-2])
    cur  = _row(klines[-1])

    o1, h1, l1, c1 = prev["open"], prev["high"], prev["low"], prev["close"]
    o2, h2, l2, c2 = cur["open"],  cur["high"],  cur["low"],  cur["close"]

    body2       = abs(c2 - o2)
    rng2        = max(h2 - l2, 1e-9)
    upper_wick2 = h2 - max(o2, c2)
    lower_wick2 = min(o2, c2) - l2

    # ── Engulfing (mayor prioridad — señal de inversión/continuación fuerte) ─
    bullish_engulfing = (c1 < o1) and (c2 > o2) and (c2 > o1) and (o2 <= c1)
    bearish_engulfing = (c1 > o1) and (c2 < o2) and (c2 < o1) and (o2 >= c1)

    if bullish_engulfing:
        return {"type": "bullish_engulfing", "direction": "long",  "strength": 80}
    if bearish_engulfing:
        return {"type": "bearish_engulfing", "direction": "short", "strength": 80}

    # ── VWAP events (segunda prioridad — requiere dato de VWAP) ──────────────
    if vwap and vwap > 0:
        if c1 < vwap <= c2:          # cruzó VWAP al alza
            return {"type": "vwap_reclaim", "direction": "long",  "strength": 75}
        if c1 > vwap >= c2:          # perdió VWAP
            return {"type": "vwap_loss",    "direction": "short", "strength": 75}

    # ── Rejection wicks (tercera prioridad) ───────────────────────────────────
    # Mecha inferior larga + vela alcista → soporte rejecting a la baja
    if lower_wick2 >= body2 * 2 and c2 > o2 and lower_wick2 / rng2 >= 0.45:
        return {"type": "bullish_rejection", "direction": "long",  "strength": 65}

    # Mecha superior larga + vela bajista → resistencia rejecting al alza
    if upper_wick2 >= body2 * 2 and c2 < o2 and upper_wick2 / rng2 >= 0.45:
        return {"type": "bearish_rejection", "direction": "short", "strength": 65}

    return None
