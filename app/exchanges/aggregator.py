"""Agregador multi-exchange con fallback a Binance.

Reglas de operación:
  - Binance = fuente primaria. Si Binance falla, el snapshot retorna ok=False.
  - Coinbase / Kraken = confirmación externa. Si fallan, no bloquean.
  - multi_exchange_confidence = None cuando no hay datos externos (sin penalización al scoring).
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from app.exchanges.base import ExchangeTicker
from app.exchanges.binance_provider import BinanceProvider
from app.exchanges.coinbase_provider import CoinbaseProvider
from app.exchanges.kraken_provider import KrakenProvider
from app.exchanges.symbol_map import get_exchange_symbol, is_supported

logger = logging.getLogger("exchanges.aggregator")

# Instancias únicas — stateless, thread-safe
_BINANCE  = BinanceProvider()
_COINBASE = CoinbaseProvider()
_KRAKEN   = KrakenProvider()

_EXTERNAL_PROVIDERS = [_COINBASE, _KRAKEN]


def _calculate_confirmation(tickers: Dict[str, ExchangeTicker],
                             normalized: str) -> Dict[str, Any]:
    """
    Calcula métricas de confirmación cruzada.

    Retorna dict con:
      exchange_availability_score  — 0-100, % de exchanges externos que respondieron
      price_deviation_pct          — None si < 2 precios disponibles
      multi_exchange_confidence    — None si sin datos externos (no penalizar en scoring)
      warnings                     — lista de strings
    """
    external_ok: List[ExchangeTicker] = [
        t for name, t in tickers.items()
        if name != "binance" and t.ok and t.price
    ]
    total_external = len(_EXTERNAL_PROVIDERS)
    availability = len(external_ok) / total_external * 100 if total_external else 0.0

    if not external_ok:
        return {
            "exchange_availability_score": round(availability, 1),
            "price_deviation_pct": None,
            "multi_exchange_confidence": None,
            "warnings": [],
        }

    # Precios disponibles incluyendo Binance
    all_ok = [t for t in tickers.values() if t.ok and t.price]
    prices = [t.price for t in all_ok]

    if len(prices) < 2:
        return {
            "exchange_availability_score": round(availability, 1),
            "price_deviation_pct": None,
            "multi_exchange_confidence": None,
            "warnings": [],
        }

    min_p = min(prices)
    max_p = max(prices)
    deviation_pct = (max_p - min_p) / min_p * 100 if min_p > 0 else 0.0

    # Base de confianza por alineación de precios
    if deviation_pct < 0.10:
        base_conf = 90
    elif deviation_pct < 0.30:
        base_conf = 75
    elif deviation_pct < 0.50:
        base_conf = 60
    else:
        base_conf = 30

    # Factor de disponibilidad: 1 exchange externo → 0.80×, 2 → 1.0×
    avail_factor = 0.80 if len(external_ok) == 1 else 1.0
    multi_conf = round(base_conf * avail_factor, 1)

    warnings: List[str] = []
    if deviation_pct > 0.50:
        warnings.append(
            f"Divergencia de precio entre exchanges: {deviation_pct:.3f}% "
            f"(min={min_p:.6g}, max={max_p:.6g})"
        )
    if len(external_ok) < total_external:
        missing = [
            p.name for p in _EXTERNAL_PROVIDERS
            if not tickers.get(p.name, ExchangeTicker("", "", "", None, None, ok=False)).ok
        ]
        warnings.append(f"Exchange(s) no disponibles: {', '.join(missing)}")

    return {
        "exchange_availability_score": round(availability, 1),
        "price_deviation_pct": round(deviation_pct, 4),
        "multi_exchange_confidence": multi_conf,
        "warnings": warnings,
    }


def get_multi_exchange_snapshot(binance_symbol: str,
                                normalized_symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Obtiene ticker de Binance + exchanges externos para un símbolo.

    Args:
        binance_symbol:   Símbolo en formato Binance (ej. "BTCUSDT")
        normalized_symbol: Base normalizada (ej. "BTC"). Si None, se infiere del symbol_map.

    Retorna dict:
        ok                         — bool (False solo si Binance falla)
        primary_available          — bool
        primary_price              — float | None
        primary_volume_24h         — float | None
        exchanges                  — dict[str, ExchangeTicker]
        exchange_availability_score — 0-100
        price_deviation_pct        — float | None
        multi_exchange_confidence  — float | None (None = no datos externos)
        warnings                   — list[str]
        external_supported         — bool (True si el símbolo está en symbol_map)
    """
    # Determinar base normalizada
    if normalized_symbol is None:
        from app.exchanges.symbol_map import get_normalized
        normalized_symbol = get_normalized(binance_symbol) or binance_symbol.replace("USDT", "")

    tickers: Dict[str, ExchangeTicker] = {}

    # ── Binance (primario) ─────────────────────────────────────────────────
    binance_ticker = _BINANCE.get_ticker(binance_symbol, normalized_symbol)
    tickers["binance"] = binance_ticker

    if not binance_ticker.ok:
        return {
            "ok": False,
            "primary_available": False,
            "primary_price": None,
            "primary_volume_24h": None,
            "exchanges": tickers,
            "exchange_availability_score": 0.0,
            "price_deviation_pct": None,
            "multi_exchange_confidence": None,
            "warnings": [f"Binance no disponible: {binance_ticker.error}"],
            "external_supported": is_supported(normalized_symbol),
        }

    # ── Exchanges externos en paralelo (solo si el símbolo está en el mapa) ─
    external_supported = is_supported(normalized_symbol)
    if external_supported:
        from app.exchanges.base import _failed_ticker as _ft

        def _fetch_external(provider):
            ext_sym = get_exchange_symbol(normalized_symbol, provider.name)
            if ext_sym is None:
                return provider.name, _ft(
                    provider.name, "", normalized_symbol,
                    f"{normalized_symbol} no listado en {provider.name}",
                )
            try:
                return provider.name, provider.get_ticker(ext_sym, normalized_symbol)
            except Exception as exc:
                logger.warning("%s get_ticker error %s: %s", provider.name, ext_sym, exc)
                return provider.name, _ft(provider.name, ext_sym, normalized_symbol, str(exc))

        with ThreadPoolExecutor(max_workers=len(_EXTERNAL_PROVIDERS)) as ex:
            futures = {ex.submit(_fetch_external, p): p.name for p in _EXTERNAL_PROVIDERS}
            for fut in as_completed(futures):
                name, ticker = fut.result()
                tickers[name] = ticker

    confirmation = _calculate_confirmation(tickers, normalized_symbol)

    return {
        "ok": True,
        "primary_available": True,
        "primary_price": binance_ticker.price,
        "primary_volume_24h": binance_ticker.volume_24h,
        "exchanges": tickers,
        "exchange_availability_score": confirmation["exchange_availability_score"],
        "price_deviation_pct": confirmation["price_deviation_pct"],
        "multi_exchange_confidence": confirmation["multi_exchange_confidence"],
        "warnings": confirmation["warnings"],
        "external_supported": external_supported,
    }
