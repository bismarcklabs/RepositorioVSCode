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
    setup_route: str              # level_breakout | pattern_break | classic_trigger | momentum_continuation | none
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
    structure: Optional[Dict[str, Any]] = None,
) -> SetupEvaluation:
    """Evalúa el setup completo y retorna un SetupEvaluation con grado A/B/C/NO_TRADE.

    Rutas de calificación (prioridad descendente):
    - level_breakout: ruptura confirmada de un nivel S/R estructural (15m)
    - pattern_break: patrón chartista (H-C-H, doble techo/piso) con neckline rota
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

    # ── 3. Nivel (+15 VP, +12 S/R estructural, +8 solo GEX) ──────────────────
    vp           = volume_profile or {}
    nearest_type = vp.get("nearest_level_type", "NONE")
    vp_dist      = abs(float(vp.get("distance_to_level_pct", 999.0) or 999.0))

    gex         = gex_data or {}
    has_gex_lvl = bool(gex.get("call_wall") or gex.get("put_wall") or gex.get("gamma_flip"))

    struct = structure or {}
    struct_lvl = struct.get("nearest_support") if is_long else struct.get("nearest_resistance")
    struct_dist = abs(float((struct_lvl or {}).get("distance_pct", 999.0) or 999.0))

    if nearest_type != "NONE" and vp_dist <= 1.0:
        checklist["level_ok"] = True
        score += 15
        reasons.append(f"Precio cerca de nivel VP relevante: {nearest_type} ({vp_dist:.2f}%).")
    elif struct_lvl and struct_dist <= 1.5:
        checklist["level_ok"] = True
        score += 12
        side = "soporte" if is_long else "resistencia"
        reasons.append(
            f"Precio sobre {side} estructural de {struct_lvl['touches']} toques ({struct_dist:.2f}%)."
        )
    elif has_gex_lvl:
        checklist["level_ok"] = True
        score += 8
        reasons.append("Existe referencia GEX relevante como nivel.")
    else:
        warnings.append("No hay nivel VP/S-R/GEX suficientemente cercano.")

    # ── 4. Gatillo (+18 breakout / +16 patrón / +15 clásico / +12 momentum) ───
    trigger_direction = (trigger or {}).get("direction")
    trigger_type_str  = (trigger or {}).get("type", "")
    trigger_strength  = int((trigger or {}).get("strength", 0))

    setup_route = "none"

    # Ruta 1: ruptura confirmada de nivel estructural (la entrada "post-breakout")
    brk = struct.get("breakout")
    brk_aligned = bool(brk) and brk.get("confirmed") and (
        (is_long and brk.get("direction") == "up")
        or (is_short and brk.get("direction") == "down")
    )
    # Ruta 2: patrón chartista con neckline rota en la dirección del trade
    pattern = next(
        (p for p in struct.get("patterns", [])
         if p.get("confirmed") and (
             (is_long and p.get("direction") == "long")
             or (is_short and p.get("direction") == "short"))),
        None,
    )
    # Ruta 3: rebote en la 2a pata de un doble techo/piso (W/M), pre-neckline —
    # entrada más temprana que esperar la ruptura confirmada de la ruta 2.
    bounce = next(
        (p for p in struct.get("patterns", [])
         if p.get("bounce_valid") and (
             (is_long and p.get("direction") == "long")
             or (is_short and p.get("direction") == "short"))),
        None,
    )

    if brk_aligned:
        checklist["trigger_ok"] = True
        setup_route = "level_breakout"
        # level_breakout rinde peor en la practica que classic_trigger/momentum
        # continuation pese a exigir menos (solo requiere breakout.confirmed,
        # sin corroborar momentum/CVD reciente) — el puntaje alto (18) solo se
        # otorga cuando ademas hay confirmacion de tendencia sostenida, igual
        # que ya exige momentum_continuation. Sin esa confirmacion, puntaje
        # reducido (13) acorde al desempeno real medido.
        score += 18 if trend_continuation_valid else 13
        trigger_type_str = f"level_breakout_{brk['direction']}"
        reasons.append(
            f"Breakout confirmado de nivel de {brk['touches']} toques "
            f"(margen {brk['margin_pct']:.2f}%, RVOL {brk['rvol']:.1f}x)."
        )
    elif pattern:
        checklist["trigger_ok"] = True
        setup_route = "pattern_break"
        # Mismo criterio que level_breakout: bono completo (16) solo con
        # confirmacion de momentum, si no puntaje reducido (12).
        score += 16 if trend_continuation_valid else 12
        trigger_type_str = f"{pattern['pattern']}_break"
        reasons.append(
            f"Patrón {pattern['pattern']} confirmado — neckline {pattern['neckline']:.6g} rota."
        )
    elif is_long and trigger_direction == "long":
        checklist["trigger_ok"] = True
        setup_route = "classic_trigger"
        score += 15
        reasons.append(f"Gatillo alcista: {trigger_type_str} (fuerza {trigger_strength}).")
    elif is_short and trigger_direction == "short":
        checklist["trigger_ok"] = True
        setup_route = "classic_trigger"
        score += 15
        reasons.append(f"Gatillo bajista: {trigger_type_str} (fuerza {trigger_strength}).")
    elif bounce:
        checklist["trigger_ok"] = True
        setup_route = "pattern_bounce"
        score += 13
        trigger_type_str = f"{bounce['pattern']}_bounce"
        reasons.append(
            f"Rebote en 2a pata de {bounce['pattern']} "
            f"(progreso {bounce['bounce_progress_pct']:.0f}% hacia neckline) — entrada temprana pre-ruptura."
        )
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

    # Estructura en contra: breakout o patrón confirmado en dirección opuesta
    if brk and brk.get("confirmed") and not brk_aligned and (
        (is_long and brk.get("direction") == "down")
        or (is_short and brk.get("direction") == "up")
    ):
        score -= 10
        warnings.append("Breakout confirmado en dirección contraria al trade.")
    opposing = next(
        (p for p in struct.get("patterns", [])
         if (p.get("confirmed") or p.get("bounce_valid")) and (
             (is_long and p.get("direction") == "short")
             or (is_short and p.get("direction") == "long"))),
        None,
    )
    if opposing:
        score -= 10
        estado = "confirmado" if opposing.get("confirmed") else "en rebote de 2a pata"
        warnings.append(f"Patrón chartista contrario {estado}: {opposing['pattern']}.")

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

    # ── 6. Confirmación multi-exchange (+5 precio / +5 tendencia / -15 divergencia) ──
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

    ext_trend = mx.get("external_trend")
    ext_count = mx.get("external_trend_count", 0)
    if ext_trend and ext_trend != "neutral":
        is_long  = action in ("LONG_FUTURES", "BUY_SPOT")
        is_short = action in ("SHORT_FUTURES", "SELL_SPOT")
        aligned = (is_long and ext_trend == "bullish") or (is_short and ext_trend == "bearish")
        opposed = (is_long and ext_trend == "bearish") or (is_short and ext_trend == "bullish")
        if aligned:
            pts = 5 if ext_count >= 2 else 3
            score += pts
            reasons.append(
                f"Tendencia {ext_trend} confirmada en {ext_count} exchange(s) externo(s)."
            )
        elif opposed:
            checklist["external_ok"] = False
            score -= 5
            warnings.append(
                f"Tendencia externa contradice la dirección del trade ({ext_trend})."
            )

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
