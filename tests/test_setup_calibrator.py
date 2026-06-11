from app.setup_calibrator import calibrate_setup


def _evaluation(**checklist):
    return {
        "grade": "NO_TRADE",
        "checklist": {
            "direction_ok": False, "context_ok": False, "level_ok": False,
            "trigger_ok": False, "risk_ok": False, **checklist,
        },
    }


def test_bearish_direction_without_entry_becomes_watch():
    result = calibrate_setup(
        action="SHORT_FUTURES",
        setup_evaluation=_evaluation(direction_ok=True),
        technical={"relative_volume": 1.0},
        metrics={"delta": -10, "cvd_15m": -20},
        setup={"stop_loss": 101, "risk_reward_1": 1.0},
        market_regime={"regime": "BTC_RISK_OFF", "active": True},
    )
    assert result["original_grade"] == "NO_TRADE"
    assert result["calibrated_grade"] == "BEARISH_WATCH"
    assert result["direction_score"] >= 60
    assert result["entry_score"] < 45


def test_short_high_relvol_does_not_get_entry_bonus():
    result = calibrate_setup(
        action="SHORT_FUTURES",
        setup_evaluation=_evaluation(direction_ok=True, trigger_ok=True, risk_ok=True),
        technical={"relative_volume": 4.8},
        metrics={"delta": -10, "cvd_15m": -20},
        setup={"stop_loss": 101, "risk_reward_1": 2.0, "risk_pct": 1.0},
        market_regime={"regime": "NORMAL", "active": False},
    )
    assert result["direction_score"] == 80
    assert result["entry_score"] == 55
    assert result["calibrated_grade"] == "B"


def test_long_high_relvol_without_trigger_does_not_get_entry_bonus():
    result = calibrate_setup(
        action="LONG_FUTURES",
        setup_evaluation=_evaluation(direction_ok=True, context_ok=True, level_ok=True, risk_ok=True),
        technical={"relative_volume": 3.5},
        metrics={"delta": 10, "cvd_15m": 20},
        setup={"stop_loss": 99, "risk_reward_1": 2.0, "risk_pct": 1.0},
        market_regime={"regime": "BTC_RISK_ON", "active": True},
    )
    assert result["entry_score"] == 55
    assert result["calibrated_grade"] == "B"


def test_complete_setup_gets_actionable_calibrated_grade():
    result = calibrate_setup(
        action="LONG_FUTURES",
        setup_evaluation=_evaluation(
            direction_ok=True, context_ok=True, level_ok=True, trigger_ok=True, risk_ok=True
        ),
        technical={"relative_volume": 2.5},
        metrics={"delta": 10, "cvd_15m": 20},
        setup={"stop_loss": 99, "risk_reward_1": 2.0, "risk_pct": 1.0},
        market_regime={"regime": "BTC_RISK_ON", "active": True},
    )
    assert result["calibrated_grade"] == "A"