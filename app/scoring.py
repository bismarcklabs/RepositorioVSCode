"""Score de confluencia institucional.

Distribución de puntos (total: ~105 teórico, efectivo 100 con cap):
    flow_score          30  — señal + CVD 1h + CVD 15m aceleración + OBI + liquidaciones
    technical_score     25  — VWAP + EMA 1m + EMA 1h (HTF) + momentum + RVOL
    volume_profile_score 15 — cercanía a POC / HVN / LVN
    footprint_score     15  — absorción, stacked imbalance, delta
    futures_score       15  — OI, funding, liquidaciones de futuros
    gex_score            5  — niveles gamma (BTC/ETH, opcional)
    risk_penalty        -30 — máximo posible de penalización

Resultado: max(0, min(100, raw - penalty))
"""
from typing import Any, Dict, List, Optional, Tuple

from app.config import EXTREME_FUNDING_ABS, MAX_SPREAD_PCT

_BULLISH = {"accumulation", "bullish_continuation", "short_squeeze"}
_BEARISH = {"distribution", "long_squeeze"}


# ── Sub-scores ────────────────────────────────────────────────────────────

def _flow_score(
    signal: str,
    metrics: Dict[str, float],
    imbalance: float,
    liquidation_summary: Optional[Dict],
) -> Tuple[int, List[str]]:
    """Señal institucional + alineación de flujo + aceleración CVD. Máx 30 pts."""
    pts = 0
    reasons: List[str] = []
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH
    cvd = metrics.get("cvd", 0.0)
    cvd_15m = metrics.get("cvd_15m", 0.0)

    if bullish or bearish:
        pts += 12
        label = "alcista" if bullish else "bajista"
        reasons.append(f"Señal institucional {label}: {signal}")

    if (bullish and cvd > 0) or (bearish and cvd < 0):
        pts += 6
        reasons.append(f"CVD alineado con señal: {cvd:.2f}")

    # Aceleración: flujo de los últimos 15 min va en la misma dirección
    # y representa más del 25% del CVD de la hora → presión reciente creciente
    cvd_abs = abs(cvd)
    cvd_15m_abs = abs(cvd_15m)
    if cvd_15m_abs > 0 and ((bullish and cvd_15m > 0) or (bearish and cvd_15m < 0)):
        if cvd_abs == 0 or cvd_15m_abs > cvd_abs * 0.25:
            pts += 3
            reasons.append(f"CVD acelerando — flujo 15m confirma dirección: {cvd_15m:.0f}")

    if (bullish and imbalance > 0.1) or (bearish and imbalance < -0.1):
        pts += 6
        reasons.append(f"Order book imbalance alineado: {imbalance:.3f}")

    if liquidation_summary:
        short_liq = liquidation_summary.get("short_count", 0)
        long_liq = liquidation_summary.get("long_count", 0)
        if bullish and short_liq > long_liq:
            pts += 6
            reasons.append("Liquidaciones de cortos confirman presión alcista")
        elif bearish and long_liq > short_liq:
            pts += 6
            reasons.append("Liquidaciones de largos confirman presión bajista")

    return min(30, pts), reasons


def _technical_score(
    technical: Dict[str, Any],
    signal: str,
) -> Tuple[int, List[str]]:
    """VWAP + EMA + momentum + volumen relativo + confirmación HTF 1h + RSI. Máx 25 pts."""
    pts = 0
    reasons: List[str] = []
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH

    above_vwap = technical.get("above_vwap", True)
    vwap_dist = technical.get("vwap_distance_pct", 0.0)
    ema20 = technical.get("ema_20", 0.0)
    ema50 = technical.get("ema_50", 0.0)
    r1h = technical.get("return_1h", 0.0)
    rel_vol = technical.get("relative_volume", 1.0)
    htf_trend = technical.get("htf_trend_bias", "neutral")
    rsi = technical.get("rsi", 50.0)

    # VWAP posición (6 pts)
    if (bullish and above_vwap) or (bearish and not above_vwap):
        pts += 6
        side = "sobre" if above_vwap else "bajo"
        reasons.append(f"Precio {side} VWAP ({vwap_dist:+.2f}%)")

    # Estructura EMA 1m (5 pts)
    ema_bullish = ema20 > ema50 > 0
    ema_bearish = ema20 < ema50
    if (bullish and ema_bullish) or (bearish and ema_bearish):
        pts += 5
        arrow = ">" if ema_bullish else "<"
        reasons.append(f"EMA20 {arrow} EMA50 — estructura {'alcista' if bullish else 'bajista'}")

    # Confirmación de tendencia horaria: EMA20 > EMA50 en 1h (5 pts)
    if (bullish and htf_trend == "bullish") or (bearish and htf_trend == "bearish"):
        pts += 5
        direction = "alcista" if bullish else "bajista"
        reasons.append(f"Tendencia 1h confirma señal {direction} — EMA horaria alineada")

    # Momentum 1h (5 pts)
    abs_r1h = abs(r1h)
    if abs_r1h >= 2.0:
        pts += 5
        reasons.append(f"Momentum 1h fuerte: {r1h:+.2f}%")
    elif abs_r1h >= 0.8:
        pts += 3
        reasons.append(f"Momentum 1h moderado: {r1h:+.2f}%")
    elif abs_r1h >= 0.3:
        pts += 1

    # Volumen relativo (8 pts) — se usa max(últimas 3 velas) vs baseline en technical_context
    if rel_vol >= 3.0:
        pts += 8
        reasons.append(f"Volumen relativo en breakout: {rel_vol:.1f}×")
    elif rel_vol >= 2.0:
        pts += 5
        reasons.append(f"Volumen relativo muy alto: {rel_vol:.1f}×")
    elif rel_vol >= 1.5:
        pts += 3
        reasons.append(f"Volumen relativo alto: {rel_vol:.1f}×")
    elif rel_vol >= 1.2:
        pts += 1

    # RSI(14): confirma zona favorable para la señal (4 pts)
    if bullish:
        if rsi <= 35:
            pts += 4
            reasons.append(f"RSI sobrevendido ({rsi:.1f}) — zona de rebote")
        elif rsi <= 50:
            pts += 2
            reasons.append(f"RSI favorable para largos ({rsi:.1f})")
    elif bearish:
        if rsi >= 65:
            pts += 4
            reasons.append(f"RSI sobrecomprado ({rsi:.1f}) — zona de reversión")
        elif rsi >= 50:
            pts += 2
            reasons.append(f"RSI favorable para cortos ({rsi:.1f})")

    return min(25, pts), reasons


def _volume_profile_score(
    vp_data: Optional[Dict[str, Any]],
    signal: str,
) -> Tuple[int, List[str]]:
    """Cercanía a niveles de Volume Profile. Máx 15 pts."""
    if not vp_data:
        return 0, []

    pts = 0
    reasons: List[str] = []
    nearest_type = vp_data.get("nearest_level_type", "NONE")
    dist_pct = abs(vp_data.get("distance_to_level_pct", 999.0))

    if nearest_type == "NONE":
        return 0, []

    if dist_pct <= 0.3:
        weight = 15 if nearest_type in ("POC", "HVN") else 7
        pts += weight
        reasons.append(f"Precio muy cerca de {nearest_type} ({dist_pct:.2f}% dist.)")
    elif dist_pct <= 0.8:
        weight = 10 if nearest_type in ("POC", "HVN") else 5
        pts += weight
        reasons.append(f"Precio cerca de {nearest_type} ({dist_pct:.2f}% dist.)")
    elif dist_pct <= 2.0:
        weight = 5 if nearest_type in ("POC", "HVN") else 3
        pts += weight
        reasons.append(f"Nivel {nearest_type} próximo ({dist_pct:.2f}% dist.)")
    elif dist_pct <= 4.0:
        pts += 2

    return min(15, pts), reasons


def _footprint_score(
    fp_data: Optional[Dict[str, Any]],
    signal: str,
) -> Tuple[int, List[str]]:
    """Absorción, stacked imbalance y delta del footprint. Máx 15 pts."""
    if not fp_data:
        return 0, []

    pts = 0
    reasons: List[str] = []
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH
    fp_delta = fp_data.get("footprint_delta", 0.0)
    abs_delta = abs(fp_delta)
    abs_bid = abs(fp_data.get("bid_volume", 0.0))
    abs_ask = abs(fp_data.get("ask_volume", 0.0))
    total_vol = abs_bid + abs_ask

    if bullish:
        if fp_data.get("absorption_buy"):
            pts += 5
            reasons.append("Absorción compradora: vendedores no logran bajar el precio")
        if fp_data.get("stacked_buy_imbalance"):
            pts += 5
            reasons.append("Stacked buy imbalance — presión compradora consecutiva")
        if fp_delta > 0 and total_vol > 0 and abs_delta / total_vol >= 0.2:
            pts += 5
            reasons.append(f"Delta del footprint positivo: {fp_delta:.2f}")
    elif bearish:
        if fp_data.get("absorption_sell"):
            pts += 5
            reasons.append("Absorción vendedora: compradores no logran subir el precio")
        if fp_data.get("stacked_sell_imbalance"):
            pts += 5
            reasons.append("Stacked sell imbalance — presión vendedora consecutiva")
        if fp_delta < 0 and total_vol > 0 and abs_delta / total_vol >= 0.2:
            pts += 5
            reasons.append(f"Delta del footprint negativo: {fp_delta:.2f}")

    return min(15, pts), reasons


def _futures_score(
    signal: str,
    funding: float,
    open_interest: float,
    liquidation_summary: Optional[Dict],
    oi_change_pct: float = 0.0,
) -> Tuple[int, List[str]]:
    """OI + OI change rate + funding + liquidaciones. Máx 15 pts."""
    pts = 0
    reasons: List[str] = []
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH

    if open_interest > 0:
        pts += 3
        reasons.append("Open interest activo")

    if bullish:
        if funding < -EXTREME_FUNDING_ABS:
            pts += 7
            reasons.append(f"Funding negativo ({funding:.5f}) — favorece largos")
        elif abs(funding) <= EXTREME_FUNDING_ABS:
            pts += 4
            reasons.append("Funding neutral — sin presión extrema")
    elif bearish:
        if funding > EXTREME_FUNDING_ABS * 2:
            pts += 7
            reasons.append(f"Funding alto ({funding:.5f}) — longs vulnerables")
        elif funding > 0:
            pts += 4
            reasons.append(f"Funding positivo ({funding:.5f}) — favorece cortos")

    # OI change rate: convicción de nuevas posiciones institucionales
    abs_oi_chg = abs(oi_change_pct)
    if abs_oi_chg >= 5.0:
        pts += 3
        direction = "creciendo" if oi_change_pct > 0 else "cayendo"
        reasons.append(f"OI {direction} fuerte ({oi_change_pct:+.1f}%) — nueva posición institucional")
    elif abs_oi_chg >= 2.0:
        pts += 1
        reasons.append(f"OI cambiando ({oi_change_pct:+.1f}%)")

    if liquidation_summary and liquidation_summary.get("total_volume", 0.0) > 0:
        pts += 5
        reasons.append("Actividad de liquidaciones registrada")

    return min(15, pts), reasons


def _gex_score(
    gex_data: Optional[Dict[str, Any]],
    signal: str,
    price: float,
) -> Tuple[int, List[str]]:
    """Soporte/resistencia gamma (solo BTC/ETH). Máx 5 pts."""
    if not gex_data or price <= 0.0:
        return 0, []

    pts = 0
    reasons: List[str] = []
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH

    put_wall = gex_data.get("put_wall", 0.0)
    call_wall = gex_data.get("call_wall", 0.0)
    gamma_flip = gex_data.get("gamma_flip", 0.0)

    if bullish and put_wall > 0.0 and price >= put_wall * 0.985:
        pts += 3
        reasons.append(f"Precio cerca de put wall — soporte GEX: {put_wall:,.0f}")
    if bearish and call_wall > 0.0 and price <= call_wall * 1.015:
        pts += 3
        reasons.append(f"Precio cerca de call wall — resistencia GEX: {call_wall:,.0f}")
    if gamma_flip > 0.0:
        if bullish and price > gamma_flip:
            pts += 2
            reasons.append(f"Precio sobre gamma flip ({gamma_flip:,.0f}) — zona positiva")
        elif bearish and price < gamma_flip:
            pts += 2
            reasons.append(f"Precio bajo gamma flip ({gamma_flip:,.0f}) — zona negativa")

    return min(5, pts), reasons


def _breakout_score(
    technical: Dict[str, Any],
    metrics: Dict[str, float],
    signal: str,
) -> Tuple[int, List[str]]:
    """Bonus por breakout de volumen + momentum alineado. Máx 15 pts.

    Activa cuando hay spike de volumen real (≥1.8×) con precio y CVD confirmando.
    Permite detectar el inicio de movimientos antes de que EMA/HTF confirmen.
    """
    rel_vol    = technical.get("relative_volume", 1.0)
    return_15m = technical.get("return_15m", 0.0)
    cvd_15m    = metrics.get("cvd_15m", 0.0)
    cvd        = metrics.get("cvd", 0.0)

    if rel_vol < 1.8:
        return 0, []

    pts = 0
    reasons: List[str] = []
    bullish = signal in _BULLISH
    bearish = signal in _BEARISH

    if rel_vol >= 3.0:
        pts += 6
        reasons.append(f"Breakout de volumen: {rel_vol:.1f}× el promedio")
    elif rel_vol >= 2.0:
        pts += 3
        reasons.append(f"Aceleración de volumen: {rel_vol:.1f}× el promedio")
    else:
        pts += 1

    if bullish and return_15m >= 0.5:
        pts += 5
        reasons.append(f"Precio rompiendo al alza: +{return_15m:.2f}% en 15m")
    elif bullish and return_15m >= 0.2:
        pts += 2
    elif bearish and return_15m <= -0.5:
        pts += 5
        reasons.append(f"Precio rompiendo a la baja: {return_15m:.2f}% en 15m")
    elif bearish and return_15m <= -0.2:
        pts += 2

    if cvd_15m != 0 and ((bullish and cvd_15m > 0) or (bearish and cvd_15m < 0)):
        if cvd == 0 or abs(cvd_15m) > abs(cvd) * 0.25:
            pts += 4
            reasons.append(f"CVD 15m acelerando en dirección del breakout")

    return min(15, pts), reasons


def _risk_penalty(
    signal: str,
    funding: float,
    spread_pct: float,
    technical: Dict[str, Any],
    breakout_pts: int = 0,
) -> Tuple[int, List[str]]:
    """Penalización por factores de riesgo. Máx -30 pts."""
    penalty = 0
    warnings: List[str] = []

    abs_f = abs(funding)
    if abs_f >= EXTREME_FUNDING_ABS * 5:
        penalty += 15
        warnings.append(f"Funding extremo ({funding:.5f}) — riesgo de reversión brusca")
    elif abs_f >= EXTREME_FUNDING_ABS * 2:
        penalty += 8
        warnings.append(f"Funding elevado ({funding:.5f})")

    if spread_pct >= MAX_SPREAD_PCT:
        penalty += 10
        warnings.append(f"Spread alto ({spread_pct:.3f}%) — liquidez reducida")
    elif spread_pct >= MAX_SPREAD_PCT * 0.5:
        penalty += 5
        warnings.append(f"Spread moderado ({spread_pct:.3f}%)")

    if signal == "neutral":
        penalty += 10
        warnings.append("Sin señal institucional clara")

    bullish = signal in _BULLISH
    bearish = signal in _BEARISH
    trend = technical.get("trend_bias", "neutral")
    htf_trend = technical.get("htf_trend_bias", "neutral")
    rsi = technical.get("rsi", 50.0)

    # Contradicción con tendencia 1m (señal más débil)
    if (bullish and trend == "bearish") or (bearish and trend == "bullish"):
        penalty += 5
        warnings.append("Señal contradice la tendencia de corto plazo (1m)")

    # Contradicción con tendencia horaria: se reduce si hay un breakout activo de volumen,
    # ya que el breakout puede estar cambiando la tendencia horaria en tiempo real.
    if (bullish and htf_trend == "bearish") or (bearish and htf_trend == "bullish"):
        htf_penalty = 4 if breakout_pts >= 8 else 8
        penalty += htf_penalty
        warnings.append(
            "Señal contradice tendencia horaria (1h)"
            + (" — breakout activo mitiga riesgo" if breakout_pts >= 8 else " — riesgo elevado de reversión")
        )

    # RSI agotado vs la dirección de la señal
    if bullish and rsi >= 78:
        penalty += 5
        warnings.append(f"RSI sobrecomprado ({rsi:.1f}) — señal alcista puede estar agotada")
    elif bearish and rsi <= 22:
        penalty += 5
        warnings.append(f"RSI sobrevendido ({rsi:.1f}) — señal bajista puede estar agotada")

    return min(penalty, 30), warnings   # cap en 30


# ── Multi-exchange confirmation ───────────────────────────────────────────

def _multi_exchange_score(
    multi_ex: Optional[Dict[str, Any]],
) -> Tuple[int, List[str]]:
    """Confirmación cruzada Coinbase + Kraken. Máx +5, mín -18.

    None = altcoin sin soporte externo → 0 pts, sin penalización.
    La lógica None-neutral es crítica: no penalizar altcoins por ausencia de dato.
    """
    if not multi_ex or not multi_ex.get("ok"):
        return 0, []

    conf = multi_ex.get("multi_exchange_confidence")
    dev  = multi_ex.get("price_deviation_pct")

    if conf is None:
        return 0, []  # altcoin sin cobertura externa — neutral

    pts: int = 0
    reasons: List[str] = []

    avail = multi_ex.get("exchange_availability_score", 100)

    if conf >= 80:
        pts += 5
        reasons.append(f"Confirmacion multi-exchange: {conf:.0f}% ({avail:.0f}% disponibilidad)")
    elif conf >= 60:
        pts += 2
        reasons.append(f"Confirmacion multi-exchange moderada: {conf:.0f}%")
    elif conf < 50:
        pts -= 10
        reasons.append(f"Divergencia entre exchanges: confianza {conf:.0f}%")

    if dev is not None and dev > 0.35:
        pts -= 8
        reasons.append(f"Divergencia de precio entre exchanges: {dev:.3f}%")

    return pts, reasons


# ── Score compuesto público ───────────────────────────────────────────────

def calculate_opportunity_score(
    symbol: str,
    metrics: Dict[str, float],
    signal: str,
    funding: float,
    open_interest: float,
    imbalance: float,
    spread_pct: float,
    technical: Dict[str, Any],
    liquidation_summary: Optional[Dict[str, Any]],
    price: float = 0.0,
    volume_profile: Optional[Dict[str, Any]] = None,
    footprint_data: Optional[Dict[str, Any]] = None,
    gex_data: Optional[Dict[str, Any]] = None,
    oi_change_pct: float = 0.0,
    # Kept for backwards compat — no longer used in scoring
    volume_24h: float = 0.0,
    multi_exchange_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    flow_pts, flow_r = _flow_score(signal, metrics, imbalance, liquidation_summary)
    tech_pts, tech_r = _technical_score(technical, signal)
    vp_pts, vp_r = _volume_profile_score(volume_profile, signal)
    fp_pts, fp_r = _footprint_score(footprint_data, signal)
    fut_pts, fut_r = _futures_score(signal, funding, open_interest, liquidation_summary, oi_change_pct)
    gex_pts, gex_r = _gex_score(gex_data, signal, price)
    bk_pts, bk_r  = _breakout_score(technical, metrics, signal)
    mx_pts, mx_r  = _multi_exchange_score(multi_exchange_data)
    penalty, warnings = _risk_penalty(signal, funding, spread_pct, technical, breakout_pts=bk_pts)

    raw = flow_pts + tech_pts + vp_pts + fp_pts + fut_pts + gex_pts + bk_pts + mx_pts - penalty
    score = max(0, min(100, raw))
    reasons = (flow_r + tech_r + vp_r + fp_r + fut_r + gex_r + bk_r + mx_r)[:8]

    return {
        "score": score,
        "flow_score": flow_pts,
        "technical_score": tech_pts,
        "volume_profile_score": vp_pts,
        "footprint_score": fp_pts,
        "futures_score": fut_pts,
        "gex_score": gex_pts,
        "breakout_score": bk_pts,
        "multi_exchange_score": mx_pts,
        "risk_penalty": penalty,
        "reasons": reasons,
        "warnings": warnings,
    }
