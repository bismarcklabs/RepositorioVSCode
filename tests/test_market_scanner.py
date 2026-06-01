import pytest
from unittest.mock import patch
from app.market_scanner import get_candidate_symbols, STABLECOIN_BLACKLIST
from app.config import MIN_QUOTE_VOLUME_USDT, MAX_SPREAD_PCT


_TICKERS = [
    {"symbol": "BTCUSDT",  "quoteVolume": "5000000000", "priceChangePercent": "2.5"},
    {"symbol": "ETHUSDT",  "quoteVolume": "2000000000", "priceChangePercent": "-1.2"},
    {"symbol": "XRPUSDT",  "quoteVolume": "200000000",  "priceChangePercent": "0.5"},
    {"symbol": "USDCUSDT", "quoteVolume": "3000000000", "priceChangePercent": "0.0"},  # stablecoin
    {"symbol": "LOWVOL",   "quoteVolume": "1000",        "priceChangePercent": "5.0"},  # too low vol
]

_PREMIUM = [
    {"symbol": "BTCUSDT",  "lastFundingRate": "0.0003"},
    {"symbol": "ETHUSDT",  "lastFundingRate": "-0.0002"},
    {"symbol": "XRPUSDT",  "lastFundingRate": "0.0001"},
    {"symbol": "USDCUSDT", "lastFundingRate": "0.0"},
    {"symbol": "LOWVOL",   "lastFundingRate": "0.0"},
]

_BOOKS = [
    {"symbol": "BTCUSDT",  "bidPrice": "50000.0", "askPrice": "50001.0"},  # spread ~0.002%
    {"symbol": "ETHUSDT",  "bidPrice": "3000.0",  "askPrice": "3000.3"},   # spread ~0.01%
    {"symbol": "XRPUSDT",  "bidPrice": "0.5",     "askPrice": "0.5001"},   # spread ~0.02%
    {"symbol": "USDCUSDT", "bidPrice": "1.0",     "askPrice": "1.0001"},
    {"symbol": "LOWVOL",   "bidPrice": "0.001",   "askPrice": "0.002"},    # spread 100% — filtered
]


@patch("app.market_scanner.get_futures_ticker_all", return_value=_TICKERS)
@patch("app.market_scanner.get_premium_index_all", return_value=_PREMIUM)
@patch("app.market_scanner.get_book_ticker_all", return_value=_BOOKS)
def test_stablecoins_excluded(mock_books, mock_prem, mock_tick):
    results = get_candidate_symbols(limit=10)
    symbols = [r["symbol"] for r in results]
    for stable in STABLECOIN_BLACKLIST:
        assert stable not in symbols


@patch("app.market_scanner.get_futures_ticker_all", return_value=_TICKERS)
@patch("app.market_scanner.get_premium_index_all", return_value=_PREMIUM)
@patch("app.market_scanner.get_book_ticker_all", return_value=_BOOKS)
def test_low_volume_excluded(mock_books, mock_prem, mock_tick):
    results = get_candidate_symbols(limit=10)
    for r in results:
        assert r["quote_volume"] >= MIN_QUOTE_VOLUME_USDT


@patch("app.market_scanner.get_futures_ticker_all", return_value=_TICKERS)
@patch("app.market_scanner.get_premium_index_all", return_value=_PREMIUM)
@patch("app.market_scanner.get_book_ticker_all", return_value=_BOOKS)
def test_wide_spread_excluded(mock_books, mock_prem, mock_tick):
    results = get_candidate_symbols(limit=10)
    for r in results:
        assert r["spread_pct"] <= MAX_SPREAD_PCT


@patch("app.market_scanner.get_futures_ticker_all", return_value=_TICKERS)
@patch("app.market_scanner.get_premium_index_all", return_value=_PREMIUM)
@patch("app.market_scanner.get_book_ticker_all", return_value=_BOOKS)
def test_sorted_by_preliminary_score_descending(mock_books, mock_prem, mock_tick):
    results = get_candidate_symbols(limit=10)
    scores = [r["preliminary_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


@patch("app.market_scanner.get_futures_ticker_all", return_value=_TICKERS)
@patch("app.market_scanner.get_premium_index_all", return_value=_PREMIUM)
@patch("app.market_scanner.get_book_ticker_all", return_value=_BOOKS)
def test_limit_respected(mock_books, mock_prem, mock_tick):
    results = get_candidate_symbols(limit=2)
    assert len(results) <= 2


@patch("app.market_scanner.get_futures_ticker_all", return_value=_TICKERS)
@patch("app.market_scanner.get_premium_index_all", return_value=_PREMIUM)
@patch("app.market_scanner.get_book_ticker_all", return_value=_BOOKS)
def test_result_has_required_keys(mock_books, mock_prem, mock_tick):
    results = get_candidate_symbols(limit=5)
    for r in results:
        for key in ("symbol", "quote_volume", "price_change_pct", "funding_rate", "spread_pct", "preliminary_score"):
            assert key in r
