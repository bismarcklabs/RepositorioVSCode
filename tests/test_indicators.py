import pytest
from app.indicators import calculate_metrics, symbol_metrics


def _make_trades(start_id: int, count: int, buy: bool = True, qty: float = 1.0):
    return [
        {"trade_id": start_id + i, "qty": qty, "maker": not buy, "price": 100.0, "timestamp": 1000 + i}
        for i in range(count)
    ]


def setup_function():
    symbol_metrics.clear()


def test_buy_trades_positive_delta():
    trades = _make_trades(1, 5, buy=True, qty=2.0)
    result = calculate_metrics("BTCUSDT", trades)
    assert result["buy_volume"] == pytest.approx(10.0)
    assert result["sell_volume"] == pytest.approx(0.0)
    assert result["delta"] == pytest.approx(10.0)
    assert result["cvd"] == pytest.approx(10.0)


def test_sell_trades_negative_delta():
    trades = _make_trades(1, 3, buy=False, qty=5.0)
    result = calculate_metrics("ETHUSDT", trades)
    assert result["sell_volume"] == pytest.approx(15.0)
    assert result["delta"] == pytest.approx(-15.0)
    assert result["cvd"] == pytest.approx(-15.0)


def test_deduplication_by_trade_id():
    trades = _make_trades(10, 4, buy=True, qty=1.0)
    calculate_metrics("SOLUSDT", trades)
    # Same trades again — must not be counted twice
    result2 = calculate_metrics("SOLUSDT", trades)
    assert result2["delta"] == pytest.approx(0.0)
    assert result2["cvd"] == pytest.approx(4.0)


def test_new_trades_after_old_batch():
    first_batch = _make_trades(1, 3, buy=True, qty=1.0)
    calculate_metrics("BNBUSDT", first_batch)
    second_batch = _make_trades(4, 2, buy=False, qty=1.0)
    result = calculate_metrics("BNBUSDT", second_batch)
    assert result["delta"] == pytest.approx(-2.0)
    assert result["cvd"] == pytest.approx(1.0)  # 3 buys - 2 sells


def test_mixed_direction():
    trades = [
        {"trade_id": 1, "qty": 3.0, "maker": False, "price": 100.0, "timestamp": 1},  # buy
        {"trade_id": 2, "qty": 1.0, "maker": True,  "price": 100.0, "timestamp": 2},  # sell
    ]
    result = calculate_metrics("ADAUSDT", trades)
    assert result["buy_volume"] == pytest.approx(3.0)
    assert result["sell_volume"] == pytest.approx(1.0)
    assert result["delta"] == pytest.approx(2.0)


def test_empty_trades_returns_zero():
    result = calculate_metrics("DOTUSDT", [])
    assert result["delta"] == 0.0
    assert result["cvd"] == 0.0
