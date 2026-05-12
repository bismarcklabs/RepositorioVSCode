from typing import Any, Dict, List, Optional

from app.alerts import generate_alert_report, summarize_liquidations


def _normalize_strength(value: float, strong: float = 1_000_000.0, moderate: float = 100_000.0) -> int:
    """Normalize a numeric value into a simple strength score."""
    abs_value = abs(value)
    if abs_value >= strong:
        return 3
    if abs_value >= moderate:
        return 2
    if abs_value > 0:
        return 1
    return 0


def _format_confidence(score: int) -> int:
    """Convert a simple score into a confidence percentage."""
    return min(95, max(40, 40 + score * 10))


def _build_suggestion(signal: str) -> Dict[str, str]:
    """Create direction and leverage suggestions based on the detected signal."""
    if signal in ("accumulation", "bullish_continuation"):
        return {
            "suggested_direction": "LONG",
            "leverage_suggestion": "2x-5x",
            "spot_note": "Buscar compra en soporte o rompimiento confirmado.",
        }
    if signal in ("distribution", "long_squeeze"):
        return {
            "suggested_direction": "SHORT",
            "leverage_suggestion": "2x-5x",
            "spot_note": "Buscar venta en resistencia o quiebre de estructura.",
        }
    if signal == "short_squeeze":
        return {
            "suggested_direction": "LONG",
            "leverage_suggestion": "2x-4x",
            "spot_note": "Buscar reversión alcista en zona de soporte.",
        }
    return {
        "suggested_direction": "NEUTRAL",
        "leverage_suggestion": "0x",
        "spot_note": "Esperar confirmación adicional antes de entrar.",
    }


def _build_trend_estimate(signal: str) -> str:
    """Provide a qualitative trend estimate for each signal type."""
    if signal == "bullish_continuation":
        return (
            "Señala continuidad alcista: sugiere que el precio probablemente seguirá subiendo con un impulso moderado. "
            "Estimación de duración: corto a mediano plazo (6-24 horas) mientras se mantenga la presión compradora y el open interest estable."
        )
    if signal == "accumulation":
        return (
            "Señal de acumulación institucional: indica compra constante antes de un posible impulso alcista. "
            "Estimación de tendencia: alcista gradual en las próximas 12-48 horas si el volumen comprador sigue siendo sólido."
        )
    if signal == "short_squeeze":
        return (
            "Señal de posible squeeze de cortos: sugiere que los vendedores en corto podrían cubrir en caso de repunte. "
            "Estimación: potencia un movimiento alcista rápido y de corta duración, aproximadamente 1-12 horas."
        )
    if signal == "long_squeeze":
        return (
            "Señal de posible squeeze de largos: sugiere que los largos pueden cerrar posiciones si el precio baja. "
            "Estimación: riesgo de corrección bajista corta, alrededor de 1-12 horas, a menos que el mercado recupere soporte."
        )
    if signal == "distribution":
        return (
            "Señal de distribución institucional: indica venta agresiva y posible debilitamiento del precio. "
            "Estimación de tendencia: probabilidad de caída gradual o consolidación bajista en 12-48 horas."
        )
    return (
        "No hay una dirección de tendencia clara actualmente. "
        "El mercado puede permanecer lateral hasta que aparezca una señal más definida."
    )


def detect_institutional_signal(
    symbol: str,
    delta: float,
    cvd: float,
    funding: float,
    open_interest: float,
    imbalance: float,
    liquidations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Detect institutional signals from market metrics."""
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
                "Institucional bulls are acumulando y el mercado muestra continuidad al alza."
            )
        else:
            signal = "short_squeeze"
            interpretation = (
                "El sesgo de mercado es alcista mientras la presión de funding es negativa, sugiriendo posible squeeze de cortos."
            )
    elif not buy_pressure and not bullish_cvd and not bullish_obi and oi_active:
        if long_bias:
            signal = "long_squeeze"
            interpretation = (
                "La presión vendedora domina mientras los traders largos siguen pagando funding, indicando un posible squeeze de largos."
            )
        else:
            signal = "distribution"
            interpretation = (
                "Institucional distribution detectada: vendedores agresivos y el mercado muestra distribución de posiciones."
            )
    elif buy_pressure and bullish_cvd and bullish_obi:
        signal = "accumulation"
        interpretation = (
            "Aumento de volumen comprador y acumulación institucional detectada."
        )
    elif not buy_pressure and not bullish_cvd and not bullish_obi:
        signal = "distribution"
        interpretation = (
            "Ventas agresivas y distribución institucional detectada."
        )
    else:
        signal = "neutral"
        interpretation = (
            "No hay una señal institucional clara basada en los datos actuales."
        )

    score = delta_strength + cvd_strength + oi_strength + imbalance_strength
    confidence = _format_confidence(score)

    suggestion = _build_suggestion(signal)

    invalidation = []
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
        invalidation.append("No se mantiene el sesgo detected" )

    result = {
        "symbol": symbol.upper(),
        "signal": signal,
        "institutional_interpretation": interpretation,
        "trend_estimate": _build_trend_estimate(signal),
        "suggested_direction": suggestion["suggested_direction"],
        "leverage_suggestion": suggestion["leverage_suggestion"],
        "confidence": f"{confidence}%",
        "invalidation_conditions": invalidation,
        "spot_note": suggestion["spot_note"],
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
