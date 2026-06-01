import pytest
from app.scoring import calculate_opportunity_score


_BASE_METRICS = {
    "cvd": 500_000.0, "delta": 200_000.0,
    "buy_volume": 300_000.0, "sell_volume": 100_000.0,
}
_BASE_TECHNICAL = {
    "return_15m": 0.8,
    "return_1h": 2.0,
    "ema_20": 105.0,
    "ema_50": 100.0,
    "vwap": 103.0,
    "vwap_distance_pct": 1.0,
    "above_vwap": True,
    "relative_volume": 2.5,
    "trend_bias": "bullish",
}


def _score(**overrides):
    kwargs = dict(
        symbol="BTCUSDT",
        metrics=_BASE_METRICS,
        signal="accumulation",
        funding=0.0002,
        open_interest=50_000.0,
        imbalance=0.2,
        spread_pct=0.02,
        technical=_BASE_TECHNICAL,
        liquidation_summary=None,
        price=103.0,
        volume_profile=None,
        footprint_data=None,
        gex_data=None,
    )
    kwargs.update(overrides)
    return calculate_opportunity_score(**kwargs)


def test_score_in_range():
    result = _score()
    assert 0 <= result["score"] <= 100


def test_neutral_signal_penalizes():
    bullish = _score(signal="accumulation")
    neutral = _score(signal="neutral")
    assert neutral["score"] < bullish["score"]


def test_extreme_funding_penalizes():
    normal  = _score(funding=0.0002)
    extreme = _score(funding=0.01)
    assert extreme["score"] < normal["score"]


def test_high_spread_penalizes():
    tight = _score(spread_pct=0.01)
    wide  = _score(spread_pct=0.15)
    assert wide["score"] < tight["score"]


def test_trend_contradiction_penalizes():
    aligned     = _score(signal="accumulation", technical={**_BASE_TECHNICAL, "trend_bias": "bullish"})
    contradicted = _score(signal="accumulation", technical={**_BASE_TECHNICAL, "trend_bias": "bearish"})
    assert contradicted["score"] < aligned["score"]


def test_above_vwap_adds_technical_score_for_bullish():
    above = _score(signal="accumulation", technical={**_BASE_TECHNICAL, "above_vwap": True})
    below = _score(signal="accumulation", technical={**_BASE_TECHNICAL, "above_vwap": False})
    assert above["score"] > below["score"]


def test_vp_data_near_poc_increases_score():
    no_vp = _score()
    with_vp = _score(volume_profile={
        "poc": 103.2, "hvn_levels": [103.2], "lvn_levels": [],
        "nearest_level": 103.2, "nearest_level_type": "POC",
        "distance_to_level_pct": 0.2,
    })
    assert with_vp["score"] > no_vp["score"]


def test_footprint_absorption_increases_score_for_bullish():
    no_fp = _score()
    with_fp = _score(footprint_data={
        "bid_volume": 100.0, "ask_volume": 200.0,
        "footprint_delta": 100.0, "delta_by_price": {},
        "stacked_buy_imbalance": True,
        "stacked_sell_imbalance": False,
        "absorption_buy": True,
        "absorption_sell": False,
    })
    assert with_fp["score"] > no_fp["score"]


def test_gex_near_put_wall_increases_bullish_score():
    no_gex = _score()
    with_gex = _score(price=103.0, gex_data={
        "spot": 103.0,
        "gamma_flip": 100.0,
        "call_wall": 110.0,
        "put_wall": 102.5,
        "positive_gex_levels": [105.0],
        "negative_gex_levels": [100.0],
    })
    assert with_gex["score"] >= no_gex["score"]


def test_result_has_all_sub_score_keys():
    result = _score()
    for key in (
        "score", "flow_score", "technical_score", "volume_profile_score",
        "footprint_score", "futures_score", "gex_score", "risk_penalty",
        "reasons", "warnings",
    ):
        assert key in result


def test_reasons_list_not_too_long():
    result = _score()
    assert len(result["reasons"]) <= 8


def test_risk_penalty_capped_at_30():
    result = _score(
        signal="neutral",
        funding=0.05,
        spread_pct=0.2,
        technical={**_BASE_TECHNICAL, "trend_bias": "bearish"},
    )
    assert result["risk_penalty"] <= 30


def test_bearish_signal_below_vwap_scores():
    bearish_tech = {**_BASE_TECHNICAL, "above_vwap": False, "trend_bias": "bearish", "return_1h": -2.0}
    bearish_metrics = {"cvd": -500_000.0, "delta": -200_000.0, "buy_volume": 100_000.0, "sell_volume": 300_000.0}
    result = _score(
        signal="distribution",
        metrics=bearish_metrics,
        imbalance=-0.3,
        technical=bearish_tech,
    )
    assert result["score"] > 0
    assert result["flow_score"] > 0
    assert result["technical_score"] > 0
