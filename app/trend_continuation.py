"""Detección de continuación de tendencia para setups sin gatillo clásico.

Complementa setup_rules.py con una ruta alternativa: cuando no hay engulfing,
rechazo o reclaim de VWAP pero el precio lleva varios snapshots en tendencia
fuerte con CVD alineado, VWAP respetado y volumen elevado.

Aplica tanto para LONG (alcista) como SHORT (bajista).
"""
from typing import Any, Dict


def is_long_momentum_continuation(snapshot: Dict[str, Any]) -> bool:
    """True si el snapshot cumple todas las condiciones de continuación alcista."""
    technical = snapshot.get("technical") or {}
    metrics   = snapshot.get("metrics")   or {}
    return (
        technical.get("trend_bias")      == "bullish"
        and technical.get("htf_trend_bias") == "bullish"
        and technical.get("above_vwap")  is True
        and float(technical.get("return_1h",       0) or 0) >= 2.0
        and float(technical.get("return_15m",      0) or 0) >= 0.5
        and float(technical.get("relative_volume", 1) or 1) >= 1.2
        and float(metrics.get("cvd_15m", 0) or 0) > 0
        and float(metrics.get("cvd",     0) or 0) > 0
        and float(technical.get("vwap_distance_pct", 0) or 0) <  8.0
        and abs(float(snapshot.get("funding", 0) or 0)) < 0.003
    )


def is_short_momentum_continuation(snapshot: Dict[str, Any]) -> bool:
    """True si el snapshot cumple todas las condiciones de continuación bajista."""
    technical = snapshot.get("technical") or {}
    metrics   = snapshot.get("metrics")   or {}
    return (
        technical.get("trend_bias")      == "bearish"
        and technical.get("htf_trend_bias") == "bearish"
        and technical.get("above_vwap")  is False
        and float(technical.get("return_1h",       0) or 0) <= -2.0
        and float(technical.get("return_15m",      0) or 0) <= -0.5
        and float(technical.get("relative_volume", 1) or 1) >= 1.2
        and float(metrics.get("cvd_15m", 0) or 0) < 0
        and float(metrics.get("cvd",     0) or 0) < 0
        and float(technical.get("vwap_distance_pct", 0) or 0) > -8.0
        and abs(float(snapshot.get("funding", 0) or 0)) < 0.003
    )


def calculate_trend_priority_score(snapshot: Dict[str, Any], direction: str) -> Dict[str, Any]:
    """Score de continuación de tendencia 0-100.

    Args:
        snapshot:  dict con keys 'technical', 'metrics', 'funding'.
        direction: 'long' | 'short'

    Returns:
        dict con trend_priority_score, trend_reasons, trend_warnings.
    """
    technical = snapshot.get("technical") or {}
    metrics   = snapshot.get("metrics")   or {}
    funding   = abs(float(snapshot.get("funding", 0) or 0))
    is_long   = direction == "long"

    score:    int       = 0
    reasons:  list      = []
    warnings: list      = []

    trend_target = "bullish" if is_long else "bearish"

    if technical.get("trend_bias") == trend_target:
        score += 15
        reasons.append(f"Tendencia 1m {'alcista' if is_long else 'bajista'}.")

    if technical.get("htf_trend_bias") == trend_target:
        score += 20
        reasons.append(f"Tendencia 1h {'alcista' if is_long else 'bajista'}.")

    above = technical.get("above_vwap")
    if is_long and above is True:
        score += 10
        reasons.append("Precio sobre VWAP.")
    elif not is_long and above is False:
        score += 10
        reasons.append("Precio bajo VWAP.")

    ret_1h  = float(technical.get("return_1h",  0) or 0)
    ret_15m = float(technical.get("return_15m", 0) or 0)

    if (is_long and ret_1h >= 2.0) or (not is_long and ret_1h <= -2.0):
        score += 20
        reasons.append(f"Momentum 1h fuerte ({ret_1h:+.1f}%).")

    if (is_long and ret_15m >= 0.5) or (not is_long and ret_15m <= -0.5):
        score += 10
        reasons.append(f"Momentum 15m positivo ({ret_15m:+.1f}%).")

    cvd_15m = float(metrics.get("cvd_15m", 0) or 0)
    if (is_long and cvd_15m > 0) or (not is_long and cvd_15m < 0):
        score += 15
        reasons.append(f"CVD 15m {'positivo' if is_long else 'negativo'} ({cvd_15m:.0f}).")

    rel_vol = float(technical.get("relative_volume", 1) or 1)
    if rel_vol >= 1.5:
        score += 10
        reasons.append(f"Volumen relativo elevado ({rel_vol:.1f}x).")

    vwap_dist = float(technical.get("vwap_distance_pct", 0) or 0)
    if (is_long and vwap_dist >= 8) or (not is_long and vwap_dist <= -8):
        score -= 15
        warnings.append(f"Precio demasiado alejado de VWAP ({vwap_dist:+.1f}%).")

    if funding >= 0.003:
        score -= 15
        warnings.append(f"Funding extremo ({funding:.5f}) — riesgo de squeeze.")

    return {
        "trend_priority_score": max(0, min(100, score)),
        "trend_reasons":        reasons,
        "trend_warnings":       warnings,
    }
