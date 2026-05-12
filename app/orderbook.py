import requests
from typing import Any, Dict, List, Tuple


def get_orderbook(symbol: str, limit: int = 20) -> Dict[str, Any]:
    """Fetch the Binance order book depth for a symbol."""
    url = "https://api.binance.com/api/v3/depth"
    try:
        response = requests.get(
            url,
            params={"symbol": symbol.upper(), "limit": limit},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return {"bids": [], "asks": []}


def parse_orderbook_levels(levels: List[List[str]]) -> List[Tuple[float, float]]:
    """Convert order book levels from strings to numeric price and quantity tuples."""
    return [(float(price), float(qty)) for price, qty in levels]


def calculate_book_volume(levels: List[List[str]]) -> float:
    """Calculate total volume from a list of order book levels."""
    return sum(float(level[1]) for level in levels if len(level) >= 2)


def get_orderbook_imbalance(symbol: str, limit: int = 20) -> Dict[str, Any]:
    """Get order book bids/asks and calculate imbalance metric."""
    orderbook = get_orderbook(symbol, limit=limit)

    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])

    bid_volume = calculate_book_volume(bids)
    ask_volume = calculate_book_volume(asks)

    imbalance = 0.0
    if bid_volume + ask_volume != 0:
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

    return {
        "symbol": symbol.upper(),
        "bids": bids,
        "asks": asks,
        "bid_volume": round(bid_volume, 8),
        "ask_volume": round(ask_volume, 8),
        "imbalance": round(imbalance, 8),
    }
