from typing import Any, Dict, List, Optional

from app.config import (
    EXTREME_FUNDING_ABS,
    MIN_ALERT_SCORE_BUY_SPOT,
    MIN_ALERT_SCORE_LONG_FUTURES,
    MIN_ALERT_SCORE_SELL_SPOT,
    MIN_ALERT_SCORE_SHORT_FUTURES,
)
from app.entry_exit import calculate_entry_exit

_BULLISH = {"accumulation", "bullish_continuation", "short_squeeze"}
_BEARISH = {"distribution", "long_squeeze"}


def _entry_narrative(signal: str, technical: Dict[str, Any]) -> str:
    trend = technical.get("trend_bias", "neutral")
    vwap_dist = technical.get("vwap_distance_pct", 0.0)
    r1h = technical.get("return_1h", 0.0)
    above_vwap = technical.get("above_vwap", True)

    direction = (
        "alcista" if signal in _BULLISH
        else "bajista" if signal in _BEARISH
        else "lateral"
    )

    vwap_note = ""
    if abs(vwap_dist) >= 0.2:
        lado = "sobre" if above_vwap else "bajo"
        vwap_note = f" Precio {lado} VWAP en {abs(vwap_dist):.2f}%."

    ema_note = ""
    if trend == "bullish":
        ema_note = " EMA20 > EMA50: estructura alcista."
    elif trend == "bearish":
        ema_note = " EMA20 < EMA50: estructura bajista."

    return f"Tendencia {direction} — retorno 1h: {r1h:+.2f}%.{vwap_note}{ema_note}"


def _invalidation(signal: str, funding: float, volume_profile: Optional[Dict]) -> List[str]:
    if signal in _BULLISH:
        conds = [
            "Delta negativo persistente con CVD cayendo",
            "Pérdida del VWAP con cierre bajo EMA20",
        ]
        if funding > EXTREME_FUNDING_ABS:
            conds.append("Funding creciente — presión de longs aumentando")
    elif signal in _BEARISH:
        conds = [
            "Delta positivo sostenido con CVD subiendo",
            "Recuperación del VWAP con cierre sobre EMA20",
        ]
        if funding < -EXTREME_FUNDING_ABS:
            conds.append("Funding negativo creciente — shorts cubriendo")
    else:
        conds = ["Aparición de señal direccional clara"]

    if volume_profile:
        nearest_type = volume_profile.get("nearest_level_type", "NONE")
        nearest_level = volume_profile.get("nearest_level", 0.0)
        if nearest_type in ("POC", "HVN") and nearest_level > 0:
            level_str = f"{nearest_level:,.2f}"
            if signal in _BULLISH:
                conds.append(f"Pérdida del {nearest_type} en {level_str}")
            elif signal in _BEARISH:
                conds.append(f"Ruptura del {nearest_type} en {level_str}")

    return conds


def build_trade_recommendation(
    symbol: str,
    signal: str,
    score_data: Dict[str, Any],
    technical: Dict[str, Any],
    funding: float,
    open_interest: float,
    price: float = 0.0,
    alert_report: Optional[Dict[str, Any]] = None,
    volume_profile: Optional[Dict[str, Any]] = None,
    gex_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    score = score_data.get("score", 0)
    warnings = list(score_data.get("warnings", []))
    reasons = list(score_data.get("reasons", []))[:5]

    risk_level = "low"
    if alert_report:
        risk_level = alert_report.get("risk", {}).get("risk_level", "low")

    above_vwap = technical.get("above_vwap", True)
    trend = technical.get("trend_bias", "neutral")
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH
    not_high_risk = risk_level != "high"

    action = "WAIT"
    market = "NONE"
    confidence = max(40, score - 5)

    # LONG_FUTURES — mayor prioridad; requiere precio sobre VWAP y sin riesgo alto
    if (
        bullish
        and score >= MIN_ALERT_SCORE_LONG_FUTURES
        and open_interest > 0
        and funding <= EXTREME_FUNDING_ABS
        and not_high_risk
        and above_vwap
    ):
        action, market = "LONG_FUTURES", "FUTURES"
        confidence = min(95, score)

    # SHORT_FUTURES — requiere precio bajo VWAP; funding puede ser negativo
    # (funding negativo durante caída = shorts overcrowded pero la dirección sigue siendo bajista)
    # Solo se bloquea si el funding es EXTREMADAMENTE negativo (shorts muy sobrecomprados)
    elif (
        bearish
        and score >= MIN_ALERT_SCORE_SHORT_FUTURES
        and open_interest > 0
        and funding >= -EXTREME_FUNDING_ABS   # permite funding negativo moderado
        and not above_vwap
    ):
        action, market = "SHORT_FUTURES", "FUTURES"
        confidence = min(95, score)
        if risk_level == "high":
            warnings.append("⚠ Riesgo alto — reducir tamaño de posición")

    # BUY_SPOT — solo en condiciones normales
    elif (
        bullish
        and score >= MIN_ALERT_SCORE_BUY_SPOT
        and trend != "bearish"
        and abs(funding) < EXTREME_FUNDING_ABS * 2
        and not_high_risk
    ):
        action, market = "BUY_SPOT", "SPOT"
        confidence = min(90, score - 3)

    # SELL_SPOT — permitido incluso con riesgo alto (dirección confirmada bajista)
    elif (
        bearish
        and score >= MIN_ALERT_SCORE_SELL_SPOT
        and trend != "bullish"
    ):
        action, market = "SELL_SPOT", "SPOT"
        confidence = min(90, score - 3)
        if risk_level == "high":
            warnings.append("⚠ Riesgo alto — venta de cobertura, no apalancada")

    if action == "WAIT" and risk_level == "high":
        warnings.append("Riesgo alto detectado — entrada directa descartada")

    # ── Calcular niveles operables ────────────────────────────────────────
    setup: Optional[Dict[str, Any]] = None
    if action != "WAIT":
        setup = calculate_entry_exit(
            action=action,
            price=price,
            technical=technical,
            volume_profile=volume_profile,
            gex_data=gex_data,
        )
        # Si no hay setup válido (sin stop o sin TP1), degradar a WAIT
        if setup is None:
            warnings.append("Setup operativo incompleto — sin niveles de entrada/stop calculables")
            action = "WAIT"
            market = "NONE"

    return {
        "action": action,
        "market": market,
        "confidence": confidence,
        "confluence_score": score,
        "entry_context": _entry_narrative(signal, technical),
        "reasons": reasons,
        "warnings": warnings,
        "invalidation": _invalidation(signal, funding, volume_profile),
        "risk_level": risk_level,
        # ── Niveles operables (None si action == WAIT) ──────────────────
        "setup": setup,
    }
