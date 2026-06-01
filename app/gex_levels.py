"""GEX (Gamma Exposure) levels calculados desde opciones de Deribit.

Solo aplica para BTCUSDT y ETHUSDT.
Usa caché de 5 minutos para no saturar la API de Deribit.
Retorna None si la API no está disponible — el sistema funciona sin GEX.

Fórmula GEX por strike K:
    net_gex(K) = gamma_calls(K)*OI_calls(K) - gamma_puts(K)*OI_puts(K)
    gamma = BS_gamma(S, K, T, σ)  donde σ viene de mark_iv de Deribit.

Niveles:
    call_wall      = strike con mayor GEX neto positivo por encima del spot.
    put_wall       = strike con mayor GEX neto negativo (abs) por debajo del spot.
    gamma_flip     = strike donde el GEX **acumulado** cruza de positivo a negativo.
    nearest_gex_level  = nivel GEX más cercano al spot actual.
    nearest_gex_type   = "call_wall" | "put_wall" | "gamma_flip"
    distance_to_gex_pct = distancia % al nearest_gex_level
"""

import math
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

_DERIBIT_BASE = "https://www.deribit.com/api/v2/public"
_GEX_CACHE: Dict[str, Tuple[Optional[Dict], float]] = {}
_GEX_LOCK = threading.Lock()
_GEX_TTL = 300.0   # 5 minutos

_SUPPORTED = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}


# ── Black-Scholes gamma ───────────────────────────────────────────────────

def _bs_gamma(S: float, K: float, T: float, sigma: float) -> float:
    """Gamma de Black-Scholes (mismo valor para call y put)."""
    if T <= 1e-6 or sigma <= 1e-6 or S <= 0.0 or K <= 0.0:
        return 0.0
    try:
        d1 = (math.log(S / K) + (sigma ** 2 / 2.0) * T) / (sigma * math.sqrt(T))
        nd1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        return nd1 / (S * sigma * math.sqrt(T))
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


# ── Parsing ───────────────────────────────────────────────────────────────

def _parse_instrument(name: str) -> Optional[Tuple[datetime, float, str]]:
    """Parsea 'BTC-30MAY25-100000-C' → (expiry_datetime, strike, 'C'|'P')."""
    parts = name.split("-")
    if len(parts) != 4:
        return None
    _, expiry_str, strike_str, opt_type = parts
    if opt_type not in ("C", "P"):
        return None
    try:
        expiry = datetime.strptime(expiry_str, "%d%b%y")
        strike = float(strike_str)
        return expiry, strike, opt_type
    except (ValueError, KeyError):
        return None


# ── Cómputo GEX ──────────────────────────────────────────────────────────

def _compute_gex(currency: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(
            f"{_DERIBIT_BASE}/get_book_summary_by_currency",
            params={"currency": currency, "kind": "option"},
            timeout=15,
        )
        resp.raise_for_status()
        options: List[Dict] = resp.json().get("result", [])
    except Exception:
        return None

    if not options:
        return None

    now = datetime.utcnow()
    spot = 0.0
    call_gex_by_strike: Dict[float, float] = {}
    put_gex_by_strike: Dict[float, float] = {}

    for opt in options:
        parsed = _parse_instrument(opt.get("instrument_name", ""))
        if parsed is None:
            continue
        expiry, K, opt_type = parsed

        T = (expiry - now).total_seconds() / (365.0 * 86400.0)
        if T <= 0.0:
            continue

        S = float(opt.get("underlying_price", 0.0))
        iv_pct = float(opt.get("mark_iv", 0.0))
        oi = float(opt.get("open_interest", 0.0))
        sigma = iv_pct / 100.0

        if S <= 0.0 or sigma <= 0.0 or oi <= 0.0:
            continue

        if spot == 0.0:
            spot = S

        gamma = _bs_gamma(S, K, T, sigma)
        contribution = gamma * oi * S * S   # notional GEX

        if opt_type == "C":
            call_gex_by_strike[K] = call_gex_by_strike.get(K, 0.0) + contribution
        else:
            put_gex_by_strike[K] = put_gex_by_strike.get(K, 0.0) + contribution

    if (not call_gex_by_strike and not put_gex_by_strike) or spot == 0.0:
        return None

    # net GEX por strike: calls positivo, puts negativo
    all_strikes = sorted(set(call_gex_by_strike) | set(put_gex_by_strike))
    net_gex_by_strike: Dict[float, float] = {
        k: call_gex_by_strike.get(k, 0.0) - put_gex_by_strike.get(k, 0.0)
        for k in all_strikes
    }

    # GEX acumulado — de menor strike a mayor
    cumulative = 0.0
    cumulative_gex_by_strike: Dict[float, float] = {}
    for k in all_strikes:
        cumulative += net_gex_by_strike[k]
        cumulative_gex_by_strike[k] = cumulative

    # Gamma flip — primer cruce de cero en el GEX **acumulado**
    gamma_flip = spot
    prev_k: Optional[float] = None
    prev_cum: float = 0.0
    for k in all_strikes:
        cum = cumulative_gex_by_strike[k]
        if prev_k is not None:
            if (prev_cum < 0.0 and cum >= 0.0) or (prev_cum > 0.0 and cum <= 0.0):
                gamma_flip = (prev_k + k) / 2.0
                break
        prev_k = k
        prev_cum = cum

    # Call wall — strike con mayor GEX neto call por encima del spot
    above_calls = [(k, call_gex_by_strike[k]) for k in all_strikes
                   if k > spot and k in call_gex_by_strike]
    call_wall = max(above_calls, key=lambda x: x[1])[0] if above_calls else spot

    # Put wall — strike con mayor GEX neto put por debajo del spot
    below_puts = [(k, put_gex_by_strike[k]) for k in all_strikes
                  if k < spot and k in put_gex_by_strike]
    put_wall = max(below_puts, key=lambda x: x[1])[0] if below_puts else spot

    pos_levels = [round(k, 2) for k in all_strikes if net_gex_by_strike[k] > 0.0][:10]
    neg_levels = [round(k, 2) for k in all_strikes if net_gex_by_strike[k] < 0.0][:10]

    # Nearest GEX level al spot
    key_levels = {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": gamma_flip,
    }
    nearest_gex_type = min(key_levels, key=lambda t: abs(key_levels[t] - spot))
    nearest_gex_level = key_levels[nearest_gex_type]
    distance_to_gex_pct = (
        abs(nearest_gex_level - spot) / spot * 100.0 if spot > 0.0 else 0.0
    )

    return {
        "spot": round(spot, 2),
        "gamma_flip": round(gamma_flip, 2),
        "call_wall": round(call_wall, 2),
        "put_wall": round(put_wall, 2),
        "positive_gex_levels": pos_levels,
        "negative_gex_levels": neg_levels,
        "nearest_gex_level": round(nearest_gex_level, 2),
        "nearest_gex_type": nearest_gex_type,
        "distance_to_gex_pct": round(distance_to_gex_pct, 4),
    }


# ── API pública ───────────────────────────────────────────────────────────

def get_gex_levels(symbol: str) -> Optional[Dict[str, Any]]:
    """Retorna niveles GEX para BTCUSDT o ETHUSDT con caché de 5 min.

    Retorna None para símbolos no soportados o si la API de Deribit falla.
    El sistema debe seguir funcionando cuando retorna None (GEX = 0 pts).
    """
    currency = _SUPPORTED.get(symbol.upper())
    if currency is None:
        return None

    cache_key = f"gex_{currency}"
    with _GEX_LOCK:
        cached = _GEX_CACHE.get(cache_key)
        if cached is not None:
            data, expires = cached
            if time.monotonic() < expires:
                return data

    result = _compute_gex(currency)

    with _GEX_LOCK:
        _GEX_CACHE[cache_key] = (result, time.monotonic() + _GEX_TTL)

    return result
