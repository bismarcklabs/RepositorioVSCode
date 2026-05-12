from typing import Any, Dict, List, Sequence

symbol_metrics: Dict[str, Dict[str, float]] = {}


def calculate_delta(symbol: str, trades: List[Dict[str, Any]]) -> float:
    """Calculate the delta for a symbol based on aggressive buy/sell volume."""
    buy_volume = 0.0
    sell_volume = 0.0

    for trade in trades:
        qty = float(trade.get("qty", 0.0))
        maker = bool(trade.get("maker", False))

        # maker=True means seller aggressive, maker=False means buyer aggressive
        if maker:
            sell_volume += qty
        else:
            buy_volume += qty

    delta = buy_volume - sell_volume
    return round(delta, 8)


def calculate_cvd(symbol: str, trades: List[Dict[str, Any]]) -> float:
    """Calculate the cumulative volume delta (CVD) for a symbol."""
    delta = calculate_delta(symbol, trades)
    previous_cvd = symbol_metrics.get(symbol, {}).get("cvd", 0.0)
    cvd = previous_cvd + delta
    symbol_metrics.setdefault(symbol, {})["cvd"] = cvd
    return round(cvd, 8)


def calculate_orderbook_imbalance(
    symbol: str,
    bids: Sequence[Sequence[float]],
    asks: Sequence[Sequence[float]],
) -> float:
    """Calculate order book imbalance (OBI) from bids and asks snapshots."""
    bid_volume = sum(float(level[1]) for level in bids if len(level) >= 2)
    ask_volume = sum(float(level[1]) for level in asks if len(level) >= 2)

    if bid_volume + ask_volume == 0:
        imbalance = 0.0
    else:
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)

    symbol_metrics.setdefault(symbol, {})["obi"] = imbalance
    return round(imbalance, 8)


def calculate_metrics(symbol: str, trades: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate and return institutional metrics for a single symbol."""
    buy_volume = 0.0
    sell_volume = 0.0

    for trade in trades:
        qty = float(trade.get("qty", 0.0))
        maker = bool(trade.get("maker", False))

        if maker:
            sell_volume += qty
        else:
            buy_volume += qty

    delta = buy_volume - sell_volume
    previous_cvd = symbol_metrics.get(symbol, {}).get("cvd", 0.0)
    cvd = previous_cvd + delta

    symbol_metrics.setdefault(symbol, {})["cvd"] = cvd
    symbol_metrics[symbol].update(
        {
            "buy_volume": round(buy_volume, 8),
            "sell_volume": round(sell_volume, 8),
            "delta": round(delta, 8),
            "cvd": round(cvd, 8),
        }
    )

    return symbol_metrics[symbol]
