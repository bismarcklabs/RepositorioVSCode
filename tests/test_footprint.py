import pytest
from unittest.mock import patch
from app.footprint import get_footprint


def _make_trades(count=50, buy_ratio=0.5, price_range=(99.0, 101.0), ascending=True):
    """Genera trades sintéticos para tests.

    buy_ratio: fracción de trades compradores (maker=False).
    ascending: si True el precio sube de price_range[0] a price_range[1].
    """
    lo, hi = price_range
    trades = []
    for i in range(count):
        frac = i / max(count - 1, 1)
        price = lo + (hi - lo) * frac if ascending else hi - (hi - lo) * frac
        maker = (i / count) >= buy_ratio    # True = sell aggressor
        trades.append({
            "trade_id": i + 1,
            "price": price,
            "qty": 1.0,
            "maker": maker,
            "timestamp": 1000 + i,
        })
    return trades


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_result_has_required_keys(mock_rest, mock_ws):
    mock_ws.return_value = _make_trades(50)
    result = get_footprint("BTCUSDT")
    for key in ("bid_volume", "ask_volume", "footprint_delta", "delta_by_price",
                "stacked_buy_imbalance", "stacked_sell_imbalance",
                "absorption_buy", "absorption_sell"):
        assert key in result


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_buy_heavy_positive_delta(mock_rest, mock_ws):
    # buy_ratio=0.8 → 80% buy aggressors (maker=False) → ask_vol >> bid_vol → positive delta
    mock_ws.return_value = _make_trades(100, buy_ratio=0.8)
    result = get_footprint("BTCUSDT")
    assert result["ask_volume"] > result["bid_volume"]
    assert result["footprint_delta"] > 0.0


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_sell_heavy_negative_delta(mock_rest, mock_ws):
    # buy_ratio=0.2 → 20% buy aggressors → bid_vol >> ask_vol → negative delta
    mock_ws.return_value = _make_trades(100, buy_ratio=0.2)
    result = get_footprint("BTCUSDT")
    assert result["bid_volume"] > result["ask_volume"]
    assert result["footprint_delta"] < 0.0


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_absorption_buy_detected(mock_rest, mock_ws):
    # buy_ratio=0.1 → 10% buy aggressors → bid_vol high (many sell aggressors)
    # but price RISES → buyers absorbed the selling pressure
    mock_ws.return_value = _make_trades(100, buy_ratio=0.1, ascending=True)
    result = get_footprint("BTCUSDT")
    assert result["absorption_buy"] is True


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_absorption_sell_detected(mock_rest, mock_ws):
    # buy_ratio=0.9 → 90% buy aggressors → ask_vol high (many buy aggressors)
    # but price FALLS → sellers absorbed the buying pressure
    mock_ws.return_value = _make_trades(100, buy_ratio=0.9, ascending=False)
    result = get_footprint("BTCUSDT")
    assert result["absorption_sell"] is True


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_default_returned_on_too_few_trades(mock_rest, mock_ws):
    mock_ws.return_value = _make_trades(3)
    result = get_footprint("BTCUSDT")
    assert result["footprint_delta"] == 0.0
    assert result["stacked_buy_imbalance"] is False


@patch("app.footprint.get_trades_snapshot", return_value=[])
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_fallback_rest_no_data_returns_default(mock_rest, mock_ws):
    result = get_footprint("BTCUSDT")
    assert result["bid_volume"] == 0.0
    assert result["ask_volume"] == 0.0
    assert result["absorption_buy"] is False


@patch("app.footprint.get_trades_snapshot")
@patch("app.footprint.get_agg_trades_raw", return_value=[])
def test_delta_by_price_populated(mock_rest, mock_ws):
    mock_ws.return_value = _make_trades(50)
    result = get_footprint("BTCUSDT")
    assert isinstance(result["delta_by_price"], dict)
    assert len(result["delta_by_price"]) > 0
