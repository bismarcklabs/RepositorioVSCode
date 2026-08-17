"""Descubrimiento de candidatos fuera del volumen — 2 canales adicionales
que comparten la watchlist multi-canal de accumulation_watch (ver
accumulation_scanner.py para el canal 'coiling'/'volatility_breakout').

- funding_extreme: reutiliza el mismo universo/funding_rate ya descargado en
  bloque para el scan de coiling — cero llamadas nuevas a Binance.
- oi_acceleration: Binance no tiene un endpoint de open interest para todos
  los símbolos a la vez (solo por símbolo, /futures/data/openInterestHist) —
  este canal SÍ agrega una llamada nueva por símbolo del universo, con el
  mismo patrón de pool de hilos que ya usa el scan de coiling.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from app import database
from app.accumulation_scanner import get_extended_universe
from app.config import (
    ACCUMULATION_FUNDING_EXTREME_ENABLED,
    ACCUMULATION_FUNDING_EXTREME_THRESHOLD,
    ACCUMULATION_MIN_QUOTE_VOLUME_USDT,
    ACCUMULATION_OI_ACCELERATION_ENABLED,
    ACCUMULATION_OI_ACCELERATION_LOOKBACK_HOURS,
    ACCUMULATION_OI_ACCELERATION_PCT,
    ACCUMULATION_WATCH_EXPIRE_HOURS,
)
from app.market_data import get_open_interest_hist

logger = logging.getLogger("candidate_discovery")


def scan_funding_extreme_candidates(
    min_quote_vol: Optional[float] = None,
    threshold: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Símbolos fuera del volumen principal con funding muy alto o muy
    negativo — presión de apalancamiento concentrada en un lado, posible
    squeeze, independiente de cuánto se opere el símbolo. Reutiliza el
    universo (ya trae funding_rate) sin llamadas nuevas."""
    if min_quote_vol is None:
        min_quote_vol = ACCUMULATION_MIN_QUOTE_VOLUME_USDT
    if threshold is None:
        threshold = ACCUMULATION_FUNDING_EXTREME_THRESHOLD

    universe = get_extended_universe(min_quote_vol)
    candidates: List[Dict[str, Any]] = []
    for item in universe:
        funding = item.get("funding_rate", 0.0)
        if abs(funding) < threshold:
            continue
        candidates.append({
            "symbol": item["symbol"],
            "quote_volume": item["quote_volume"],
            "funding_rate": funding,
            "channel": "funding_extreme",
            "channel_score": min(100.0, abs(funding) * 10_000.0),
        })
    candidates.sort(key=lambda x: x["channel_score"], reverse=True)
    return candidates


def _oi_change_pct(hist: List[Dict[str, Any]]) -> Optional[float]:
    """% de cambio entre el primer y último punto de la serie de OI
    (Binance las devuelve ordenadas de más antigua a más reciente)."""
    if len(hist) < 2:
        return None
    try:
        first = float(hist[0]["sumOpenInterest"])
        last = float(hist[-1]["sumOpenInterest"])
    except (KeyError, TypeError, ValueError):
        return None
    if first <= 0:
        return None
    return (last - first) / first * 100.0


def _scan_symbol_oi(symbol: str, limit: int) -> Optional[float]:
    try:
        hist = get_open_interest_hist(symbol, period="1h", limit=limit)
    except Exception:
        return None
    return _oi_change_pct(hist)


def scan_oi_acceleration_candidates(
    min_quote_vol: Optional[float] = None,
    pct_threshold: Optional[float] = None,
    lookback_hours: Optional[float] = None,
    max_workers: int = 10,
) -> List[Dict[str, Any]]:
    """Símbolos fuera del volumen principal cuyo open interest creció o
    cayó fuerte en las últimas `lookback_hours` — capital institucional
    entrando/saliendo, independiente del volumen de trading spot/futuros.
    Único de los 3 canales que agrega llamadas nuevas (una por símbolo, sin
    endpoint en bloque disponible en Binance para OI)."""
    if min_quote_vol is None:
        min_quote_vol = ACCUMULATION_MIN_QUOTE_VOLUME_USDT
    if pct_threshold is None:
        pct_threshold = ACCUMULATION_OI_ACCELERATION_PCT
    if lookback_hours is None:
        lookback_hours = ACCUMULATION_OI_ACCELERATION_LOOKBACK_HOURS

    universe = get_extended_universe(min_quote_vol)
    if not universe:
        return []

    limit = max(2, min(500, int(lookback_hours)))   # period=1h -> ~1 punto/hora

    candidates: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(_scan_symbol_oi, item["symbol"], limit): item
            for item in universe
        }
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                pct_change = future.result()
            except Exception:
                logger.debug("[%s] error en oi acceleration scan", item["symbol"])
                continue
            if pct_change is None or abs(pct_change) < pct_threshold:
                continue
            candidates.append({
                "symbol": item["symbol"],
                "quote_volume": item["quote_volume"],
                "funding_rate": item.get("funding_rate", 0.0),
                "oi_change_pct": pct_change,
                "channel": "oi_acceleration",
                "channel_score": min(100.0, abs(pct_change) / pct_threshold * 50.0),
            })

    candidates.sort(key=lambda x: x["channel_score"], reverse=True)
    return candidates


def run_candidate_discovery_scan() -> List[Dict[str, Any]]:
    """Ejecuta los canales habilitados (funding_extreme + oi_acceleration),
    persiste en accumulation_watch (misma tabla/expiry que Accumulation
    Watch) y retorna los candidatos detectados."""
    candidates: List[Dict[str, Any]] = []

    if ACCUMULATION_FUNDING_EXTREME_ENABLED:
        candidates.extend(scan_funding_extreme_candidates())

    if ACCUMULATION_OI_ACCELERATION_ENABLED:
        candidates.extend(scan_oi_acceleration_candidates())

    for c in candidates:
        try:
            database.upsert_accumulation_watch({
                "symbol": c["symbol"],
                "quote_volume": c["quote_volume"],
                "funding_at_watch": c.get("funding_rate", 0.0),
                "channel": c["channel"],
                "channel_score": c["channel_score"],
                "metrics": {
                    k: v for k, v in c.items()
                    if k not in ("symbol", "channel", "channel_score")
                },
            })
        except Exception:
            logger.exception("[%s] error guardando candidate_discovery", c.get("symbol"))

    try:
        expired = database.expire_stale_accumulation_watch(ACCUMULATION_WATCH_EXPIRE_HOURS)
        if expired:
            logger.info("CANDIDATE DISCOVERY: %d símbolo(s) expirado(s)", expired)
    except Exception:
        logger.exception("Error expirando accumulation_watch desde candidate_discovery")

    n_funding = sum(1 for c in candidates if c["channel"] == "funding_extreme")
    n_oi = len(candidates) - n_funding
    logger.info(
        "CANDIDATE DISCOVERY: %d funding_extreme + %d oi_acceleration",
        n_funding, n_oi,
    )
    return candidates
