"""Evaluación estructurada de setups operables.

Valida cinco condiciones antes de asignar un grado al setup:
  1. Dirección — CVD, delta y footprint apuntan al mismo lado
  2. Contexto  — VWAP, tendencia y HTF son coherentes
  3. Nivel     — precio cerca de zona VP o referencia GEX
  4. Gatillo   — hay un patrón de price action confirmando la entrada
  5. Riesgo    — setup tiene R:R ≥ 1.5 y stop ≤ 5% del precio

Grados: A (score≥85, core completo) / B (score≥70, core completo) /
        C (score≥60, core incompleto) / NO_TRADE (resto).

NO bloquea alertas por defecto — eso lo controla ENABLE_SETUP_GATE en config.py.
"""
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SetupEvaluation:
    valid: bool
    grade: str                    # A | B | C | NO_TRADE
    score: int                    # 0-100
    direction: str                # long | short | neutral
    trigger_type: Optional[str]   # tipo de gatillo o None
    setup_route: str              # classic_trigger | momentum_continuation | none
    reasons: List[str]
    warnings: List[str]
    checklist: Dict[str, bool]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_trade_setup(
    *,
    action: str,
    technical: Dict[str, Any],
    metrics: Dict[str, Any],
    footprint: Optional[Dict[str, Any]],
    volume_profile: Optional[Dict[str, Any]],
    gex_data: Optional[Dict[str, Any]],
    setup: Optional[Dict[str, Any]],
    trigger: Optional[Dict[str, Any]],
    multi_exchange: Optional[Dict[str, Any]] = None,
    trend_continuation_valid: bool = False,
    trend_priority_score: int = 0,
) -> SetupEvaluation:
    """Evalúa el setup completo y retorna un SetupEvaluation con grado A/B/C/NO_TRADE.

    Dos rutas de calificación:
    - classic_trigger: gatillo de price action (engulfing / rechazo / VWAP reclaim)
    - momentum_continuation: tendencia fuerte sostenida sin gatillo clásico
    """

    is_long  = action in {"LONG_FUTURES", "BUY_SPOT"}
    is_short = action in {"SHORT_FUTURES", "SELL_SPOT"}

    reasons:  List[str] = []
    warnings: List[str] = []
    score = 0

    checklist: Dict[str, bool] = {
        "direction_ok": False,
        "context_ok":   False,
        "level_ok":     False,
        "trigger_ok":   False,
        "risk_ok":      False,
        "external_ok":  True,   # neutro por defecto; puede degradarse con mx débil
    }

    # ── 1. Dirección (+20 base, +10 footprint) ────────────────────────────────
    delta    = float(metrics.get("delta",    0.0) or 0.0)
    cvd      = float(metrics.get("cvd",      0.0) or 0.0)
    fp_delta = float((footprint or {}).get("footprint_delta", 0.0) or 0.0)

    if is_long and delta > 0 and cvd > 0:
        checklist["direction_ok"] = True
        score += 20
        reasons.append("Delta y CVD confirman presión compradora.")
    elif is_short and delta < 0 and cvd < 0:
        checklist["direction_ok"] = True
        score += 20
        reasons.append("Delta y CVD confirman presión vendedora.")
    else:
        warnings.append("Delta/CVD no confirman plenamente la dirección.")

    if is_long and fp_delta > 0:
        score += 10
        reasons.append("Footprint acompaña la compra.")
    elif is_short and fp_delta < 0:
        score += 10
        reasons.append("Footprint acompaña la venta.")

    # ── 2. Contexto (+15 base, +5 HTF) ───────────────────────────────────────
    above_vwap = technical.get("above_vwap")
    trend      = technical.get("trend_bias",     "neutral")
    htf        = technical.get("htf_trend_bias", "neutral")

    if is_long and above_vwap and trend != "bearish":
        checklist["context_ok"] = True
        score += 15
        reasons.append("Contexto técnico favorable para largo.")
    elif is_short and above_vwap is False and trend != "bullish":
        checklist["context_ok"] = True
        score += 15
        reasons.append("Contexto técnico favorable para corto.")
    else:
        warnings.append("VWAP/tendencia no dan contexto ideal.")

    if is_long  and htf == "bullish":
        score += 5
    elif is_short and htf == "bearish":
        score += 5

    # ── 3. Nivel (+15 VP, +8 solo GEX) ───────────────────────────────────────
    vp           = volume_profile or {}
    nearest_type = vp.get("nearest_level_type", "NONE")
    vp_dist      = abs(float(vp.get("distance_to_level_pct", 999.0) or 999.0))

    gex         = gex_data or {}
    has_gex_lvl = bool(gex.get("call_wall") or gex.get("put_wall") or gex.get("gamma_flip"))

    if nearest_type != "NONE" and vp_dist <= 1.0:
        checklist["level_ok"] = True
        score += 15
        reasons.append(f"Precio cerca de nivel VP relevante: {nearest_type} ({vp_dist:.2f}%).")
    elif has_gex_lvl:
        checklist["level_ok"] = True
        score += 8
        reasons.append("Existe referencia GEX relevante como nivel.")
    else:
        warnings.append("No hay nivel VP/GEX suficientemente cercano.")

    # ── 4. Gatillo (+15) ──────────────────────────────────────────────────────
    trigger_direction = (trigger or {}).get("direction")
    trigger_type_str  = (trigger or {}).get("type", "")
    trigger_strength  = int((trigger or {}).get("strength", 0))

    setup_route = "none"

    if is_long and trigger_direction == "long":
        checklist["trigger_ok"] = True
        setup_route = "classic_trigger"
        score += 15
        reasons.append(f"Gatillo alcista: {trigger_type_str} (fuerza {trigger_strength}).")
    elif is_short and trigger_direction == "short":
        checklist["trigger_ok"] = True
        setup_route = "classic_trigger"
        score += 15
        reasons.append(f"Gatillo bajista: {trigger_type_str} (fuerza {trigger_strength}).")
    elif trend_continuation_valid:
        # Ruta alternativa: tendencia fuerte y persistente sustituye al gatillo clásico
        checklist["trigger_ok"] = True
        setup_route = "momentum_continuation"
        score += 12   # ligeramente menos que un gatillo clásico (+15)
        trigger_type_str = "momentum_continuation"
        reasons.append(
            f"Continuación de tendencia: CVD, VWAP, HTF y momentum alineados "
            f"(trend_score={trend_priority_score})."
        )
    else:
        warnings.append("Sin gatillo claro de price action.")

    # ── 5. Riesgo (+15) ───────────────────────────────────────────────────────
    if setup:
        rr1      = float(setup.get("risk_reward_1", 0.0) or 0.0)
        risk_pct = float(setup.get("risk_pct",      0.0) or 0.0)

        if rr1 >= 1.5 and risk_pct <= 5.0:
            checklist["risk_ok"] = True
            score += 15
            reasons.append(f"R:R aceptable — TP1 {rr1:.1f}R, stop {risk_pct:.2f}%.")
        elif rr1 >= 1.5:
            # R:R ok pero stop amplio — penalización parcial
            score += 7
            warnings.append(f"Stop amplio ({risk_pct:.2f}%) — reducir tamaño de posición.")
        else:
            warnings.append(f"R:R insuficiente: {rr1:.1f}R (mínimo 1.5R).")
    else:
        warnings.append("No hay niveles de entrada, stop y take profit calculados.")

    # ── 6. Confirmación multi-exchange (+5 / -10) ─────────────────────────────
    mx      = multi_exchange or {}
    mx_conf = mx.get("multi_exchange_confidence")
    if mx_conf is not None:
        if mx_conf >= 80:
            score += 5
            reasons.append(f"Confirmación multi-exchange fuerte: {mx_conf:.0f}%.")
        elif mx_conf < 50:
            checklist["external_ok"] = False
            score -= 10
            warnings.append(f"Confirmación multi-exchange débil: {mx_conf:.0f}%.")

    # ── Grado final ───────────────────────────────────────────────────────────
    score = max(0, min(100, score))

    core_ok = all([
        checklist["direction_ok"],
        checklist["context_ok"],
        checklist["level_ok"],
        checklist["trigger_ok"],
        checklist["risk_ok"],
    ])

    if core_ok and score >= 85:
        grade, valid = "A", True
    elif core_ok and score >= 70:
        grade, valid = "B", True
    elif score >= 60:
        grade, valid = "C", False
    else:
        grade, valid = "NO_TRADE", False

    return SetupEvaluation(
        valid=valid,
        grade=grade,
        score=score,
        direction="long" if is_long else "short" if is_short else "neutral",
        trigger_type=trigger_type_str or None,
        setup_route=setup_route,
        reasons=reasons,
        warnings=warnings,
        checklist=checklist,
    )
