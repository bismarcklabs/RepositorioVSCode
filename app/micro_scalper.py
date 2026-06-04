"""Micro-alertas para scalping agresivo.

Este modulo es independiente del motor institucional principal. Usa retornos
3m/5m, volumen relativo, delta/CVD, footprint, orderbook y futuros para detectar
impulsos rapidos con salida corta.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    MICRO_SCALP_MIN_SCORE,
    MICRO_SCALP_STRONG_SCORE,
    MICRO_SCALP_MIN_RVOL,
    MICRO_SCALP_MIN_RETURN_5M,
    MICRO_SCALP_MIN_RETURN_3M,
    MICRO_SCALP_MAX_SPREAD_PCT,
    MICRO_SCALP_TIMEOUT_MINUTES,
)


def _direction(action: str) -> int:
    return 1 if action == "MICRO_LONG_SCALP" else -1


def _build_setup(action: str, price: float, atr: float) -> Dict[str, Any]:
    direction = _direction(action)
    atr = max(float(atr or 0.0), 0.0)

    tp1_dist = max(price * 0.0025, atr * 0.8)
    tp2_dist = max(price * 0.0055, atr * 1.5)
    sl_dist = max(price * 0.0025, atr * 0.7)

    tp1 = price + direction * tp1_dist
    tp2 = price + direction * tp2_dist
    sl = price - direction * sl_dist

    return {
        "timing": "NOW",
        "entry": round(price, 8),
        "take_profit_1": round(tp1, 8),
        "take_profit_2": round(tp2, 8),
        "stop_loss": round(sl, 8),
        "timeout_minutes": MICRO_SCALP_TIMEOUT_MINUTES,
        "risk_pct": round(sl_dist / price * 100.0, 4) if price > 0 else 0.0,
    }


def calculate_micro_scalp_score(
    direction: str,
    technical: Dict[str, Any],
    metrics: Dict[str, Any],
    footprint: Dict[str, Any],
    orderbook: Dict[str, Any],
    funding: float,
    oi_change_pct: float,
    multi_ex: Optional[Dict[str, Any]] = None,
) -> Tuple[int, List[str], List[str]]:
    """Calcula score de scalping para direction='long' o 'short'."""
    is_long = direction == "long"
    pts = 0
    reasons: List[str] = []
    warnings: List[str] = []

    r3m = float(technical.get("return_3m", 0.0) or 0.0)
    r5m = float(technical.get("return_5m", 0.0) or 0.0)
    rel_vol = float(technical.get("relative_volume", 1.0) or 1.0)
    above_vwap = bool(technical.get("above_vwap", True))
    vwap_dist = float(technical.get("vwap_distance_pct", 0.0) or 0.0)
    spread_pct = float(orderbook.get("spread_pct", 0.0) or 0.0)
    imbalance = float(orderbook.get("imbalance", 0.0) or 0.0)
    cvd_15m = float(metrics.get("cvd_15m", 0.0) or 0.0)
    delta = float(metrics.get("delta", 0.0) or 0.0)
    fp_delta = float(footprint.get("footprint_delta", 0.0) or 0.0)

    signed_r3m = r3m if is_long else -r3m
    signed_r5m = r5m if is_long else -r5m
    signed_imb = imbalance if is_long else -imbalance
    signed_cvd = cvd_15m if is_long else -cvd_15m
    signed_delta = delta if is_long else -delta
    signed_fp = fp_delta if is_long else -fp_delta

    # ── RVOL — escalonado y con penalización si no hay momentum ──────────
    # Datos: RVOL 1.5-1.9x tiene mejor WR (64%) que RVOL 5x+ (51%).
    # RVOL muy alto sin momentum en 5m/3m = volumen de fin de impulso, no inicio.
    if rel_vol >= 5.0:
        pts += 12   # reducido de 20 — RVOL extremo sin momentum es trompa
        reasons.append(f"RVOL extremo: {rel_vol:.1f}x")
        if signed_r5m < 0.3:
            pts -= 8
            warnings.append(f"RVOL extremo pero momentum 5m débil ({r5m:+.2f}%) — impulso puede estar agotado")
    elif rel_vol >= 3.0:
        pts += 18   # reducido de 20
        reasons.append(f"RVOL alto: {rel_vol:.1f}x")
    elif rel_vol >= MICRO_SCALP_MIN_RVOL:
        pts += 15
        reasons.append(f"RVOL elevado: {rel_vol:.1f}x")
    elif rel_vol >= 1.5:
        pts += 10   # aumentado de 8 — rango 1.5-1.9x es el más efectivo

    if signed_cvd > 0:
        pts += 10
        reasons.append("CVD 15m alineado")
    if signed_delta > 0:
        pts += 8
        reasons.append("Delta reciente alineado")
    if signed_fp > 0:
        pts += 7
        reasons.append("Footprint delta alineado")

    if signed_r5m >= MICRO_SCALP_MIN_RETURN_5M:
        pts += 12
        reasons.append(f"Momentum 5m activo ({r5m:+.2f}%)")
    elif signed_r5m > 0:
        pts += 6

    if signed_r3m >= MICRO_SCALP_MIN_RETURN_3M:
        pts += 8
        reasons.append(f"Micro momentum 3m confirma ({r3m:+.2f}%)")
    elif signed_r3m < 0:
        warnings.append("3m contradice al impulso 5m")

    # ── Bonus por momentum fuerte y confirmado en ambas ventanas ──────────
    if signed_r5m >= 2.0 and signed_r3m >= 0.5:
        pts += 8
        reasons.append(f"Impulso fuerte: 5m={r5m:+.2f}% + 3m={r3m:+.2f}%")

    if (is_long and above_vwap) or ((not is_long) and not above_vwap):
        pts += 10
        reasons.append(f"VWAP alineado ({vwap_dist:+.2f}%)")
    else:
        warnings.append("VWAP no confirma el scalp")

    # ── OB: reducido — datos muestran que no discrimina bien ──────────────
    # Lift de orderbook en wins vs losses: -7.5pp → señal de confirmación tardía.
    if signed_imb >= 0.15:
        pts += 4   # reducido de 10
        reasons.append(f"Orderbook alineado ({imbalance:+.2f})")
    elif signed_imb >= 0.08:
        pts += 2   # reducido de 6

    if abs(oi_change_pct) >= 2.0:
        pts += 8
        reasons.append(f"OI cambiando ({oi_change_pct:+.1f}%)")
    elif abs(oi_change_pct) >= 0.5:
        pts += 4

    if spread_pct <= MICRO_SCALP_MAX_SPREAD_PCT:
        pts += 5
    else:
        pts -= 12
        warnings.append(f"Spread alto para scalping ({spread_pct:.3f}%)")

    if abs(funding) >= 0.003:
        pts -= 8
        warnings.append(f"Funding extremo para scalp ({funding:.5f})")

    # ── Multi-exchange: eliminado del scoring positivo ─────────────────────
    # Datos: presencia en wins 15% vs losses 25% → lift -9.3pp.
    # Cuando multi-ex confirma, el movimiento ya está priceado en todos los
    # exchanges — el scalp llega tarde. Solo penalizamos tendencia contraria.
    mx = multi_ex or {}
    if mx.get("ok") and mx.get("external_supported"):
        ext_trend = mx.get("external_trend")
        if ext_trend and ext_trend != "neutral":
            trend_bullish = ext_trend == "bullish"
            trend_bearish = ext_trend == "bearish"
            opposed = (is_long and trend_bearish) or (not is_long and trend_bullish)
            if opposed:
                pts -= 5
                warnings.append(f"Tendencia externa ({ext_trend}) contradice el scalp")

    return max(0, min(100, pts)), reasons[:8], warnings[:5]


def detect_micro_scalp(
    symbol: str,
    price: float,
    technical: Dict[str, Any],
    metrics: Dict[str, Any],
    footprint: Dict[str, Any],
    orderbook: Dict[str, Any],
    funding: float,
    open_interest: float,
    oi_change_pct: float,
    multi_ex: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retorna una micro-alerta o WAIT."""
    if price <= 0 or open_interest <= 0:
        return {"action": "WAIT", "score": 0, "confidence": 0}

    long_score, long_reasons, long_warnings = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, funding, oi_change_pct, multi_ex
    )
    short_score, short_reasons, short_warnings = calculate_micro_scalp_score(
        "short", technical, metrics, footprint, orderbook, funding, oi_change_pct, multi_ex
    )

    if long_score >= short_score:
        action = "MICRO_LONG_SCALP"
        score, reasons, warnings = long_score, long_reasons, long_warnings
    else:
        action = "MICRO_SHORT_SCALP"
        score, reasons, warnings = short_score, short_reasons, short_warnings

    if score < MICRO_SCALP_MIN_SCORE:
        return {
            "action": "WAIT",
            "score": score,
            "confidence": max(0, min(95, score)),
            "reasons": reasons,
            "warnings": warnings,
        }

    setup = _build_setup(action, price, float(technical.get("atr", 0.0) or 0.0))
    confidence = min(95, score + 5 if score >= MICRO_SCALP_STRONG_SCORE else score)

    return {
        "timestamp": "",
        "symbol": symbol.upper(),
        "action": action,
        "score": score,
        "confidence": confidence,
        "setup": setup,
        "technical": technical,
        "metrics": metrics,
        "footprint": footprint,
        "orderbook": orderbook,
        "funding": funding,
        "oi_change_pct": oi_change_pct,
        "reasons": reasons,
        "warnings": warnings,
    }
