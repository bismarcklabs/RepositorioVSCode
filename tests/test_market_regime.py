from app.market_regime import detect_btc_market_regime


def test_detects_btc_risk_on():
    regime = detect_btc_market_regime({
        "return_1h": 1.4,
        "return_15m": 0.7,
        "return_5m": 0.2,
        "trend_bias": "bullish",
        "htf_trend_bias": "bullish",
    })
    assert regime["active"] is True
    assert regime["regime"] == "BTC_RISK_ON"


def test_detects_btc_risk_off():
    regime = detect_btc_market_regime({
        "return_1h": -1.4,
        "return_15m": -0.7,
        "return_5m": -0.2,
        "trend_bias": "bearish",
        "htf_trend_bias": "bearish",
    })
    assert regime["active"] is True
    assert regime["regime"] == "BTC_RISK_OFF"


def test_normal_when_btc_not_impulsive():
    regime = detect_btc_market_regime({
        "return_1h": 0.2,
        "return_15m": 0.1,
        "return_5m": 0.0,
        "trend_bias": "neutral",
    })
    assert regime["active"] is False
    assert regime["regime"] == "NORMAL"
