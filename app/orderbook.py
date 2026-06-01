from typing import Any, Dict, List, Literal

from app import market_data

_MarketType = Literal["spot", "futures"]


def _book_volume(levels: List[List[str]]) -> float:
    return sum(float(level[1]) for level in levels if len(level) >= 2)


def get_orderbook_imbalance(
    symbol: str,
    limit: int = 20,
    market: _MarketType = "spot",
) -> Dict[str, Any]:
    """Calcula imbalance y spread del order book.

    market="futures" usa el endpoint /fapi/v1/depth (más relevante para
    acciones LONG_FUTURES / SHORT_FUTURES).
    market="spot" usa /api/v3/depth (default, retrocompatible).
    """
    if market == "futures":
        ob = market_data.get_futures_orderbook_raw(symbol, limit)
    else:
        ob = market_data.get_orderbook_raw(symbol, limit)

    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids and not asks:
        return {
            "symbol": symbol.upper(),
            "bids": [],
            "asks": [],
            "bid_volume": 0.0,
            "ask_volume": 0.0,
            "imbalance": 0.0,
            "spread_pct": 999.0,
            "orderbook_available": False,
        }

    bid_vol = _book_volume(bids)
    ask_vol = _book_volume(asks)

    imbalance = (
        (bid_vol - ask_vol) / (bid_vol + ask_vol) if bid_vol + ask_vol > 0 else 0.0
    )

    best_bid = float(bids[0][0]) if bids else 0.0
    best_ask = float(asks[0][0]) if asks else 0.0
    spread_pct = (best_ask - best_bid) / best_bid * 100.0 if best_bid > 0.0 else 999.0

    return {
        "symbol": symbol.upper(),
        "bids": bids,
        "asks": asks,
        "bid_volume": round(bid_vol, 8),
        "ask_volume": round(ask_vol, 8),
        "imbalance": round(imbalance, 8),
        "spread_pct": round(spread_pct, 6),
        "orderbook_available": True,
    }
