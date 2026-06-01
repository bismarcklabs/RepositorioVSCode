"""Tests para app/ml_dataset.py."""
import os
import tempfile
import time

import pytest


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    """Crea una DB temporal con snapshots y alertas de prueba."""
    db_file = str(tmp_path / "test_ml.sqlite3")
    monkeypatch.setenv("DATABASE_PATH", db_file)
    import app.database as db
    monkeypatch.setattr(db, "DATABASE_PATH", db_file)
    monkeypatch.setattr(db, "_db_initialized", False)
    if hasattr(db._db_local, "conn") and db._db_local.conn:
        db._db_local.conn.close()
        db._db_local.conn = None
    db.init_db()

    # Insertar snapshots sintéticos
    snaps = []
    for i in range(10):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - (10 - i) * 60))
        snaps.append({
            "timestamp": ts,
            "symbol": "BTCUSDT",
            "price": 100_000.0 + i * 100,
            "futures_price": 100_050.0,
            "recommendation": {
                "action": "LONG_FUTURES" if i % 2 == 0 else "WAIT",
                "market": "FUTURES",
                "confidence": 70 + i,
                "risk_level": "low",
                "setup": {
                    "entry": 100_000.0, "entry_zone_low": 99_900.0,
                    "entry_zone_high": 100_100.0, "stop_loss": 98_500.0,
                    "take_profit_1": 102_000.0, "take_profit_2": 104_000.0,
                    "risk_reward_1": 1.33, "risk_reward_2": 2.67,
                } if i % 2 == 0 else None,
                "reasons": ["CVD positivo"], "warnings": [], "invalidation": [],
            },
            "signal": {"signal": "accumulation" if i < 7 else "short_squeeze"},
            "score_data": {"score": 70 + i, "gex_score": 3},
            "metrics": {"delta": float(i), "cvd": float(i * 100),
                        "buy_volume": 100.0, "sell_volume": 90.0},
            "funding": 0.0001, "open_interest": 5_000_000.0,
            "orderbook": {"imbalance": 0.1, "spread_pct": 0.02},
            "technical": {"return_15m": 0.2, "return_1h": 0.8,
                          "vwap": 99_800.0, "vwap_distance_pct": 0.2,
                          "above_vwap": True, "relative_volume": 1.2, "trend_bias": "bullish"},
            "volume_profile": {"poc": 99_700.0, "nearest_level": 99_700.0,
                               "nearest_level_type": "POC", "distance_to_level_pct": 0.3},
            "footprint": {"footprint_delta": float(i), "absorption_buy": False,
                          "absorption_sell": False, "stacked_buy_imbalance": False,
                          "stacked_sell_imbalance": False},
            "gex": {"call_wall": 105_000.0, "put_wall": 95_000.0, "gamma_flip": 100_500.0},
        })
    db.insert_snapshots_batch(snaps)
    import app.ml_dataset as mld
    monkeypatch.setattr(mld, "DATABASE_PATH", db_file)
    return db, tmp_path, mld


def test_export_returns_row_count(populated_db):
    _, tmp_path, mld = populated_db
    out_csv = str(tmp_path / "out.csv")
    n = mld.export_training_dataset(out_csv)
    assert n == 10


def test_export_creates_csv(populated_db):
    _, tmp_path, mld = populated_db
    out_csv = str(tmp_path / "out.csv")
    mld.export_training_dataset(out_csv)
    assert os.path.exists(out_csv)


def test_export_csv_has_feature_cols(populated_db):
    import csv
    _, tmp_path, mld = populated_db
    out_csv = str(tmp_path / "out.csv")
    mld.export_training_dataset(out_csv)
    with open(out_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    assert "cvd" in headers
    assert "delta" in headers
    assert "funding" in headers
    assert "signal" in headers
    assert "action" in headers


def test_derived_features_present(populated_db):
    import csv
    _, tmp_path, mld = populated_db
    out_csv = str(tmp_path / "out.csv")
    mld.export_training_dataset(out_csv)
    with open(out_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
    assert "cvd_slope_5" in headers
    assert "delta_ma_5" in headers
    assert "squeeze_label" in headers
    assert "anomaly_candidate" in headers


def test_squeeze_label_set(populated_db):
    import csv
    _, tmp_path, mld = populated_db
    out_csv = str(tmp_path / "out.csv")
    mld.export_training_dataset(out_csv)
    with open(out_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    squeeze_rows = [r for r in rows if r["squeeze_label"] == "1"]
    assert len(squeeze_rows) > 0  # los últimos 3 snaps tienen short_squeeze


def test_build_features_and_labels_returns_list(populated_db):
    _, _, mld = populated_db
    rows = mld.build_features_and_labels(horizon_minutes=60)
    assert isinstance(rows, list)
    assert len(rows) == 10


def test_export_empty_db_returns_zero(tmp_path, monkeypatch):
    db_file = str(tmp_path / "empty.sqlite3")
    monkeypatch.setenv("DATABASE_PATH", db_file)
    import app.database as db
    monkeypatch.setattr(db, "DATABASE_PATH", db_file)
    monkeypatch.setattr(db, "_db_initialized", False)
    if hasattr(db._db_local, "conn") and db._db_local.conn:
        db._db_local.conn.close()
        db._db_local.conn = None
    db.init_db()
    import app.ml_dataset as mld
    monkeypatch.setattr(mld, "DATABASE_PATH", db_file)
    n = mld.export_training_dataset(str(tmp_path / "empty.csv"))
    assert n == 0
