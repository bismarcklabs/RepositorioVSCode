from typing import Any, Dict, List, Optional


def summarize_liquidations(liquidations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize liquidation events into counts, volumes and pressure."""
    long_count = 0
    short_count = 0
    long_volume = 0.0
    short_volume = 0.0

    for event in liquidations:
        side = str(event.get("positionSide", event.get("side", ""))).upper()
        qty = float(event.get("origQty", event.get("qty", 0.0)))

        if "LONG" in side:
            long_count += 1
            long_volume += qty
        elif "SHORT" in side:
            short_count += 1
            short_volume += qty

    total_volume = long_volume + short_volume
    total_count = long_count + short_count
    pressure = 0.0
    if total_volume > 0:
        pressure = (long_volume - short_volume) / total_volume

    return {
        "total_count": total_count,
        "total_volume": round(total_volume, 8),
        "long_count": long_count,
        "short_count": short_count,
        "long_volume": round(long_volume, 8),
        "short_volume": round(short_volume, 8),
        "pressure": round(pressure, 8),
    }


def evaluate_risk(
    signal_data: Dict[str, Any],
    liquidation_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a market risk alert based on metrics and liquidations."""
    metrics = signal_data.get("metrics", {})
    delta = metrics.get("delta", 0.0)
    funding = metrics.get("funding", 0.0)
    imbalance = metrics.get("imbalance", 0.0)

    reasons: List[str] = []
    if abs(funding) >= 0.001:
        reasons.append("Funding rate extremo")
    if abs(imbalance) >= 0.35:
        reasons.append("Imbalance del order book muy alto")
    if delta < 0 and signal_data["signal"] in ("long_squeeze", "distribution"):
        reasons.append("Presión vendedora persistente")
    if liquidation_summary is not None:
        if liquidation_summary["total_count"] >= 20:
            reasons.append("Alta cantidad de liquidaciones recientes")
        if abs(liquidation_summary["pressure"]) >= 0.4:
            reasons.append("Fuerte presión de liquidaciones en un solo lado")

    risk_level = "low"
    if len(reasons) >= 3:
        risk_level = "high"
    elif len(reasons) == 2:
        risk_level = "medium"

    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
    }


def confirm_squeeze(
    signal_data: Dict[str, Any],
    liquidation_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Confirm whether the current signal is supported by liquidation flow."""
    signal = signal_data.get("signal", "neutral")
    confirmation = "none"
    message = "No hay confirmación de squeeze disponible."

    if liquidation_summary is None:
        return {
            "confirmation": confirmation,
            "message": message,
        }

    if signal == "short_squeeze":
        if liquidation_summary["short_count"] > liquidation_summary["long_count"]:
            confirmation = "strong"
            message = "Liquidaciones cortas elevadas confirman un posible short squeeze."
        else:
            confirmation = "weak"
            message = "No hay suficientes liquidaciones cortas para confirmar el squeeze."
    elif signal == "long_squeeze":
        if liquidation_summary["long_count"] > liquidation_summary["short_count"]:
            confirmation = "strong"
            message = "Liquidaciones largas elevadas confirman un posible long squeeze."
        else:
            confirmation = "weak"
            message = "No hay suficientes liquidaciones largas para confirmar el squeeze."
    elif signal == "bullish_continuation":
        if liquidation_summary["long_volume"] > liquidation_summary["short_volume"]:
            confirmation = "moderate"
            message = "La extracción de shorts y el flujo de compras respaldan la continuación alcista."
    elif signal == "distribution":
        if liquidation_summary["short_volume"] > liquidation_summary["long_volume"]:
            confirmation = "moderate"
            message = "La presión de shorts refuerza la distribución institucional."

    return {
        "confirmation": confirmation,
        "message": message,
    }


def assess_market_stress(
    signal_data: Dict[str, Any],
    liquidation_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce a stress evaluation using market metrics and liquidation flow."""
    metrics = signal_data.get("metrics", {})
    funding = metrics.get("funding", 0.0)
    imbalance = metrics.get("imbalance", 0.0)
    oi = metrics.get("open_interest", 0.0)

    score = 0
    if abs(funding) >= 0.001:
        score += 1
    if abs(imbalance) >= 0.35:
        score += 1
    if oi > 0 and oi < 1_000_000:
        score += 1
    if liquidation_summary is not None:
        if liquidation_summary["total_count"] >= 15:
            score += 1
        if liquidation_summary["total_volume"] > 1_000_000:
            score += 1

    if score >= 4:
        stress_level = "high"
    elif score >= 2:
        stress_level = "medium"
    else:
        stress_level = "low"

    return {
        "stress_level": stress_level,
        "stress_score": score,
    }


def generate_alert_report(
    signal_data: Dict[str, Any],
    liquidation_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a full alert report combining risk, squeeze and stress checks."""
    risk = evaluate_risk(signal_data, liquidation_summary)
    squeeze = confirm_squeeze(signal_data, liquidation_summary)
    stress = assess_market_stress(signal_data, liquidation_summary)

    return {
        "risk": risk,
        "squeeze_confirmation": squeeze,
        "stress": stress,
    }
