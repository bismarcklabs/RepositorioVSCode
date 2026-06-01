import pytest
from unittest.mock import patch
from app.volume_profile import get_volume_profile


def _kline(i, lo, hi, close, qvol=1000.0):
    o = (lo + hi) / 2
    return [i * 60000, str(o), str(hi), str(lo), str(close), "10", (i + 1) * 60000, str(qvol), 0, 0, 0, 0]


def _flat_klines(price=100.0, count=60):
    return [_kline(i, price * 0.999, price * 1.001, price) for i in range(count)]


def _range_klines(lo_price=95.0, hi_price=105.0, count=60):
    """Klines alternando entre extremos para crear volumen distribuido."""
    klines = []
    for i in range(count):
        mid = (lo_price + hi_price) / 2
        klines.append(_kline(i, lo_price, hi_price, mid))
    return klines


@patch("app.volume_profile.get_klines")
def test_poc_exists(mock_klines):
    mock_klines.return_value = _flat_klines(100.0)
    result = get_volume_profile("BTCUSDT")
    assert result["poc"] > 0.0


@patch("app.volume_profile.get_klines")
def test_poc_near_price_in_flat_market(mock_klines):
    mock_klines.return_value = _flat_klines(100.0)
    result = get_volume_profile("BTCUSDT")
    assert abs(result["poc"] - 100.0) < 1.0


@patch("app.volume_profile.get_klines")
def test_nearest_level_type_is_poc_or_hvn_or_lvn(mock_klines):
    mock_klines.return_value = _range_klines(95.0, 105.0)
    result = get_volume_profile("BTCUSDT")
    assert result["nearest_level_type"] in ("POC", "HVN", "LVN", "NONE")


@patch("app.volume_profile.get_klines")
def test_result_has_required_keys(mock_klines):
    mock_klines.return_value = _flat_klines()
    result = get_volume_profile("BTCUSDT")
    for key in ("poc", "hvn_levels", "lvn_levels", "nearest_level",
                "nearest_level_type", "distance_to_level_pct"):
        assert key in result


@patch("app.volume_profile.get_klines")
def test_returns_default_on_insufficient_data(mock_klines):
    mock_klines.return_value = _flat_klines(count=5)
    result = get_volume_profile("BTCUSDT")
    assert result["hvn_levels"] == []
    assert result["lvn_levels"] == []


@patch("app.volume_profile.get_klines")
def test_distance_is_non_negative(mock_klines):
    mock_klines.return_value = _flat_klines(100.0)
    result = get_volume_profile("BTCUSDT")
    assert result["distance_to_level_pct"] >= 0.0


@patch("app.volume_profile.get_klines")
def test_hvn_levels_non_empty_with_varied_volume(mock_klines):
    # 10 klines clustered near price 100 with very high volume (HVN zone)
    # + 50 klines spread across wide range with tiny volume
    klines = []
    for i in range(10):
        klines.append(_kline(i, 99.8, 100.2, 100.0, qvol=50_000.0))
    for i in range(50):
        price = 80.0 + i * 0.5   # spread from 80 to 104.5
        klines.append(_kline(i + 10, price - 0.1, price + 0.1, price, qvol=10.0))
    mock_klines.return_value = klines
    result = get_volume_profile("BTCUSDT")
    assert len(result["hvn_levels"]) >= 1


@patch("app.volume_profile.get_klines")
def test_empty_klines_returns_default(mock_klines):
    mock_klines.return_value = []
    result = get_volume_profile("BTCUSDT")
    assert result["nearest_level_type"] == "NONE"
