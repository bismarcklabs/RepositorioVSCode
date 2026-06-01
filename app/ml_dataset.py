"""Exportador de dataset para Machine Learning.

Genera un CSV con features históricas y labels derivadas del outcome tracker.

Features disponibles desde el día 1 (instantáneas):
    cvd, delta, buy_volume, sell_volume, funding, open_interest,
    imbalance, spread_pct, return_15m, return_1h, vwap_distance_pct,
    above_vwap, relative_volume, trend_bias, poc, vp_distance,
    footprint_delta, absorption_buy, absorption_sell,
    stacked_buy_imbalance, stacked_sell_imbalance,
    gex_available, gex_score, call_wall, put_wall, gamma_flip,
    score, confidence, signal, action

Features derivadas (requieren historial acumulado, calculadas aquí):
    cvd_slope_5  — pendiente del CVD en los últimos 5 snapshots del símbolo
    delta_ma_5   — media del delta en los últimos 5 snapshots

Labels (de alert_outcomes, solo para filas con alerta):
    future_return_1h, hit_tp1, hit_tp2, hit_stop, outcome
    squeeze_label    — 1 si signal in (short_squeeze, long_squeeze)
    anomaly_candidate — 1 si |cvd_zscore| > 2.5 (umbral heurístico)
"""

import csv
import logging
import sqlite3
from pathlib import Path
from typing import List, Optional

from app.config import DATABASE_PATH

logger = logging.getLogger("ml_dataset")

# Features que se exportan directamente desde market_snapshots
_FEATURE_COLS = [
    "timestamp", "symbol",
    # Flow
    "cvd", "delta", "buy_volume", "sell_volume",
    "funding", "open_interest", "imbalance", "spread_pct",
    # Technical
    "return_15m", "return_1h", "vwap", "vwap_distance_pct",
    "above_vwap", "relative_volume", "trend_bias",
    # VP
    "poc", "nearest_vp_type", "vp_distance",
    # Footprint
    "footprint_delta", "absorption_buy", "absorption_sell",
    "stacked_buy_imbalance", "stacked_sell_imbalance",
    # GEX
    "gex_available", "gex_score", "call_wall", "put_wall", "gamma_flip",
    # Score / signal
    "score", "confidence", "signal", "action",
    "price", "futures_price",
]

# Labels de outcome (LEFT JOIN con trade_alerts + alert_outcomes)
_LABEL_COLS = [
    "alert_id", "future_return_1h", "hit_tp1", "hit_tp2", "hit_stop", "outcome_1h",
]

# Columnas derivadas calculadas en Python
_DERIVED_COLS = ["cvd_slope_5", "delta_ma_5", "squeeze_label", "anomaly_candidate"]


def export_training_dataset(path: str = "data/ml_dataset.csv") -> int:
    """Exporta el dataset completo a CSV. Retorna el número de filas exportadas."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")

    try:
        rows = _fetch_rows(conn)
        if not rows:
            logger.warning("No hay datos en market_snapshots para exportar")
            return 0

        rows = _add_derived_features(rows, conn)

        all_cols = _FEATURE_COLS + _DERIVED_COLS + _LABEL_COLS
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        logger.info("Dataset exportado: %d filas → %s", len(rows), out_path)
        return len(rows)
    finally:
        conn.close()


def build_features_and_labels(horizon_minutes: int = 60) -> List[dict]:
    """Retorna lista de dicts con features + label del horizonte indicado (en memoria)."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        rows = _fetch_rows(conn, horizon_minutes=horizon_minutes)
        rows = _add_derived_features(rows, conn)
        return rows
    finally:
        conn.close()


# ── Internos ──────────────────────────────────────────────────────────────

def _fetch_rows(conn: sqlite3.Connection, horizon_minutes: int = 60) -> List[dict]:
    """Query principal: snapshots + LEFT JOIN con alertas y outcomes."""
    query = f"""
        SELECT
            ms.{', ms.'.join(_FEATURE_COLS)},
            ta.id  AS alert_id,
            ao.future_return_pct  AS future_return_1h,
            ao.hit_tp1,
            ao.hit_tp2,
            ao.hit_stop,
            ao.outcome            AS outcome_1h
        FROM market_snapshots ms
        LEFT JOIN trade_alerts ta
            ON ta.symbol = ms.symbol
            AND ta.timestamp = ms.timestamp
        LEFT JOIN alert_outcomes ao
            ON ao.alert_id = ta.id
            AND ao.horizon_minutes = {horizon_minutes}
        ORDER BY ms.timestamp ASC
    """
    try:
        cur = conn.execute(query)
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        logger.exception("Error al fetch rows para ML dataset")
        return []


def _add_derived_features(rows: List[dict], conn: sqlite3.Connection) -> List[dict]:
    """Añade features derivadas calculadas en Python."""
    from collections import deque

    # Rolling buffers por símbolo (últimas 5 observaciones)
    cvd_buf: dict = {}
    delta_buf: dict = {}

    # Calcular z-score de CVD por símbolo (usando todos los snapshots del símbolo)
    cvd_by_symbol: dict = {}
    for r in rows:
        sym = r["symbol"]
        cvd_by_symbol.setdefault(sym, []).append(float(r.get("cvd") or 0.0))

    cvd_mean: dict = {}
    cvd_std: dict = {}
    for sym, vals in cvd_by_symbol.items():
        n = len(vals)
        mean = sum(vals) / n if n else 0.0
        std = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5 if n > 1 else 1.0
        cvd_mean[sym] = mean
        cvd_std[sym] = std if std > 0.0 else 1.0

    for r in rows:
        sym = r["symbol"]

        # Rolling slope CVD (últimas 5)
        buf_c = cvd_buf.setdefault(sym, deque(maxlen=5))
        buf_d = delta_buf.setdefault(sym, deque(maxlen=5))
        buf_c.append(float(r.get("cvd") or 0.0))
        buf_d.append(float(r.get("delta") or 0.0))

        if len(buf_c) >= 2:
            # Pendiente simple: último - primero / n
            r["cvd_slope_5"] = round((buf_c[-1] - buf_c[0]) / len(buf_c), 6)
            r["delta_ma_5"]  = round(sum(buf_d) / len(buf_d), 6)
        else:
            r["cvd_slope_5"] = 0.0
            r["delta_ma_5"]  = float(r.get("delta") or 0.0)

        # Squeeze label
        signal = r.get("signal", "")
        r["squeeze_label"] = 1 if signal in ("short_squeeze", "long_squeeze") else 0

        # Anomaly candidate: |CVD z-score| > 2.5 (heurístico, sin supervisión)
        cvd_val = float(r.get("cvd") or 0.0)
        z = abs(cvd_val - cvd_mean.get(sym, 0.0)) / cvd_std.get(sym, 1.0)
        r["anomaly_candidate"] = 1 if z > 2.5 else 0

    return rows
