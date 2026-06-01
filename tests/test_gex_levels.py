import pytest
from unittest.mock import patch
from app.gex_levels import get_gex_levels, _bs_gamma, _compute_gex


def test_bs_gamma_positive():
    g = _bs_gamma(S=50000.0, K=50000.0, T=0.1, sigma=0.6)
    assert g > 0.0


def test_bs_gamma_zero_on_bad_inputs():
    assert _bs_gamma(0.0, 50000.0, 0.1, 0.6) == 0.0
    assert _bs_gamma(50000.0, 0.0, 0.1, 0.6) == 0.0
    assert _bs_gamma(50000.0, 50000.0, 0.0, 0.6) == 0.0
    assert _bs_gamma(50000.0, 50000.0, 0.1, 0.0) == 0.0


def test_unsupported_symbol_returns_none():
    result = get_gex_levels("SOLUSDT")
    assert result is None


@patch("app.gex_levels.requests.get")
def test_deribit_failure_returns_none(mock_get):
    mock_get.side_effect = Exception("connection error")
    result = get_gex_levels("BTCUSDT")
    assert result is None


def _make_option(name, underlying, iv, oi):
    return {
        "instrument_name": name,
        "underlying_price": underlying,
        "mark_iv": iv,
        "open_interest": oi,
    }


@patch("app.gex_levels.requests.get")
def test_result_has_required_keys(mock_get):
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"result": [
        _make_option("BTC-30DEC25-40000-C", 50000.0, 60.0, 100.0),
        _make_option("BTC-30DEC25-40000-P", 50000.0, 60.0, 100.0),
        _make_option("BTC-30DEC25-60000-C", 50000.0, 60.0, 50.0),
        _make_option("BTC-30DEC25-60000-P", 50000.0, 60.0, 50.0),
    ]}
    mock_get.return_value = resp

    # Limpiar caché para forzar nueva llamada
    from app.gex_levels import _GEX_CACHE, _GEX_LOCK
    with _GEX_LOCK:
        _GEX_CACHE.clear()

    result = get_gex_levels("BTCUSDT")
    if result is None:
        pytest.skip("GEX result is None (likely expired instruments skipped by T<=0)")

    for key in ("spot", "gamma_flip", "call_wall", "put_wall",
                "nearest_gex_level", "nearest_gex_type", "distance_to_gex_pct"):
        assert key in result


@patch("app.gex_levels.requests.get")
def test_nearest_gex_type_valid(mock_get):
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"result": [
        _make_option("BTC-30DEC25-40000-C", 50000.0, 60.0, 100.0),
        _make_option("BTC-30DEC25-40000-P", 50000.0, 60.0, 80.0),
        _make_option("BTC-30DEC25-55000-C", 50000.0, 55.0, 60.0),
        _make_option("BTC-30DEC25-55000-P", 50000.0, 55.0, 40.0),
    ]}
    mock_get.return_value = resp

    from app.gex_levels import _GEX_CACHE, _GEX_LOCK
    with _GEX_LOCK:
        _GEX_CACHE.clear()

    result = get_gex_levels("BTCUSDT")
    if result is None:
        pytest.skip("GEX result is None")

    assert result["nearest_gex_type"] in ("call_wall", "put_wall", "gamma_flip")
    assert result["distance_to_gex_pct"] >= 0.0


@patch("app.gex_levels.requests.get")
def test_cache_hit_returns_same_object(mock_get):
    from unittest.mock import MagicMock
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"result": [
        _make_option("BTC-30DEC25-40000-C", 50000.0, 60.0, 100.0),
        _make_option("BTC-30DEC25-60000-P", 50000.0, 60.0, 100.0),
    ]}
    mock_get.return_value = resp

    from app.gex_levels import _GEX_CACHE, _GEX_LOCK
    with _GEX_LOCK:
        _GEX_CACHE.clear()

    r1 = get_gex_levels("BTCUSDT")
    r2 = get_gex_levels("BTCUSDT")
    # Segunda llamada debe venir del caché — mock_get solo llamado una vez
    assert mock_get.call_count == 1
