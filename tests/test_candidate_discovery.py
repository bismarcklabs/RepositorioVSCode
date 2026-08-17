"""Tests para app/candidate_discovery.py (canales funding_extreme y
oi_acceleration de la watchlist multi-canal, ver accumulation_watch)."""
import os
import time

import pytest

os.environ.setdefault("ENABLE_DATABASE", "true")
os.environ.setdefault("SNAPSHOT_RETENTION_DAYS", "90")


@pytest.fixture
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


# ── scan_funding_extreme_candidates ──────────────────────────────────────────

def test_funding_extreme_filters_by_threshold(monkeypatch):
    import app.candidate_discovery as cd

    universe = [
        {"symbol": "EXTREMEUSDT", "quote_volume": 3_000_000.0, "funding_rate": 0.005},
        {"symbol": "NORMALUSDT", "quote_volume": 3_000_000.0, "funding_rate": 0.0001},
        {"symbol": "NEGEXTUSDT", "quote_volume": 3_000_000.0, "funding_rate": -0.006},
    ]
    monkeypatch.setattr(cd, "get_extended_universe", lambda min_vol: universe)

    candidates = cd.scan_funding_extreme_candidates(min_quote_vol=2_000_000, threshold=0.003)
    symbols = {c["symbol"] for c in candidates}
    assert symbols == {"EXTREMEUSDT", "NEGEXTUSDT"}
    # ordenado de mayor a menor channel_score (funding absoluto mayor primero)
    assert candidates[0]["symbol"] == "NEGEXTUSDT"
    assert all(c["channel"] == "funding_extreme" for c in candidates)


def test_funding_extreme_empty_universe_returns_empty(monkeypatch):
    import app.candidate_discovery as cd
    monkeypatch.setattr(cd, "get_extended_universe", lambda min_vol: [])
    assert cd.scan_funding_extreme_candidates(min_quote_vol=2_000_000, threshold=0.003) == []


# ── _oi_change_pct ────────────────────────────────────────────────────────

def test_oi_change_pct_computes_growth():
    from app.candidate_discovery import _oi_change_pct
    hist = [{"sumOpenInterest": "1000"}, {"sumOpenInterest": "1150"}]
    assert _oi_change_pct(hist) == pytest.approx(15.0)


def test_oi_change_pct_computes_decline():
    from app.candidate_discovery import _oi_change_pct
    hist = [{"sumOpenInterest": "1000"}, {"sumOpenInterest": "800"}]
    assert _oi_change_pct(hist) == pytest.approx(-20.0)


def test_oi_change_pct_insufficient_data_returns_none():
    from app.candidate_discovery import _oi_change_pct
    assert _oi_change_pct([{"sumOpenInterest": "1000"}]) is None
    assert _oi_change_pct([]) is None


def test_oi_change_pct_malformed_data_returns_none():
    from app.candidate_discovery import _oi_change_pct
    assert _oi_change_pct([{"sumOpenInterest": "0"}, {"sumOpenInterest": "100"}]) is None
    assert _oi_change_pct([{"foo": "bar"}, {"sumOpenInterest": "100"}]) is None


# ── scan_oi_acceleration_candidates ──────────────────────────────────────────

def test_oi_acceleration_filters_by_threshold(monkeypatch):
    import app.candidate_discovery as cd

    universe = [
        {"symbol": "ACCELUSDT", "quote_volume": 3_000_000.0, "funding_rate": 0.0001},
        {"symbol": "FLATUSDT", "quote_volume": 3_000_000.0, "funding_rate": 0.0001},
    ]
    monkeypatch.setattr(cd, "get_extended_universe", lambda min_vol: universe)

    def fake_get_oi_hist(symbol, period="1h", limit=24):
        if symbol == "ACCELUSDT":
            return [{"sumOpenInterest": "1000"}, {"sumOpenInterest": "1200"}]
        return [{"sumOpenInterest": "1000"}, {"sumOpenInterest": "1010"}]

    monkeypatch.setattr(cd, "get_open_interest_hist", fake_get_oi_hist)

    candidates = cd.scan_oi_acceleration_candidates(
        min_quote_vol=2_000_000, pct_threshold=15.0, lookback_hours=24,
    )
    assert len(candidates) == 1
    assert candidates[0]["symbol"] == "ACCELUSDT"
    assert candidates[0]["channel"] == "oi_acceleration"
    assert candidates[0]["oi_change_pct"] == pytest.approx(20.0)


def test_oi_acceleration_handles_fetch_errors_gracefully(monkeypatch):
    import app.candidate_discovery as cd

    universe = [{"symbol": "BROKENUSDT", "quote_volume": 3_000_000.0, "funding_rate": 0.0}]
    monkeypatch.setattr(cd, "get_extended_universe", lambda min_vol: universe)

    def raising_fetch(symbol, period="1h", limit=24):
        raise RuntimeError("network error")

    monkeypatch.setattr(cd, "get_open_interest_hist", raising_fetch)

    candidates = cd.scan_oi_acceleration_candidates(min_quote_vol=2_000_000, pct_threshold=15.0)
    assert candidates == []


# ── run_candidate_discovery_scan (integración) ───────────────────────────────

def test_run_candidate_discovery_scan_persists_both_channels(fresh_db, monkeypatch):
    import app.candidate_discovery as cd

    monkeypatch.setattr(cd, "ACCUMULATION_FUNDING_EXTREME_ENABLED", True)
    monkeypatch.setattr(cd, "ACCUMULATION_OI_ACCELERATION_ENABLED", True)

    monkeypatch.setattr(
        cd, "scan_funding_extreme_candidates",
        lambda: [{"symbol": "FUNUSDT", "quote_volume": 3_000_000.0,
                  "funding_rate": 0.005, "channel": "funding_extreme", "channel_score": 50.0}],
    )
    monkeypatch.setattr(
        cd, "scan_oi_acceleration_candidates",
        lambda: [{"symbol": "OIUSDT", "quote_volume": 3_000_000.0, "funding_rate": 0.0,
                  "oi_change_pct": 20.0, "channel": "oi_acceleration", "channel_score": 40.0}],
    )

    candidates = cd.run_candidate_discovery_scan()
    assert {c["symbol"] for c in candidates} == {"FUNUSDT", "OIUSDT"}

    watch_map = fresh_db.get_accumulation_watch_map()
    assert watch_map["FUNUSDT"]["channel"] == "funding_extreme"
    assert watch_map["OIUSDT"]["channel"] == "oi_acceleration"
    assert watch_map["OIUSDT"]["channel_score"] == pytest.approx(40.0)


def test_run_candidate_discovery_scan_respects_disabled_channels(fresh_db, monkeypatch):
    import app.candidate_discovery as cd

    monkeypatch.setattr(cd, "ACCUMULATION_FUNDING_EXTREME_ENABLED", False)
    monkeypatch.setattr(cd, "ACCUMULATION_OI_ACCELERATION_ENABLED", False)

    called = {"n": 0}
    monkeypatch.setattr(cd, "scan_funding_extreme_candidates", lambda: called.update(n=called["n"] + 1) or [])
    monkeypatch.setattr(cd, "scan_oi_acceleration_candidates", lambda: called.update(n=called["n"] + 1) or [])

    assert cd.run_candidate_discovery_scan() == []
    assert called["n"] == 0
