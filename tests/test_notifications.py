import pytest
from unittest.mock import patch, MagicMock
from app.notifications.alert_models import TradeAlert
from app.notifications.alerts_dispatcher import dispatch_alert, _cooldown_store, _cooldown_lock


def _make_alert(**kwargs):
    defaults = dict(
        symbol="BTCUSDT",
        action="LONG_FUTURES",
        market="FUTURES",
        confidence=85,
        price=50_000.0,
        confluence_score=85,
        timing="NOW",
        entry=50_000.0,
        entry_zone_low=49_950.0,
        entry_zone_high=50_050.0,
        stop_loss=49_250.0,
        take_profit_1=50_750.0,
        take_profit_2=51_500.0,
        risk_reward_1=1.0,
        risk_reward_2=2.0,
        reasons=["CVD positivo", "Sobre VWAP"],
        warnings=[],
        invalidation=["Pérdida de VWAP"],
        position_note="Entrada inmediata",
    )
    defaults.update(kwargs)
    return TradeAlert(**defaults)


# ── TradeAlert.is_valid() ─────────────────────────────────────────────────

def test_alert_is_valid():
    a = _make_alert()
    assert a.is_valid()


def test_alert_invalid_when_no_entry():
    a = _make_alert(entry=0.0)
    assert not a.is_valid()


def test_alert_invalid_when_no_stop():
    a = _make_alert(stop_loss=0.0)
    assert not a.is_valid()


def test_alert_invalid_when_no_tp1():
    a = _make_alert(take_profit_1=0.0)
    assert not a.is_valid()


def test_alert_invalid_when_stop_equals_entry():
    a = _make_alert(stop_loss=50_000.0)
    assert not a.is_valid()


# ── TradeAlert.subject ────────────────────────────────────────────────────

def test_alert_subject_format():
    a = _make_alert()
    assert "LONG_FUTURES" in a.subject
    assert "BTCUSDT" in a.subject
    assert "85%" in a.subject


# ── TradeAlert.from_row ───────────────────────────────────────────────────

def test_from_row_returns_none_for_wait():
    row = {"action": "WAIT", "setup": None}
    assert TradeAlert.from_row(row) is None


def test_from_row_returns_none_when_no_setup():
    row = {"action": "BUY_SPOT", "setup": None}
    assert TradeAlert.from_row(row) is None


def test_from_row_builds_alert():
    row = {
        "symbol": "ETHUSDT", "action": "BUY_SPOT", "market": "SPOT",
        "confidence": 78, "price": 3000.0, "score": 78,
        "reasons": ["r1"], "warnings": [], "invalidation": ["i1"],
        "setup": {
            "timing": "NOW", "entry": 3000.0,
            "entry_zone_low": 2997.0, "entry_zone_high": 3003.0,
            "stop_loss": 2940.0, "take_profit_1": 3060.0,
            "take_profit_2": 3120.0, "risk_reward_1": 1.0,
            "risk_reward_2": 2.0, "position_note": "",
        },
    }
    alert = TradeAlert.from_row(row)
    assert alert is not None
    assert alert.symbol == "ETHUSDT"
    assert alert.entry == 3000.0
    assert alert.stop_loss == 2940.0


# ── dispatch_alert — canales deshabilitados ───────────────────────────────

def test_dispatch_no_channels_returns_empty():
    with _cooldown_lock:
        _cooldown_store.clear()
    with (
        patch("app.notifications.alerts_dispatcher.ENABLE_DISCORD_ALERTS", False),
        patch("app.notifications.alerts_dispatcher.ENABLE_TELEGRAM_ALERTS", False),
        patch("app.notifications.alerts_dispatcher.ENABLE_EMAIL_ALERTS", False),
    ):
        result = dispatch_alert(_make_alert(symbol="NODISCORD"))
    assert result == {}


# ── dispatch_alert — cooldown ─────────────────────────────────────────────

def test_dispatch_cooldown_blocks_repeat():
    with _cooldown_lock:
        _cooldown_store.clear()

    with (
        patch("app.notifications.alerts_dispatcher.ENABLE_DISCORD_ALERTS", True),
        patch("app.notifications.alerts_dispatcher.DISCORD_WEBHOOK_URL", "http://fake"),
        patch("app.notifications.alerts_dispatcher.ENABLE_TELEGRAM_ALERTS", False),
        patch("app.notifications.alerts_dispatcher.ENABLE_EMAIL_ALERTS", False),
        patch("app.notifications.discord_notifier.send_discord_alert", return_value=True),
    ):
        a = _make_alert(symbol="COOLTEST", confidence=80)
        r1 = dispatch_alert(a)
        assert r1.get("discord") is True

        # Segunda llamada inmediata — debe bloquearse por cooldown
        r2 = dispatch_alert(a)
        assert r2 == {}


def test_dispatch_resends_on_confidence_jump():
    with _cooldown_lock:
        _cooldown_store.clear()

    with (
        patch("app.notifications.alerts_dispatcher.ENABLE_DISCORD_ALERTS", True),
        patch("app.notifications.alerts_dispatcher.DISCORD_WEBHOOK_URL", "http://fake"),
        patch("app.notifications.alerts_dispatcher.ENABLE_TELEGRAM_ALERTS", False),
        patch("app.notifications.alerts_dispatcher.ENABLE_EMAIL_ALERTS", False),
        patch("app.notifications.discord_notifier.send_discord_alert", return_value=True),
    ):
        a_low = _make_alert(symbol="RETEST", confidence=70)
        dispatch_alert(a_low)

        # +10 pts de confianza → debe reenviar aunque esté en cooldown
        a_high = _make_alert(symbol="RETEST", confidence=80)
        r = dispatch_alert(a_high)
        assert r.get("discord") is True


# ── dispatch_alert — error de Discord no bloquea Telegram ─────────────────

def test_discord_failure_does_not_block_telegram():
    with _cooldown_lock:
        _cooldown_store.clear()

    tg_mock = MagicMock(return_value=True)
    with (
        patch("app.notifications.alerts_dispatcher.ENABLE_DISCORD_ALERTS", True),
        patch("app.notifications.alerts_dispatcher.DISCORD_WEBHOOK_URL", "http://fake"),
        patch("app.notifications.alerts_dispatcher.ENABLE_TELEGRAM_ALERTS", True),
        patch("app.notifications.alerts_dispatcher.TELEGRAM_BOT_TOKEN", "tok"),
        patch("app.notifications.alerts_dispatcher.TELEGRAM_CHAT_ID", "123"),
        patch("app.notifications.alerts_dispatcher.ENABLE_EMAIL_ALERTS", False),
        patch("app.notifications.discord_notifier.send_discord_alert",
              side_effect=Exception("discord down")),
        patch("app.notifications.telegram_notifier.send_telegram_alert", tg_mock),
    ):
        result = dispatch_alert(_make_alert(symbol="FAILTEST"))

    assert result.get("discord") is False
    assert result.get("telegram") is True


# ── Formato del mensaje ───────────────────────────────────────────────────

def test_discord_embed_contains_entry_and_stop():
    from app.notifications.discord_notifier import send_discord_alert
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        m = MagicMock()
        m.raise_for_status.return_value = None
        return m

    with patch("app.notifications.discord_notifier.requests.post", side_effect=fake_post):
        send_discord_alert(_make_alert(), "http://fake-webhook")

    fields = {f["name"]: f["value"] for f in captured["payload"]["embeds"][0]["fields"]}
    assert "📈 Entrada" in fields
    assert "🛑 Stop" in fields
    assert "🎯 TP1" in fields


def test_telegram_message_contains_key_data():
    from app.notifications.telegram_notifier import send_telegram_alert
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        m = MagicMock()
        m.raise_for_status.return_value = None
        return m

    with patch("app.notifications.telegram_notifier.requests.post", side_effect=fake_post):
        send_telegram_alert(_make_alert(), "bot_token", "chat_id")

    text = captured["payload"]["text"]
    assert "LONG_FUTURES" in text or "BTCUSDT" in text
