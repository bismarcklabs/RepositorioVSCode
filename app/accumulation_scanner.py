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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from app import database
from app.db import _iso_to_ts
from app.config import (
    ACCUMULATION_ATL_ZONE_BAND_PCT,
    ACCUMULATION_COILING_SCORE_THRESHOLD,
    ACCUMULATION_DEEP_VALUE_ENABLED,
    ACCUMULATION_DEEP_VALUE_REFRESH_HOURS,
    ACCUMULATION_FUNDING_DROP_THRESHOLD,
    ACCUMULATION_IGNITION_VOLUME_MULT,
    ACCUMULATION_MIN_QUOTE_VOLUME_USDT,
    ACCUMULATION_STRUCTURAL_IGNITION_MIN_CVD_15M,
    ACCUMULATION_STRUCTURAL_IGNITION_MIN_OB_IMBALANCE,
    ACCUMULATION_VOLATILITY_BREAKOUT_ENABLED,
    ACCUMULATION_VOLATILITY_BREAKOUT_RATIO,
    ACCUMULATION_WATCH_ENABLED,
    ACCUMULATION_WATCH_EXPIRE_HOURS,
    MIN_QUOTE_VOLUME_USDT,
)
from app.historical_cache import ensure_history, get_klines_df
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


def get_extended_universe(min_quote_vol: float) -> List[Dict[str, Any]]:
    """Símbolos USDT-perp entre `min_quote_vol` y `MIN_QUOTE_VOLUME_USDT`.

    Los símbolos que ya superan `MIN_QUOTE_VOLUME_USDT` son candidatos del
    scanner principal (top-50) y no necesitan este canal. Público (no
    prefijo `_`) porque candidate_discovery.py reutiliza el mismo universo
    para sus propios canales (funding_extreme, oi_acceleration) — evita
    pedir tickers/funding en bloque dos veces por ciclo de scan.
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


def _classify_channel(
    metrics: Dict[str, Any],
    coiling_threshold: float,
    breakout_ratio: float,
    breakout_enabled: bool = True,
) -> Optional[Tuple[str, float]]:
    """Decide, a partir de las MISMAS métricas de compute_coiling_metrics()
    (sin pedir datos nuevos), si el símbolo califica para 'coiling'
    (contracción de volatilidad, heurística backtesteada — ver docstring del
    módulo) o 'volatility_breakout' (expansión ya en marcha: el mismo
    contraction_ratio pero invertido — un ATR reciente varias veces mayor al
    ATR base es un breakout ya ocurriendo, no una contracción previa a uno).
    Retorna (channel, channel_score) o None si no califica para ninguno."""
    coiling_score = metrics.get("coiling_score", 0.0)
    if coiling_score >= coiling_threshold:
        return "coiling", coiling_score

    if breakout_enabled:
        contraction_ratio = metrics.get("contraction_ratio", 1.0)
        if contraction_ratio >= breakout_ratio:
            # Normalizado a una escala comparable con coiling_score (0-100).
            breakout_score = min(100.0, contraction_ratio / breakout_ratio * 50.0)
            return "volatility_breakout", breakout_score

    return None


def scan_accumulation_candidates(
    min_quote_vol: Optional[float] = None,
    score_threshold: Optional[float] = None,
    breakout_ratio: Optional[float] = None,
    breakout_enabled: Optional[bool] = None,
    max_workers: int = 10,
) -> List[Dict[str, Any]]:
    """Escanea el universo extendido y retorna candidatos de los canales
    'coiling' (contracción) y 'volatility_breakout' (expansión ya en marcha),
    clasificados desde las mismas métricas — ver _classify_channel.
    Ordenados de mayor a menor channel_score."""
    if min_quote_vol is None:
        min_quote_vol = ACCUMULATION_MIN_QUOTE_VOLUME_USDT
    if score_threshold is None:
        score_threshold = ACCUMULATION_COILING_SCORE_THRESHOLD
    if breakout_ratio is None:
        breakout_ratio = ACCUMULATION_VOLATILITY_BREAKOUT_RATIO
    if breakout_enabled is None:
        breakout_enabled = ACCUMULATION_VOLATILITY_BREAKOUT_ENABLED

    universe = get_extended_universe(min_quote_vol)
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

            classification = _classify_channel(metrics, score_threshold, breakout_ratio, breakout_enabled)
            if classification is None:
                continue
            channel, channel_score = classification

            metrics["symbol"] = item["symbol"]
            metrics["quote_volume"] = item["quote_volume"]
            metrics["funding_rate"] = item["funding_rate"]
            metrics["channel"] = channel
            metrics["channel_score"] = channel_score
            candidates.append(metrics)

    candidates.sort(key=lambda x: x["channel_score"], reverse=True)
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
                "channel": c["channel"],
                "channel_score": c["channel_score"],
                "metrics": {
                    "contraction_ratio": c["contraction_ratio"],
                    "position_in_range": c["position_in_range"],
                    "vol_ratio_7_30": c["vol_ratio_7_30"],
                },
            })
        except Exception:
            logger.exception("[%s] error guardando accumulation_watch", c.get("symbol"))

        if ACCUMULATION_DEEP_VALUE_ENABLED:
            try:
                _maybe_refresh_deep_value(c["symbol"])
            except Exception:
                logger.exception("[%s] error calculando deep value", c["symbol"])

    try:
        expired = database.expire_stale_accumulation_watch(ACCUMULATION_WATCH_EXPIRE_HOURS)
        if expired:
            logger.info("ACCUMULATION WATCH: %d simbolo(s) expirado(s)", expired)
    except Exception:
        logger.exception("Error expirando accumulation_watch")

    n_coiling = sum(1 for c in candidates if c["channel"] == "coiling")
    n_breakout = len(candidates) - n_coiling
    logger.info(
        "ACCUMULATION SCAN: %d coiling (score>=%.0f) + %d volatility_breakout (ratio>=%.1f)",
        n_coiling, ACCUMULATION_COILING_SCORE_THRESHOLD, n_breakout, ACCUMULATION_VOLATILITY_BREAKOUT_RATIO,
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


_MIN_DEEP_VALUE_KLINES = 10


def compute_deep_value_metrics(symbol: str, source: str = "futures") -> Optional[Dict[str, Any]]:
    """Backfillea (incremental, via historical_cache) el historico diario
    completo del simbolo y calcula distancia al minimo historico real (ATL)
    + dias consecutivos con el cierre dentro de una banda sobre ese ATL
    (ACCUMULATION_ATL_ZONE_BAND_PCT).

    Es la unica funcion de este modulo que dispara I/O de red por simbolo
    fuera del universo por lotes — debe llamarse solo para simbolos ya
    clasificados por un canal (ver _maybe_refresh_deep_value), nunca sobre
    el universo extendido completo.
    """
    try:
        ensure_history(symbol, "1d", source=source)
        df = get_klines_df(symbol, "1d")
    except Exception:
        logger.debug("[%s] error en backfill historico para deep value", symbol)
        return None
    if df is None or df.empty or len(df) < _MIN_DEEP_VALUE_KLINES:
        return None

    atl_idx = df["low"].idxmin()
    atl_price = float(df.loc[atl_idx, "low"])
    if atl_price <= 0:
        return None
    atl_date = df.loc[atl_idx, "open_time"].strftime("%Y-%m-%d")
    close = float(df["close"].iloc[-1])
    dist_to_atl_pct = (close - atl_price) / atl_price * 100.0

    zone_ceiling = atl_price * (1 + ACCUMULATION_ATL_ZONE_BAND_PCT / 100.0)
    days_in_zone = 0
    for close_i in reversed(df["close"].tolist()):
        if close_i <= zone_ceiling:
            days_in_zone += 1
        else:
            break

    return {
        "atl_price": atl_price,
        "atl_date": atl_date,
        "dist_to_atl_pct": round(dist_to_atl_pct, 4),
        "days_in_atl_zone": days_in_zone,
    }


def _maybe_refresh_deep_value(symbol: str) -> None:
    """Llama compute_deep_value_metrics solo si no se ha refrescado en las
    ultimas ACCUMULATION_DEEP_VALUE_REFRESH_HOURS — el ATL no cambia de un
    dia para otro salvo nuevo minimo, y 'dias en zona' tampoco necesita mas
    resolucion que diaria."""
    existing = database.get_accumulation_watch_row(symbol)
    checked_at = (existing or {}).get("deep_value_checked_at")
    if checked_at:
        hours_since = (time.time() - _iso_to_ts(checked_at)) / 3600.0
        if hours_since < ACCUMULATION_DEEP_VALUE_REFRESH_HOURS:
            return
    deep = compute_deep_value_metrics(symbol)
    if deep:
        database.update_accumulation_deep_value(symbol, deep)


def check_structural_ignition_trigger(
    watch_entry: Dict[str, Any],
    result_row: Dict[str, Any],
) -> Optional[str]:
    """Ignición "fuerte": breakout de estructura confirmado (precio+RVOL, ver
    structure_levels.py) alineado con CVD 15m y order flow (footprint u
    orderbook) — la tesis de accumulation watch es long-only, solo evalúa
    dirección "up".

    Vía adicional a check_ignition_trigger() (RVOL/funding, más rápida pero
    más ruidosa) — pensada para dar una razón de ignición de mayor confianza
    cuando estructura, flujo de órdenes y delta acumulado coinciden.
    """
    structure = result_row.get("structure") or {}
    breakout = structure.get("breakout") or {}
    if not breakout.get("confirmed") or breakout.get("direction") != "up":
        return None

    metrics = result_row.get("metrics") or {}
    cvd_15m = float(metrics.get("cvd_15m", 0.0) or 0.0)
    if cvd_15m < ACCUMULATION_STRUCTURAL_IGNITION_MIN_CVD_15M:
        return None

    footprint = result_row.get("footprint") or {}
    orderbook = result_row.get("orderbook") or {}
    footprint_delta = float(footprint.get("footprint_delta", 0.0) or 0.0)
    stacked_buy = bool(footprint.get("stacked_buy_imbalance", False))
    ob_imbalance = float(orderbook.get("imbalance", 0.0) or 0.0)

    flow_confirmed = (
        footprint_delta > 0
        or stacked_buy
        or ob_imbalance >= ACCUMULATION_STRUCTURAL_IGNITION_MIN_OB_IMBALANCE
    )
    if not flow_confirmed:
        return None

    return (
        f"structural_breakout_cvd_confirmed level={breakout.get('level', 0.0):.6g} "
        f"margin={breakout.get('margin_pct', 0.0):.2f}% cvd_15m={cvd_15m:+.2f} "
        f"ob_imbalance={ob_imbalance:+.2f}"
    )
