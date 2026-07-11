"""Provider KuCoin — endpoints públicos spot, sin autenticación.

API base: https://api.kucoin.com/api/v1
Documentación: https://www.kucoin.com/docs/rest/spot-trading/market-data

Símbolos en formato KuCoin: "BTC-USDT", "ETH-USDT", etc.
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

logger = logging.getLogger("exchanges.kucoin")

_BASE = "https://api.kucoin.com"

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
                "Accept":     "application/json",
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
    key = f"kc:{path}|{sorted((params or {}).items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = _get_session().get(f"{_BASE}{path}", params=params or {}, timeout=2)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != "200000":
            logger.debug("kucoin api error %s: %s", path, body.get("msg"))
            return None
        data = body.get("data")
        _cache_set(key, data, ttl)
        return data
    except Exception as exc:
        logger.debug("kucoin fetch error %s: %s", path, exc)
        return None


class KuCoinProvider:
    name = "kucoin"

    def get_ticker(self, symbol: str, normalized_symbol: str) -> ExchangeTicker:
        """
        GET /api/v1/market/orderbook/level1?symbol=BTC-USDT
        Retorna: price (last trade), bestBid, bestAsk, size, time
        Volumen 24h: GET /api/v1/market/stats?symbol=BTC-USDT → vol field
        """
        l1 = _fetch("/api/v1/market/orderbook/level1", {"symbol": symbol}, ttl=8.0)
        if not l1 or "price" not in l1:
            return _failed_ticker(self.name, symbol, normalized_symbol,
                                  "no data" if not l1 else "missing price")
        try:
            price = float(l1["price"])
            bid   = float(l1["bestBid"]) if l1.get("bestBid") else None
            ask   = float(l1["bestAsk"]) if l1.get("bestAsk") else None
            spread_pct = (ask - bid) / bid * 100 if bid and ask else None

            # Volumen 24h en llamada separada (misma caché TTL)
            stats = _fetch("/api/v1/market/stats", {"symbol": symbol}, ttl=30.0)
            vol = float(stats["volValue"]) if stats and stats.get("volValue") else None

            return ExchangeTicker(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                price=price,
                volume_24h=vol,
                bid=bid,
                ask=ask,
                spread_pct=round(spread_pct, 4) if spread_pct is not None else None,
                timestamp=str(l1.get("time", "")),
            )
        except Exception as exc:
            logger.debug("kucoin ticker parse error %s: %s", symbol, exc)
            return _failed_ticker(self.name, symbol, normalized_symbol, str(exc))

    def get_orderbook(self, symbol: str, normalized_symbol: str,
                      limit: int = 50) -> ExchangeOrderBook:
        """
        GET /api/v1/market/orderbook/level2_20?symbol=BTC-USDT   (level2_20 o level2_100)
        Retorna: {"bids": [["price", "size"], ...], "asks": [...], "time": ms}
        """
        endpoint = "/api/v1/market/orderbook/level2_20" if limit <= 20 else "/api/v1/market/orderbook/level2_100"
        data = _fetch(endpoint, {"symbol": symbol}, ttl=5.0)
        if not data or "bids" not in data:
            return _failed_orderbook(self.name, symbol, normalized_symbol,
                                     "no data" if not data else "missing bids")
        try:
            bids = [(float(b[0]), float(b[1])) for b in data["bids"][:limit]]
            asks = [(float(a[0]), float(a[1])) for a in data["asks"][:limit]]
            return ExchangeOrderBook(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                bids=bids,
                asks=asks,
                timestamp=str(data.get("time", "")),
            )
        except Exception as exc:
            logger.debug("kucoin orderbook parse error %s: %s", symbol, exc)
            return _failed_orderbook(self.name, symbol, normalized_symbol, str(exc))

    def get_klines(self, symbol: str, interval: str = "1m",
                   limit: int = 100) -> List[ExchangeKline]:
        """
        GET /api/v1/market/candles?type=1min&symbol=BTC-USDT
        Intervalo: 1min, 3min, 5min, 15min, 30min, 1hour, 2hour, 4hour, 6hour, 8hour, 12hour, 1day, 1week
        Retorna: [["startAt", "open", "close", "high", "low", "volume", "turnover"], ...]
        Nota: índices distintos a Coinbase — close está en [2], high en [3], low en [4]
        """
        _interval_map = {
            "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
            "30m": "30min", "1h": "1hour", "4h": "4hour", "1d": "1day",
        }
        kc_interval = _interval_map.get(interval, "1min")
        data = _fetch("/api/v1/market/candles",
                      {"type": kc_interval, "symbol": symbol}, ttl=30.0)
        if not isinstance(data, list):
            return []
        try:
            klines = []
            for row in reversed(data[:limit]):   # KuCoin devuelve desc → asc
                klines.append(ExchangeKline(
                    open_time_ms=int(row[0]) * 1000,
                    open=float(row[1]),
                    high=float(row[3]),
                    low=float(row[4]),
                    close=float(row[2]),
                    volume=float(row[5]),
                ))
            return klines
        except Exception as exc:
            logger.debug("kucoin klines parse error %s: %s", symbol, exc)
            return []
