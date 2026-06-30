"""Accumulation Watch: detecta tokens fuera del top-50 por volumen en fase de
"coiling" (contracción de volatilidad + acumulación de volumen), antes de su
"ignición" (breakout tipo FOMO observado en HOME/ID/LAB/BEAT/RAVE, etc.).

Heurística `coiling_score` validada con backtest sobre 262 símbolos / 180 días
(hit rate ~20.7% en score>=45, retorno promedio +164% en aciertos). Una
contracción extrema (`contraction_ratio` < 0.2) cerca de mínimos de rango es
una señal fuerte por sí sola — no requiere estar sobre la SMA50 (eso solo
aporta un bono de tendencia).
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from app import database
from app.config import (
    ACCUMULATION_COILING_SCORE_THRESHOLD,
    ACCUMULATION_FUNDING_DROP_THRESHOLD,
    ACCUMULATION_IGNITION_VOLUME_MULT,
    ACCUMULATION_MIN_QUOTE_VOLUME_USDT,
    ACCUMULATION_WATCH_ENABLED,
    ACCUMULATION_WATCH_EXPIRE_HOURS,
    MIN_QUOTE_VOLUME_USDT,
)
from app.market_data import get_futures_ticker_all, get_klines, get_premium_index_all
from app.market_scanner import STABLECOIN_BLACKLIST

logger = logging.getLogger("accumulation_scanner")

_RECENT_ATR_WINDOW = 14
_BASELINE_ATR_WINDOW = 45
_RANGE_WINDOW = 60
_SMA_WINDOW = 50
_MIN_DAILY_KLINES = 60
_EXTREME_CONTRACTION_RATIO = 0.2


def compute_coiling_metrics(klines_1d: List[List[Any]]) -> Optional[Dict[str, Any]]:
    """Calcula el `coiling_score` (0-100) a partir de velas diarias.

    Requiere al menos `_MIN_DAILY_KLINES` velas. Retorna None si no hay
    suficientes datos.
    """
    if not klines_1d or len(klines_1d) < _MIN_DAILY_KLINES:
        return None

    highs = [float(k[2]) for k in klines_1d]
    lows = [float(k[3]) for k in klines_1d]
    closes = [float(k[4]) for k in klines_1d]
    volumes = [float(k[5]) for k in klines_1d]
    n = len(closes)

    daily_range_pct = [
        (h - l) / c * 100.0 if c > 0 else 0.0
        for h, l, c in zip(highs, lows, closes)
    ]

    recent_slice = daily_range_pct[-_RECENT_ATR_WINDOW:]
    recent_atr = sum(recent_slice) / len(recent_slice)

    baseline_start = max(0, n - _RECENT_ATR_WINDOW - _BASELINE_ATR_WINDOW)
    baseline_slice = daily_range_pct[baseline_start:-_RECENT_ATR_WINDOW]
    if not baseline_slice:
        baseline_slice = recent_slice
    baseline_atr = sum(baseline_slice) / len(baseline_slice)

    contraction_ratio = recent_atr / baseline_atr if baseline_atr > 0 else 1.0

    range_window = min(_RANGE_WINDOW, n)
    high_range = max(highs[-range_window:])
    low_range = min(lows[-range_window:])
    close = closes[-1]
    position_in_range = (
        (close - low_range) / (high_range - low_range)
        if high_range > low_range else 0.5
    )

    sma_window = min(_SMA_WINDOW, n)
    sma50 = sum(closes[-sma_window:]) / sma_window
    above_sma50 = close >= sma50

    vol7 = sum(volumes[-7:]) / min(7, n)
    vol30_window = min(30, n)
    vol30 = sum(volumes[-vol30_window:]) / vol30_window
    vol_ratio = vol7 / vol30 if vol30 > 0 else 1.0

    extreme_contraction = contraction_ratio < _EXTREME_CONTRACTION_RATIO

    # contraction_score (max 40)
    if contraction_ratio < 0.2:
        contraction_score = 40.0
    elif contraction_ratio < 0.4:
        contraction_score = 32.0
    elif contraction_ratio < 0.6:
        contraction_score = 22.0
    elif contraction_ratio < 0.8:
        contraction_score = 12.0
    else:
        contraction_score = 0.0

    # position_score (max 30) — favorece ~0.3 cerca de mínimos del rango.
    # Con contracción extrema, posiciones muy bajas (pos≈0) también son
    # válidas sin requerir above_sma50.
    if extreme_contraction:
        if position_in_range <= 0.15:
            position_score = 30.0
        elif position_in_range <= 0.35:
            position_score = 25.0
        elif position_in_range <= 0.5:
            position_score = 15.0
        else:
            position_score = 5.0
    else:
        if 0.15 <= position_in_range <= 0.45:
            position_score = 30.0
        elif position_in_range < 0.15:
            position_score = 18.0
        elif position_in_range <= 0.6:
            position_score = 15.0
        else:
            position_score = 0.0

    # trend_score (15) — bono, no gate
    trend_score = 15.0 if above_sma50 else 0.0

    # vol_score (15) — favorece acumulación moderada de volumen (1.0x-3.0x)
    if 1.0 <= vol_ratio <= 3.0:
        vol_score = 15.0
    elif vol_ratio > 3.0:
        vol_score = 7.5
    elif vol_ratio >= 0.6:
        vol_score = 8.0
    else:
        vol_score = 3.0

    coiling_score = contraction_score + position_score + trend_score + vol_score

    return {
        "coiling_score": round(coiling_score, 2),
        "contraction_ratio": round(contraction_ratio, 4),
        "position_in_range": round(position_in_range, 4),
        "above_sma50": above_sma50,
        "vol_ratio_7_30": round(vol_ratio, 4),
        "close": close,
    }


def _get_universe(min_quote_vol: float) -> List[Dict[str, Any]]:
    """Símbolos USDT-perp entre `min_quote_vol` y `MIN_QUOTE_VOLUME_USDT`.

    Los símbolos que ya superan `MIN_QUOTE_VOLUME_USDT` son candidatos del
    scanner principal (top-50) y no necesitan este canal.
    """
    tickers = {
        t["symbol"]: t
        for t in get_futures_ticker_all()
        if isinstance(t, dict) and "symbol" in t
    }
    funding_map = {
        f["symbol"]: float(f.get("lastFundingRate", 0.0))
        for f in get_premium_index_all()
        if isinstance(f, dict) and "symbol" in f
    }

    universe: List[Dict[str, Any]] = []
    for symbol, ticker in tickers.items():
        if not symbol.endswith("USDT"):
            continue
        if symbol in STABLECOIN_BLACKLIST:
            continue
        quote_vol = float(ticker.get("quoteVolume", 0.0))
        if quote_vol < min_quote_vol or quote_vol >= MIN_QUOTE_VOLUME_USDT:
            continue
        universe.append({
            "symbol": symbol,
            "quote_volume": quote_vol,
            "funding_rate": funding_map.get(symbol, 0.0),
        })
    return universe


def _scan_symbol_coiling(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        klines = get_klines(symbol, interval="1d", limit=90)
    except Exception:
        logger.debug("[%s] error obteniendo klines diarias", symbol)
        return None
    return compute_coiling_metrics(klines)


def scan_accumulation_candidates(
    min_quote_vol: Optional[float] = None,
    score_threshold: Optional[float] = None,
    max_workers: int = 10,
) -> List[Dict[str, Any]]:
    """Escanea el universo extendido y retorna candidatos con coiling_score
    >= `score_threshold`, ordenados de mayor a menor score."""
    if min_quote_vol is None:
        min_quote_vol = ACCUMULATION_MIN_QUOTE_VOLUME_USDT
    if score_threshold is None:
        score_threshold = ACCUMULATION_COILING_SCORE_THRESHOLD

    universe = _get_universe(min_quote_vol)
    if not universe:
        return []

    candidates: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_scan_symbol_coiling, item["symbol"]): item
            for item in universe
        }
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                metrics = future.result()
            except Exception:
                logger.debug("[%s] error en coiling scan", item["symbol"])
                continue
            if metrics is None:
                continue
            if metrics["coiling_score"] < score_threshold:
                continue
            metrics["symbol"] = item["symbol"]
            metrics["quote_volume"] = item["quote_volume"]
            metrics["funding_rate"] = item["funding_rate"]
            candidates.append(metrics)

    candidates.sort(key=lambda x: x["coiling_score"], reverse=True)
    return candidates


def run_accumulation_scan() -> List[Dict[str, Any]]:
    """Ejecuta el scan completo, persiste resultados en `accumulation_watch`
    y expira entradas obsoletas. Retorna los candidatos detectados."""
    if not ACCUMULATION_WATCH_ENABLED:
        return []

    candidates = scan_accumulation_candidates()
    for c in candidates:
        try:
            database.upsert_accumulation_watch({
                "symbol": c["symbol"],
                "coiling_score": c["coiling_score"],
                "contraction_ratio": c["contraction_ratio"],
                "position_in_range": c["position_in_range"],
                "above_sma50": c["above_sma50"],
                "vol_ratio_7_30": c["vol_ratio_7_30"],
                "quote_volume": c["quote_volume"],
                "funding_at_watch": c["funding_rate"],
                "price_at_watch": c["close"],
            })
        except Exception:
            logger.exception("[%s] error guardando accumulation_watch", c.get("symbol"))

    try:
        expired = database.expire_stale_accumulation_watch(ACCUMULATION_WATCH_EXPIRE_HOURS)
        if expired:
            logger.info("ACCUMULATION WATCH: %d simbolo(s) expirado(s)", expired)
    except Exception:
        logger.exception("Error expirando accumulation_watch")

    logger.info(
        "ACCUMULATION SCAN: %d candidato(s) con coiling_score>=%.0f",
        len(candidates), ACCUMULATION_COILING_SCORE_THRESHOLD,
    )
    return candidates


def check_ignition_trigger(
    watch_entry: Dict[str, Any],
    technical: Dict[str, Any],
    funding: float,
) -> Optional[str]:
    """Retorna la razón de "ignición" detectada, o None si no aplica.

    Disparadores (cualquiera basta):
    - `relative_volume` del pipeline principal >= `ACCUMULATION_IGNITION_VOLUME_MULT`
      (pico súbito de volumen — FOMO).
    - Funding cruza hacia/por debajo de cero respecto a la línea base
      registrada al entrar en watchlist (señal de short-squeeze, ej. HOME/ID/STO).
    """
    relative_volume = float(technical.get("relative_volume", 1.0) or 1.0)
    if relative_volume >= ACCUMULATION_IGNITION_VOLUME_MULT:
        return f"relative_volume {relative_volume:.2f}x >= {ACCUMULATION_IGNITION_VOLUME_MULT:.1f}x"

    funding_at_watch = float(watch_entry.get("funding_at_watch", 0.0) or 0.0)
    funding_now = float(funding or 0.0)
    if funding_at_watch > ACCUMULATION_FUNDING_DROP_THRESHOLD and funding_now <= ACCUMULATION_FUNDING_DROP_THRESHOLD:
        return f"funding {funding_at_watch:.5f} -> {funding_now:.5f} (cruce hacia/bajo cero)"

    return None
