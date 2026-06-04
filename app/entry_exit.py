"""Cálculo de niveles operables para cada tipo de acción.

Produce timing, zona de entrada, stop loss, take profit 1/2, R/R y apalancamiento sugerido.
Retorna None si no hay setup válido (sin stop o sin TP1 calculable).
"""
from typing import Any, Dict, List, Optional

# Distancias mínimas de SL para evitar stops demasiado ajustados por ATR de 1m.
# Con 5x leverage, 1.5% → 7.5% riesgo efectivo — demasiado para un trade que
# con TP1 a 1.5R queda con R:R casi 1:1 cuando el precio deriva.
# Aumentado a 2.0% para garantizar que hay espacio real entre ruido y señal.
_MIN_SL_PCT_FUTURES = 0.020   # 2.0% mínimo para futuros
_MIN_SL_PCT_SPOT    = 0.012   # 1.2% mínimo para spot

# R:R mínimo para TPs — 1:1 no justifica la operativa
_MIN_TP1_RR = 1.5   # TP1 al menos 1.5R
_MIN_TP2_RR = 3.0   # TP2 al menos 3R


_LEVERAGE_LEVELS = [2, 3, 5, 7, 10, 15, 20]


def _suggest_leverage(sl_pct: float, action: str) -> int:
    """Apalancamiento máximo razonable: SL no debe superar el 10% del margen.

    Fórmula: leverage = floor(10 / sl_pct), luego ajustado al nivel estándar
    más bajo. Límite duro de 10x para futuros de altcoins (mayor volatilidad).
    """
    if "SPOT" in action or sl_pct <= 0:
        return 1
    raw = 10.0 / sl_pct            # leverage donde el SL consume ~10% del margen
    raw = min(raw, 10.0)           # cap en 10x para altcoins
    for lvl in reversed(_LEVERAGE_LEVELS):
        if lvl <= raw:
            return lvl
    return 2


def _rr(entry: float, stop: float, target: float) -> float:
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0.0:
        return 0.0
    return round(reward / risk, 2)


def _nearest_above(price: float, levels: List[float]) -> Optional[float]:
    above = [l for l in levels if l > price]
    return min(above) if above else None


def _nearest_below(price: float, levels: List[float]) -> Optional[float]:
    below = [l for l in levels if l < price]
    return max(below) if below else None


def calculate_entry_exit(
    action: str,
    price: float,
    technical: Dict[str, Any],
    volume_profile: Optional[Dict[str, Any]],
    gex_data: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Calcula timing, entrada, stop y TPs para una acción dada.

    Retorna None si no es posible construir un setup mínimo válido
    (entry > 0, stop > 0, stop != entry, TP1 > 0).
    """
    if price <= 0.0 or action not in ("BUY_SPOT", "LONG_FUTURES", "SHORT_FUTURES", "SELL_SPOT"):
        return None

    vwap = technical.get("vwap", 0.0)
    vwap_dist_pct = technical.get("vwap_distance_pct", 0.0)
    above_vwap = technical.get("above_vwap", True)
    atr = technical.get("atr", 0.0)

    poc = (volume_profile or {}).get("poc", 0.0)
    hvn_levels: List[float] = (volume_profile or {}).get("hvn_levels", [])
    lvn_levels: List[float] = (volume_profile or {}).get("lvn_levels", [])

    call_wall = (gex_data or {}).get("call_wall", 0.0)
    put_wall = (gex_data or {}).get("put_wall", 0.0)
    gamma_flip = (gex_data or {}).get("gamma_flip", 0.0)

    if action in ("BUY_SPOT", "LONG_FUTURES"):
        return _build_long(
            action, price, vwap, vwap_dist_pct, above_vwap,
            poc, hvn_levels, lvn_levels, put_wall, call_wall, gamma_flip,
            atr=atr,
        )

    if action in ("SHORT_FUTURES", "SELL_SPOT"):
        return _build_short(
            action, price, vwap, vwap_dist_pct, above_vwap,
            poc, hvn_levels, lvn_levels, call_wall, put_wall, gamma_flip,
            atr=atr,
        )

    return None


# ── Lógica long ───────────────────────────────────────────────────────────

def _build_long(
    action: str,
    price: float,
    vwap: float,
    vwap_dist_pct: float,
    above_vwap: bool,
    poc: float,
    hvn_levels: List[float],
    lvn_levels: List[float],
    put_wall: float,
    call_wall: float,
    gamma_flip: float,
    atr: float = 0.0,
) -> Optional[Dict[str, Any]]:

    # ── Timing ──────────────────────────────────────────────────────────────
    # NOW: precio sobre VWAP y a ≤ 0.8% de él
    if above_vwap and abs(vwap_dist_pct) <= 0.8:
        timing = "NOW"
        entry_type = "market_zone"
        entry_low = price * 0.999
        entry_high = price * 1.001
        entry = price
    elif above_vwap and abs(vwap_dist_pct) > 0.8:
        # Precio extendido sobre VWAP — esperar pullback a VWAP / POC / HVN
        timing = "WAIT_FOR_PULLBACK"
        entry_type = "pullback"
        pullback_target = _best_pullback_support(price, vwap, poc, hvn_levels, put_wall)
        if pullback_target <= 0.0:
            return None
        entry = pullback_target
        entry_low = pullback_target * 0.998
        entry_high = pullback_target * 1.002
    elif not above_vwap:
        # Precio bajo VWAP — esperar breakout de VWAP o de swing high reciente
        timing = "WAIT_FOR_BREAKOUT"
        entry_type = "breakout"
        entry = vwap if vwap > 0.0 else price
        entry_low = entry * 0.999
        entry_high = entry * 1.003
    else:
        timing = "WAIT"
        return None

    # ── Stop loss ────────────────────────────────────────────────────────────
    min_sl = _MIN_SL_PCT_SPOT if action == "BUY_SPOT" else _MIN_SL_PCT_FUTURES
    stop = _long_stop(entry, vwap, poc, hvn_levels, lvn_levels, put_wall, atr=atr, min_sl_pct=min_sl)
    if stop <= 0.0 or stop >= entry:
        return None

    risk_pct = (entry - stop) / entry * 100.0
    if risk_pct > 10.0:
        return None

    # ── Take profits — mínimo 1.5R / 3R para que el trade justifique el riesgo ──
    min_tp1 = entry + _MIN_TP1_RR * (entry - stop)
    min_tp2 = entry + _MIN_TP2_RR * (entry - stop)

    tp1_candidates: List[float] = []
    if call_wall > entry:
        tp1_candidates.append(call_wall)
    if gamma_flip > entry:
        tp1_candidates.append(gamma_flip)
    nearest_hvn_above = _nearest_above(entry, hvn_levels)
    if nearest_hvn_above:
        tp1_candidates.append(nearest_hvn_above)
    if poc > entry:
        tp1_candidates.append(poc)

    tp1 = min(tp1_candidates) if tp1_candidates else min_tp1
    tp1 = max(tp1, min_tp1)   # nunca menos de 1.5R

    tp2_candidates: List[float] = []
    if call_wall > tp1:
        tp2_candidates.append(call_wall)
    hvn_above_tp1 = [l for l in hvn_levels if l > tp1]
    if hvn_above_tp1:
        tp2_candidates.append(min(hvn_above_tp1))

    tp2 = min(tp2_candidates) if tp2_candidates else min_tp2
    tp2 = max(tp2, min_tp2)
    tp2 = max(tp2, tp1)   # TP2 nunca puede ser menor que TP1

    rr1 = _rr(entry, stop, tp1)
    rr2 = _rr(entry, stop, tp2)
    leverage = _suggest_leverage(risk_pct, action)
    note = _long_note(action, timing, entry_type, vwap, poc, put_wall, call_wall)

    return {
        "timing": timing,
        "entry_type": entry_type,
        "entry_zone_low": round(entry_low, 6),
        "entry_zone_high": round(entry_high, 6),
        "entry": round(entry, 6),
        "stop_loss": round(stop, 6),
        "take_profit_1": round(tp1, 6),
        "take_profit_2": round(tp2, 6),
        "risk_reward_1": rr1,
        "risk_reward_2": rr2,
        "risk_pct": round(risk_pct, 2),
        "suggested_leverage": leverage,
        "position_note": note,
    }


def _best_pullback_support(
    price: float,
    vwap: float,
    poc: float,
    hvn_levels: List[float],
    put_wall: float,
) -> float:
    candidates = []
    if vwap > 0.0 and vwap < price:
        candidates.append(vwap)
    hvn_below = [l for l in hvn_levels if l < price]
    if hvn_below:
        candidates.append(max(hvn_below))
    if poc > 0.0 and poc < price:
        candidates.append(poc)
    if put_wall > 0.0 and put_wall < price:
        candidates.append(put_wall)
    return max(candidates) if candidates else 0.0


def _long_stop(
    entry: float,
    vwap: float,
    poc: float,
    hvn_levels: List[float],
    lvn_levels: List[float],
    put_wall: float,
    atr: float = 0.0,
    min_sl_pct: float = _MIN_SL_PCT_FUTURES,
) -> float:
    candidates = []
    if vwap > 0.0 and vwap < entry:
        candidates.append(vwap * 0.998)
    hvn_below = [l for l in hvn_levels if l < entry]
    if hvn_below:
        candidates.append(max(hvn_below) * 0.997)
    if poc > 0.0 and poc < entry:
        candidates.append(poc * 0.997)
    if put_wall > 0.0 and put_wall < entry:
        candidates.append(put_wall * 0.997)
    if atr > 0.0:
        candidates.append(entry - 1.5 * atr)
    else:
        candidates.append(entry * 0.985)
    raw = max(candidates)
    # Garantizar distancia mínima: si la señal estructural es muy ajustada,
    # usar al menos min_sl_pct para evitar stops sacudidos por ruido de 1m.
    floor_stop = entry * (1.0 - min_sl_pct)
    return min(raw, floor_stop)   # el más bajo de los dos = más margen


def _long_note(
    action: str,
    timing: str,
    entry_type: str,
    vwap: float,
    poc: float,
    put_wall: float,
    call_wall: float,
) -> str:
    notes = []
    if timing == "NOW":
        notes.append("Entrada inmediata — precio en zona de confluencia")
    elif timing == "WAIT_FOR_PULLBACK":
        ref = "VWAP" if vwap > 0.0 else "soporte VP"
        notes.append(f"Esperar pullback a {ref} antes de entrar")
    elif timing == "WAIT_FOR_BREAKOUT":
        notes.append("Esperar cierre sobre VWAP para confirmar dirección")
    if put_wall > 0.0:
        notes.append(f"Put wall en {put_wall:,.2f} actúa como soporte dealer")
    if call_wall > 0.0:
        notes.append(f"Objetivo call wall {call_wall:,.2f}")
    if action == "LONG_FUTURES":
        notes.append("Ajustar tamaño según volatilidad — usar stop ajustado")
    return " | ".join(notes)


# ── Lógica short ──────────────────────────────────────────────────────────

def _build_short(
    action: str,
    price: float,
    vwap: float,
    vwap_dist_pct: float,
    above_vwap: bool,
    poc: float,
    hvn_levels: List[float],
    lvn_levels: List[float],
    call_wall: float,
    put_wall: float,
    gamma_flip: float,
    atr: float = 0.0,
) -> Optional[Dict[str, Any]]:

    # ── Timing ──────────────────────────────────────────────────────────────
    if not above_vwap and abs(vwap_dist_pct) <= 0.8:
        timing = "NOW"
        entry_type = "market_zone"
        entry = price
        entry_low = price * 0.999
        entry_high = price * 1.001
    elif not above_vwap and abs(vwap_dist_pct) > 0.8:
        # Precio muy extendido bajo VWAP — esperar pullback a VWAP / POC / HVN
        timing = "WAIT_FOR_PULLBACK"
        entry_type = "pullback"
        pullback_target = _best_pullback_resistance(price, vwap, poc, hvn_levels, call_wall)
        if pullback_target <= 0.0:
            return None
        entry = pullback_target
        entry_low = pullback_target * 0.998
        entry_high = pullback_target * 1.002
    elif above_vwap:
        # Precio sobre VWAP — esperar breakdown
        timing = "WAIT_FOR_BREAKOUT"
        entry_type = "breakout"
        entry = vwap if vwap > 0.0 else price
        entry_low = entry * 0.997
        entry_high = entry * 1.001
    else:
        return None

    # ── Stop loss ────────────────────────────────────────────────────────────
    min_sl = _MIN_SL_PCT_SPOT if action == "SELL_SPOT" else _MIN_SL_PCT_FUTURES
    stop = _short_stop(entry, vwap, poc, hvn_levels, call_wall, atr=atr, min_sl_pct=min_sl)
    if stop <= 0.0 or stop <= entry:
        return None

    risk_pct = (stop - entry) / entry * 100.0
    if risk_pct > 10.0:
        return None

    # ── Take profits — mínimo 1.5R / 3R para que el trade justifique el riesgo ──
    min_tp1 = entry - _MIN_TP1_RR * (stop - entry)
    min_tp2 = entry - _MIN_TP2_RR * (stop - entry)

    tp1_candidates: List[float] = []
    if put_wall > 0.0 and put_wall < entry:
        tp1_candidates.append(put_wall)
    if gamma_flip > 0.0 and gamma_flip < entry:
        tp1_candidates.append(gamma_flip)
    nearest_hvn_below = _nearest_below(entry, hvn_levels)
    if nearest_hvn_below:
        tp1_candidates.append(nearest_hvn_below)
    if poc > 0.0 and poc < entry:
        tp1_candidates.append(poc)

    tp1 = max(tp1_candidates) if tp1_candidates else min_tp1
    tp1 = min(tp1, min_tp1)   # para shorts, tp1 más bajo = más reward; min() lo hace más agresivo

    tp2_candidates: List[float] = []
    if put_wall > 0.0 and put_wall < tp1:
        tp2_candidates.append(put_wall)
    hvn_below_tp1 = [l for l in hvn_levels if l < tp1]
    if hvn_below_tp1:
        tp2_candidates.append(max(hvn_below_tp1))

    tp2 = max(tp2_candidates) if tp2_candidates else min_tp2
    tp2 = min(tp2, min_tp2)
    tp2 = min(tp2, tp1)   # TP2 nunca puede ser mayor que TP1 para shorts

    rr1 = _rr(entry, stop, tp1)
    rr2 = _rr(entry, stop, tp2)
    leverage = _suggest_leverage(risk_pct, action)
    note = _short_note(action, timing, entry_type, vwap, poc, call_wall, put_wall)

    return {
        "timing": timing,
        "entry_type": entry_type,
        "entry_zone_low": round(entry_low, 6),
        "entry_zone_high": round(entry_high, 6),
        "entry": round(entry, 6),
        "stop_loss": round(stop, 6),
        "take_profit_1": round(tp1, 6),
        "take_profit_2": round(tp2, 6),
        "risk_reward_1": rr1,
        "risk_reward_2": rr2,
        "risk_pct": round(risk_pct, 2),
        "suggested_leverage": leverage,
        "position_note": note,
    }


def _best_pullback_resistance(
    price: float,
    vwap: float,
    poc: float,
    hvn_levels: List[float],
    call_wall: float,
) -> float:
    candidates = []
    if vwap > 0.0 and vwap > price:
        candidates.append(vwap)
    hvn_above = [l for l in hvn_levels if l > price]
    if hvn_above:
        candidates.append(min(hvn_above))
    if poc > 0.0 and poc > price:
        candidates.append(poc)
    if call_wall > 0.0 and call_wall > price:
        candidates.append(call_wall)
    return min(candidates) if candidates else 0.0


def _short_stop(
    entry: float,
    vwap: float,
    poc: float,
    hvn_levels: List[float],
    call_wall: float,
    atr: float = 0.0,
    min_sl_pct: float = _MIN_SL_PCT_FUTURES,
) -> float:
    candidates = []
    if vwap > 0.0 and vwap > entry:
        candidates.append(vwap * 1.002)
    hvn_above = [l for l in hvn_levels if l > entry]
    if hvn_above:
        candidates.append(min(hvn_above) * 1.003)
    if poc > 0.0 and poc > entry:
        candidates.append(poc * 1.003)
    if call_wall > 0.0 and call_wall > entry:
        candidates.append(call_wall * 1.003)
    if atr > 0.0:
        candidates.append(entry + 1.5 * atr)
    else:
        candidates.append(entry * 1.015)
    raw = min(candidates)
    # Garantizar distancia mínima: si la resistencia estructural es muy ajustada,
    # usar al menos min_sl_pct para evitar stops sacudidos por ruido de 1m.
    ceil_stop = entry * (1.0 + min_sl_pct)
    return max(raw, ceil_stop)    # el más alto de los dos = más margen


def _short_note(
    action: str,
    timing: str,
    entry_type: str,
    vwap: float,
    poc: float,
    call_wall: float,
    put_wall: float,
) -> str:
    notes = []
    if timing == "NOW":
        notes.append("Entrada inmediata — precio bajo VWAP con flujo vendedor")
    elif timing == "WAIT_FOR_PULLBACK":
        ref = "VWAP" if vwap > 0.0 else "resistencia VP"
        notes.append(f"Esperar pullback a {ref} para entrada de menor riesgo")
    elif timing == "WAIT_FOR_BREAKOUT":
        notes.append("Esperar pérdida de VWAP con cierre bajo para confirmar")
    if call_wall > 0.0:
        notes.append(f"Call wall en {call_wall:,.2f} actúa como resistencia dealer")
    if put_wall > 0.0:
        notes.append(f"Objetivo put wall {put_wall:,.2f}")
    if action == "SHORT_FUTURES":
        notes.append("Funding debe mantenerse positivo — monitorear cobertura de shorts")
    return " | ".join(notes)
