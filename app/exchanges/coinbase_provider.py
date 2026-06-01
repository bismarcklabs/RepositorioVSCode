"""Provider Coinbase Exchange — endpoints públicos, sin autenticación.

API base: https://api.exchange.coinbase.com
Documentación: https://docs.cdp.coinbase.com/exchange/reference
"""
import logging
import time
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.exchanges.base import (
    ExchangeKline,
    ExchangeOrderBook,
    ExchangeTicker,
    _failed_orderbook,
    _failed_ticker,
)

logger = logging.getLogger("exchanges.coinbase")

_BASE = "https://api.exchange.coinbase.com"

# Cache compartido con lock (mismo patrón que market_data.py)
_cache: Dict[str, Tuple[Any, float]] = {}
_cache_lock = threading.Lock()
_session_lock = threading.Lock()
_session: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    global _session
    with _session_lock:
        if _session is None:
            _session = requests.Session()
            _session.headers.update({
                "User-Agent": "crypto-dashboard/2.0",
                "Accept": "application/json",
            })
        return _session


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires = entry
        if time.monotonic() < expires:
            return value
        del _cache[key]
    return None


def _cache_set(key: str, value: Any, ttl: float) -> None:
    with _cache_lock:
        _cache[key] = (value, time.monotonic() + ttl)


def _fetch(path: str, params: Optional[Dict] = None, ttl: float = 10.0) -> Optional[Any]:
    key = f"cb:{path}|{sorted((params or {}).items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = _get_session().get(f"{_BASE}{path}", params=params or {}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _cache_set(key, data, ttl)
        return data
    except Exception as exc:
        logger.debug("coinbase fetch error %s: %s", path, exc)
        return None


class CoinbaseProvider:
    name = "coinbase"

    def get_ticker(self, symbol: str, normalized_symbol: str) -> ExchangeTicker:
        """
        GET /products/{product-id}/ticker
        Retorna: price, bid, ask, volume, time
        """
        data = _fetch(f"/products/{symbol}/ticker", ttl=8.0)
        if not data or "price" not in data:
            return _failed_ticker(self.name, symbol, normalized_symbol,
                                  "no data" if not data else "missing price")
        try:
            price = float(data["price"])
            bid   = float(data["bid"])   if data.get("bid")   else None
            ask   = float(data["ask"])   if data.get("ask")   else None
            vol   = float(data["volume"]) if data.get("volume") else None
            spread_pct = (ask - bid) / bid * 100 if bid and ask else None
            return ExchangeTicker(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                price=price,
                volume_24h=vol,
                bid=bid,
                ask=ask,
                spread_pct=round(spread_pct, 4) if spread_pct is not None else None,
                timestamp=data.get("time"),
            )
        except Exception as exc:
            logger.debug("coinbase ticker parse error %s: %s", symbol, exc)
            return _failed_ticker(self.name, symbol, normalized_symbol, str(exc))

    def get_orderbook(self, symbol: str, normalized_symbol: str,
                      limit: int = 50) -> ExchangeOrderBook:
        """
        GET /products/{product-id}/book?level=2
        level=2: top 50 bids/asks agregados.
        """
        data = _fetch(f"/products/{symbol}/book", params={"level": 2}, ttl=5.0)
        if not data or "bids" not in data:
            return _failed_orderbook(self.name, symbol, normalized_symbol,
                                     "no data" if not data else "missing bids")
        try:
            # Cada entrada: [price, size, num_orders]
            bids = [(float(b[0]), float(b[1])) for b in data["bids"][:limit]]
            asks = [(float(a[0]), float(a[1])) for a in data["asks"][:limit]]
            return ExchangeOrderBook(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                bids=bids,
                asks=asks,
            )
        except Exception as exc:
            logger.debug("coinbase orderbook parse error %s: %s", symbol, exc)
            return _failed_orderbook(self.name, symbol, normalized_symbol, str(exc))

    def get_klines(self, symbol: str, interval: str = "1m",
                   limit: int = 100) -> List[ExchangeKline]:
        """
        GET /products/{product-id}/candles?granularity=<seconds>
        Coinbase usa granularidad en segundos: 60, 300, 900, 3600, 21600, 86400.
        Retorna: [[time_sec, low, high, open, close, volume], ...]  (desc)
        Máx 300 velas por llamada.
        """
        _interval_map = {
            "1m": 60, "5m": 300, "15m": 900, "1h": 3600,
            "6h": 21600, "1d": 86400,
        }
        gran = _interval_map.get(interval, 60)
        data = _fetch(f"/products/{symbol}/candles",
                      params={"granularity": gran}, ttl=30.0)
        if not isinstance(data, list):
            return []
        try:
            klines = []
            for row in reversed(data[:limit]):  # desc → asc
                klines.append(ExchangeKline(
                    open_time_ms=int(row[0]) * 1000,
                    open=float(row[3]),
                    high=float(row[2]),
                    low=float(row[1]),
                    close=float(row[4]),
                    volume=float(row[5]),
                ))
            return klines
        except Exception as exc:
            logger.debug("coinbase klines parse error %s: %s", symbol, exc)
            return []
