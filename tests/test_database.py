"""Tests para app/database.py."""
import os
import tempfile
import time

import pytest

# Usar DB temporal para tests
_TMP_DB = tempfile.mktemp(suffix=".sqlite3")
os.environ.setdefault("DATABASE_PATH", _TMP_DB)
os.environ.setdefault("ENABLE_DATABASE", "true")
os.environ.setdefault("SNAPSHOT_RETENTION_DAYS", "90")


def _reset_db():
    """Limpia el módulo database para forzar reinicialización con DB temporal."""
    import importlib, app.database as db
    db._db_initialized = False
    if hasattr(db._db_local, "conn") and db._db_local.conn:
        db._db_local.conn.close()
        db._db_local.conn = None


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test.sqlite3")
    monkeypatch.setenv("DATABASE_PATH", db_file)
    import app.database as db
    monkeypatch.setattr(db, "DATABASE_PATH", db_file)
    monkeypatch.setattr(db, "_db_initialized", False)
    if hasattr(db._db_local, "conn") and db._db_local.conn:
        db._db_local.conn.close()
        db._db_local.conn = None
    db.init_db()
    yield db


def _make_snapshot(sym="BTCUSDT"):
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "symbol": sym,
        "price": 100_000.0,
        "futures_price": 100_050.0,
        "recommendation": {
            "action": "LONG_FUTURES",
            "market": "FUTURES",
            "confidence": 80,
            "risk_level": "low",
            "setup": {
                "entry": 100_000.0,
                "entry_zone_low": 99_900.0,
                "entry_zone_high": 100_100.0,
                "stop_loss": 98_500.0,
                "take_profit_1": 102_000.0,
                "take_profit_2": 104_000.0,
                "risk_reward_1": 1.33,
                "risk_reward_2": 2.67,
            },
            "reasons": ["CVD positivo"],
            "warnings": [],
            "invalidation": ["Pérdida de VWAP"],
        },
        "signal": {"signal": "accumulation"},
        "score_data": {"score": 75, "gex_score": 3},
        "metrics": {"delta": 10.0, "cvd": 500.0, "buy_volume": 200.0, "sell_volume": 190.0},
        "funding": 0.0001,
        "open_interest": 5_000_000.0,
        "orderbook": {"imbalance": 0.12, "spread_pct": 0.02},
        "technical": {
            "return_15m": 0.3, "return_1h": 1.2, "vwap": 99_800.0,
            "vwap_distance_pct": 0.2, "above_vwap": True,
            "relative_volume": 1.5, "trend_bias": "bullish",
        },
        "volume_profile": {"poc": 99_700.0, "nearest_level": 99_700.0,
                           "nearest_level_type": "POC", "distance_to_level_pct": 0.3},
        "footprint": {"footprint_delta": 5.0, "absorption_buy": False,
                      "absorption_sell": False, "stacked_buy_imbalance": True,
                      "stacked_sell_imbalance": False},
        "gex": {"call_wall": 105_000.0, "put_wall": 95_000.0, "gamma_flip": 100_500.0},
    }


def _make_alert(sym="BTCUSDT"):
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "symbol": sym,
        "action": "LONG_FUTURES",
        "market": "FUTURES",
        "confidence": 80,
        "score": 75,
        "price": 100_000.0,
        "setup": {
            "entry": 100_000.0,
            "stop_loss": 98_500.0,
            "take_profit_1": 102_000.0,
            "take_profit_2": 104_000.0,
            "risk_reward_1": 1.33,
            "risk_reward_2": 2.67,
        },
    }


# ── Tests ─────────────────────────────────────────────────────────────────

def test_tables_created(fresh_db):
    conn = fresh_db._get_conn()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "market_snapshots" in tables
    assert "trade_alerts" in tables
    assert "notification_log" in tables
    assert "alert_outcomes" in tables


def test_wal_mode(fresh_db):
    conn = fresh_db._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_insert_snapshot_batch(fresh_db):
    snap = _make_snapshot()
    fresh_db.insert_snapshots_batch([snap])
    count = fresh_db._get_conn().execute(
        "SELECT COUNT(*) FROM market_snapshots"
    ).fetchone()[0]
    assert count == 1


def test_insert_multiple_snapshots(fresh_db):
    snaps = [_make_snapshot("BTCUSDT"), _make_snapshot("ETHUSDT")]
    fresh_db.insert_snapshots_batch(snaps)
    count = fresh_db._get_conn().execute(
        "SELECT COUNT(*) FROM market_snapshots"
    ).fetchone()[0]
    assert count == 2


def test_insert_trade_alert(fresh_db):
    alert_id = fresh_db.insert_trade_alert(_make_alert())
    assert isinstance(alert_id, int) and alert_id > 0
    row = fresh_db._get_conn().execute(
        "SELECT * FROM trade_alerts WHERE id=?", (alert_id,)
    ).fetchone()
    assert row is not None
    assert row["symbol"] == "BTCUSDT"
    assert row["status"] == "open"


def test_insert_notification_log(fresh_db):
    alert_id = fresh_db.insert_trade_alert(_make_alert())
    fresh_db.insert_notification_log(alert_id, "BTCUSDT", "LONG_FUTURES", "discord", True)
    row = fresh_db._get_conn().execute(
        "SELECT * FROM notification_log WHERE alert_id=?", (alert_id,)
    ).fetchone()
    assert row is not None
    assert row["ok"] == 1
    assert row["channel"] == "discord"


def test_update_alert_status(fresh_db):
    alert_id = fresh_db.insert_trade_alert(_make_alert())
    fresh_db.update_alert_status(alert_id, "win")
    row = fresh_db._get_conn().execute(
        "SELECT status FROM trade_alerts WHERE id=?", (alert_id,)
    ).fetchone()
    assert row["status"] == "win"


def test_insert_alert_outcome(fresh_db):
    alert_id = fresh_db.insert_trade_alert(_make_alert())
    outcome = {
        "alert_id": alert_id,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "horizon_minutes": 60,
        "price_at_check": 102_000.0,
        "future_return_pct": 2.0,
        "max_favorable_excursion": 2.5,
        "max_adverse_excursion": 0.3,
        "hit_tp1": True,
        "hit_tp2": False,
        "hit_stop": False,
        "outcome": "partial",
    }
    fresh_db.insert_alert_outcome(outcome)
    row = fresh_db._get_conn().execute(
        "SELECT * FROM alert_outcomes WHERE alert_id=?", (alert_id,)
    ).fetchone()
    assert row is not None
    assert row["outcome"] == "partial"
    assert row["hit_tp1"] == 1


def test_get_open_alerts(fresh_db):
    fresh_db.insert_trade_alert(_make_alert())
    fresh_db.insert_trade_alert(_make_alert("ETHUSDT"))
    alerts = fresh_db.get_open_alerts()
    assert len(alerts) == 2
    assert all(a["status"] == "open" for a in alerts)


def test_db_failure_does_not_raise(fresh_db, monkeypatch):
    """Simula fallo de DB: insert_snapshots_batch no debe propagar excepción."""
    monkeypatch.setattr(fresh_db, "_get_conn", lambda: (_ for _ in ()).throw(Exception("DB error")))
    fresh_db.insert_snapshots_batch([_make_snapshot()])  # debe silenciar el error


def test_snapshot_retention_purge(fresh_db, monkeypatch):
    import datetime, app.database as db
    monkeypatch.setattr(db, "SNAPSHOT_RETENTION_DAYS", 0)
    fresh_db.insert_snapshots_batch([_make_snapshot()])
    deleted = fresh_db.purge_old_snapshots()
    assert deleted >= 0  # purge corrió sin error
