"""Calibracion paralela de setups sin reemplazar el grado historico."""
from typing import Any, Dict, Optional

from app.config import CALIBRATION_VERSION
from app.market_regime import is_aligned_action, is_countertrend_action


def calibrate_setup(
    *, action: str, setup_evaluation: Optional[Dict[str, Any]],
    technical: Dict[str, Any], metrics: Dict[str, Any], setup: Optional[Dict[str, Any]],
    market_regime: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce sub-scores comparables y un grado calibrado observacional."""
    evaluation = setup_evaluation or {}
    checklist = evaluation.get("checklist") or {}
    is_long = action in {"LONG_FUTURES", "BUY_SPOT"}
    is_short = action in {"SHORT_FUTURES", "SELL_SPOT"}
    sign = 1 if is_long else -1 if is_short else 0

    direction_score = 20 + (35 if checklist.get("direction_ok") else 0)
    if sign * float(metrics.get("cvd_15m", metrics.get("cvd", 0)) or 0) > 0:
        direction_score += 15
    if sign * float(metrics.get("delta", 0) or 0) > 0:
        direction_score += 10
    if is_aligned_action(action, market_regime or {}):
        direction_score += 20
    elif is_countertrend_action(action, market_regime or {}):
        direction_score -= 25

    entry_score = 20
    entry_score += 35 if checklist.get("trigger_ok") else 0
    entry_score += 20 if checklist.get("context_ok") else 0
    entry_score += 15 if checklist.get("level_ok") else 0
    # Volumen relativo alto en SHORT suele indicar un selloff ya extendido
    # (entrada tardia / agotamiento) en vez de confirmacion de entrada.
    # En LONG, el bonus solo aplica si el gatillo ya se confirmo; sin trigger_ok,
    # alto relvol marca un setup "casi listo" con peor hit-rate a TP1 en 60min.
    if not is_short and checklist.get("trigger_ok") and float(technical.get("relative_volume", 1.0) or 1.0) >= 2.0:
        entry_score += 10

    trade_setup = setup or {}
    rr1 = float(trade_setup.get("risk_reward_1", 0) or 0)
    risk_pct = float(trade_setup.get("risk_pct", 0) or 0)
    risk_score = 20 + (55 if checklist.get("risk_ok") else 30 if rr1 >= 1.5 else 0)
    risk_score += 15 if trade_setup.get("stop_loss") else 0
    risk_score += 10 if 0 < risk_pct <= 3 else 0

    direction_score = max(0, min(100, direction_score))
    entry_score = max(0, min(100, entry_score))
    risk_score = max(0, min(100, risk_score))

    if direction_score >= 75 and entry_score >= 65 and risk_score >= 60:
        grade, watch_type = "A", ""
    elif direction_score >= 65 and entry_score >= 55 and risk_score >= 55:
        grade, watch_type = "B", ""
    elif direction_score >= 55 and entry_score >= 45 and risk_score >= 45:
        grade, watch_type = "C", ""
    elif is_short and direction_score >= 60:
        grade, watch_type = "BEARISH_WATCH", "BEARISH_WATCH"
    elif is_long and direction_score >= 60:
        grade, watch_type = "BULLISH_WATCH", "BULLISH_WATCH"
    else:
        grade, watch_type = "NO_TRADE", ""

    return {
        "original_grade": evaluation.get("grade", ""),
        "calibrated_grade": grade,
        "direction_score": direction_score,
        "entry_score": entry_score,
        "risk_score": risk_score,
        "calibration_version": CALIBRATION_VERSION,
        "watch_type": watch_type,
    }