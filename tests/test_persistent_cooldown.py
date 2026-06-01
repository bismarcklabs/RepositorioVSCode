"""Tests para el cooldown persistente en alerts_dispatcher.py."""
import time
import pytest
from unittest.mock import MagicMock, patch

from app.notifications.alert_models import TradeAlert


def _make_alert(symbol="BTCUSDT", action="LONG_FUTURES", market="FUTURES", confidence=80):
    return TradeAlert(
        symbol=symbol, action=action, market=market, confidence=confidence,
        price=100_000.0, confluence_score=75,
        timing="NOW", entry=100_000.0,
        entry_zone_low=99_900.0, entry_zone_high=100_100.0,
        stop_loss=98_500.0, take_profit_1=102_000.0, take_profit_2=104_000.0,
        risk_reward_1=1.33, risk_reward_2=2.67,
        reasons=["CVD positivo"], warnings=[], invalidation=[],
    )


@pytest.fixture(autouse=True)
def reset_cooldown():
    """Limpia el store en memoria y el flag de preload antes de cada test."""
    import app.notifications.alerts_dispatcher as d
    d._cooldown_store.clear()
    d._preloaded = True  # Evitar que intente cargar de DB en tests
    yield
    d._cooldown_store.clear()
    d._preloaded = True


def test_first_alert_is_sent():
    from app.notifications.alerts_dispatcher import _should_send
    alert = _make_alert()
    assert _should_send(alert) is True


def test_second_alert_within_cooldown_is_blocked():
    from app.notifications.alerts_dispatcher import _should_send
    alert = _make_alert()
    _should_send(alert)  # primera
    assert _should_send(alert) is False


def test_alert_resent_after_cooldown_expires(monkeypatch):
    import app.notifications.alerts_dispatcher as d
    monkeypatch.setattr(d, "ALERT_COOLDOWN_SECONDS", 1)
    alert = _make_alert()
    d._should_send(alert)
    time.sleep(1.1)
    assert d._should_send(alert) is True


def test_alert_resent_when_confidence_increases():
    from app.notifications.alerts_dispatcher import _should_send, _cooldown_store
    alert_low = _make_alert(confidence=70)
    _should_send(alert_low)
    alert_high = _make_alert(confidence=81)  # +11 puntos
    assert _should_send(alert_high) is True


def test_alert_not_resent_when_confidence_insufficient():
    from app.notifications.alerts_dispatcher import _should_send
    alert_low = _make_alert(confidence=70)
    _should_send(alert_low)
    alert_mid = _make_alert(confidence=75)  # +5 (< delta de 10)
    assert _should_send(alert_mid) is False


def test_different_symbols_independent_cooldown():
    from app.notifications.alerts_dispatcher import _should_send
    btc = _make_alert("BTCUSDT")
    eth = _make_alert("ETHUSDT")
    _should_send(btc)
    assert _should_send(eth) is True


def test_different_actions_independent_cooldown():
    from app.notifications.alerts_dispatcher import _should_send
    long_a = _make_alert(action="LONG_FUTURES", market="FUTURES")
    short_a = _make_alert(action="SHORT_FUTURES", market="FUTURES")
    _should_send(long_a)
    assert _should_send(short_a) is True


def test_preload_from_db_populates_store(monkeypatch):
    """Simula que la DB tiene una alerta reciente y verifica que el store se precarga."""
    import app.notifications.alerts_dispatcher as d
    d._preloaded = False
    d._cooldown_store.clear()

    mock_rows = [{
        "symbol": "BTCUSDT",
        "action": "LONG_FUTURES",
        "market": "FUTURES",
        "confidence": 80,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 300)),
    }]
    monkeypatch.setattr("app.notifications.alerts_dispatcher.ENABLE_DATABASE", True)
    with patch("app.database.get_recent_sent_alerts", return_value=mock_rows):
        d._preload_from_db()

    assert ("BTCUSDT", "LONG_FUTURES", "FUTURES") in d._cooldown_store


def test_cooldown_preloaded_blocks_immediate_resend(monkeypatch):
    """Si la DB dice que enviamos una alerta hace 5 min, no reenviar hasta los 15 min."""
    import app.notifications.alerts_dispatcher as d
    d._preloaded = False
    d._cooldown_store.clear()

    mock_rows = [{
        "symbol": "BTCUSDT",
        "action": "LONG_FUTURES",
        "market": "FUTURES",
        "confidence": 80,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 300)),
    }]
    monkeypatch.setattr("app.notifications.alerts_dispatcher.ENABLE_DATABASE", True)
    with patch("app.database.get_recent_sent_alerts", return_value=mock_rows):
        d._preload_from_db()

    alert = _make_alert(confidence=80)
    assert d._should_send(alert) is False  # aún en cooldown (solo 5 min de 15 han pasado)
