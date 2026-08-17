from typing import Any, Dict, List, Optional

from app.market_data import get_agg_trades_raw
from app.websocket_client import get_trades_snapshot

_PRICE_BUCKETS = 20
_IMBALANCE_RATIO = 2.0   # ask_vol / bid_vol > 2× para considerar un bucket comprador
_CONSECUTIVE_MIN = 3     # mínimo de buckets consecutivos para stacked imbalance
_ABSORPTION_THRESHOLD = 0.3  # el lado dominante supera en un 30% al otro


def _normalize_rest_trades(raw: List[Dict]) -> List[Dict[str, Any]]:
    """Convierte aggTrades del endpoint REST al formato interno."""
    return [
        {
            "trade_id": int(t.get("a", 0)),
            "price": float(t.get("p", 0.0)),
            "qty": float(t.get("q", 0.0)),
            "maker": bool(t.get("m", False)),
            "timestamp": int(t.get("T", 0)),
        }
        for t in raw
        if isinstance(t, dict)
    ]


def _default_footprint() -> Dict[str, Any]:
    return {
        "bid_volume": 0.0,
        "ask_volume": 0.0,
        "footprint_delta": 0.0,
        "delta_by_price": {},
        "stacked_buy_imbalance": False,
        "stacked_sell_imbalance": False,
        "absorption_buy": False,
        "absorption_sell": False,
    }


def _has_consecutive(bucket_indices: List[int], min_count: int) -> bool:
    if len(bucket_indices) < min_count:
        return False
    idx_set = set(bucket_indices)
    for b in bucket_indices:
        if all(b + i in idx_set for i in range(min_count)):
            return True
    return False


def get_footprint(symbol: str, trades: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Calcula footprint básico a partir de aggTrades del WebSocket (o REST fallback).

    Terminología Binance aggTrade:
    - maker=True  → el comprador fue el maker (limit buy en libro) → el vendedor fue
                    el agresor → presión vendedora (bid_volume).
    - maker=False → el vendedor fue el maker → el comprador fue el agresor
                    → presión compradora (ask_volume).

    Absorción:
    - absorption_buy: presión vendedora dominante pero el precio no bajó
                      (compradores absorbieron a los vendedores).
    - absorption_sell: presión compradora dominante pero el precio no subió
                       (vendedores absorbieron a los compradores).

    Si el llamador ya resolvió los trades del ciclo (ws + fallback REST, ej.
    _scan_symbol), pasarlos en `trades` evita repetir esa misma resolución aquí.
    """
    if trades is None:
        trades = get_trades_snapshot(symbol)
        if not trades:
            raw = get_agg_trades_raw(symbol, limit=100)
            trades = _normalize_rest_trades(raw)

    if len(trades) < 10:
        return _default_footprint()

    prices = [t["price"] for t in trades]
    price_min = min(prices)
    price_max = max(prices)

    if price_max <= price_min:
        return _default_footprint()

    bucket_size = (price_max - price_min) / _PRICE_BUCKETS

    # bucket arrays: [bid_vol, ask_vol] per level
    bid_at: Dict[int, float] = {}
    ask_at: Dict[int, float] = {}
    total_bid = 0.0
    total_ask = 0.0

    for t in trades:
        b = min(_PRICE_BUCKETS - 1, int((t["price"] - price_min) / bucket_size))
        qty = t["qty"]
        if t["maker"]:           # aggressive seller
            bid_at[b] = bid_at.get(b, 0.0) + qty
            total_bid += qty
        else:                    # aggressive buyer
            ask_at[b] = ask_at.get(b, 0.0) + qty
            total_ask += qty

    footprint_delta = total_ask - total_bid

    # delta_by_price: keyed by representative price level
    delta_by_price: Dict[float, float] = {}
    all_buckets = set(bid_at) | set(ask_at)
    for b in all_buckets:
        level_price = round(price_min + (b + 0.5) * bucket_size, 6)
        delta_by_price[level_price] = round(ask_at.get(b, 0.0) - bid_at.get(b, 0.0), 4)

    # Stacked imbalance: 3+ consecutive buckets strongly one-sided
    buy_buckets = [
        b for b in all_buckets
        if ask_at.get(b, 0.0) > bid_at.get(b, 0.0) * _IMBALANCE_RATIO
    ]
    sell_buckets = [
        b for b in all_buckets
        if bid_at.get(b, 0.0) > ask_at.get(b, 0.0) * _IMBALANCE_RATIO
    ]

    stacked_buy = _has_consecutive(sorted(buy_buckets), _CONSECUTIVE_MIN)
    stacked_sell = _has_consecutive(sorted(sell_buckets), _CONSECUTIVE_MIN)

    # Absorption: one side dominates volumetrically but price moved opposite
    price_start = trades[0]["price"]
    price_end = trades[-1]["price"]
    price_moved_up = price_end > price_start * 1.0001
    price_moved_down = price_end < price_start * 0.9999

    # Dominant sell pressure (bid_vol >> ask_vol) but price didn't fall
    net_sell_pressure = total_bid > total_ask * (1.0 + _ABSORPTION_THRESHOLD)
    # Dominant buy pressure (ask_vol >> bid_vol) but price didn't rise
    net_buy_pressure = total_ask > total_bid * (1.0 + _ABSORPTION_THRESHOLD)

    absorption_buy = net_sell_pressure and not price_moved_down
    absorption_sell = net_buy_pressure and not price_moved_up

    return {
        "bid_volume": round(total_bid, 8),
        "ask_volume": round(total_ask, 8),
        "footprint_delta": round(footprint_delta, 8),
        "delta_by_price": delta_by_price,
        "stacked_buy_imbalance": stacked_buy,
        "stacked_sell_imbalance": stacked_sell,
        "absorption_buy": absorption_buy,
        "absorption_sell": absorption_sell,
    }
