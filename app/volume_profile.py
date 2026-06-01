from typing import Any, Dict, List, Tuple

from app.market_data import get_klines

_BINS = 50


def _default_profile(last_price: float = 0.0) -> Dict[str, Any]:
    return {
        "poc": last_price,
        "hvn_levels": [],
        "lvn_levels": [],
        "nearest_level": last_price,
        "nearest_level_type": "NONE",
        "distance_to_level_pct": 0.0,
    }


def _find_nearest(
    poc: float,
    hvn: List[float],
    lvn: List[float],
    price: float,
) -> Tuple[float, str]:
    candidates = [(poc, "POC")] + [(l, "HVN") for l in hvn] + [(l, "LVN") for l in lvn]
    return min(candidates, key=lambda x: abs(x[0] - price))


def get_volume_profile(symbol: str, bins: int = _BINS) -> Dict[str, Any]:
    """Calcula un Volume Profile usando las últimas 48 velas de 5m (~4h) de futuros.

    Distribuye el volumen USDT de cada vela uniformemente entre el rango high-low,
    luego identifica:
    - POC  (Point of Control): nivel de precio con mayor volumen acumulado.
    - HVN  (High Volume Node): niveles con volumen >= 1.5× el promedio.
    - LVN  (Low Volume Node): niveles con volumen <= 0.5× el promedio y > 0.

    Fuente: /fapi/v1/klines (caché 30 s en market_data).
    """
    klines = get_klines(symbol, interval="5m", limit=48)
    if len(klines) < 10:
        return _default_profile()

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    quote_vols = [float(k[7]) for k in klines]

    last_price = closes[-1]
    price_min = min(lows)
    price_max = max(highs)

    if price_max <= price_min:
        return _default_profile(last_price)

    bucket_size = (price_max - price_min) / bins
    volume_at: List[float] = [0.0] * bins

    for h, lo, qv in zip(highs, lows, quote_vols):
        lo_idx = max(0, int((lo - price_min) / bucket_size))
        hi_idx = min(bins - 1, int((h - price_min) / bucket_size))
        n = hi_idx - lo_idx + 1
        if n <= 0:
            continue
        share = qv / n
        for i in range(lo_idx, hi_idx + 1):
            volume_at[i] += share

    poc_idx = max(range(bins), key=lambda i: volume_at[i])
    poc = price_min + (poc_idx + 0.5) * bucket_size

    avg_vol = sum(volume_at) / bins
    hvn: List[float] = []
    lvn: List[float] = []
    for i, vol in enumerate(volume_at):
        level = price_min + (i + 0.5) * bucket_size
        if vol >= avg_vol * 1.5:
            hvn.append(level)
        elif 0.0 < vol <= avg_vol * 0.5:
            lvn.append(level)

    nearest_level, nearest_type = _find_nearest(poc, hvn, lvn, last_price)
    dist_pct = (
        (last_price - nearest_level) / nearest_level * 100.0
        if nearest_level > 0.0
        else 0.0
    )

    return {
        "poc": round(poc, 8),
        "hvn_levels": [round(l, 8) for l in hvn],
        "lvn_levels": [round(l, 8) for l in lvn],
        "nearest_level": round(nearest_level, 8),
        "nearest_level_type": nearest_type,
        "distance_to_level_pct": round(dist_pct, 4),
    }
