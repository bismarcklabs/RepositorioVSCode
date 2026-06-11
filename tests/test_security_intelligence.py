import time

from app.security_intelligence import build_security_alert, process_security_events


def _event(source="google_news", domain="Example News", score=-21.0):
    return {
        "symbol": "ZECUSDT",
        "source": source,
        "source_domain": domain,
        "title": "Zcash critical vulnerability reported",
        "url": "https://example.com/security",
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "event_types": ["critical_protocol_bug"],
        "weighted_score": score,
    }


def test_single_media_source_is_unconfirmed():
    alert = build_security_alert("ZECUSDT", [_event()])
    assert alert["confirmation_status"] == "UNCONFIRMED"
    assert alert["trade_bias"] == "RESEARCH_ONLY"


def test_official_github_source_confirms_even_with_moderate_score():
    event = _event("github_release", "github.com/zcash/zcash", -7.2)
    event["event_types"] = ["emergency_security_response"]
    alert = build_security_alert("ZECUSDT", [event])
    assert alert["confirmation_status"] == "CONFIRMED"
    assert alert["trade_bias"] == "WATCH_SHORT_AVOID_LONGS"


def test_two_independent_media_sources_confirm():
    second = _event(domain="Second News")
    alert = build_security_alert("ZECUSDT", [_event(), second])
    assert alert["confirmation_status"] == "CONFIRMED"


def test_process_dispatches_only_when_database_requests_notification(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.security_intelligence.database.upsert_security_event_alert",
        lambda alert: {"id": 1, "should_notify": True},
    )
    monkeypatch.setattr(
        "app.security_intelligence.dispatch_attention_alert",
        lambda symbol, action, dc, tg: sent.append((symbol, action, tg)),
    )
    emitted = process_security_events([_event("github_advisory", "github.com/zcash/zcash", -30)])
    assert len(emitted) == 1
    assert sent[0][1] == "CRITICAL_PROTOCOL_SECURITY"
    assert "No abre posiciones" in sent[0][2]
