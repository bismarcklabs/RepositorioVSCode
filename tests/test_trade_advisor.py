import pytest
from app.trade_advisor import build_trade_recommendation
from app.config import (
    MIN_ALERT_SCORE_BUY_SPOT,
    MIN_ALERT_SCORE_SELL_SPOT,
    MIN_ALERT_SCORE_LONG_FUTURES,
    MIN_ALERT_SCORE_SHORT_FUTURES,
    EXTREME_FUNDING_ABS,
)


_BASE_TECHNICAL = {
    "trend_bias": "bullish",
    "vwap_distance_pct": 0.5,
    "return_1h": 1.5,
    "above_vwap": True,
}
_BEARISH_TECHNICAL = {
    "trend_bias": "bearish",
    "vwap_distance_pct": -0.5,
    "return_1h": -1.5,
    "above_vwap": False,
}


def _rec(signal, score, funding=0.0002, oi=50_000.0, risk="low",
         technical=None, volume_profile=None, price=50_000.0):
    technical = technical or _BASE_TECHNICAL
    score_data = {"score": score, "warnings": [], "reasons": ["Señal fuerte", "CVD positivo"]}
    alert_report = {"risk": {"risk_level": risk}} if risk != "low" else None
    return build_trade_recommendation(
        symbol="BTCUSDT",
        signal=signal,
        score_data=score_data,
        technical=technical,
        funding=funding,
        open_interest=oi,
        price=price,
        alert_report=alert_report,
        volume_profile=volume_profile,
    )


def test_long_futures_all_conditions_met():
    result = _rec("accumulation", score=MIN_ALERT_SCORE_LONG_FUTURES, funding=0.0002, oi=1.0)
    assert result["action"] == "LONG_FUTURES"
    assert result["market"] == "FUTURES"


def test_long_futures_blocked_when_below_vwap():
    tech_below = {**_BASE_TECHNICAL, "above_vwap": False}
    result = _rec("accumulation", score=MIN_ALERT_SCORE_LONG_FUTURES, oi=1.0, technical=tech_below)
    assert result["action"] != "LONG_FUTURES"


def test_short_futures_all_conditions_met():
    result = _rec(
        "distribution", score=MIN_ALERT_SCORE_SHORT_FUTURES,
        funding=0.0005, oi=1.0, technical=_BEARISH_TECHNICAL,
    )
    assert result["action"] == "SHORT_FUTURES"
    assert result["market"] == "FUTURES"


def test_short_futures_blocked_when_above_vwap():
    tech_above = {**_BEARISH_TECHNICAL, "above_vwap": True}
    result = _rec(
        "distribution", score=MIN_ALERT_SCORE_SHORT_FUTURES,
        funding=0.0005, oi=1.0, technical=tech_above,
    )
    assert result["action"] != "SHORT_FUTURES"


def test_buy_spot_fallback_when_low_score_for_futures():
    result = _rec("accumulation", score=MIN_ALERT_SCORE_BUY_SPOT, oi=0.0)
    assert result["action"] == "BUY_SPOT"
    assert result["market"] == "SPOT"


def test_sell_spot():
    result = _rec(
        "distribution", score=MIN_ALERT_SCORE_SELL_SPOT, oi=0.0,
        technical=_BEARISH_TECHNICAL,
    )
    assert result["action"] == "SELL_SPOT"
    assert result["market"] == "SPOT"


def test_wait_when_score_too_low():
    result = _rec("accumulation", score=MIN_ALERT_SCORE_BUY_SPOT - 10)
    assert result["action"] == "WAIT"


def test_wait_when_risk_high():
    result = _rec("accumulation", score=90, risk="high")
    assert result["action"] == "WAIT"
    assert any("alto" in w.lower() for w in result["warnings"])


def test_wait_for_neutral_signal():
    result = _rec("neutral", score=85)
    assert result["action"] == "WAIT"


def test_extreme_funding_blocks_long_futures():
    result = _rec(
        "accumulation", score=MIN_ALERT_SCORE_LONG_FUTURES,
        funding=EXTREME_FUNDING_ABS + 0.002, oi=1.0,
    )
    assert result["action"] != "LONG_FUTURES"


def test_confidence_capped_at_95():
    result = _rec("accumulation", score=99, funding=0.0001, oi=1.0)
    assert result["confidence"] <= 95


def test_confluence_score_in_result():
    result = _rec("accumulation", score=80, funding=0.0001, oi=1.0)
    assert "confluence_score" in result
    assert result["confluence_score"] == 80


def test_vp_invalidation_included_when_vp_provided():
    vp = {
        "poc": 50000.0, "hvn_levels": [50000.0], "lvn_levels": [],
        "nearest_level": 50000.0, "nearest_level_type": "POC",
        "distance_to_level_pct": 0.1,
    }
    result = _rec("accumulation", score=MIN_ALERT_SCORE_LONG_FUTURES, oi=1.0, volume_profile=vp)
    assert any("POC" in c or "HVN" in c for c in result["invalidation"])


def test_result_has_required_keys():
    result = _rec("accumulation", score=80)
    for key in ("action", "market", "confidence", "confluence_score",
                "entry_context", "reasons", "warnings", "invalidation", "risk_level", "setup"):
        assert key in result


def test_setup_has_entry_stop_tp_when_actionable():
    result = _rec("accumulation", score=MIN_ALERT_SCORE_LONG_FUTURES, funding=0.0002, oi=1.0)
    assert result["action"] != "WAIT"
    setup = result["setup"]
    assert setup is not None
    assert setup["entry"] > 0.0
    assert setup["stop_loss"] > 0.0
    assert setup["take_profit_1"] > 0.0
    assert setup["take_profit_2"] >= setup["take_profit_1"]
    assert setup["risk_reward_1"] > 0.0


def test_setup_is_none_when_wait():
    result = _rec("accumulation", score=MIN_ALERT_SCORE_BUY_SPOT - 10)
    assert result["action"] == "WAIT"
    assert result["setup"] is None


def test_action_wait_when_price_zero():
    # price=0 → entry_exit returns None → action degrades to WAIT
    result = _rec("accumulation", score=MIN_ALERT_SCORE_LONG_FUTURES, oi=1.0, price=0.0)
    assert result["action"] == "WAIT"
    assert result["setup"] is None


def test_setup_stop_below_entry_for_long():
    result = _rec("accumulation", score=MIN_ALERT_SCORE_BUY_SPOT, oi=0.0)
    assert result["action"] == "BUY_SPOT"
    setup = result["setup"]
    assert setup["stop_loss"] < setup["entry"]


def test_setup_stop_above_entry_for_short():
    result = _rec(
        "distribution", score=MIN_ALERT_SCORE_SHORT_FUTURES,
        funding=0.0005, oi=1.0, technical=_BEARISH_TECHNICAL,
    )
    assert result["action"] == "SHORT_FUTURES"
    setup = result["setup"]
    assert setup["stop_loss"] > setup["entry"]
