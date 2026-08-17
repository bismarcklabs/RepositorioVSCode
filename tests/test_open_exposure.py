"""Tests para database.get_symbols_with_open_exposure() — símbolos con
posición abierta en cualquiera de los 3 sistemas de trading, usados por
run_scanner.py para forzar continuidad de escaneo aunque salgan del top
de volumen."""
import os
import tempfile
import time

import pytest

_TMP_DB = tempfile.mktemp(suffix=".sqlite3")
os.environ.setdefault("DATABASE_PATH", _TMP_DB)
os.environ.setdefault("ENABLE_DATABASE", "true")


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


def _make_micro_alert(sym):
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "symbol": sym, "action": "MICRO_LONG_SCALP", "score": 82, "confidence": 85,
        "setup": {"entry": 100.0, "take_profit_1": 100.3, "take_profit_2": 100.6,
                  "stop_loss": 99.75, "timeout_minutes": 10},
        "technical": {"return_3m": 0.12, "return_5m": 0.25, "relative_volume": 2.5},
        "metrics": {"delta": 100, "cvd_15m": 300},
        "footprint": {"footprint_delta": 80},
        "orderbook": {"imbalance": 0.2},
        "oi_change_pct": 1.5, "funding": 0.0001, "reasons": [], "warnings": [],
    }


class TestGetSymbolsWithOpenExposure:
    def test_no_open_positions_returns_empty(self, fresh_db):
        assert fresh_db.get_symbols_with_open_exposure() == []

    def test_open_auto_position_is_included(self, fresh_db):
        fresh_db.insert_auto_position({
            "alert_id": None, "symbol": "AAAUSDT", "action": "LONG_FUTURES", "mode": "paper",
            "open_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "entry_price": 1.0, "size_usdt": 10.0, "leverage": 3,
            "tp1": 1.1, "tp2": 1.2, "sl": 0.9, "sl_current": 0.9,
        })
        assert fresh_db.get_symbols_with_open_exposure() == ["AAAUSDT"]

    def test_open_micro_scalp_alert_is_included(self, fresh_db):
        fresh_db.insert_micro_scalp_alert(_make_micro_alert("BBBUSDT"))
        assert fresh_db.get_symbols_with_open_exposure() == ["BBBUSDT"]

    def test_open_strategy_position_is_included(self, fresh_db):
        fresh_db.insert_strategy_position({
            "alert_id": None, "strategy_id": "agile_futures", "symbol": "CCCUSDT",
            "direction": "LONG", "mode": "paper",
            "open_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "entry_price": 1.0, "size_usdt": 10.0, "leverage": 3, "timeout_hours": 1.5,
            "tp1": 1.1, "tp2": 1.2, "sl": 0.9, "sl_current": 0.9,
        })
        assert fresh_db.get_symbols_with_open_exposure() == ["CCCUSDT"]

    def test_dedupes_symbol_across_systems_and_sorts(self, fresh_db):
        fresh_db.insert_auto_position({
            "alert_id": None, "symbol": "ZZZUSDT", "action": "LONG_FUTURES", "mode": "paper",
            "open_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "entry_price": 1.0, "size_usdt": 10.0, "leverage": 3,
            "tp1": 1.1, "tp2": 1.2, "sl": 0.9, "sl_current": 0.9,
        })
        fresh_db.insert_micro_scalp_alert(_make_micro_alert("ZZZUSDT"))
        fresh_db.insert_strategy_position({
            "alert_id": None, "strategy_id": "agile_futures", "symbol": "AAAUSDT",
            "direction": "LONG", "mode": "paper",
            "open_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "entry_price": 1.0, "size_usdt": 10.0, "leverage": 3, "timeout_hours": 1.5,
            "tp1": 1.1, "tp2": 1.2, "sl": 0.9, "sl_current": 0.9,
        })
        assert fresh_db.get_symbols_with_open_exposure() == ["AAAUSDT", "ZZZUSDT"]

    def test_closed_positions_are_excluded(self, fresh_db):
        pos_id = fresh_db.insert_auto_position({
            "alert_id": None, "symbol": "DDDUSDT", "action": "LONG_FUTURES", "mode": "paper",
            "open_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "entry_price": 1.0, "size_usdt": 10.0, "leverage": 3,
            "tp1": 1.1, "tp2": 1.2, "sl": 0.9, "sl_current": 0.9,
        })
        fresh_db.close_auto_position(pos_id, 1.1, "tp1_only", 1.0, 1.0, 10.0)
        assert fresh_db.get_symbols_with_open_exposure() == []
