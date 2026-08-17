from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.market_data import get_klines


def _ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    k = 2.0 / (period + 1)
    result = prices[0]
    for p in prices[1:]:
        result = p * k + result * (1 - k)
    return result


def _atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Wilder's ATR. Requiere al menos 2 velas."""
    if len(closes) < 2:
        return 0.0
    true_ranges = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    if not true_ranges:
        return 0.0
    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges)
    atr_val = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def _rsi(closes: List[float], period: int = 14) -> float:
    """RSI con suavizado de Wilder. Retorna 50.0 si no hay suficientes datos."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0.0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _default_context(last_price: float = 0.0) -> Dict[str, Any]:
    return {
        "return_3m": 0.0,
        "return_5m": 0.0,
        "return_15m": 0.0,
        "return_1h": 0.0,
        "ema_20": last_price,
        "ema_50": last_price,
        "vwap": last_price,
        "vwap_distance_pct": 0.0,
        "above_vwap": True,
        "relative_volume": 1.0,
        "trend_bias": "neutral",
        "atr": 0.0,
        "atr_pct": 0.0,
        "htf_trend_bias": "neutral",
        "ema_50_1h": last_price,
        "rsi": 50.0,
    }


def get_technical_context(symbol: str, klines_1m: Optional[List] = None) -> Dict[str, Any]:
    """EMA20/50 (1m), VWAP, momentum, ATR(14) y tendencia horaria (1h) en paralelo.

    Formato de kline Binance:
    [openTime, open, high, low, close, baseVol, closeTime, quoteVol, ...]

    Si el llamador ya tiene velas de 1m del mismo ciclo (ej. _scan_symbol), pasarlas
    en klines_1m evita un segundo fetch idéntico a Binance.
    """
    if klines_1m is None:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_1m = ex.submit(get_klines, symbol, "1m", 60)
            f_1h = ex.submit(get_klines, symbol, "1h", 50)
            klines = f_1m.result()
            klines_1h = f_1h.result()
    else:
        klines = klines_1m
        klines_1h = get_klines(symbol, "1h", 50)

    if len(klines) < 20:
        return _default_context()

    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    quote_vols = [float(k[7]) for k in klines]

    last_price = closes[-1]

    ema_20 = _ema(closes, 20)
    ema_50 = _ema(closes, 50 if len(closes) >= 50 else len(closes))

    # VWAP ponderado por volumen USDT
    typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    vwap_num = sum(tp * qv for tp, qv in zip(typical, quote_vols))
    vwap_den = sum(quote_vols)
    vwap = vwap_num / vwap_den if vwap_den > 0.0 else last_price
    vwap_distance_pct = (last_price - vwap) / vwap * 100.0 if vwap > 0.0 else 0.0

    # Momentum
    return_3m = 0.0
    if len(closes) >= 3:
        ref = closes[-3]
        return_3m = (last_price - ref) / ref * 100.0 if ref > 0.0 else 0.0

    return_5m = 0.0
    if len(closes) >= 5:
        ref = closes[-5]
        return_5m = (last_price - ref) / ref * 100.0 if ref > 0.0 else 0.0

    return_15m = 0.0
    if len(closes) >= 15:
        ref = closes[-15]
        return_15m = (last_price - ref) / ref * 100.0 if ref > 0.0 else 0.0
    return_1h = (last_price - closes[0]) / closes[0] * 100.0 if closes[0] > 0.0 else 0.0

    # Volumen relativo: máximo de las últimas 3 velas vs baseline de 20 velas completas.
    # Usar max() captura el pico aunque la vela actual esté incompleta (Binance incluye
    # la vela abierta como último elemento) o el spike haya empezado 1-2 velas antes.
    baseline_vols = quote_vols[-21:-1] if len(quote_vols) >= 21 else quote_vols[:-1]
    avg_vol = sum(baseline_vols) / len(baseline_vols) if baseline_vols else (quote_vols[-1] or 1.0)
    recent_peak_vol = max(quote_vols[-3:]) if len(quote_vols) >= 3 else quote_vols[-1]
    relative_volume = recent_peak_vol / avg_vol if avg_vol > 0.0 else 1.0

    # Bias de tendencia en 1m
    if ema_20 > ema_50 and return_1h > 0.3:
        trend_bias = "bullish"
    elif ema_20 < ema_50 and return_1h < -0.3:
        trend_bias = "bearish"
    else:
        trend_bias = "neutral"

    # ATR(14) y RSI(14) desde velas de 1m
    atr_val = _atr(highs, lows, closes, period=14)
    atr_pct = atr_val / last_price * 100.0 if last_price > 0.0 else 0.0
    rsi_val = _rsi(closes, period=14)

    # Tendencia horaria: EMA20 y EMA50 en velas de 1h
    htf_trend_bias = "neutral"
    ema_50_1h = 0.0
    if len(klines_1h) >= 20:
        closes_1h = [float(k[4]) for k in klines_1h]
        ema_20_1h = _ema(closes_1h, 20)
        ema_50_1h = _ema(closes_1h, min(50, len(closes_1h)))
        htf_ret = (last_price - closes_1h[0]) / closes_1h[0] * 100.0 if closes_1h[0] > 0.0 else 0.0
        if ema_20_1h > ema_50_1h and htf_ret > 0:
            htf_trend_bias = "bullish"
        elif ema_20_1h < ema_50_1h and htf_ret < 0:
            htf_trend_bias = "bearish"

    return {
        "return_3m": round(return_3m, 4),
        "return_5m": round(return_5m, 4),
        "return_15m": round(return_15m, 4),
        "return_1h": round(return_1h, 4),
        "ema_20": round(ema_20, 8),
        "ema_50": round(ema_50, 8),
        "vwap": round(vwap, 8),
        "vwap_distance_pct": round(vwap_distance_pct, 4),
        "above_vwap": last_price >= vwap,
        "relative_volume": round(relative_volume, 4),
        "trend_bias": trend_bias,
        "atr": round(atr_val, 8),
        "atr_pct": round(atr_pct, 4),
        "htf_trend_bias": htf_trend_bias,
        "ema_50_1h": round(ema_50_1h, 8),
        "rsi": round(rsi_val, 2),
    }
