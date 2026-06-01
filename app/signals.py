from typing import Any, Dict, List, Optional

from app.alerts import generate_alert_report, summarize_liquidations


def _normalize_strength(value: float, strong: float = 1_000_000.0, moderate: float = 100_000.0) -> int:
    abs_value = abs(value)
    if abs_value >= strong:
        return 3
    if abs_value >= moderate:
        return 2
    if abs_value > 0:
        return 1
    return 0


def _format_confidence(score: int) -> int:
    return min(95, max(40, 40 + score * 10))


def detect_institutional_signal(
    symbol: str,
    delta: float,
    cvd: float,
    funding: float,
    open_interest: float,
    imbalance: float,
    liquidations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Detecta señales institucionales a partir de métricas de mercado.

    Señales posibles: accumulation, bullish_continuation, short_squeeze,
    long_squeeze, distribution, neutral.
    """
    delta_strength = _normalize_strength(delta)
    cvd_strength = _normalize_strength(cvd)
    oi_strength = _normalize_strength(open_interest)
    imbalance_strength = _normalize_strength(imbalance, strong=0.5, moderate=0.1)

    buy_pressure = delta > 0
    bullish_cvd = cvd > 0
    bullish_obi = imbalance > 0
    long_bias = funding > 0
    oi_active = open_interest > 0

    if buy_pressure and bullish_cvd and bullish_obi and oi_active:
        if long_bias:
            signal = "bullish_continuation"
            interpretation = (
                "Los toros institucionales están acumulando y el mercado muestra continuidad al alza."
            )
        else:
            signal = "short_squeeze"
            interpretation = (
                "El sesgo de mercado es alcista mientras la presión de funding es negativa, "
                "sugiriendo posible squeeze de cortos."
            )
    elif not buy_pressure and not bullish_cvd and not bullish_obi and oi_active:
        if long_bias:
            signal = "long_squeeze"
            interpretation = (
                "La presión vendedora domina mientras los traders largos siguen pagando funding, "
                "indicando un posible squeeze de largos."
            )
        else:
            signal = "distribution"
            interpretation = (
                "Distribución institucional detectada: vendedores agresivos y el mercado "
                "muestra distribución de posiciones."
            )
    elif buy_pressure and bullish_cvd and bullish_obi:
        signal = "accumulation"
        interpretation = "Aumento de volumen comprador y acumulación institucional detectada."
    elif not buy_pressure and not bullish_cvd and not bullish_obi:
        signal = "distribution"
        interpretation = "Ventas agresivas y distribución institucional detectada."
    else:
        signal = "neutral"
        interpretation = "No hay una señal institucional clara basada en los datos actuales."

    score = delta_strength + cvd_strength + oi_strength + imbalance_strength
    confidence = _format_confidence(score)

    invalidation: List[str] = []
    if signal in ("accumulation", "bullish_continuation"):
        invalidation.append("Delta negativo persistente")
        invalidation.append("Inversión de OBI hacia el lado negativo")
    elif signal in ("distribution", "long_squeeze"):
        invalidation.append("Delta positivo sostenido")
        invalidation.append("Cambio de funding hacia valores negativos")
    elif signal == "short_squeeze":
        invalidation.append("Delta negativo con OBI negativo")
        invalidation.append("Open interest en caída")
    else:
        invalidation.append("No se mantiene el sesgo detectado")

    result: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "signal": signal,
        "institutional_interpretation": interpretation,
        "confidence": confidence,
        "invalidation_conditions": invalidation,
        "metrics": {
            "delta": round(delta, 8),
            "cvd": round(cvd, 8),
            "funding": round(funding, 8),
            "open_interest": round(open_interest, 8),
            "imbalance": round(imbalance, 8),
        },
    }

    if liquidations is not None:
        liquidation_summary = summarize_liquidations(liquidations)
        result["liquidation_summary"] = liquidation_summary
        result["alert_report"] = generate_alert_report(result, liquidation_summary)

    return result
