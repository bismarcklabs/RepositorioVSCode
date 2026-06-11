from app.micro_scalper import detect_micro_scalp


def _base_inputs():
    technical = {
        "return_3m": 0.18,
        "return_5m": 0.35,
        "relative_volume": 3.2,
        "above_vwap": True,
        "vwap_distance_pct": 0.4,
        "atr": 0.2,
    }
    metrics = {"delta": 1200, "cvd_15m": 3500}
    footprint = {"footprint_delta": 900}
    orderbook = {"imbalance": 0.22, "spread_pct": 0.02}
    return technical, metrics, footprint, orderbook


def test_detects_micro_long_scalp_when_fast_flow_aligns():
    technical, metrics, footprint, orderbook = _base_inputs()
    result = detect_micro_scalp(
        symbol="BTCUSDT",
        price=100.0,
        technical=technical,
        metrics=metrics,
        footprint=footprint,
        orderbook=orderbook,
        funding=0.0002,
        open_interest=1000,
        oi_change_pct=2.5,
    )
    assert result["action"] == "MICRO_LONG_SCALP"
    assert result["score"] >= 75
    assert result["setup"]["take_profit_1"] > result["setup"]["entry"]
    assert result["setup"]["stop_loss"] < result["setup"]["entry"]


def test_waits_when_score_is_too_low():
    technical, metrics, footprint, orderbook = _base_inputs()
    technical = {**technical, "return_3m": -0.1, "return_5m": 0.05, "relative_volume": 1.0}
    metrics = {"delta": 0, "cvd_15m": 0}
    footprint = {"footprint_delta": 0}
    orderbook = {"imbalance": 0.0, "spread_pct": 0.02}
    result = detect_micro_scalp(
        symbol="BTCUSDT",
        price=100.0,
        technical=technical,
        metrics=metrics,
        footprint=footprint,
        orderbook=orderbook,
        funding=0.0002,
        open_interest=1000,
        oi_change_pct=0.0,
    )
    assert result["action"] == "WAIT"
