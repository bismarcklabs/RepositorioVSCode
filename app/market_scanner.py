import requests
from typing import Any, Dict, List

from app.config import (
    MAX_SPREAD_PCT,
    MIN_QUOTE_VOLUME_USDT,
    SCANNER_CANDIDATE_LIMIT,
)
from app.market_data import (
    get_book_ticker_all,
    get_futures_ticker_all,
    get_premium_index_all,
)

STABLECOIN_BLACKLIST = frozenset({
    "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "BUSDUSDT",
    "DAIUSDT", "USDPUSDT", "EURUSDT", "PAXGUSDT", "USTCUSDT",
})


def get_candidate_symbols(limit: int = SCANNER_CANDIDATE_LIMIT) -> List[Dict[str, Any]]:
    """Two-pass scanner: 3 batch calls → preliminary score → top N candidates.

    Returns list of dicts: symbol, quote_volume, price_change_pct,
    funding_rate, spread_pct, preliminary_score.
    """
    tickers = {
        t["symbol"]: t
        for t in get_futures_ticker_all()
        if isinstance(t, dict) and "symbol" in t
    }
    funding_map = {
        f["symbol"]: float(f.get("lastFundingRate", 0.0))
        for f in get_premium_index_all()
        if isinstance(f, dict) and "symbol" in f
    }
    books = {
        b["symbol"]: b
        for b in get_book_ticker_all()
        if isinstance(b, dict) and "symbol" in b
    }

    candidates: List[Dict[str, Any]] = []
    for symbol, ticker in tickers.items():
        if not symbol.endswith("USDT"):
            continue
        if symbol in STABLECOIN_BLACKLIST:
            continue

        quote_vol = float(ticker.get("quoteVolume", 0.0))
        if quote_vol < MIN_QUOTE_VOLUME_USDT:
            continue

        book = books.get(symbol, {})
        bid = float(book.get("bidPrice", 0.0))
        ask = float(book.get("askPrice", 0.0))
        spread_pct = (ask - bid) / bid * 100.0 if bid > 0.0 else 999.0
        if spread_pct > MAX_SPREAD_PCT:
            continue

        price_chg_pct = float(ticker.get("priceChangePercent", 0.0))
        fund_rate = funding_map.get(symbol, 0.0)

        # Desviación del precio actual vs VWAP de 24h: detecta breakouts en curso.
        # Un símbolo que acaba de dispararse (último 5-15 min) tendrá lastPrice >> weightedAvgPrice
        # aunque su priceChangePercent de 24h sea bajo. Esto lo promueve antes en el ranking.
        last_price = float(ticker.get("lastPrice", 0.0))
        weighted_avg = float(ticker.get("weightedAvgPrice", 0.0)) or last_price
        vwap_dev = abs((last_price - weighted_avg) / weighted_avg * 100.0) if weighted_avg > 0 else 0.0

        preliminary_score = (
            abs(price_chg_pct) * 3.0           # 24h momentum — reducido (premia historial)
            + abs(fund_rate) * 30_000.0         # presión de funding
            + min(10.0, quote_vol / 2e8)        # base de liquidez
            + min(25.0, vwap_dev * 6.0)         # breakout actual: precio > VWAP 24h
        )

        candidates.append({
            "symbol": symbol,
            "quote_volume": quote_vol,
            "price_change_pct": price_chg_pct,
            "funding_rate": fund_rate,
            "spread_pct": round(spread_pct, 6),
            "preliminary_score": round(preliminary_score, 4),
        })

    candidates.sort(key=lambda x: x["preliminary_score"], reverse=True)
    return candidates[:limit]


def get_top_symbols(limit: int = 20) -> List[str]:
    """Return the top USDT symbols by 24h quote volume from Binance spot.

    Used as the symbol list for WebSocket aggTrade subscriptions.
    Symbols are returned in UPPERCASE (e.g. 'BTCUSDT') to match WebSocket
    message field 's', which Binance always sends in uppercase.
    """
    url = "https://api.binance.com/api/v3/ticker/24hr"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Error al consultar Binance ticker: {exc}") from exc

    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected response format from Binance API")

    usdt_pairs: List[Dict[str, Any]] = [
        item for item in data
        if isinstance(item, dict) and item.get("symbol", "").endswith("USDT")
    ]

    sorted_pairs = sorted(
        usdt_pairs,
        key=lambda item: float(item.get("quoteVolume", 0.0)),
        reverse=True,
    )

    return [item["symbol"].upper() for item in sorted_pairs[:limit]]
