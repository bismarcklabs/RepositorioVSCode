import requests
from typing import Any, Dict, List


def get_top_symbols(limit: int = 20) -> List[str]:
    """Return the top USDT symbols by 24h quote volume from Binance.

    This function connects to Binance public REST API, fetches the 24hr ticker
    data, filters only USDT pairs, sorts the remaining pairs by quoteVolume in
    descending order and returns the top symbols.
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected response format from Binance API")

    usdt_pairs: List[Dict[str, Any]] = [
        item for item in data
        if (
            isinstance(item, dict)
            and item.get("symbol", "").endswith("USDT")
        )
    ]

    sorted_pairs = sorted(
        usdt_pairs,
        key=lambda item: float(item.get("quoteVolume", 0.0)),
        reverse=True,
    )

    return [
        item["symbol"].lower()
        for item in sorted_pairs[:limit]
    ]
