"""Tests para app/accumulation_scanner.py (Accumulation Watch)."""
import os
import time

import pytest

os.environ.setdefault("ENABLE_DATABASE", "true")
os.environ.setdefault("SNAPSHOT_RETENTION_DAYS", "90")

DAY_MS = 86_400_000


def _make_daily_klines(
    n,
    base_high, base_low, base_close,
    recent_high=None, recent_low=None, recent_close=None,
    recent_days=14, volume=1000.0, recent_volume=None,
):
    """Genera `n` velas diarias: las primeras `n - recent_days` usan los
    valores `base_*`, las últimas `recent_days` usan los valores `recent_*`
    (si no se especifican, igual a los `base_*`)."""
    recent_high = base_high if recent_high is None else recent_high
    recent_low = base_low if recent_low is None else recent_low
    recent_close = base_close if recent_close is None else recent_close
    recent_volume = volume if recent_volume is None else recent_volume

    klines = []
    for i in range(n):
        ts = i * DAY_MS
        if i >= n - recent_days:
            high, low, close, vol = recent_high, recent_low, recent_close, recent_volume
        else:
            high, low, close, vol = base_high, base_low, base_close, volume
        klines.append([ts, close, high, low, close, vol, ts + DAY_MS - 1, "0", 1, "0", "0", "0"])
    return klines


# ── compute_coiling_metrics ─────────────────────────────────────────────────

def test_compute_coiling_metrics_insufficient_data_returns_none():
    from app.accumulation_scanner import compute_coiling_metrics
    assert compute_coiling_metrics([]) is None
    assert compute_coiling_metrics(_make_daily_klines(30, 110, 90, 100)) is None


def test_extreme_contraction_near_range_low_is_valid_without_above_sma50():
    """Caso HOME/ID/LAB: contracción extrema cerca de mínimos del rango es
    señal fuerte por sí sola, sin requerir estar sobre la SMA50."""
    from app.accumulation_scanner import compute_coiling_metrics, ACCUMULATION_COILING_SCORE_THRESHOLD
    klines = _make_daily_klines(
        n=90,
        base_high=160, base_low=140, base_close=150,
        recent_high=102, recent_low=100, recent_close=100,
        recent_days=14,
    )
    result = compute_coiling_metrics(klines)
    assert result is not None
    assert result["contraction_ratio"] < 0.2
    assert result["position_in_range"] <= 0.15
    assert result["above_sma50"] is False
    assert result["coiling_score"] >= ACCUMULATION_COILING_SCORE_THRESHOLD


def test_normal_volatility_near_range_top_is_not_a_candidate():
    from app.accumulation_scanner import compute_coiling_metrics, ACCUMULATION_COILING_SCORE_THRESHOLD
    klines = _make_daily_klines(
        n=90,
        base_high=105, base_low=95, base_close=100,
        recent_high=105, recent_low=95, recent_close=104,
        recent_days=14,
    )
    result = compute_coiling_metrics(klines)
    assert result is not None
    assert result["contraction_ratio"] >= 0.8   # sin contracción
    assert result["position_in_range"] > 0.6     # cerca del techo del rango
    assert result["coiling_score"] < ACCUMULATION_COILING_SCORE_THRESHOLD


# ── check_ignition_trigger ───────────────────────────────────────────────────

def test_ignition_trigger_on_volume_spike():
    from app.accumulation_scanner import check_ignition_trigger
    watch_entry = {"funding_at_watch": 0.0001}
    reason = check_ignition_trigger(watch_entry, {"relative_volume": 3.0}, 0.0001)
    assert reason is not None
    assert "relative_volume" in reason


def test_ignition_trigger_on_funding_cross_zero():
    """Caso HOME/ID/STO: funding cae de positivo a negativo (short squeeze)."""
    from app.accumulation_scanner import check_ignition_trigger
    watch_entry = {"funding_at_watch": 0.0005}
    reason = check_ignition_trigger(watch_entry, {"relative_volume": 1.0}, -0.0002)
    assert reason is not None
    assert "funding" in reason


def test_no_ignition_trigger_when_nothing_changed():
    from app.accumulation_scanner import check_ignition_trigger
    watch_entry = {"funding_at_watch": 0.0001}
    reason = check_ignition_trigger(watch_entry, {"relative_volume": 1.2}, 0.0001)
    assert reason is None


# ── get_extended_universe / scan_accumulation_candidates ────────────────────

def test_get_universe_filters_volume_and_blacklist(monkeypatch):
    import app.accumulation_scanner as acc

    tickers = [
        {"symbol": "ABCUSDT", "quoteVolume": "3000000", "priceChangePercent": "5"},
        {"symbol": "BIGUSDT", "quoteVolume": "60000000", "priceChangePercent": "2"},
        {"symbol": "TINYUSDT", "quoteVolume": "500000", "priceChangePercent": "1"},
        {"symbol": "USDCUSDT", "quoteVolume": "3000000", "priceChangePercent": "0"},
        {"symbol": "ABCBUSD", "quoteVolume": "3000000", "priceChangePercent": "1"},
    ]
    monkeypatch.setattr(acc, "get_futures_ticker_all", lambda: tickers)
    monkeypatch.setattr(acc, "get_premium_index_all", lambda: [{"symbol": "ABCUSDT", "lastFundingRate": "0.0002"}])

    universe = acc.get_extended_universe(2_000_000)
    symbols = {u["symbol"] for u in universe}
    assert symbols == {"ABCUSDT"}
    assert universe[0]["funding_rate"] == pytest.approx(0.0002)


def test_scan_accumulation_candidates(monkeypatch):
    import app.accumulation_scanner as acc

    tickers = [{"symbol": "ABCUSDT", "quoteVolume": "3000000", "priceChangePercent": "5"}]
    monkeypatch.setattr(acc, "get_futures_ticker_all", lambda: tickers)
    monkeypatch.setattr(acc, "get_premium_index_all", lambda: [])

    coiling_klines = _make_daily_klines(
        n=90, base_high=160, base_low=140, base_close=150,
        recent_high=102, recent_low=100, recent_close=100, recent_days=14,
    )
    monkeypatch.setattr(acc, "get_klines", lambda symbol, interval="1d", limit=90: coiling_klines)

    candidates = acc.scan_accumulation_candidates(min_quote_vol=2_000_000, score_threshold=45)
    assert len(candidates) == 1
    assert candidates[0]["symbol"] == "ABCUSDT"
    assert candidates[0]["coiling_score"] >= 45


def test_scan_accumulation_candidates_excludes_below_threshold(monkeypatch):
    import app.accumulation_scanner as acc

    tickers = [{"symbol": "ABCUSDT", "quoteVolume": "3000000", "priceChangePercent": "5"}]
    monkeypatch.setattr(acc, "get_futures_ticker_all", lambda: tickers)
    monkeypatch.setattr(acc, "get_premium_index_all", lambda: [])

    flat_klines = _make_daily_klines(
        n=90, base_high=105, base_low=95, base_close=100,
        recent_high=105, recent_low=95, recent_close=104, recent_days=14,
    )
    monkeypatch.setattr(acc, "get_klines", lambda symbol, interval="1d", limit=90: flat_klines)

    candidates = acc.scan_accumulation_candidates(min_quote_vol=2_000_000, score_threshold=45, breakout_enabled=False)
    assert candidates == []


# ── _classify_channel / canal volatility_breakout ────────────────────────────

def test_classify_channel_coiling_takes_priority(monkeypatch):
    from app.accumulation_scanner import _classify_channel
    metrics = {"coiling_score": 60.0, "contraction_ratio": 0.15}
    channel, score = _classify_channel(metrics, coiling_threshold=45, breakout_ratio=2.5)
    assert channel == "coiling"
    assert score == pytest.approx(60.0)


def test_classify_channel_volatility_breakout_when_expanding():
    from app.accumulation_scanner import _classify_channel
    metrics = {"coiling_score": 10.0, "contraction_ratio": 3.0}
    channel, score = _classify_channel(metrics, coiling_threshold=45, breakout_ratio=2.5)
    assert channel == "volatility_breakout"
    assert score > 0


def test_classify_channel_none_when_neither_qualifies():
    from app.accumulation_scanner import _classify_channel
    metrics = {"coiling_score": 10.0, "contraction_ratio": 1.0}
    assert _classify_channel(metrics, coiling_threshold=45, breakout_ratio=2.5) is None


def test_classify_channel_breakout_disabled_returns_none():
    from app.accumulation_scanner import _classify_channel
    metrics = {"coiling_score": 10.0, "contraction_ratio": 5.0}
    result = _classify_channel(metrics, coiling_threshold=45, breakout_ratio=2.5, breakout_enabled=False)
    assert result is None


def test_scan_accumulation_candidates_includes_volatility_breakout(monkeypatch):
    import app.accumulation_scanner as acc

    tickers = [{"symbol": "EXPUSDT", "quoteVolume": "3000000", "priceChangePercent": "5"}]
    monkeypatch.setattr(acc, "get_futures_ticker_all", lambda: tickers)
    monkeypatch.setattr(acc, "get_premium_index_all", lambda: [])

    # Expansion: ATR reciente muy por encima del ATR base (contraction_ratio
    # alto) pero SIN los bonos de coiling (cierre bajo su propia SMA50 y
    # volumen reciente bajo) — para que quede claro que el canal se decide
    # por contraction_ratio, no porque también cruce el umbral de coiling.
    expanding_klines = _make_daily_klines(
        n=90, base_high=101, base_low=99, base_close=100, volume=1000.0,
        recent_high=140, recent_low=60, recent_close=70, recent_days=14,
        recent_volume=200.0,
    )
    monkeypatch.setattr(acc, "get_klines", lambda symbol, interval="1d", limit=90: expanding_klines)

    candidates = acc.scan_accumulation_candidates(
        min_quote_vol=2_000_000, score_threshold=45, breakout_ratio=2.5, breakout_enabled=True,
    )
    assert len(candidates) == 1
    assert candidates[0]["symbol"] == "EXPUSDT"
    assert candidates[0]["channel"] == "volatility_breakout"
    assert candidates[0]["channel_score"] > 0


# ── DB layer (accumulation_watch table) ─────────────────────────────────────

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


def _watch_payload(symbol="ABCUSDT", **overrides):
    payload = {
        "symbol": symbol,
        "coiling_score": 60.0,
        "contraction_ratio": 0.15,
        "position_in_range": 0.1,
        "above_sma50": False,
        "vol_ratio_7_30": 1.5,
        "quote_volume": 3_000_000.0,
        "funding_at_watch": 0.0003,
        "price_at_watch": 1.234,
    }
    payload.update(overrides)
    return payload


def test_upsert_and_query_accumulation_watch(fresh_db):
    db = fresh_db
    db.upsert_accumulation_watch(_watch_payload())

    assert db.get_accumulation_watchlist_symbols(10) == ["ABCUSDT"]

    watch_map = db.get_accumulation_watch_map()
    assert "ABCUSDT" in watch_map
    assert watch_map["ABCUSDT"]["status"] == "watching"
    assert watch_map["ABCUSDT"]["funding_at_watch"] == pytest.approx(0.0003)


def test_upsert_preserves_baseline_on_rescan(fresh_db):
    db = fresh_db
    db.upsert_accumulation_watch(_watch_payload(coiling_score=50.0, funding_at_watch=0.0005, price_at_watch=1.0))
    # Re-scan: las métricas de coiling cambian, pero la línea base
    # (funding_at_watch/price_at_watch/first_seen) debe persistir.
    db.upsert_accumulation_watch(_watch_payload(coiling_score=65.0, funding_at_watch=-0.0002, price_at_watch=1.5))

    entry = db.get_accumulation_watch_map()["ABCUSDT"]
    assert entry["coiling_score"] == pytest.approx(65.0)
    assert entry["funding_at_watch"] == pytest.approx(0.0005)
    assert entry["price_at_watch"] == pytest.approx(1.0)


def test_mark_ignited_keeps_symbol_in_watchlist(fresh_db):
    db = fresh_db
    db.upsert_accumulation_watch(_watch_payload())
    db.mark_accumulation_ignited("ABCUSDT", "relative_volume 3.0x >= 2.5x")

    watch_map = db.get_accumulation_watch_map()
    assert watch_map["ABCUSDT"]["status"] == "ignited"
    assert "relative_volume" in watch_map["ABCUSDT"]["ignition_reason"]
    # Símbolos ignited siguen en la fast-cycle watchlist (la oportunidad ya está activa)
    assert "ABCUSDT" in db.get_accumulation_watchlist_symbols(10)


def test_upsert_does_not_revert_ignited_status(fresh_db):
    db = fresh_db
    db.upsert_accumulation_watch(_watch_payload())
    db.mark_accumulation_ignited("ABCUSDT", "relative_volume 3.0x >= 2.5x")

    # Un nuevo scan no debe regresar el estado a 'watching'
    db.upsert_accumulation_watch(_watch_payload(coiling_score=70.0))
    assert db.get_accumulation_watch_map()["ABCUSDT"]["status"] == "ignited"


def test_expire_stale_watch_entries(fresh_db):
    db = fresh_db
    db.upsert_accumulation_watch(_watch_payload(symbol="OLDUSDT"))

    conn = db._get_conn()
    old_ts = db._ts_to_iso(time.time() - 100 * 3600)
    conn.execute("UPDATE accumulation_watch SET last_scan=? WHERE symbol='OLDUSDT'", (old_ts,))
    conn.commit()

    expired = db.expire_stale_accumulation_watch(48.0)
    assert expired == 1
    assert db.get_accumulation_watchlist_symbols(10) == []


# ── run_accumulation_scan (integración) ──────────────────────────────────────

def test_run_accumulation_scan_persists_candidates(fresh_db, monkeypatch):
    import app.accumulation_scanner as acc

    tickers = [{"symbol": "ABCUSDT", "quoteVolume": "3000000", "priceChangePercent": "5"}]
    monkeypatch.setattr(acc, "get_futures_ticker_all", lambda: tickers)
    monkeypatch.setattr(acc, "get_premium_index_all", lambda: [{"symbol": "ABCUSDT", "lastFundingRate": "0.0004"}])

    coiling_klines = _make_daily_klines(
        n=90, base_high=160, base_low=140, base_close=150,
        recent_high=102, recent_low=100, recent_close=100, recent_days=14,
    )
    monkeypatch.setattr(acc, "get_klines", lambda symbol, interval="1d", limit=90: coiling_klines)

    candidates = acc.run_accumulation_scan()
    assert len(candidates) == 1

    watch_map = fresh_db.get_accumulation_watch_map()
    assert "ABCUSDT" in watch_map
    assert watch_map["ABCUSDT"]["funding_at_watch"] == pytest.approx(0.0004)
    assert watch_map["ABCUSDT"]["channel"] == "coiling"


# ── channel/channel_score genericos (watchlist multi-canal) ─────────────────

def test_upsert_defaults_to_coiling_channel(fresh_db):
    fresh_db.upsert_accumulation_watch(_watch_payload(coiling_score=55.0))
    entry = fresh_db.get_accumulation_watch_map()["ABCUSDT"]
    assert entry["channel"] == "coiling"
    assert entry["channel_score"] == pytest.approx(55.0)


def test_upsert_stores_custom_channel_and_metrics(fresh_db):
    fresh_db.upsert_accumulation_watch(_watch_payload(
        symbol="FUNUSDT", channel="funding_extreme", channel_score=42.0,
        metrics={"funding_rate": 0.0042},
    ))
    entry = fresh_db.get_accumulation_watch_map()["FUNUSDT"]
    assert entry["channel"] == "funding_extreme"
    assert entry["channel_score"] == pytest.approx(42.0)
    assert '"funding_rate": 0.0042' in entry["metrics_json"]


def test_watchlist_orders_by_channel_score_across_channels(fresh_db):
    fresh_db.upsert_accumulation_watch(_watch_payload(
        symbol="LOWUSDT", channel="coiling", channel_score=20.0,
    ))
    fresh_db.upsert_accumulation_watch(_watch_payload(
        symbol="HIGHUSDT", channel="oi_acceleration", channel_score=90.0,
    ))
    assert fresh_db.get_accumulation_watchlist_symbols(10) == ["HIGHUSDT", "LOWUSDT"]
