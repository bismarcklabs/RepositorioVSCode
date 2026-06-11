from typing import Any, Dict, List, Optional

from app.config import (
    EXTREME_FUNDING_ABS,
    MIN_ALERT_SCORE_BUY_SPOT,
    MIN_ALERT_SCORE_LONG_FUTURES,
    MIN_ALERT_SCORE_SELL_SPOT,
    MIN_ALERT_SCORE_SHORT_FUTURES,
    BTC_REGIME_BLOCK_COUNTERTREND_BELOW_SCORE,
    BTC_REGIME_COUNTERTREND_CONFIDENCE_PENALTY,
    BTC_REGIME_ALIGNED_CONFIDENCE_BOOST,
)
from app.entry_exit import calculate_entry_exit
from app.market_regime import is_aligned_action, is_countertrend_action

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
    futures_price: Optional[float] = None,
    alert_report: Optional[Dict[str, Any]] = None,
    volume_profile: Optional[Dict[str, Any]] = None,
    gex_data: Optional[Dict[str, Any]] = None,
    multi_exchange_data: Optional[Dict[str, Any]] = None,
    market_regime: Optional[Dict[str, Any]] = None,
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

    # ── Ajuste por confirmación multi-exchange ────────────────────────────
    # Solo actúa cuando hay datos externos (external_supported=True).
    # Para altcoins (external_supported=False o mx_conf=None): sin ajuste,
    # sin warning — no penalizar por ausencia de dato externo.
    regime = market_regime or {}
    if action != "WAIT" and regime.get("active"):
        regime_name = regime.get("regime", "NORMAL")
        if is_countertrend_action(action, regime):
            if score < BTC_REGIME_BLOCK_COUNTERTREND_BELOW_SCORE:
                warnings.append(
                    f"{regime_name} activo: {action} bloqueado por ir contra BTC "
                    f"(score {score} < {BTC_REGIME_BLOCK_COUNTERTREND_BELOW_SCORE})"
                )
                action = "WAIT"
                market = "NONE"
            else:
                confidence = max(40, confidence - BTC_REGIME_COUNTERTREND_CONFIDENCE_PENALTY)
                warnings.append(
                    f"{regime_name} activo: {action} permitido solo por score alto; confianza penalizada"
                )
        elif is_aligned_action(action, regime):
            confidence = min(95, confidence + BTC_REGIME_ALIGNED_CONFIDENCE_BOOST)
            reasons.append(f"{regime_name} activo: direccion alineada con BTC")

    if action != "WAIT" and multi_exchange_data and multi_exchange_data.get("ok"):
        if multi_exchange_data.get("external_supported"):
            mx_conf  = multi_exchange_data.get("multi_exchange_confidence")
            mx_dev   = multi_exchange_data.get("price_deviation_pct")
            mx_warns = multi_exchange_data.get("warnings", [])

            if mx_conf is not None:
                if mx_conf < 50:
                    # Confirmación externa débil: bajar confianza 5 pts
                    confidence = max(40, confidence - 5)
                    dev_str = f" / divergencia {mx_dev:.3f}%" if mx_dev else ""
                    warnings.append(
                        f"Confirmacion externa baja: {mx_conf:.0f}%{dev_str}"
                    )
                elif mx_conf >= 80:
                    # Confirmación sólida: agregar como razón positiva
                    reasons.append(
                        f"Confirmacion multi-exchange: {mx_conf:.0f}%"
                    )

                # Divergencia de precio llamativa (independiente del tier de confianza)
                if mx_dev is not None and mx_dev > 0.50:
                    warnings.append(
                        f"Divergencia de precio entre exchanges: {mx_dev:.3f}% — validar entrada"
                    )

            # Ajuste por tendencia confirmada en exchanges externos (historial en memoria)
            ext_trend = multi_exchange_data.get("external_trend")
            ext_count = multi_exchange_data.get("external_trend_count", 0)
            if ext_trend and ext_trend != "neutral":
                is_bullish_action = action in ("LONG_FUTURES", "BUY_SPOT")
                is_bearish_action = action in ("SHORT_FUTURES", "SELL_SPOT")
                aligned = (is_bullish_action and ext_trend == "bullish") or \
                          (is_bearish_action and ext_trend == "bearish")
                opposed = (is_bullish_action and ext_trend == "bearish") or \
                          (is_bearish_action and ext_trend == "bullish")
                if aligned and ext_count >= 2:
                    confidence = min(95, confidence + 3)
                    reasons.append(f"Tendencia {ext_trend} confirmada en {ext_count} exchanges externos")
                elif aligned:
                    confidence = min(95, confidence + 1)
                elif opposed:
                    confidence = max(40, confidence - 4)
                    warnings.append(f"Tendencia externa contradice la operacion: {ext_trend}")

            # Propagar advertencias del aggregator que no estén ya cubiertas
            for w in mx_warns:
                already_covered = any(
                    existing.startswith(w[:30]) or w.startswith(existing[:30])
                    for existing in warnings
                )
                if not already_covered:
                    warnings.append(w)

    # ── Calcular niveles operables ────────────────────────────────────────
    setup: Optional[Dict[str, Any]] = None
    if action != "WAIT":
        setup_price = (futures_price or price) if "FUTURES" in action else price
        setup = calculate_entry_exit(
            action=action,
            price=setup_price,
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
        "market_regime": regime,
        # ── Niveles operables (None si action == WAIT) ──────────────────
        "setup": setup,
    }
