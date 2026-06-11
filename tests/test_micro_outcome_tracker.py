import time
import pytest


def _make_micro_alert(action="MICRO_LONG_SCALP", ts_offset_minutes=-20):
    ts = time.time() + ts_offset_minutes * 60
    if action == "MICRO_LONG_SCALP":
        tp1, tp2, sl = 100.3, 100.6, 99.75
    else:
        tp1, tp2, sl = 99.7, 99.4, 100.25
    return {
        "id": 1,
        "symbol": "BTCUSDT",
        "action": action,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)),
        "entry": 100.0,
        "take_profit_1": tp1,
        "take_profit_2": tp2,
        "stop_loss": sl,
        "timeout_minutes": 10,
    }


def _klines(high, low, close, n=10, open_after_ts=0):
    base_ts = int((open_after_ts + 10) * 1000)
    return [
        [base_ts + i * 60_000, close, high, low, close, "1",
         base_ts + (i + 1) * 60_000, "1000", 1, "1", "1000", "0"]
        for i in range(n)
    ]


def _klines_seq(rows, open_after_ts=0):
    """rows: lista de (high, low, close), una vela por minuto."""
    base_ts = int((open_after_ts + 10) * 1000)
    return [
        [base_ts + i * 60_000, close, high, low, close, "1",
         base_ts + (i + 1) * 60_000, "1000", 1, "1", "1000", "0"]
        for i, (high, low, close) in enumerate(rows)
    ]


def test_micro_long_win_tp2_hit():
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP")
    kl = _klines(100.8, 99.95, 100.7, open_after_ts=time.time() - 20 * 60)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: kl)
        result = _evaluate_micro_alert(alert)
    assert result["outcome"] == "win"
    assert result["hit_tp2"] is True


def test_micro_short_loss_stop_hit():
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_SHORT_SCALP")
    kl = _klines(100.4, 99.9, 100.3, open_after_ts=time.time() - 20 * 60)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: kl)
        result = _evaluate_micro_alert(alert)
    assert result["outcome"] == "loss"
    assert result["hit_stop"] is True


def test_micro_not_elapsed_returns_none():
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP", ts_offset_minutes=-3)
    assert _evaluate_micro_alert(alert) is None


def test_micro_uses_historical_window_kwargs():
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP")
    captured = {}

    def fake_get_klines(*args, **kwargs):
        captured.update(kwargs)
        return _klines(100.8, 99.95, 100.7, open_after_ts=time.time() - 20 * 60)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", fake_get_klines)
        result = _evaluate_micro_alert(alert)

    assert result["outcome"] == "win"
    assert "start_time_ms" in captured
    assert "end_time_ms" in captured


def test_micro_long_sl_hit_before_later_tp_is_loss_at_sl_price():
    """SL roto en la vela 1; TP1 se toca recien en la vela 2 (no deberia
    revertir el resultado a 'partial' ni reflejar el cierre de ventana)."""
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP")  # tp1=100.3 tp2=100.6 sl=99.75
    kl = _klines_seq(
        [(100.0, 99.7, 99.8), (100.4, 99.9, 100.3)],
        open_after_ts=time.time() - 20 * 60,
    )
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: kl)
        result = _evaluate_micro_alert(alert)
    assert result["outcome"] == "loss"
    assert result["hit_stop"] is True
    assert result["exit_price"] == 99.75
    assert result["pnl_pct"] == pytest.approx(-0.25, abs=1e-4)


def test_micro_long_tp1_then_tp2_is_win_at_tp2_price():
    """TP1 se toca en la vela 1 y TP2 en la vela 2, sin tocar el SL nunca:
    la salida debe ser TP2, no el cierre de la ultima vela."""
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP")  # tp1=100.3 tp2=100.6 sl=99.75
    kl = _klines_seq(
        [(100.4, 99.9, 100.3), (100.7, 99.95, 100.5)],
        open_after_ts=time.time() - 20 * 60,
    )
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: kl)
        result = _evaluate_micro_alert(alert)
    assert result["outcome"] == "win"
    assert result["hit_tp1"] is True
    assert result["hit_tp2"] is True
    assert result["exit_price"] == 100.6
    assert result["pnl_pct"] == pytest.approx(0.6, abs=1e-4)


def test_micro_short_tp1_then_sl_is_loss_at_sl_price():
    """Para SHORT: TP1 se toca primero y luego el SL — la salida real es el
    SL, no un 'partial' calculado al cierre de la ventana."""
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_SHORT_SCALP")  # tp1=99.7 tp2=99.4 sl=100.25
    kl = _klines_seq(
        [(100.0, 99.6, 99.7), (100.3, 99.9, 100.2)],
        open_after_ts=time.time() - 20 * 60,
    )
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: kl)
        result = _evaluate_micro_alert(alert)
    assert result["outcome"] == "loss"
    assert result["hit_stop"] is True
    assert result["exit_price"] == 100.25
    assert result["pnl_pct"] == pytest.approx(-0.25, abs=1e-4)


def test_micro_long_tp1_only_then_timeout_is_partial_at_close():
    """TP1 se toca pero ni TP2 ni SL llegan a romperse: la posicion sigue
    abierta hasta el timeout y el resultado es 'partial' al precio de cierre."""
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP")  # tp1=100.3 tp2=100.6 sl=99.75
    kl = _klines_seq(
        [(100.35, 99.9, 100.1), (100.1, 99.95, 100.05)],
        open_after_ts=time.time() - 20 * 60,
    )
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: kl)
        result = _evaluate_micro_alert(alert)
    assert result["outcome"] == "partial"
    assert result["hit_tp1"] is True
    assert result["hit_tp2"] is False
    assert result["hit_stop"] is False
    assert result["exit_price"] == 100.05


def test_micro_force_closes_stale_alert_without_klines():
    from app.micro_outcome_tracker import _evaluate_micro_alert
    alert = _make_micro_alert("MICRO_LONG_SCALP", ts_offset_minutes=-120)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("app.micro_outcome_tracker.MICRO_SCALP_FORCE_CLOSE_AFTER_MINUTES", 30)
        mp.setattr("app.micro_outcome_tracker.get_klines", lambda *a, **k: [])
        result = _evaluate_micro_alert(alert)

    assert result["outcome"] == "expired"
    assert result["pnl_pct"] == 0.0
