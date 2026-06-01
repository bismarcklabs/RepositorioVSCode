"""Tests para app/outcome_tracker.py."""
import time
import pytest


def _make_alert(action="LONG_FUTURES", ts_offset_minutes=-90):
    """Crea un dict de alerta con timestamp UTC en el pasado."""
    ts = time.time() + ts_offset_minutes * 60
    return {
        "id": 1,
        "symbol": "BTCUSDT",
        "action": action,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)),
        "entry": 100_000.0,
        "stop_loss": 98_500.0,
        "take_profit_1": 102_000.0,
        "take_profit_2": 104_000.0,
    }


def _make_klines(high, low, close, n=10, open_after_ts=0):
    """Crea lista de klines sintéticas con open_time > open_after_ts."""
    interval_ms = 60_000  # 1 minuto
    base_ts = int((open_after_ts + 10) * 1000)
    return [
        [base_ts + i * interval_ms, close - 100, high, low, close, "1000",
         base_ts + (i + 1) * interval_ms, "5000000", 100, "500", "2500000", "0"]
        for i in range(n)
    ]


# ── Tests de lógica de outcome ────────────────────────────────────────────

def test_long_win_tp2_hit():
    from app.outcome_tracker import _evaluate_alert
    alert = _make_alert("LONG_FUTURES", ts_offset_minutes=-90)
    klines = _make_klines(high=105_000, low=99_000, close=104_500,
                          open_after_ts=time.time() - 90 * 60)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.outcome_tracker.get_klines", lambda *a, **k: klines)
        result = _evaluate_alert(alert, horizon_minutes=60)

    assert result is not None
    assert result["hit_tp2"] is True
    assert result["outcome"] == "win"


def test_long_partial_tp1_only():
    from app.outcome_tracker import _evaluate_alert
    alert = _make_alert("LONG_FUTURES", ts_offset_minutes=-90)
    klines = _make_klines(high=102_500, low=99_500, close=101_500,
                          open_after_ts=time.time() - 90 * 60)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.outcome_tracker.get_klines", lambda *a, **k: klines)
        result = _evaluate_alert(alert, horizon_minutes=60)

    assert result is not None
    assert result["hit_tp1"] is True
    assert result["hit_tp2"] is False
    assert result["hit_stop"] is False
    assert result["outcome"] == "partial"


def test_long_loss_stop_hit():
    from app.outcome_tracker import _evaluate_alert
    alert = _make_alert("LONG_FUTURES", ts_offset_minutes=-90)
    klines = _make_klines(high=100_500, low=97_000, close=97_500,
                          open_after_ts=time.time() - 90 * 60)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.outcome_tracker.get_klines", lambda *a, **k: klines)
        result = _evaluate_alert(alert, horizon_minutes=60)

    assert result is not None
    assert result["hit_stop"] is True
    assert result["hit_tp1"] is False
    assert result["outcome"] == "loss"


def test_short_win_tp2_hit():
    from app.outcome_tracker import _evaluate_alert
    alert_data = _make_alert("SHORT_FUTURES", ts_offset_minutes=-90)
    alert_data["entry"] = 100_000.0
    alert_data["stop_loss"] = 101_500.0
    alert_data["take_profit_1"] = 98_500.0
    alert_data["take_profit_2"] = 96_000.0
    klines = _make_klines(high=100_200, low=95_000, close=95_500,
                          open_after_ts=time.time() - 90 * 60)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.outcome_tracker.get_klines", lambda *a, **k: klines)
        result = _evaluate_alert(alert_data, horizon_minutes=60)

    assert result is not None
    assert result["hit_tp2"] is True
    assert result["outcome"] == "win"


def test_short_loss_stop_hit():
    from app.outcome_tracker import _evaluate_alert
    alert_data = _make_alert("SHORT_FUTURES", ts_offset_minutes=-90)
    alert_data["entry"] = 100_000.0
    alert_data["stop_loss"] = 101_500.0
    alert_data["take_profit_1"] = 98_500.0
    alert_data["take_profit_2"] = 96_000.0
    klines = _make_klines(high=102_000, low=99_500, close=101_800,
                          open_after_ts=time.time() - 90 * 60)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.outcome_tracker.get_klines", lambda *a, **k: klines)
        result = _evaluate_alert(alert_data, horizon_minutes=60)

    assert result is not None
    assert result["hit_stop"] is True
    assert result["outcome"] == "loss"


def test_horizon_not_yet_elapsed_returns_none():
    from app.outcome_tracker import _evaluate_alert
    alert = _make_alert("LONG_FUTURES", ts_offset_minutes=-10)  # solo 10 min atrás
    result = _evaluate_alert(alert, horizon_minutes=60)
    assert result is None


def test_anti_lookahead_filters_past_klines():
    """Klines con open_time ANTES de la alerta no deben usarse."""
    from app.outcome_tracker import _evaluate_alert
    alert = _make_alert("LONG_FUTURES", ts_offset_minutes=-90)
    # Klines todas en el pasado respecto a la alerta → future_klines = []
    past_ts = time.time() - 200 * 60
    klines = _make_klines(high=200_000, low=50_000, close=99_000,
                          open_after_ts=past_ts - 3600)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.outcome_tracker.get_klines", lambda *a, **k: klines)
        result = _evaluate_alert(alert, horizon_minutes=60)

    # Si no hay velas futuras, retorna None
    assert result is None
