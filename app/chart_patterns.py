"""Detección de patrones chartistas sobre pivots.

Patrones soportados (sobre los swing highs/lows de structure_levels.find_pivots):
- Hombro-cabeza-hombro (head_and_shoulders) y su inverso
- Doble techo (double_top) y doble piso (double_bottom)

Cada patrón reporta su neckline y si ya está CONFIRMADO (cierre más allá de la
neckline) — la confirmación es lo que habilita meter la orden: el patrón sin
ruptura de neckline es solo una advertencia.
"""
from typing import Any, Dict, List, Optional

from app.config import (
    PATTERN_SHOULDER_TOLERANCE_PCT,
    PATTERN_DOUBLE_TOLERANCE_PCT,
    PATTERN_MIN_HEAD_PROMINENCE_PCT,
    PATTERN_BOUNCE_MAX_AGE_CANDLES,
    PATTERN_BOUNCE_MIN_PROGRESS_PCT,
    PATTERN_BOUNCE_MAX_PROGRESS_PCT,
)
from app.structure_levels import _row, find_pivots


def _bounce_state(
    *, confirmed: bool, extreme_index: int, last_index: int,
    extreme_price: float, neckline: float, close: float,
) -> Dict[str, Any]:
    """Estado de "rebote en 2a pata": el precio ya se alejó del extremo del
    segundo pivot hacia la neckline, pero sin haberla roto todavía. Es una
    entrada más temprana que esperar la ruptura confirmada (pattern_break).
    """
    if confirmed:
        return {"bounce_age_candles": 0, "bounce_progress_pct": 0.0, "bounce_valid": False}

    age = last_index - extreme_index
    height = abs(neckline - extreme_price)
    progress = abs(close - extreme_price) / height * 100.0 if height > 0 else 0.0
    valid = (
        age <= PATTERN_BOUNCE_MAX_AGE_CANDLES
        and PATTERN_BOUNCE_MIN_PROGRESS_PCT <= progress <= PATTERN_BOUNCE_MAX_PROGRESS_PCT
    )
    return {
        "bounce_age_candles": age,
        "bounce_progress_pct": round(progress, 2),
        "bounce_valid": valid,
    }


def _detect_double(
    highs: List[Dict[str, Any]],
    lows: List[Dict[str, Any]],
    rows: List[Dict[str, float]],
) -> Optional[Dict[str, Any]]:
    """Doble techo/piso con los dos últimos pivots del mismo tipo."""
    close = rows[-1]["close"]
    last_index = len(rows) - 1
    # Doble techo: dos highs casi iguales con un low intermedio (neckline)
    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        ref = (h1["price"] + h2["price"]) / 2
        if ref > 0 and abs(h1["price"] - h2["price"]) / ref * 100.0 <= PATTERN_DOUBLE_TOLERANCE_PCT:
            valley = [p for p in lows if h1["index"] < p["index"] < h2["index"]]
            if valley:
                neckline = min(p["price"] for p in valley)
                if neckline < ref:
                    height = ref - neckline
                    confirmed = close < neckline
                    return {
                        "pattern":   "double_top",
                        "direction": "short",
                        "neckline":  neckline,
                        "extreme":   ref,
                        "confirmed": confirmed,
                        "target":    neckline - height,
                        **_bounce_state(
                            confirmed=confirmed, extreme_index=h2["index"], last_index=last_index,
                            extreme_price=ref, neckline=neckline, close=close,
                        ),
                    }
    # Doble piso: espejo
    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        ref = (l1["price"] + l2["price"]) / 2
        if ref > 0 and abs(l1["price"] - l2["price"]) / ref * 100.0 <= PATTERN_DOUBLE_TOLERANCE_PCT:
            peak = [p for p in highs if l1["index"] < p["index"] < l2["index"]]
            if peak:
                neckline = max(p["price"] for p in peak)
                if neckline > ref:
                    height = neckline - ref
                    confirmed = close > neckline
                    return {
                        "pattern":   "double_bottom",
                        "direction": "long",
                        "neckline":  neckline,
                        "extreme":   ref,
                        "confirmed": confirmed,
                        "target":    neckline + height,
                        **_bounce_state(
                            confirmed=confirmed, extreme_index=l2["index"], last_index=last_index,
                            extreme_price=ref, neckline=neckline, close=close,
                        ),
                    }
    return None


def _detect_hns(
    highs: List[Dict[str, Any]],
    lows: List[Dict[str, Any]],
    close: float,
) -> Optional[Dict[str, Any]]:
    """Hombro-cabeza-hombro (y su inverso) con los tres últimos pivots."""
    # H-C-H clásico: tres highs, el del medio claramente mayor, hombros parejos
    if len(highs) >= 3:
        ls, head, rs = highs[-3], highs[-2], highs[-1]
        shoulders_ref = (ls["price"] + rs["price"]) / 2
        if shoulders_ref > 0:
            shoulders_even = abs(ls["price"] - rs["price"]) / shoulders_ref * 100.0 <= PATTERN_SHOULDER_TOLERANCE_PCT
            head_prominent = (head["price"] - shoulders_ref) / shoulders_ref * 100.0 >= PATTERN_MIN_HEAD_PROMINENCE_PCT
            if shoulders_even and head_prominent:
                valleys = [p for p in lows if ls["index"] < p["index"] < rs["index"]]
                if len(valleys) >= 2:
                    neckline = sum(p["price"] for p in valleys[-2:]) / 2
                    if neckline < shoulders_ref:
                        height = head["price"] - neckline
                        return {
                            "pattern":   "head_and_shoulders",
                            "direction": "short",
                            "neckline":  neckline,
                            "extreme":   head["price"],
                            "confirmed": close < neckline,
                            "target":    neckline - height,
                        }
    # H-C-H invertido: espejo con lows
    if len(lows) >= 3:
        ls, head, rs = lows[-3], lows[-2], lows[-1]
        shoulders_ref = (ls["price"] + rs["price"]) / 2
        if shoulders_ref > 0:
            shoulders_even = abs(ls["price"] - rs["price"]) / shoulders_ref * 100.0 <= PATTERN_SHOULDER_TOLERANCE_PCT
            head_prominent = (shoulders_ref - head["price"]) / shoulders_ref * 100.0 >= PATTERN_MIN_HEAD_PROMINENCE_PCT
            if shoulders_even and head_prominent:
                peaks = [p for p in highs if ls["index"] < p["index"] < rs["index"]]
                if len(peaks) >= 2:
                    neckline = sum(p["price"] for p in peaks[-2:]) / 2
                    if neckline > shoulders_ref:
                        height = neckline - head["price"]
                        return {
                            "pattern":   "inverse_head_and_shoulders",
                            "direction": "long",
                            "neckline":  neckline,
                            "extreme":   head["price"],
                            "confirmed": close > neckline,
                            "target":    neckline + height,
                        }
    return None


def detect_chart_patterns(klines: List[Any]) -> List[Dict[str, Any]]:
    """Detecta patrones chartistas en las velas dadas (típicamente 15m).

    Retorna lista (posiblemente vacía) ordenada: confirmados primero, luego
    H-C-H antes que dobles. Cada patrón redondea neckline/target y añade
    `distance_to_neckline_pct` respecto al cierre actual.
    """
    if not klines or len(klines) < 15:
        return []

    pivots = find_pivots(klines)
    if len(pivots) < 3:
        return []

    highs = [p for p in pivots if p["kind"] == "high"]
    lows  = [p for p in pivots if p["kind"] == "low"]
    rows  = [_row(k) for k in klines]
    close = rows[-1]["close"]
    if close <= 0:
        return []

    found: List[Dict[str, Any]] = []
    hns = _detect_hns(highs, lows, close)
    if hns:
        found.append(hns)
    dbl = _detect_double(highs, lows, rows)
    if dbl:
        found.append(dbl)

    for p in found:
        p["neckline"] = round(p["neckline"], 8)
        p["target"]   = round(p["target"], 8)
        p["extreme"]  = round(p["extreme"], 8)
        p["distance_to_neckline_pct"] = round(
            (close - p["neckline"]) / close * 100.0, 4
        )

    found.sort(key=lambda p: (not p["confirmed"], p["pattern"].startswith("double")))
    return found
