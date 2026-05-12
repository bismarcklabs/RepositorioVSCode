import requests
from typing import Any


def _safe_request(url: str, params: dict) -> Any:
    response = requests.get(url, params=params, timeout=10)
    try:
        response.raise_for_status()
    except requests.HTTPError:
        return None
    except requests.RequestException:
        return None

    return response.json()


def get_open_interest(symbol: str) -> float:
    """Return the open interest for a Binance Futures symbol, or 0 if unavailable."""
    url = "https://fapi.binance.com/fapi/v1/openInterest"
    data = _safe_request(url, {"symbol": symbol.upper()})
    if not isinstance(data, dict):
        return 0.0
    return float(data.get("openInterest", 0.0))


def get_funding_rate(symbol: str) -> float:
    """Return the latest funding rate for a Binance Futures symbol, or 0 if unavailable."""
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    data = _safe_request(url, {"symbol": symbol.upper(), "limit": 1})
    if isinstance(data, list) and data:
        latest = data[0]
    elif isinstance(data, dict):
        latest = data
    else:
        return 0.0

    return float(latest.get("fundingRate", 0.0))


def get_funding(symbol: str) -> float:
    """Return the latest funding rate for a Binance Futures symbol using premiumIndex, or 0 if unavailable."""
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    data = _safe_request(url, {"symbol": symbol.upper()})
    if not isinstance(data, dict):
        return 0.0
    return float(data.get("lastFundingRate", 0.0))
