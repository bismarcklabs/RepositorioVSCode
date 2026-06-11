import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.config import BINANCE_FUTURES_BASE_URL

_SPOT_BASE = "https://api.binance.com"
_FUTURES_BASE = BINANCE_FUTURES_BASE_URL

# ── Per-thread Session (thread-safe, reutiliza conexiones dentro del hilo) ─
_thread_local = threading.local()

# ── TTL cache compartido entre hilos, protegido con lock ──────────────────
_cache: Dict[str, Tuple[Any, float]] = {}
_cache_lock = threading.Lock()


def _get_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers["User-Agent"] = "crypto-dashboard/2.0"
        _thread_local.session = s
    return _thread_local.session


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


def _fetch(url: str, params: Optional[Dict] = None, ttl: float = 10.0) -> Optional[Any]:
    key = f"{url}|{sorted((params or {}).items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = _get_session().get(url, params=params or {}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _cache_set(key, data, ttl)
        return data
    except Exception:
        return None


# ── Batch endpoints — 3 llamadas cubren todos los pares USDT de futuros ───

def get_futures_ticker_all() -> List[Dict]:
    """Ticker 24h de todos los pares de futuros. TTL 60s."""
    data = _fetch(f"{_FUTURES_BASE}/fapi/v1/ticker/24hr", ttl=60.0)
    return data if isinstance(data, list) else []


def get_premium_index_all() -> List[Dict]:
    """Funding rate actual de todos los pares. TTL 120s."""
    data = _fetch(f"{_FUTURES_BASE}/fapi/v1/premiumIndex", ttl=120.0)
    return data if isinstance(data, list) else []


def get_book_ticker_all() -> List[Dict]:
    """Mejor bid/ask de todos los pares de futuros. TTL 5s."""
    data = _fetch(f"{_FUTURES_BASE}/fapi/v1/ticker/bookTicker", ttl=5.0)
    return data if isinstance(data, list) else []


# ── Endpoints por símbolo ─────────────────────────────────────────────────

def get_spot_price(symbol: str) -> float:
    """Precio spot actual. TTL 5s."""
    data = _fetch(
        f"{_SPOT_BASE}/api/v3/ticker/price",
        params={"symbol": symbol.upper()},
        ttl=5.0,
    )
    return float(data["price"]) if isinstance(data, dict) and "price" in data else 0.0


def get_open_interest(symbol: str) -> float:
    """Open interest en unidades del activo base. TTL 30s."""
    data = _fetch(
        f"{_FUTURES_BASE}/fapi/v1/openInterest",
        params={"symbol": symbol.upper()},
        ttl=30.0,
    )
    return float(data["openInterest"]) if isinstance(data, dict) and "openInterest" in data else 0.0


def get_funding(symbol: str) -> float:
    """Tasa de funding actual (decimal, ej. 0.0001 = 0.01%). TTL 120s."""
    data = _fetch(
        f"{_FUTURES_BASE}/fapi/v1/premiumIndex",
        params={"symbol": symbol.upper()},
        ttl=120.0,
    )
    return float(data["lastFundingRate"]) if isinstance(data, dict) and "lastFundingRate" in data else 0.0


def get_orderbook_raw(symbol: str, limit: int = 20) -> Dict:
    """Snapshot del order book spot. TTL 5s."""
    data = _fetch(
        f"{_SPOT_BASE}/api/v3/depth",
        params={"symbol": symbol.upper(), "limit": limit},
        ttl=5.0,
    )
    return data if isinstance(data, dict) else {"bids": [], "asks": []}


def get_klines(
    symbol: str,
    interval: str = "1m",
    limit: int = 60,
    start_time_ms: Optional[int] = None,
    end_time_ms: Optional[int] = None,
) -> List:
    """Velas de futuros.

    Si se pasan start_time_ms/end_time_ms, obtiene una ventana historica exacta.
    Eso evita que los outcome trackers pierdan alertas antiguas al consultar solo
    las ultimas velas.
    """
    params: Dict[str, Any] = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": limit,
    }
    if start_time_ms is not None:
        params["startTime"] = int(start_time_ms)
    if end_time_ms is not None:
        params["endTime"] = int(end_time_ms)

    data = _fetch(
        f"{_FUTURES_BASE}/fapi/v1/klines",
        params=params,
        ttl=30.0,
    )
    return data if isinstance(data, list) else []


def get_agg_trades_raw(symbol: str, limit: int = 100) -> List[Dict]:
    """AggTrades crudos del endpoint REST spot (campo 'a' = aggTradeId). TTL 5s."""
    data = _fetch(
        f"{_SPOT_BASE}/api/v3/aggTrades",
        params={"symbol": symbol.upper(), "limit": limit},
        ttl=5.0,
    )
    return data if isinstance(data, list) else []


def get_futures_price(symbol: str) -> float:
    """Precio mark price de futuros. TTL 5s."""
    data = _fetch(
        f"{_FUTURES_BASE}/fapi/v1/ticker/price",
        params={"symbol": symbol.upper()},
        ttl=5.0,
    )
    return float(data["price"]) if isinstance(data, dict) and "price" in data else 0.0


def get_futures_orderbook_raw(symbol: str, limit: int = 20) -> Dict:
    """Snapshot del order book de futuros. TTL 5s."""
    data = _fetch(
        f"{_FUTURES_BASE}/fapi/v1/depth",
        params={"symbol": symbol.upper(), "limit": limit},
        ttl=5.0,
    )
    if isinstance(data, dict) and "bids" in data and "asks" in data:
        return data
    return {"bids": [], "asks": [], "orderbook_available": False}


def get_long_short_ratio(symbol: str) -> Optional[Dict]:
    """Ratio long/short de los top traders (posición). TTL 60s."""
    data = _fetch(
        f"{_FUTURES_BASE}/futures/data/topLongShortPositionRatio",
        params={"symbol": symbol.upper(), "period": "5m", "limit": 1},
        ttl=60.0,
    )
    if isinstance(data, list) and data:
        return data[0]
    return None
