"""Tests para app/snapshot_backfill.py."""
import datetime as dt
import os
import tempfile

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


def _make_kline(open_ms, close, volume=1000.0, taker_buy=600.0):
    # Formato crudo de Binance: [open_time, open, high, low, close, volume,
    # close_time, quote_vol, n_trades, taker_buy_base_vol, taker_buy_quote_vol, ignore]
    return [open_ms, close, close, close, close, volume, open_ms + 59_999,
            volume * close, 10, taker_buy, taker_buy * close, "0"]


class TestDeltaProxy:
    def test_more_buying_than_selling_gives_positive_delta(self):
        from app.snapshot_backfill import _delta_proxy
        k = _make_kline(0, 100.0, volume=1000.0, taker_buy=700.0)
        assert _delta_proxy(k) == pytest.approx(2 * 700.0 - 1000.0)

    def test_balanced_volume_gives_zero_delta(self):
        from app.snapshot_backfill import _delta_proxy
        k = _make_kline(0, 100.0, volume=1000.0, taker_buy=500.0)
        assert _delta_proxy(k) == pytest.approx(0.0)

    def test_more_selling_than_buying_gives_negative_delta(self):
        from app.snapshot_backfill import _delta_proxy
        k = _make_kline(0, 100.0, volume=1000.0, taker_buy=200.0)
        assert _delta_proxy(k) == pytest.approx(2 * 200.0 - 1000.0)


class TestRollingSum:
    def test_window_larger_than_series_sums_everything(self):
        from app.snapshot_backfill import _rolling_sum
        assert _rolling_sum([1.0, 2.0, 3.0], window=10) == [1.0, 3.0, 6.0]

    def test_window_caps_at_trailing_n_elements(self):
        from app.snapshot_backfill import _rolling_sum
        # ventana de 2: cada posicion suma solo el valor actual + el anterior
        assert _rolling_sum([1.0, 2.0, 3.0, 4.0], window=2) == [1.0, 3.0, 5.0, 7.0]


class TestBackfillSnapshotGaps:
    def test_no_prior_history_is_a_noop(self, fresh_db, monkeypatch):
        from app import snapshot_backfill as sb
        called = {"n": 0}
        monkeypatch.setattr(sb.market_data, "get_klines", lambda *a, **k: called.update(n=called["n"] + 1) or [])
        sb.backfill_snapshot_gaps()
        assert called["n"] == 0

    def test_small_gap_below_threshold_is_skipped(self, fresh_db, monkeypatch):
        from app import database, snapshot_backfill as sb

        recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S")
        database.insert_snapshots_batch([{
            "timestamp": recent, "symbol": "BTCUSDT", "price": 100.0, "futures_price": 100.0,
            "score_data": {"score": 90}, "recommendation": {"action": "WAIT"},
        }])

        called = {"n": 0}
        monkeypatch.setattr(sb.market_data, "get_klines", lambda *a, **k: called.update(n=called["n"] + 1) or [])
        sb.backfill_snapshot_gaps()
        assert called["n"] == 0   # gap < _MIN_GAP_MINUTES, no deberia pedir klines

    def test_ancient_gap_beyond_max_window_is_skipped(self, fresh_db, monkeypatch):
        from app import database, snapshot_backfill as sb

        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
        database.insert_snapshots_batch([{
            "timestamp": old, "symbol": "OLDUSDT", "price": 1.0, "futures_price": 1.0,
            "score_data": {"score": 90}, "recommendation": {"action": "WAIT"},
        }])

        called = {"n": 0}
        monkeypatch.setattr(sb.market_data, "get_klines", lambda *a, **k: called.update(n=called["n"] + 1) or [])
        sb.backfill_snapshot_gaps()
        assert called["n"] == 0   # demasiado viejo/abandonado, no vale la pena reconstruir

    def test_real_gap_backfills_price_and_delta_proxy(self, fresh_db, monkeypatch):
        from app import database, snapshot_backfill as sb

        last_dt = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
        last_ts = last_dt.strftime("%Y-%m-%dT%H:%M:%S")
        database.insert_snapshots_batch([{
            "timestamp": last_ts, "symbol": "ETHUSDT", "price": 2000.0, "futures_price": 2000.0,
            "score_data": {"score": 90}, "recommendation": {"action": "WAIT"},
        }])

        start_ms = int(last_dt.timestamp() * 1000) + 60_000
        klines = [_make_kline(start_ms + i * 60_000, 2000.0 + i, volume=1000.0, taker_buy=700.0)
                  for i in range(5)]
        monkeypatch.setattr(sb.market_data, "get_klines", lambda *a, **k: klines)

        sb.backfill_snapshot_gaps()

        rows = database._get_conn().execute(
            "SELECT price, delta, is_backfilled FROM market_snapshots "
            "WHERE symbol='ETHUSDT' AND is_backfilled=1 ORDER BY timestamp"
        ).fetchall()
        assert len(rows) == 5
        assert rows[0]["price"] == pytest.approx(2000.0)
        assert rows[0]["delta"] == pytest.approx(2 * 700.0 - 1000.0)
        assert all(r["is_backfilled"] == 1 for r in rows)

    def test_backfilled_rows_bypass_snapshot_min_score_filter(self, fresh_db, monkeypatch):
        """insert_backfilled_snapshots no debe filtrar por SNAPSHOT_MIN_SCORE —
        estas filas tienen score=0 (WAIT) por construccion y aun asi deben
        insertarse, a diferencia de insert_snapshots_batch."""
        from app import database, snapshot_backfill as sb

        last_dt = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        database.insert_snapshots_batch([{
            "timestamp": last_dt.strftime("%Y-%m-%dT%H:%M:%S"), "symbol": "SOLUSDT",
            "price": 150.0, "futures_price": 150.0,
            "score_data": {"score": 90}, "recommendation": {"action": "WAIT"},
        }])
        start_ms = int(last_dt.timestamp() * 1000) + 60_000
        klines = [_make_kline(start_ms, 150.0, volume=500.0, taker_buy=250.0)]
        monkeypatch.setattr(sb.market_data, "get_klines", lambda *a, **k: klines)

        sb.backfill_snapshot_gaps()

        n = database._get_conn().execute(
            "SELECT COUNT(*) c FROM market_snapshots WHERE symbol='SOLUSDT' AND is_backfilled=1"
        ).fetchone()["c"]
        assert n == 1
