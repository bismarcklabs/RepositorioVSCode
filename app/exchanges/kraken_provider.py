"""Provider Kraken — endpoints públicos REST.

API base: https://api.kraken.com/0/public
Nota: Kraken usa nombres internos distintos a los solicitados.
  - XBT/USD → respuesta con clave "XXBTZUSD"
  - ETH/USD → respuesta con clave "XETHZUSD"
  Resolvemos tomando el primer key del resultado.
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

logger = logging.getLogger("exchanges.kraken")

_BASE = "https://api.kraken.com/0/public"

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
    key = f"kr:{path}|{sorted((params or {}).items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = _get_session().get(f"{_BASE}{path}", params=params or {}, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            logger.debug("kraken api error %s: %s", path, data["error"])
            return None
        _cache_set(key, data.get("result"), ttl)
        return data.get("result")
    except Exception as exc:
        logger.debug("kraken fetch error %s: %s", path, exc)
        return None


def _normalize_pair(pair: str) -> str:
    """Convierte XBT/USD → XBTUSD para la API de Kraken."""
    return pair.replace("/", "")


class KrakenProvider:
    name = "kraken"

    def get_ticker(self, symbol: str, normalized_symbol: str) -> ExchangeTicker:
        """
        GET /Ticker?pair=XBTUSD
        Estructura resultado: {"XXBTZUSD": {"a": [ask, ...], "b": [bid, ...], "c": [last, ...], "v": [vol_today, vol_24h]}}
        """
        pair = _normalize_pair(symbol)
        result = _fetch("/Ticker", params={"pair": pair}, ttl=8.0)
        if not result:
            return _failed_ticker(self.name, symbol, normalized_symbol, "no data")
        try:
            # Kraken devuelve la clave interna del par, no la solicitada
            inner = next(iter(result.values()))
            price = float(inner["c"][0])      # last trade price
            bid   = float(inner["b"][0])      # best bid
            ask   = float(inner["a"][0])      # best ask
            vol   = float(inner["v"][1])      # volume últimas 24h
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
            )
        except Exception as exc:
            logger.debug("kraken ticker parse error %s: %s", symbol, exc)
            return _failed_ticker(self.name, symbol, normalized_symbol, str(exc))

    def get_orderbook(self, symbol: str, normalized_symbol: str,
                      limit: int = 50) -> ExchangeOrderBook:
        """
        GET /Depth?pair=XBTUSD&count=50
        Resultado: {"XXBTZUSD": {"bids": [[price, volume, timestamp], ...], "asks": [...]}}
        """
        pair = _normalize_pair(symbol)
        result = _fetch("/Depth", params={"pair": pair, "count": limit}, ttl=5.0)
        if not result:
            return _failed_orderbook(self.name, symbol, normalized_symbol, "no data")
        try:
            inner = next(iter(result.values()))
            bids = [(float(b[0]), float(b[1])) for b in inner.get("bids", [])]
            asks = [(float(a[0]), float(a[1])) for a in inner.get("asks", [])]
            return ExchangeOrderBook(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                bids=bids,
                asks=asks,
            )
        except Exception as exc:
            logger.debug("kraken orderbook parse error %s: %s", symbol, exc)
            return _failed_orderbook(self.name, symbol, normalized_symbol, str(exc))

    def get_klines(self, symbol: str, interval: str = "1m",
                   limit: int = 100) -> List[ExchangeKline]:
        """
        GET /OHLC?pair=XBTUSD&interval=1
        interval (minutos): 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
        Resultado: {"XXBTZUSD": [[time_sec, open, high, low, close, vwap, volume, count], ...], "last": N}
        Retorna hasta 720 velas.
        """
        _interval_map = {
            "1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440,
        }
        interval_min = _interval_map.get(interval, 1)
        pair = _normalize_pair(symbol)
        result = _fetch("/OHLC", params={"pair": pair, "interval": interval_min}, ttl=30.0)
        if not result:
            return []
        try:
            # Excluir la clave "last" (timestamp del último registro)
            data_key = next(k for k in result if k != "last")
            raw = result[data_key]
            klines = []
            for row in raw[-limit:]:   # últimas `limit` velas
                klines.append(ExchangeKline(
                    open_time_ms=int(row[0]) * 1000,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[6]),
                ))
            return klines
        except Exception as exc:
            logger.debug("kraken klines parse error %s: %s", symbol, exc)
            return []
