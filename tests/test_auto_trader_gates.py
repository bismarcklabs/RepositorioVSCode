from app import auto_trader


def _result(action="SHORT_FUTURES", grade="B", score=80, regime="BTC_RISK_OFF"):
    return {
        "symbol": "BTCUSDT",
        "score_data": {"score": score},
        "market_regime": {"regime": regime, "active": regime != "NORMAL"},
        "setup_calibration": {"calibrated_grade": grade},
        "recommendation": {
            "action": action,
            "confidence": 80,
            "setup": {"stop_loss": 101},
            "setup_evaluation": {"grade": "C", "checklist": {"trigger_ok": True}},
        },
    }


def test_watch_is_never_auto_traded(monkeypatch):
    monkeypatch.setattr(auto_trader.database, "count_recent_auto_losses", lambda *args: 0)
    ok, reason = auto_trader._passes_gates(_result(grade="BEARISH_WATCH"), [])
    assert not ok
    assert "no es auto-operable" in reason


def test_grade_c_long_requires_risk_on(monkeypatch):
    monkeypatch.setattr(auto_trader.database, "count_recent_auto_losses", lambda *args: 0)
    ok, reason = auto_trader._passes_gates(
        _result(action="LONG_FUTURES", grade="C", score=90, regime="NORMAL"), []
    )
    assert not ok
    assert "requiere BTC_RISK_ON" in reason


def test_consecutive_losses_start_cooldown(monkeypatch):
    monkeypatch.setattr(auto_trader.database, "count_recent_auto_losses", lambda *args: 2)
    ok, reason = auto_trader._passes_gates(_result(), [])
    assert not ok
    assert "perdidas consecutivas" in reason