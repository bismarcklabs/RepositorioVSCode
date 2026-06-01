import pytest
from unittest.mock import patch
from app.technical_context import get_technical_context


def _kline(open_t, o, h, l, c, bvol, close_t, qvol):
    return [open_t, str(o), str(h), str(l), str(c), str(bvol), close_t, str(qvol), 0, 0, 0, 0]


def _flat_klines(price: float = 100.0, count: int = 60) -> list:
    return [_kline(i * 60000, price, price, price, price, 10.0, (i + 1) * 60000, 1000.0) for i in range(count)]


def _trending_klines(start: float = 100.0, step: float = 0.1, count: int = 60) -> list:
    klines = []
    for i in range(count):
        p = start + i * step
        klines.append(_kline(i * 60000, p, p * 1.001, p * 0.999, p, 10.0, (i + 1) * 60000, 1000.0))
    return klines


@patch("app.technical_context.get_klines")
def test_flat_market_neutral_trend(mock_klines):
    mock_klines.return_value = _flat_klines(100.0)
    ctx = get_technical_context("BTCUSDT")
    assert ctx["trend_bias"] == "neutral"
    assert ctx["return_1h"] == pytest.approx(0.0, abs=1e-3)
    assert ctx["return_15m"] == pytest.approx(0.0, abs=1e-3)
    assert ctx["relative_volume"] == pytest.approx(1.0, abs=0.01)


@patch("app.technical_context.get_klines")
def test_uptrend_detected(mock_klines):
    mock_klines.return_value = _trending_klines(100.0, step=0.2, count=60)
    ctx = get_technical_context("BTCUSDT")
    assert ctx["return_1h"] > 0.3
    assert ctx["trend_bias"] == "bullish"
    assert ctx["ema_20"] > ctx["ema_50"]


@patch("app.technical_context.get_klines")
def test_downtrend_detected(mock_klines):
    mock_klines.return_value = _trending_klines(100.0, step=-0.1, count=60)
    ctx = get_technical_context("BTCUSDT")
    assert ctx["return_1h"] < -0.3
    assert ctx["trend_bias"] == "bearish"
    assert ctx["ema_20"] < ctx["ema_50"]


@patch("app.technical_context.get_klines")
def test_returns_default_on_insufficient_data(mock_klines):
    mock_klines.return_value = _flat_klines(100.0, count=5)
    ctx = get_technical_context("BTCUSDT")
    assert ctx["trend_bias"] == "neutral"
    assert ctx["return_1h"] == 0.0


@patch("app.technical_context.get_klines")
def test_result_has_required_keys(mock_klines):
    mock_klines.return_value = _flat_klines()
    ctx = get_technical_context("BTCUSDT")
    for key in ("return_15m", "return_1h", "ema_20", "ema_50", "vwap", "vwap_distance_pct", "relative_volume", "trend_bias"):
        assert key in ctx


@patch("app.technical_context.get_klines")
def test_vwap_close_to_price_in_flat_market(mock_klines):
    mock_klines.return_value = _flat_klines(200.0)
    ctx = get_technical_context("BTCUSDT")
    assert abs(ctx["vwap_distance_pct"]) < 0.1
