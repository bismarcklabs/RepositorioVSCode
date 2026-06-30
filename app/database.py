"""Capa de persistencia SQLite para el crypto dashboard.

Diseño:
- WAL mode + synchronous=NORMAL para soportar escrituras concurrentes sin lock.
- Una conexión por hilo (thread-local) para evitar conflictos.
- Todos los errores se capturan y logean; nunca propagan al llamador.
- Inserciones de snapshots en batch (un executemany por ciclo de scan).
"""

import calendar
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import DATABASE_PATH, SNAPSHOT_RETENTION_DAYS, SNAPSHOT_MIN_SCORE

logger = logging.getLogger("database")

_db_local = threading.local()
_init_lock = threading.Lock()
_db_initialized = False


# ── Conexión ──────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        db_path = Path(DATABASE_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # timeout=30 → Python espera hasta 30s por el lock antes de lanzar OperationalError
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        # busy_timeout=30000ms → SQLite espera 30s a nivel de motor (refuerza el timeout de Python)
        conn.execute("PRAGMA busy_timeout=30000;")
        # Checkpoint automático cada 200 páginas — evita que el WAL file crezca indefinidamente
        conn.execute("PRAGMA wal_autocheckpoint=200;")
        # Cache de 32MB por conexión — reduce I/O en lecturas repetidas del dashboard
        conn.execute("PRAGMA cache_size=-32000;")
        _db_local.conn = conn
    return _db_local.conn


# ── Inicialización de tablas ──────────────────────────────────────────────

def _migrate_schema() -> None:
    """Agrega columnas nuevas a tablas existentes de forma idempotente.

    SQLite no soporta ALTER TABLE ... ADD COLUMN IF NOT EXISTS, así que
    intentamos cada ALTER y silenciamos el error de columna duplicada.
    """
    conn = _get_conn()
    new_columns = [
        ("market_snapshots", "return_3m",            "REAL DEFAULT 0"),
        ("market_snapshots", "return_5m",            "REAL DEFAULT 0"),
        ("market_snapshots", "cvd_15m",              "REAL DEFAULT 0"),
        ("market_snapshots", "atr",                  "REAL DEFAULT 0"),
        ("market_snapshots", "atr_pct",              "REAL DEFAULT 0"),
        ("market_snapshots", "htf_trend_bias",       "TEXT DEFAULT 'neutral'"),
        ("market_snapshots", "rsi",                  "REAL DEFAULT 50"),
        ("market_snapshots", "oi_change_pct",        "REAL DEFAULT 0"),
        # sub-scores individuales (para ML y modo DB-display)
        ("market_snapshots", "flow_score",           "INTEGER DEFAULT 0"),
        ("market_snapshots", "technical_score",      "INTEGER DEFAULT 0"),
        ("market_snapshots", "volume_profile_score", "INTEGER DEFAULT 0"),
        ("market_snapshots", "footprint_score",      "INTEGER DEFAULT 0"),
        ("market_snapshots", "futures_score",        "INTEGER DEFAULT 0"),
        ("market_snapshots", "risk_penalty",         "INTEGER DEFAULT 0"),
        ("market_snapshots", "confluence_score",     "INTEGER DEFAULT 0"),
        # contexto completo serializado (para reconstruir la UI desde DB)
        ("market_snapshots", "recommendation_json",          "TEXT DEFAULT '{}'"),
        ("market_snapshots", "signal_json",                  "TEXT DEFAULT '{}'"),
        ("market_snapshots", "alert_report_json",            "TEXT DEFAULT '{}'"),
        # multi-exchange confirmation (Phase 5/6)
        ("market_snapshots", "multi_exchange_score",         "INTEGER DEFAULT 0"),
        ("market_snapshots", "multi_exchange_confidence",    "REAL"),
        ("market_snapshots", "price_deviation_pct",          "REAL"),
        ("market_snapshots", "exchange_availability_score",  "REAL"),
        # setup evaluation + ML
        ("market_snapshots", "setup_valid",                  "INTEGER DEFAULT 0"),
        ("market_snapshots", "setup_grade",                  "TEXT DEFAULT ''"),
        ("market_snapshots", "setup_score",                  "INTEGER DEFAULT 0"),
        ("market_snapshots", "trigger_type",                 "TEXT DEFAULT ''"),
        ("market_snapshots", "ml_probability",               "REAL"),
        ("market_snapshots", "ml_filtered",                  "INTEGER DEFAULT 0"),
        # setup/ML en trade_alerts para sobrevivir la purga de snapshots
        ("trade_alerts", "setup_grade",    "TEXT DEFAULT ''"),
        ("trade_alerts", "setup_score",    "INTEGER DEFAULT 0"),
        ("trade_alerts", "trigger_type",   "TEXT DEFAULT ''"),
        ("trade_alerts", "ml_probability", "REAL"),
        ("trade_alerts", "ml_filtered",    "INTEGER DEFAULT 0"),
        # trend continuation
        ("market_snapshots", "trend_priority_score",       "INTEGER DEFAULT 0"),
        ("market_snapshots", "momentum_continuation",      "INTEGER DEFAULT 0"),
        ("market_snapshots", "momentum_persistence_count", "INTEGER DEFAULT 0"),
        ("market_snapshots", "setup_route",                "TEXT DEFAULT ''"),
        # trend continuation en trade_alerts (sobrevive purga de 7 días)
        ("trade_alerts", "setup_route",          "TEXT DEFAULT ''"),
        ("trade_alerts", "trend_priority_score", "INTEGER DEFAULT 0"),
        ("trade_alerts", "original_setup_grade", "TEXT DEFAULT ''"),
        ("trade_alerts", "calibrated_grade",     "TEXT DEFAULT ''"),
        ("trade_alerts", "direction_score",      "INTEGER DEFAULT 0"),
        ("trade_alerts", "entry_score",          "INTEGER DEFAULT 0"),
        ("trade_alerts", "risk_score",           "INTEGER DEFAULT 0"),
        ("trade_alerts", "calibration_version",  "TEXT DEFAULT ''"),
        ("trade_alerts", "btc_regime",           "TEXT DEFAULT 'NORMAL'"),
        ("trade_alerts", "watch_type",           "TEXT DEFAULT ''"),
        # micro-scalp outcomes
        ("micro_scalp_alerts", "close_time",       "TEXT"),
        ("micro_scalp_alerts", "exit_price",       "REAL"),
        ("micro_scalp_alerts", "outcome",          "TEXT DEFAULT 'open'"),
        ("micro_scalp_alerts", "hit_tp1",          "INTEGER DEFAULT 0"),
        ("micro_scalp_alerts", "hit_tp2",          "INTEGER DEFAULT 0"),
        ("micro_scalp_alerts", "hit_stop",         "INTEGER DEFAULT 0"),
        ("micro_scalp_alerts", "pnl_pct",          "REAL DEFAULT 0"),
        ("micro_scalp_alerts", "max_favorable_pct","REAL DEFAULT 0"),
        ("micro_scalp_alerts", "max_adverse_pct",  "REAL DEFAULT 0"),
        # exchange tracking en auto_positions (real trading)
        ("auto_positions", "exchange",          "TEXT NOT NULL DEFAULT 'paper'"),
        ("auto_positions", "exchange_order_id", "TEXT"),
    ]
    for table, col, col_def in new_columns:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            conn.commit()
            logger.info("Columna agregada: %s.%s", table, col)
        except Exception:
            pass  # ya existe


def init_db() -> None:
    global _db_initialized
    with _init_lock:
        if _db_initialized:
            return
        try:
            conn = _get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    price           REAL,
                    futures_price   REAL,
                    action          TEXT,
                    market          TEXT,
                    confidence      INTEGER,
                    score           INTEGER,
                    signal          TEXT,
                    risk_level      TEXT,

                    delta           REAL,
                    cvd             REAL,
                    buy_volume      REAL,
                    sell_volume     REAL,
                    funding         REAL,
                    open_interest   REAL,
                    imbalance       REAL,
                    spread_pct      REAL,

                    return_3m       REAL,
                    return_5m       REAL,
                    return_15m      REAL,
                    return_1h       REAL,
                    vwap            REAL,
                    vwap_distance_pct REAL,
                    above_vwap      INTEGER,
                    relative_volume REAL,
                    trend_bias      TEXT,

                    poc             REAL,
                    nearest_vp_level REAL,
                    nearest_vp_type  TEXT,
                    vp_distance     REAL,

                    footprint_delta      REAL,
                    absorption_buy       INTEGER,
                    absorption_sell      INTEGER,
                    stacked_buy_imbalance  INTEGER,
                    stacked_sell_imbalance INTEGER,

                    gex_available   INTEGER,
                    gex_score       INTEGER,
                    call_wall       REAL,
                    put_wall        REAL,
                    gamma_flip      REAL,

                    entry           REAL,
                    entry_zone_low  REAL,
                    entry_zone_high REAL,
                    stop_loss       REAL,
                    take_profit_1   REAL,
                    take_profit_2   REAL,
                    risk_reward_1   REAL,
                    risk_reward_2   REAL,

                    reasons_json    TEXT,
                    warnings_json   TEXT,
                    invalidation_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_sym_ts
                    ON market_snapshots(symbol, timestamp);
                CREATE INDEX IF NOT EXISTS idx_snapshots_ts
                    ON market_snapshots(timestamp);

                CREATE TABLE IF NOT EXISTS trade_alerts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    action          TEXT    NOT NULL,
                    market          TEXT    NOT NULL,
                    confidence      INTEGER,
                    score           INTEGER,
                    price           REAL,
                    entry           REAL,
                    stop_loss       REAL,
                    take_profit_1   REAL,
                    take_profit_2   REAL,
                    risk_reward_1   REAL,
                    risk_reward_2   REAL,
                    status          TEXT    DEFAULT 'open'
                );

                CREATE INDEX IF NOT EXISTS idx_alerts_sym_ts
                    ON trade_alerts(symbol, timestamp);
                CREATE INDEX IF NOT EXISTS idx_alerts_status
                    ON trade_alerts(status);

                CREATE TABLE IF NOT EXISTS notification_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    alert_id        INTEGER REFERENCES trade_alerts(id),
                    symbol          TEXT    NOT NULL,
                    action          TEXT    NOT NULL,
                    channel         TEXT    NOT NULL,
                    ok              INTEGER NOT NULL,
                    error           TEXT    DEFAULT '',
                    cooldown_skipped INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_notif_alert_id
                    ON notification_log(alert_id);

                CREATE TABLE IF NOT EXISTS alert_outcomes (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id                INTEGER NOT NULL REFERENCES trade_alerts(id),
                    checked_at              TEXT    NOT NULL,
                    horizon_minutes         INTEGER NOT NULL,
                    price_at_check          REAL,
                    future_return_pct       REAL,
                    max_favorable_excursion REAL,
                    max_adverse_excursion   REAL,
                    hit_tp1                 INTEGER DEFAULT 0,
                    hit_tp2                 INTEGER DEFAULT 0,
                    hit_stop                INTEGER DEFAULT 0,
                    outcome                 TEXT    DEFAULT 'unknown',
                    UNIQUE(alert_id, horizon_minutes)
                );

                CREATE INDEX IF NOT EXISTS idx_outcomes_alert_id
                    ON alert_outcomes(alert_id);

                CREATE TABLE IF NOT EXISTS auto_positions (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id          INTEGER REFERENCES trade_alerts(id),
                    symbol            TEXT    NOT NULL,
                    action            TEXT    NOT NULL,
                    mode              TEXT    NOT NULL DEFAULT 'paper',
                    exchange          TEXT    NOT NULL DEFAULT 'paper',
                    exchange_order_id TEXT,
                    open_time         TEXT    NOT NULL,
                    close_time        TEXT,
                    entry_price       REAL    NOT NULL,
                    size_usdt         REAL    NOT NULL,
                    leverage          INTEGER NOT NULL DEFAULT 1,
                    tp1               REAL,
                    tp2               REAL,
                    sl                REAL    NOT NULL,
                    sl_current        REAL    NOT NULL,
                    status            TEXT    NOT NULL DEFAULT 'open',
                    tp1_hit           INTEGER NOT NULL DEFAULT 0,
                    tp1_pnl_usdt      REAL    NOT NULL DEFAULT 0.0,
                    close_reason      TEXT,
                    exit_price        REAL,
                    final_pnl_usdt    REAL,
                    total_pnl_usdt    REAL,
                    total_pnl_pct     REAL
                );

                CREATE INDEX IF NOT EXISTS idx_autopos_status
                    ON auto_positions(status);
                CREATE INDEX IF NOT EXISTS idx_autopos_symbol
                    ON auto_positions(symbol, status);

                -- Ticker por exchange externo (Coinbase, Kraken) por ciclo
                CREATE TABLE IF NOT EXISTS exchange_market_snapshots (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,           -- normalizado: "BTC"
                    binance_symbol  TEXT    NOT NULL,           -- "BTCUSDT"
                    exchange        TEXT    NOT NULL,           -- "coinbase" | "kraken"
                    exchange_symbol TEXT    NOT NULL DEFAULT '', -- "BTC-USD" | "XBT/USD"
                    price           REAL,
                    bid             REAL,
                    ask             REAL,
                    spread_pct      REAL,
                    volume_24h      REAL,
                    ok              INTEGER DEFAULT 1,
                    error           TEXT    DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_exsnap_sym_ts
                    ON exchange_market_snapshots(binance_symbol, timestamp);
                CREATE INDEX IF NOT EXISTS idx_exsnap_ts
                    ON exchange_market_snapshots(timestamp);

                -- Métricas agregadas por símbolo soportado por ciclo
                CREATE TABLE IF NOT EXISTS multi_exchange_metrics (
                    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp                   TEXT    NOT NULL,
                    symbol                      TEXT    NOT NULL,
                    binance_symbol              TEXT    NOT NULL,
                    binance_price               REAL,
                    coinbase_price              REAL,
                    kraken_price                REAL,
                    price_deviation_pct         REAL,
                    exchange_availability_score REAL,
                    multi_exchange_confidence   REAL,
                    multi_exchange_score        INTEGER DEFAULT 0,
                    warnings_json               TEXT    DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_mexmetrics_sym_ts
                    ON multi_exchange_metrics(binance_symbol, timestamp);

                CREATE TABLE IF NOT EXISTS micro_scalp_alerts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    action          TEXT    NOT NULL,
                    score           INTEGER NOT NULL,
                    confidence      INTEGER DEFAULT 0,
                    entry           REAL,
                    take_profit_1   REAL,
                    take_profit_2   REAL,
                    stop_loss       REAL,
                    timeout_minutes INTEGER DEFAULT 10,
                    return_3m       REAL DEFAULT 0,
                    return_5m       REAL DEFAULT 0,
                    relative_volume REAL DEFAULT 1,
                    delta           REAL DEFAULT 0,
                    cvd_15m         REAL DEFAULT 0,
                    footprint_delta REAL DEFAULT 0,
                    imbalance       REAL DEFAULT 0,
                    oi_change_pct   REAL DEFAULT 0,
                    funding         REAL DEFAULT 0,
                    status          TEXT DEFAULT 'open',
                    close_time      TEXT,
                    exit_price      REAL,
                    outcome         TEXT DEFAULT 'open',
                    hit_tp1         INTEGER DEFAULT 0,
                    hit_tp2         INTEGER DEFAULT 0,
                    hit_stop        INTEGER DEFAULT 0,
                    pnl_pct         REAL DEFAULT 0,
                    max_favorable_pct REAL DEFAULT 0,
                    max_adverse_pct REAL DEFAULT 0,
                    reasons_json    TEXT DEFAULT '[]',
                    warnings_json   TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_micro_scalp_sym_ts
                    ON micro_scalp_alerts(symbol, timestamp);
                CREATE INDEX IF NOT EXISTS idx_micro_scalp_status
                    ON micro_scalp_alerts(status);

                CREATE TABLE IF NOT EXISTS micro_notification_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    micro_alert_id  INTEGER REFERENCES micro_scalp_alerts(id),
                    symbol          TEXT    NOT NULL,
                    action          TEXT    NOT NULL,
                    channel         TEXT    NOT NULL,
                    ok              INTEGER NOT NULL,
                    error           TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_micro_notif_alert_id
                    ON micro_notification_log(micro_alert_id);

                CREATE TABLE IF NOT EXISTS news_events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id        TEXT NOT NULL UNIQUE,
                    symbol          TEXT NOT NULL,
                    source          TEXT NOT NULL,
                    source_domain   TEXT DEFAULT '',
                    title           TEXT NOT NULL,
                    summary         TEXT DEFAULT '',
                    url             TEXT DEFAULT '',
                    published_at    TEXT NOT NULL,
                    collected_at    TEXT NOT NULL,
                    event_type      TEXT DEFAULT 'general',
                    sentiment_score REAL DEFAULT 0,
                    weighted_score  REAL DEFAULT 0,
                    prediction      TEXT DEFAULT 'NEUTRAL',
                    credibility     REAL DEFAULT 0,
                    event_types_json TEXT DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS idx_news_events_sym_ts
                    ON news_events(symbol, published_at);

                CREATE TABLE IF NOT EXISTS news_predictions (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp           TEXT NOT NULL,
                    symbol              TEXT NOT NULL,
                    prediction          TEXT NOT NULL,
                    sentiment_score     REAL DEFAULT 0,
                    confidence          INTEGER DEFAULT 0,
                    news_count          INTEGER DEFAULT 0,
                    positive_count      INTEGER DEFAULT 0,
                    negative_count      INTEGER DEFAULT 0,
                    contradictory       INTEGER DEFAULT 0,
                    top_events_json     TEXT DEFAULT '[]',
                    price_at_prediction REAL,
                    horizon_minutes     INTEGER DEFAULT 60,
                    evaluated_at        TEXT,
                    price_at_outcome    REAL,
                    return_pct          REAL,
                    outcome             TEXT DEFAULT 'open'
                );
                CREATE INDEX IF NOT EXISTS idx_news_predictions_status
                    ON news_predictions(outcome, timestamp);
                CREATE INDEX IF NOT EXISTS idx_news_predictions_sym_ts
                    ON news_predictions(symbol, timestamp);

                CREATE TABLE IF NOT EXISTS security_event_alerts (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint           TEXT NOT NULL UNIQUE,
                    created_at            TEXT NOT NULL,
                    updated_at            TEXT NOT NULL,
                    symbol                TEXT NOT NULL,
                    severity              TEXT NOT NULL,
                    confirmation_status   TEXT NOT NULL,
                    security_score        REAL DEFAULT 0,
                    source_count          INTEGER DEFAULT 0,
                    official_source_count INTEGER DEFAULT 0,
                    first_published_at    TEXT,
                    title                 TEXT NOT NULL,
                    analysis_json         TEXT DEFAULT '{}',
                    last_notified_at      TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_security_alerts_sym_ts
                    ON security_event_alerts(symbol, created_at);

                -- Accumulation Watch: tokens fuera del top-50 por volumen en fase
                -- de "coiling" (contracción de volatilidad + acumulación), candidatos
                -- a "ignición" (breakout tipo FOMO).
                CREATE TABLE IF NOT EXISTS accumulation_watch (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol              TEXT    NOT NULL UNIQUE,
                    first_seen          TEXT    NOT NULL,
                    last_scan           TEXT    NOT NULL,
                    coiling_score       REAL    DEFAULT 0,
                    contraction_ratio   REAL    DEFAULT 0,
                    position_in_range   REAL    DEFAULT 0,
                    above_sma50         INTEGER DEFAULT 0,
                    vol_ratio_7_30      REAL    DEFAULT 0,
                    quote_volume        REAL    DEFAULT 0,
                    funding_at_watch    REAL    DEFAULT 0,
                    price_at_watch      REAL    DEFAULT 0,
                    status              TEXT    DEFAULT 'watching',
                    ignited_at          TEXT,
                    ignition_reason     TEXT    DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_accum_watch_status
                    ON accumulation_watch(status);
                CREATE INDEX IF NOT EXISTS idx_accum_watch_score
                    ON accumulation_watch(coiling_score);
                CREATE TABLE IF NOT EXISTS historical_klines (
                    symbol     TEXT    NOT NULL,
                    interval   TEXT    NOT NULL,
                    open_time  INTEGER NOT NULL,
                    open       REAL    NOT NULL,
                    high       REAL    NOT NULL,
                    low        REAL    NOT NULL,
                    close      REAL    NOT NULL,
                    volume     REAL    NOT NULL,
                    PRIMARY KEY (symbol, interval, open_time)
                );
                CREATE INDEX IF NOT EXISTS idx_hk_symbol_interval
                    ON historical_klines(symbol, interval);
            """)
            conn.commit()
            _migrate_schema()
            _db_initialized = True
            logger.info("Base de datos inicializada: %s", DATABASE_PATH)
        except Exception:
            logger.exception("Error al inicializar la base de datos")


# ── Snapshots ─────────────────────────────────────────────────────────────

def _snapshot_row(data: Dict[str, Any]) -> Tuple:
    """Extrae una tupla ordenada para insertar en market_snapshots."""
    ts = data.get("timestamp", "")
    rec = data.get("recommendation", {})
    setup = rec.get("setup") or {}
    tech = data.get("technical") or {}
    vp = data.get("volume_profile") or {}
    fp = data.get("footprint") or {}
    gex = data.get("gex") or {}
    metrics = data.get("metrics") or {}
    ob = data.get("orderbook") or {}
    sd = data.get("score_data") or {}
    mx = data.get("multi_exchange") or {}

    return (
        ts,
        data.get("symbol", ""),
        data.get("price", 0.0),
        data.get("futures_price", 0.0),
        rec.get("action", "WAIT"),
        rec.get("market", "NONE"),
        rec.get("confidence", 0),
        sd.get("score", 0),
        (data.get("signal") or {}).get("signal", ""),
        rec.get("risk_level", "low"),
        # flow
        metrics.get("delta", 0.0),
        metrics.get("cvd", 0.0),
        metrics.get("buy_volume", 0.0),
        metrics.get("sell_volume", 0.0),
        data.get("funding", 0.0),
        data.get("open_interest", 0.0),
        ob.get("imbalance", 0.0),
        ob.get("spread_pct", 0.0),
        # technical
        tech.get("return_3m", 0.0),
        tech.get("return_5m", 0.0),
        tech.get("return_15m", 0.0),
        tech.get("return_1h", 0.0),
        tech.get("vwap", 0.0),
        tech.get("vwap_distance_pct", 0.0),
        int(bool(tech.get("above_vwap", True))),
        tech.get("relative_volume", 1.0),
        tech.get("trend_bias", "neutral"),
        # volume profile
        vp.get("poc", 0.0),
        vp.get("nearest_level", 0.0),
        vp.get("nearest_level_type", "NONE"),
        vp.get("distance_to_level_pct", 0.0),
        # footprint
        fp.get("footprint_delta", 0.0),
        int(bool(fp.get("absorption_buy", False))),
        int(bool(fp.get("absorption_sell", False))),
        int(bool(fp.get("stacked_buy_imbalance", False))),
        int(bool(fp.get("stacked_sell_imbalance", False))),
        # gex
        int(gex is not None and bool(gex)),
        sd.get("gex_score", 0),
        gex.get("call_wall", 0.0),
        gex.get("put_wall", 0.0),
        gex.get("gamma_flip", 0.0),
        # setup levels
        setup.get("entry", 0.0),
        setup.get("entry_zone_low", 0.0),
        setup.get("entry_zone_high", 0.0),
        setup.get("stop_loss", 0.0),
        setup.get("take_profit_1", 0.0),
        setup.get("take_profit_2", 0.0),
        setup.get("risk_reward_1", 0.0),
        setup.get("risk_reward_2", 0.0),
        # json arrays
        json.dumps(rec.get("reasons", [])),
        json.dumps(rec.get("warnings", [])),
        json.dumps(rec.get("invalidation", [])),
        # nuevas métricas
        metrics.get("cvd_15m", 0.0),
        tech.get("atr", 0.0),
        tech.get("atr_pct", 0.0),
        tech.get("htf_trend_bias", "neutral"),
        tech.get("rsi", 50.0),
        data.get("oi_change_pct", 0.0),
        # sub-scores
        sd.get("flow_score", 0),
        sd.get("technical_score", 0),
        sd.get("volume_profile_score", 0),
        sd.get("footprint_score", 0),
        sd.get("futures_score", 0),
        sd.get("risk_penalty", 0),
        rec.get("confluence_score", 0),
        # contexto completo
        json.dumps(rec),
        json.dumps(data.get("signal") or {}),
        json.dumps(data.get("alert_report") or {}),
        # multi-exchange
        sd.get("multi_exchange_score", 0),
        mx.get("multi_exchange_confidence"),       # None para altcoins
        mx.get("price_deviation_pct"),             # None para altcoins
        mx.get("exchange_availability_score"),
        # setup evaluation
        int(bool((data.get("setup_evaluation") or rec.get("setup_evaluation") or {}).get("valid", False))),
        (data.get("setup_evaluation") or rec.get("setup_evaluation") or {}).get("grade", ""),
        int((data.get("setup_evaluation") or rec.get("setup_evaluation") or {}).get("score", 0)),
        (data.get("setup_evaluation") or rec.get("setup_evaluation") or {}).get("trigger_type") or "",
        # ml
        data.get("ml_probability"),
        int(rec.get("action") == "WAIT" and data.get("ml_probability") is not None),
        # trend continuation
        data.get("trend_priority_score", 0),
        int(bool(data.get("momentum_continuation", False))),
        data.get("momentum_persistence_count", 0),
        (data.get("setup_evaluation") or rec.get("setup_evaluation") or {}).get("setup_route") or "",
    )


_SNAPSHOT_INSERT = """
    INSERT INTO market_snapshots (
        timestamp, symbol, price, futures_price,
        action, market, confidence, score, signal, risk_level,
        delta, cvd, buy_volume, sell_volume, funding, open_interest,
        imbalance, spread_pct,
        return_3m, return_5m, return_15m, return_1h, vwap, vwap_distance_pct, above_vwap,
        relative_volume, trend_bias,
        poc, nearest_vp_level, nearest_vp_type, vp_distance,
        footprint_delta, absorption_buy, absorption_sell,
        stacked_buy_imbalance, stacked_sell_imbalance,
        gex_available, gex_score, call_wall, put_wall, gamma_flip,
        entry, entry_zone_low, entry_zone_high, stop_loss,
        take_profit_1, take_profit_2, risk_reward_1, risk_reward_2,
        reasons_json, warnings_json, invalidation_json,
        cvd_15m, atr, atr_pct, htf_trend_bias, rsi, oi_change_pct,
        flow_score, technical_score, volume_profile_score, footprint_score,
        futures_score, risk_penalty, confluence_score,
        recommendation_json, signal_json, alert_report_json,
        multi_exchange_score, multi_exchange_confidence,
        price_deviation_pct, exchange_availability_score,
        setup_valid, setup_grade, setup_score, trigger_type,
        ml_probability, ml_filtered,
        trend_priority_score, momentum_continuation,
        momentum_persistence_count, setup_route
    ) VALUES (
        ?,?,?,?,?,?,?,?,?,?,
        ?,?,?,?,?,?,?,?,
        ?,?,?,?,?,?,?,?,?,
        ?,?,?,?,
        ?,?,?,?,?,
        ?,?,?,?,?,
        ?,?,?,?,?,?,?,?,
        ?,?,?,
        ?,?,?,?,?,?,
        ?,?,?,?,?,?,?,
        ?,?,?,
        ?,?,?,?,
        ?,?,?,?,?,?,
        ?,?,?,?
    )
"""


def insert_snapshots_batch(records: List[Dict[str, Any]]) -> None:
    """Inserta snapshots del ciclo — solo los que superen SNAPSHOT_MIN_SCORE.

    Filtrar aquí reduce el volumen de escrituras de ~288k filas/día (todos los
    símbolos) a ~50-80k filas/día (solo los interesantes), aliviando el lock.
    """
    if not records:
        return
    filtered = [r for r in records if (r.get("score_data") or {}).get("score", 0) >= SNAPSHOT_MIN_SCORE]
    if not filtered:
        return
    try:
        rows = [_snapshot_row(r) for r in filtered]
        conn = _get_conn()
        conn.executemany(_SNAPSHOT_INSERT, rows)
        conn.commit()
        logger.debug("Snapshots insertados: %d/%d (score>=%d)", len(rows), len(records), SNAPSHOT_MIN_SCORE)
    except Exception:
        logger.exception("Error al insertar snapshots")


# ── Trade alerts ──────────────────────────────────────────────────────────

def insert_trade_alert(data: Dict[str, Any]) -> Optional[int]:
    """Inserta una alerta accionable. Retorna el alert_id o None en error."""
    setup = data.get("setup") or {}
    try:
        conn = _get_conn()
        cur = conn.execute(
            """
            INSERT INTO trade_alerts
                (timestamp, symbol, action, market, confidence, score,
                 price, entry, stop_loss, take_profit_1, take_profit_2,
                 risk_reward_1, risk_reward_2,
                 setup_grade, setup_score, trigger_type,
                 ml_probability, ml_filtered,
                 setup_route, trend_priority_score,
                 original_setup_grade, calibrated_grade, direction_score,
                 entry_score, risk_score, calibration_version, btc_regime, watch_type,
                 status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open')
            """,
            (
                data.get("timestamp", ""),
                data.get("symbol", ""),
                data.get("action", ""),
                data.get("market", ""),
                data.get("confidence", 0),
                data.get("score", 0),
                data.get("price", 0.0),
                setup.get("entry", 0.0),
                setup.get("stop_loss", 0.0),
                setup.get("take_profit_1", 0.0),
                setup.get("take_profit_2", 0.0),
                setup.get("risk_reward_1", 0.0),
                setup.get("risk_reward_2", 0.0),
                data.get("setup_grade", ""),
                data.get("setup_score", 0),
                data.get("trigger_type", ""),
                data.get("ml_probability"),
                int(data.get("ml_filtered", False)),
                data.get("setup_route", ""),
                data.get("trend_priority_score", 0),
                data.get("original_setup_grade", data.get("setup_grade", "")),
                data.get("calibrated_grade", ""),
                data.get("direction_score", 0),
                data.get("entry_score", 0),
                data.get("risk_score", 0),
                data.get("calibration_version", ""),
                data.get("btc_regime", "NORMAL"),
                data.get("watch_type", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        logger.exception("Error al insertar trade_alert")
        return None


def insert_micro_scalp_alert(data: Dict[str, Any]) -> Optional[int]:
    """Inserta una alerta de scalping agresivo. Retorna micro_alert_id o None."""
    setup = data.get("setup") or {}
    technical = data.get("technical") or {}
    metrics = data.get("metrics") or {}
    footprint = data.get("footprint") or {}
    orderbook = data.get("orderbook") or {}
    try:
        conn = _get_conn()
        cur = conn.execute(
            """
            INSERT INTO micro_scalp_alerts
                (timestamp, symbol, action, score, confidence,
                 entry, take_profit_1, take_profit_2, stop_loss, timeout_minutes,
                 return_3m, return_5m, relative_volume,
                 delta, cvd_15m, footprint_delta, imbalance,
                 oi_change_pct, funding, status, reasons_json, warnings_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?,?)
            """,
            (
                data.get("timestamp", ""),
                data.get("symbol", ""),
                data.get("action", ""),
                data.get("score", 0),
                data.get("confidence", 0),
                setup.get("entry", 0.0),
                setup.get("take_profit_1", 0.0),
                setup.get("take_profit_2", 0.0),
                setup.get("stop_loss", 0.0),
                setup.get("timeout_minutes", 0),
                technical.get("return_3m", 0.0),
                technical.get("return_5m", 0.0),
                technical.get("relative_volume", 1.0),
                metrics.get("delta", 0.0),
                metrics.get("cvd_15m", 0.0),
                footprint.get("footprint_delta", 0.0),
                orderbook.get("imbalance", 0.0),
                data.get("oi_change_pct", 0.0),
                data.get("funding", 0.0),
                json.dumps(data.get("reasons", [])),
                json.dumps(data.get("warnings", [])),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        logger.exception("Error al insertar micro_scalp_alert")
        return None


def get_open_micro_scalp_alerts() -> List[Dict[str, Any]]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM micro_scalp_alerts WHERE status='open' ORDER BY timestamp ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener micro_scalp_alerts abiertas")
        return []


def close_micro_scalp_alert(
    micro_alert_id: int,
    outcome: str,
    exit_price: float,
    hit_tp1: bool,
    hit_tp2: bool,
    hit_stop: bool,
    pnl_pct: float,
    max_favorable_pct: float,
    max_adverse_pct: float,
) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            """
            UPDATE micro_scalp_alerts SET
                status = 'closed',
                close_time = ?,
                exit_price = ?,
                outcome = ?,
                hit_tp1 = ?,
                hit_tp2 = ?,
                hit_stop = ?,
                pnl_pct = ?,
                max_favorable_pct = ?,
                max_adverse_pct = ?
            WHERE id = ?
            """,
            (
                _now_iso(), exit_price, outcome,
                int(hit_tp1), int(hit_tp2), int(hit_stop),
                pnl_pct, max_favorable_pct, max_adverse_pct,
                micro_alert_id,
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Error al cerrar micro_scalp_alert %d", micro_alert_id)


def update_alert_status(alert_id: int, status: str) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            "UPDATE trade_alerts SET status=? WHERE id=?",
            (status, alert_id),
        )
        conn.commit()
    except Exception:
        logger.exception("Error al actualizar status de alerta %d", alert_id)


# ── Notification log ──────────────────────────────────────────────────────

def insert_notification_log(
    alert_id: Optional[int],
    symbol: str,
    action: str,
    channel: str,
    ok: bool,
    error: str = "",
    cooldown_skipped: bool = False,
) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO notification_log
                (timestamp, alert_id, symbol, action, channel, ok, error, cooldown_skipped)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                _now_iso(),
                alert_id,
                symbol,
                action,
                channel,
                int(ok),
                error,
                int(cooldown_skipped),
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Error al insertar notification_log")


def insert_micro_notification_log(
    micro_alert_id: Optional[int],
    symbol: str,
    action: str,
    channel: str,
    ok: bool,
    error: str = "",
) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO micro_notification_log
                (timestamp, micro_alert_id, symbol, action, channel, ok, error)
            VALUES (?,?,?,?,?,?,?)
            """,
            (_now_iso(), micro_alert_id, symbol, action, channel, int(ok), error),
        )
        conn.commit()
    except Exception:
        logger.exception("Error al insertar micro_notification_log")


# ── Cooldown persistente ──────────────────────────────────────────────────

def get_recent_sent_alerts(
    within_seconds: int = 86400,
) -> List[Dict[str, Any]]:
    """Carga alertas enviadas en las últimas `within_seconds` para precalibrar el cooldown."""
    try:
        conn = _get_conn()
        cutoff = time.time() - within_seconds
        cutoff_iso = _ts_to_iso(cutoff)
        rows = conn.execute(
            """
            SELECT ta.symbol, ta.action, ta.market, ta.confidence, ta.timestamp
            FROM trade_alerts ta
            JOIN notification_log nl ON nl.alert_id = ta.id
            WHERE nl.ok = 1 AND ta.timestamp >= ?
            ORDER BY ta.timestamp DESC
            """,
            (cutoff_iso,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al cargar alertas recientes para cooldown")
        return []


# ── Open alerts (para outcome tracker) ────────────────────────────────────

def get_open_alerts() -> List[Dict[str, Any]]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM trade_alerts WHERE status='open' ORDER BY timestamp ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener alertas abiertas")
        return []


def get_evaluated_horizons(alert_id: int) -> List[int]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT horizon_minutes FROM alert_outcomes WHERE alert_id=?",
            (alert_id,),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        logger.exception("Error al obtener horizontes evaluados para alerta %d", alert_id)
        return []


def insert_alert_outcome(outcome: Dict[str, Any]) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO alert_outcomes
                (alert_id, checked_at, horizon_minutes, price_at_check,
                 future_return_pct, max_favorable_excursion, max_adverse_excursion,
                 hit_tp1, hit_tp2, hit_stop, outcome)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                outcome["alert_id"],
                outcome["checked_at"],
                outcome["horizon_minutes"],
                outcome.get("price_at_check", 0.0),
                outcome.get("future_return_pct", 0.0),
                outcome.get("max_favorable_excursion", 0.0),
                outcome.get("max_adverse_excursion", 0.0),
                int(outcome.get("hit_tp1", False)),
                int(outcome.get("hit_tp2", False)),
                int(outcome.get("hit_stop", False)),
                outcome.get("outcome", "unknown"),
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Error al insertar alert_outcome")


# ── Multi-exchange persistence ────────────────────────────────────────────

_EXSNAP_INSERT = """
    INSERT INTO exchange_market_snapshots
        (timestamp, symbol, binance_symbol, exchange, exchange_symbol,
         price, bid, ask, spread_pct, volume_24h, ok, error)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
"""

_MEXMETRICS_INSERT = """
    INSERT INTO multi_exchange_metrics
        (timestamp, symbol, binance_symbol, binance_price,
         coinbase_price, kraken_price, price_deviation_pct,
         exchange_availability_score, multi_exchange_confidence,
         multi_exchange_score, warnings_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
"""


def insert_multi_exchange_batch(records: List[Dict[str, Any]]) -> None:
    """Persiste datos externos (Coinbase, Kraken) para símbolos soportados.

    Solo inserta cuando el símbolo tiene soporte externo Y score >= SNAPSHOT_MIN_SCORE.
    Binance no se guarda aquí (ya está en market_snapshots).
    """
    if not records:
        return

    supported = [
        r for r in records
        if (r.get("score_data") or {}).get("score", 0) >= SNAPSHOT_MIN_SCORE
        and (r.get("multi_exchange") or {}).get("external_supported")
    ]
    if not supported:
        return

    exsnap_rows: List[Tuple] = []
    mexmet_rows: List[Tuple] = []
    ts = _now_iso()

    for r in supported:
        mx      = r["multi_exchange"]
        bsym    = r["symbol"]
        tickers = mx.get("exchanges", {})

        # Extraer precio de cada exchange externo
        cb_price = kr_price = None

        for ex_name, ticker in tickers.items():
            if ex_name == "binance":
                continue
            ok    = int(bool(ticker.ok))
            price = ticker.price
            if ex_name == "coinbase":
                cb_price = price
            elif ex_name == "kraken":
                kr_price = price

            exsnap_rows.append((
                ts,
                ticker.normalized_symbol,
                bsym,
                ex_name,
                ticker.symbol or "",
                price,
                ticker.bid,
                ticker.ask,
                ticker.spread_pct,
                ticker.volume_24h,
                ok,
                ticker.error or "",
            ))

        # Una fila por símbolo con métricas agregadas
        mexmet_rows.append((
            ts,
            tickers.get("binance", type("", (), {"normalized_symbol": bsym.replace("USDT", "")})()).normalized_symbol
            if "binance" in tickers else bsym.replace("USDT", ""),
            bsym,
            mx.get("primary_price"),
            cb_price,
            kr_price,
            mx.get("price_deviation_pct"),
            mx.get("exchange_availability_score"),
            mx.get("multi_exchange_confidence"),
            (r.get("score_data") or {}).get("multi_exchange_score", 0),
            json.dumps(mx.get("warnings", [])),
        ))

    try:
        conn = _get_conn()
        if exsnap_rows:
            conn.executemany(_EXSNAP_INSERT, exsnap_rows)
        if mexmet_rows:
            conn.executemany(_MEXMETRICS_INSERT, mexmet_rows)
        conn.commit()
        logger.debug(
            "Multi-exchange: %d tickers externos, %d metricas insertadas",
            len(exsnap_rows), len(mexmet_rows),
        )
    except Exception:
        logger.exception("Error al insertar datos multi-exchange")


def get_multi_exchange_history(
    binance_symbol: str,
    hours: float = 24.0,
) -> List[Dict[str, Any]]:
    """Retorna historial de métricas multi-exchange para un símbolo."""
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - hours * 3600)
        rows = conn.execute(
            """
            SELECT * FROM multi_exchange_metrics
            WHERE binance_symbol = ? AND timestamp >= ?
            ORDER BY timestamp DESC
            """,
            (binance_symbol.upper(), cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener historial multi-exchange para %s", binance_symbol)
        return []


# ── Filtro de estancamiento ───────────────────────────────────────────────

def get_zone_tp1_hits(symbol: str, action: str, anchor_price: float,
                      lookback_hours: float = 8.0) -> int:
    """Alertas en zona ±1.5% del precio ancla que tocaron TP1 en las últimas N horas.

    Usado por el filtro de estancamiento para distinguir breakouts reales
    (donde TP1 se toca) de distribución silenciosa (donde no avanza).
    """
    is_long = action in ("LONG_FUTURES", "BUY_SPOT")
    actions = ("LONG_FUTURES", "BUY_SPOT") if is_long else ("SHORT_FUTURES", "SELL_SPOT")
    placeholders = ",".join("?" * len(actions))
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - lookback_hours * 3600)
        row = conn.execute(
            f"""
            SELECT COUNT(*) FROM trade_alerts ta
            JOIN alert_outcomes ao
                ON ao.alert_id = ta.id AND ao.horizon_minutes = 60
            WHERE ta.symbol = ?
              AND ta.action IN ({placeholders})
              AND ta.timestamp >= ?
              AND ao.hit_tp1 = 1
              AND ABS(ta.price - ?) / ? * 100 <= 1.5
            """,
            (symbol, *actions, cutoff, anchor_price, anchor_price),
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        logger.exception("Error en get_zone_tp1_hits para %s", symbol)
        return 0


# ── Retención / limpieza ──────────────────────────────────────────────────

def purge_old_snapshots() -> int:
    """Elimina snapshots más viejos que SNAPSHOT_RETENTION_DAYS. Retorna filas eliminadas."""
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - SNAPSHOT_RETENTION_DAYS * 86400)
        cur = conn.execute(
            "DELETE FROM market_snapshots WHERE timestamp < ?", (cutoff,)
        )
        # Purgar también tablas multi-exchange con la misma retención
        conn.execute("DELETE FROM exchange_market_snapshots WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM multi_exchange_metrics WHERE timestamp < ?", (cutoff,))
        conn.commit()
        deleted = cur.rowcount
        if deleted > 0:
            logger.info("Purga: %d snapshots eliminados (>%d días)", deleted, SNAPSHOT_RETENTION_DAYS)
        return deleted
    except Exception:
        logger.exception("Error al purgar snapshots")
        return 0


# ── Dashboard queries ─────────────────────────────────────────────────────

def get_recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT ta.*,
                   ao.outcome, ao.hit_tp1, ao.hit_tp2, ao.hit_stop,
                   ao.future_return_pct,
                   GROUP_CONCAT(DISTINCT nl.channel) AS channels
            FROM trade_alerts ta
            LEFT JOIN alert_outcomes ao
                ON ao.alert_id = ta.id AND ao.horizon_minutes = 60
            LEFT JOIN notification_log nl
                ON nl.alert_id = ta.id AND nl.ok = 1
            GROUP BY ta.id
            ORDER BY ta.timestamp DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener alertas recientes")
        return []


def get_winrate_summary(since_hours: float = 24.0) -> Dict[str, Any]:
    """Resumen de win rate para enviar como reporte periódico.

    Retorna:
        {
          "since_hours": 24,
          "total_alerts": 12,
          "by_action": [{"action", "total", "wins", "partials", "losses", "neutrals",
                         "winrate_pct", "avg_return_pct", "avg_score"}, ...],
          "top_symbols": [{"symbol", "action", "total", "wins", "winrate_pct"}, ...],
          "global_winrate_pct": 58.3,
          "global_avg_return_pct": 1.2,
        }
    """
    empty: Dict[str, Any] = {
        "since_hours": since_hours,
        "total_alerts": 0,
        "by_action": [],
        "top_symbols": [],
        "global_winrate_pct": 0.0,
        "global_avg_return_pct": 0.0,
    }
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - since_hours * 3600)

        by_action = conn.execute(
            """
            SELECT ta.action,
                   COUNT(*) AS total,
                   SUM(CASE WHEN ao.outcome = 'win'     THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN ao.outcome = 'partial' THEN 1 ELSE 0 END) AS partials,
                   SUM(CASE WHEN ao.outcome = 'loss'    THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN ao.outcome IS NULL OR ao.outcome = 'neutral'
                             THEN 1 ELSE 0 END) AS neutrals,
                   AVG(ta.score) AS avg_score,
                   AVG(CASE WHEN ao.outcome IN ('win','partial','loss')
                            THEN MAX(-50.0, MIN(50.0, ao.future_return_pct))
                            ELSE NULL END) AS avg_return_pct
            FROM trade_alerts ta
            LEFT JOIN alert_outcomes ao ON ao.alert_id = ta.id AND ao.horizon_minutes = 60
            WHERE ta.timestamp >= ?
            GROUP BY ta.action
            ORDER BY total DESC
            """,
            (cutoff,),
        ).fetchall()

        top_symbols = conn.execute(
            """
            SELECT ta.symbol, ta.action,
                   COUNT(*) AS total,
                   SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
                   ROUND(100.0 * SUM(CASE WHEN ao.outcome IN ('win','partial')
                                          THEN 1 ELSE 0 END) / COUNT(*), 1) AS winrate_pct,
                   AVG(ao.future_return_pct) AS avg_return_pct
            FROM trade_alerts ta
            LEFT JOIN alert_outcomes ao ON ao.alert_id = ta.id AND ao.horizon_minutes = 60
            WHERE ta.timestamp >= ?
            GROUP BY ta.symbol, ta.action
            HAVING total >= 2
            ORDER BY winrate_pct DESC, total DESC
            LIMIT 5
            """,
            (cutoff,),
        ).fetchall()

        rows_action = []
        total_all = 0
        total_wins_all = 0
        total_partials_all = 0
        total_evaluated_all = 0
        returns_all: List[float] = []

        for r in by_action:
            total = r["total"] or 0
            w     = r["wins"] or 0
            p     = r["partials"] or 0
            l     = r["losses"] or 0
            n     = r["neutrals"] or 0
            evaluated = w + p + l
            strict_wr  = round(w / evaluated * 100.0, 1) if evaluated else 0.0
            dir_wr     = round((w + p) / evaluated * 100.0, 1) if evaluated else 0.0
            avg_ret = round(r["avg_return_pct"] or 0.0, 2)
            rows_action.append({
                "action":                  r["action"],
                "total":                   total,
                "wins":                    w,
                "partials":                p,
                "losses":                  l,
                "neutrals":                n,
                "evaluated":               evaluated,
                "winrate_pct":             strict_wr,   # wins / evaluated
                "directional_winrate_pct": dir_wr,      # (wins+partials) / evaluated
                "avg_return_pct":          avg_ret,
                "avg_score":               round(r["avg_score"] or 0.0, 1),
            })
            total_all           += total
            total_wins_all      += w
            total_partials_all  += p
            total_evaluated_all += evaluated
            if r["avg_return_pct"] is not None:
                returns_all.append(r["avg_return_pct"])

        global_wr  = round(total_wins_all / total_evaluated_all * 100.0, 1) if total_evaluated_all else 0.0
        global_dir = round((total_wins_all + total_partials_all) / total_evaluated_all * 100.0, 1) if total_evaluated_all else 0.0
        global_ret = round(sum(returns_all) / len(returns_all), 2) if returns_all else 0.0

        return {
            "since_hours":                  since_hours,
            "total_alerts":                 total_all,
            "total_evaluated":              total_evaluated_all,
            "by_action":                    rows_action,
            "top_symbols":                  [dict(r) for r in top_symbols],
            "global_winrate_pct":           global_wr,
            "global_directional_winrate_pct": global_dir,
            "global_avg_return_pct":        global_ret,
        }
    except Exception:
        logger.exception("Error al calcular winrate summary")
        return empty


def get_micro_scalp_summary(since_hours: float = 12.0) -> Dict[str, Any]:
    """Resumen de win rate para micro_scalp_alerts cerradas en las últimas N horas."""
    empty: Dict[str, Any] = {
        "since_hours": since_hours,
        "total": 0,
        "by_action": [],
        "top_symbols": [],
        "global_winrate_pct": 0.0,
        "global_avg_pnl_pct": 0.0,
    }
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - since_hours * 3600)

        by_action = conn.execute(
            """
            SELECT action,
                   COUNT(*) AS total,
                   SUM(CASE WHEN outcome = 'win'     THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN outcome = 'partial' THEN 1 ELSE 0 END) AS partials,
                   SUM(CASE WHEN outcome = 'loss'    THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN outcome NOT IN ('win','partial','loss') THEN 1 ELSE 0 END) AS neutrals,
                   AVG(score) AS avg_score,
                   AVG(CASE WHEN outcome IN ('win','partial','loss') THEN pnl_pct   ELSE NULL END) AS avg_pnl_pct,
                   AVG(CASE WHEN outcome IN ('win','partial','loss') THEN max_favorable_pct ELSE NULL END) AS avg_mfe,
                   AVG(CASE WHEN outcome IN ('win','partial','loss') THEN max_adverse_pct  ELSE NULL END) AS avg_mae
            FROM micro_scalp_alerts
            WHERE status = 'closed' AND timestamp >= ?
            GROUP BY action
            ORDER BY total DESC
            """,
            (cutoff,),
        ).fetchall()

        top_symbols = conn.execute(
            """
            SELECT symbol, action,
                   COUNT(*) AS total,
                   SUM(CASE WHEN outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
                   ROUND(100.0 * SUM(CASE WHEN outcome IN ('win','partial')
                                          THEN 1 ELSE 0 END) / COUNT(*), 1) AS winrate_pct,
                   AVG(pnl_pct) AS avg_pnl_pct
            FROM micro_scalp_alerts
            WHERE status = 'closed' AND timestamp >= ?
            GROUP BY symbol, action
            HAVING total >= 2
            ORDER BY winrate_pct DESC, total DESC
            LIMIT 5
            """,
            (cutoff,),
        ).fetchall()

        rows = []
        total_all = wins_all = partials_all = evaluated_all = 0
        pnl_vals: List[float] = []

        for r in by_action:
            total = r["total"] or 0
            w, p, l, n = r["wins"] or 0, r["partials"] or 0, r["losses"] or 0, r["neutrals"] or 0
            evaluated = w + p + l
            strict_wr = round(w / evaluated * 100.0, 1) if evaluated else 0.0
            dir_wr    = round((w + p) / evaluated * 100.0, 1) if evaluated else 0.0
            avg_pnl   = round(r["avg_pnl_pct"] or 0.0, 3)
            avg_mfe   = round(r["avg_mfe"] or 0.0, 3)
            avg_mae   = round(r["avg_mae"] or 0.0, 3)
            rows.append({
                "action":      r["action"],
                "total":       total,
                "wins":        w,
                "partials":    p,
                "losses":      l,
                "neutrals":    n,
                "evaluated":   evaluated,
                "winrate_pct": strict_wr,
                "directional_winrate_pct": dir_wr,
                "avg_pnl_pct": avg_pnl,
                "avg_mfe_pct": avg_mfe,
                "avg_mae_pct": avg_mae,
                "avg_score":   round(r["avg_score"] or 0.0, 1),
            })
            total_all     += total
            wins_all      += w
            partials_all  += p
            evaluated_all += evaluated
            if r["avg_pnl_pct"] is not None:
                pnl_vals.append(r["avg_pnl_pct"])

        global_wr  = round(wins_all / evaluated_all * 100.0, 1) if evaluated_all else 0.0
        global_dir = round((wins_all + partials_all) / evaluated_all * 100.0, 1) if evaluated_all else 0.0
        global_pnl = round(sum(pnl_vals) / len(pnl_vals), 3) if pnl_vals else 0.0

        return {
            "since_hours":                  since_hours,
            "total":                        total_all,
            "total_evaluated":              evaluated_all,
            "by_action":                    rows,
            "top_symbols":                  [dict(r) for r in top_symbols],
            "global_winrate_pct":           global_wr,
            "global_directional_winrate_pct": global_dir,
            "global_avg_pnl_pct":           global_pnl,
        }
    except Exception:
        logger.exception("Error al calcular micro scalp summary")
        return empty


def get_win_rate_by_action() -> List[Dict[str, Any]]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT ta.action,
                   COUNT(*) AS total,
                   SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
                   AVG(ta.score) AS avg_score,
                   AVG(ao.future_return_pct) AS avg_return_pct
            FROM trade_alerts ta
            LEFT JOIN alert_outcomes ao ON ao.alert_id=ta.id AND ao.horizon_minutes=60
            GROUP BY ta.action
            """,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al calcular win rate")
        return []


def get_symbols_by_action() -> List[Dict[str, Any]]:
    """Top símbolos por tipo de acción con win rate individual."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT ta.action,
                   ta.symbol,
                   COUNT(*) AS total,
                   SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
                   AVG(ta.score) AS avg_score,
                   AVG(ao.future_return_pct) AS avg_return_pct
            FROM trade_alerts ta
            LEFT JOIN alert_outcomes ao ON ao.alert_id = ta.id AND ao.horizon_minutes = 60
            GROUP BY ta.action, ta.symbol
            ORDER BY ta.action, total DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener símbolos por acción")
        return []


def get_channel_stats() -> List[Dict[str, Any]]:
    """Conteo de notificaciones enviadas por canal y tipo de acción."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            """
            SELECT ta.action,
                   nl.channel,
                   COUNT(*) AS total_sent,
                   SUM(CASE WHEN nl.ok = 1 THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN nl.ok = 0 THEN 1 ELSE 0 END) AS failed
            FROM notification_log nl
            JOIN trade_alerts ta ON ta.id = nl.alert_id
            GROUP BY ta.action, nl.channel
            ORDER BY ta.action, total_sent DESC
            """,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener estadísticas de canales")
        return []


def get_snapshot_count() -> int:
    try:
        conn = _get_conn()
        return conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    except Exception:
        return 0


def get_latest_snapshots(limit: int = 60, max_age_seconds: int = 120) -> List[Dict[str, Any]]:
    """Retorna el snapshot más reciente por símbolo, excluyendo los más viejos de max_age_seconds.

    Usa MAX(id) para garantizar unicidad — dos inserts en el mismo segundo
    comparten timestamp y causarían filas duplicadas con MAX(timestamp).
    """
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - max_age_seconds)
        rows = conn.execute(
            """
            SELECT ms.*
            FROM market_snapshots ms
            INNER JOIN (
                SELECT symbol, MAX(id) AS max_id
                FROM market_snapshots
                WHERE timestamp >= ?
                GROUP BY symbol
            ) latest ON ms.id = latest.max_id
            ORDER BY ms.score DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("Error al obtener últimos snapshots")
        return []


def get_scanner_freshness() -> Optional[str]:
    """Retorna el timestamp del snapshot más reciente en la DB, o None si está vacía."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT MAX(timestamp) FROM market_snapshots"
        ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ── Auto-trading positions ─────────────────────────────────────────────────

def insert_auto_position(data: Dict[str, Any]) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO auto_positions
            (alert_id, symbol, action, mode, exchange, exchange_order_id,
             open_time, entry_price, size_usdt, leverage, tp1, tp2, sl, sl_current)
        VALUES
            (:alert_id, :symbol, :action, :mode, :exchange, :exchange_order_id,
             :open_time, :entry_price, :size_usdt, :leverage, :tp1, :tp2, :sl, :sl_current)
        """,
        {
            "exchange":          data.get("exchange", "paper"),
            "exchange_order_id": data.get("exchange_order_id"),
            **data,
        },
    )
    conn.commit()
    return cur.lastrowid


def update_auto_position_exchange_order(position_id: int, exchange: str, order_id: str) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE auto_positions SET exchange=?, exchange_order_id=? WHERE id=?",
        (exchange, order_id, position_id),
    )
    conn.commit()


def get_open_auto_positions() -> List[Dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM auto_positions WHERE status = 'open' ORDER BY open_time"
    ).fetchall()
    return [dict(r) for r in rows]


def update_auto_position_tp1(position_id: int, tp1_pnl_usdt: float, new_sl: float) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE auto_positions SET tp1_hit=1, tp1_pnl_usdt=?, sl_current=? WHERE id=?",
        (tp1_pnl_usdt, new_sl, position_id),
    )
    conn.commit()


def close_auto_position(position_id: int, exit_price: float, close_reason: str,
                        final_pnl_usdt: float, total_pnl_usdt: float,
                        total_pnl_pct: float) -> None:
    conn = _get_conn()
    conn.execute(
        """
        UPDATE auto_positions SET
            status         = 'closed',
            close_time     = ?,
            exit_price     = ?,
            close_reason   = ?,
            final_pnl_usdt = ?,
            total_pnl_usdt = ?,
            total_pnl_pct  = ?
        WHERE id = ?
        """,
        (_now_iso(), exit_price, close_reason,
         final_pnl_usdt, total_pnl_usdt, total_pnl_pct,
         position_id),
    )
    conn.commit()


def get_auto_positions_summary(since_hours: float = 24.0) -> Dict[str, Any]:
    conn = _get_conn()
    cutoff = _ts_to_iso(time.time() - since_hours * 3600)
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                                    AS total,
            SUM(CASE WHEN close_reason = 'tp2'         THEN 1 ELSE 0 END) AS tp2_count,
            SUM(CASE WHEN close_reason = 'tp1_only'    THEN 1 ELSE 0 END) AS tp1_count,
            SUM(CASE WHEN close_reason IN ('sl','sl_breakeven','risk_cut') THEN 1 ELSE 0 END) AS sl_count,
            SUM(CASE WHEN close_reason = 'timeout'     THEN 1 ELSE 0 END) AS timeout_count,
            COALESCE(SUM(total_pnl_usdt), 0.0)                         AS total_pnl_usdt,
            COALESCE(AVG(total_pnl_pct),  0.0)                         AS avg_pnl_pct
        FROM auto_positions
        WHERE status = 'closed' AND close_time >= ?
        """,
        (cutoff,),
    ).fetchone()
    return {
        "total":         row["total"] or 0,
        "tp2_count":     row["tp2_count"] or 0,
        "tp1_count":     row["tp1_count"] or 0,
        "sl_count":      row["sl_count"] or 0,
        "timeout_count": row["timeout_count"] or 0,
        "total_pnl_usdt": round(row["total_pnl_usdt"] or 0.0, 4),
        "avg_pnl_pct":   round(row["avg_pnl_pct"] or 0.0, 2),
        "total_pnl_pct": round((row["total_pnl_usdt"] or 0.0), 4),
    }


def get_pnl_overview() -> Dict[str, Any]:
    """PnL acumulado historico (todas las fechas) por categoria: futures, spot y micro-scalping."""
    conn = _get_conn()

    def _positions_pnl(actions: tuple) -> Dict[str, Any]:
        placeholders = ",".join("?" for _ in actions)
        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN status = 'closed' THEN total_pnl_usdt ELSE 0 END), 0.0) AS pnl_usdt,
                SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN status = 'closed' AND total_pnl_usdt > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'closed' AND total_pnl_usdt <= 0 THEN 1 ELSE 0 END) AS losses
            FROM auto_positions
            WHERE action IN ({placeholders})
            """,
            actions,
        ).fetchone()
        closed = row["closed"] or 0
        wins = row["wins"] or 0
        return {
            "pnl_usdt": round(row["pnl_usdt"] or 0.0, 4),
            "closed": closed,
            "open": row["open_count"] or 0,
            "wins": wins,
            "losses": row["losses"] or 0,
            "winrate_pct": round(wins / closed * 100, 2) if closed else 0.0,
        }

    futures = _positions_pnl(("LONG_FUTURES", "SHORT_FUTURES"))
    spot = _positions_pnl(("BUY_SPOT", "SELL_SPOT"))

    ms_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN status = 'closed' THEN pnl_pct ELSE 0 END), 0.0) AS pnl_pct_total,
            COALESCE(AVG(CASE WHEN status = 'closed' THEN pnl_pct END), 0.0) AS pnl_pct_avg,
            SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
            SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN outcome IN ('win', 'partial') THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS losses
        FROM micro_scalp_alerts
        """
    ).fetchone()
    ms_closed = ms_row["closed"] or 0
    ms_wins = ms_row["wins"] or 0
    ms_losses = ms_row["losses"] or 0
    micro_scalp = {
        "pnl_pct_total": round(ms_row["pnl_pct_total"] or 0.0, 4),
        "pnl_pct_avg": round(ms_row["pnl_pct_avg"] or 0.0, 4),
        "closed": ms_closed,
        "open": ms_row["open_count"] or 0,
        "wins": ms_wins,
        "losses": ms_losses,
        "winrate_pct": round(ms_wins / (ms_wins + ms_losses) * 100, 2) if (ms_wins + ms_losses) else 0.0,
    }

    return {"futures": futures, "spot": spot, "micro_scalp": micro_scalp}


# ── Helpers ───────────────────────────────────────────────────────────────

# News intelligence observacional

def get_recent_symbols(limit: int = 20) -> List[str]:
    try:
        rows = _get_conn().execute(
            """
            SELECT symbol, MAX(id) AS latest_id
            FROM market_snapshots GROUP BY symbol
            ORDER BY latest_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row["symbol"] for row in rows]
    except Exception:
        logger.exception("Error al obtener simbolos recientes para noticias")
        return []


def get_latest_symbol_price(symbol: str) -> float:
    try:
        row = _get_conn().execute(
            """
            SELECT COALESCE(NULLIF(futures_price, 0), price) AS price
            FROM market_snapshots WHERE symbol=?
            ORDER BY timestamp DESC, id DESC LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        return float(row["price"] or 0.0) if row else 0.0
    except Exception:
        return 0.0


def get_latest_symbol_context(symbol: str) -> Dict[str, Any]:
    try:
        row = _get_conn().execute(
            """
            SELECT timestamp, COALESCE(NULLIF(futures_price, 0), price) AS price,
                   action, signal, score, return_5m, return_15m, return_1h,
                   relative_volume, cvd, cvd_15m, funding, oi_change_pct
            FROM market_snapshots WHERE symbol=?
            ORDER BY timestamp DESC, id DESC LIMIT 1
            """,
            (symbol,),
        ).fetchone()
        return dict(row) if row else {}
    except Exception:
        return {}


def insert_news_events(events: List[Dict[str, Any]]) -> int:
    if not events:
        return 0
    try:
        conn = _get_conn()
        before = conn.total_changes
        conn.executemany(
            """
            INSERT INTO news_events
                (event_id, symbol, source, source_domain, title, summary, url,
                 published_at, collected_at, event_type, sentiment_score,
                 weighted_score, prediction, credibility, event_types_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO UPDATE SET
                source_domain=excluded.source_domain,
                title=excluded.title,
                summary=excluded.summary,
                url=excluded.url,
                published_at=excluded.published_at,
                collected_at=excluded.collected_at,
                event_type=excluded.event_type,
                sentiment_score=excluded.sentiment_score,
                weighted_score=excluded.weighted_score,
                prediction=excluded.prediction,
                credibility=excluded.credibility,
                event_types_json=excluded.event_types_json
            """,
            [(
                event.get("event_id", ""), event.get("symbol", ""),
                event.get("source", ""), event.get("source_domain", ""),
                event.get("title", ""), event.get("summary", ""),
                event.get("url", ""), event.get("published_at", _now_iso()),
                _now_iso(), event.get("event_type", "general"),
                event.get("sentiment_score", 0.0), event.get("weighted_score", 0.0),
                event.get("prediction", "NEUTRAL"), event.get("credibility", 0.0),
                json.dumps(event.get("event_types", [])),
            ) for event in events],
        )
        conn.commit()
        return conn.total_changes - before
    except Exception:
        logger.exception("Error insertando news_events")
        return 0


def insert_news_prediction(prediction: Dict[str, Any]) -> Optional[int]:
    try:
        conn = _get_conn()
        cur = conn.execute(
            """
            INSERT INTO news_predictions
                (timestamp, symbol, prediction, sentiment_score, confidence,
                 news_count, positive_count, negative_count, contradictory,
                 top_events_json, price_at_prediction, horizon_minutes, outcome)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'open')
            """,
            (
                prediction.get("timestamp", _now_iso()), prediction.get("symbol", ""),
                prediction.get("prediction", "NEUTRAL"), prediction.get("sentiment_score", 0.0),
                prediction.get("confidence", 0), prediction.get("news_count", 0),
                prediction.get("positive_count", 0), prediction.get("negative_count", 0),
                int(prediction.get("contradictory", False)),
                json.dumps(prediction.get("top_events", [])),
                prediction.get("price_at_prediction", 0.0),
                prediction.get("horizon_minutes", 60),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        logger.exception("Error insertando news_prediction")
        return None


def upsert_security_event_alert(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste incidente y decide si amerita notificacion nueva/escalada."""
    try:
        conn = _get_conn()
        existing = conn.execute(
            "SELECT * FROM security_event_alerts WHERE fingerprint=?",
            (alert["fingerprint"],),
        ).fetchone()
        should_notify = existing is None
        if existing:
            should_notify = (
                existing["confirmation_status"] != alert["confirmation_status"]
                or float(alert["security_score"]) <= float(existing["security_score"]) - 10
                or int(alert["source_count"]) > int(existing["source_count"])
            )
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO security_event_alerts
                (fingerprint, created_at, updated_at, symbol, severity,
                 confirmation_status, security_score, source_count,
                 official_source_count, first_published_at, title, analysis_json,
                 last_notified_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                updated_at=excluded.updated_at,
                severity=excluded.severity,
                confirmation_status=excluded.confirmation_status,
                security_score=excluded.security_score,
                source_count=excluded.source_count,
                official_source_count=excluded.official_source_count,
                first_published_at=excluded.first_published_at,
                title=excluded.title,
                analysis_json=excluded.analysis_json,
                last_notified_at=CASE
                    WHEN excluded.last_notified_at IS NOT NULL THEN excluded.last_notified_at
                    ELSE security_event_alerts.last_notified_at
                END
            """,
            (
                alert["fingerprint"], now, now, alert["symbol"], alert["severity"],
                alert["confirmation_status"], alert["security_score"], alert["source_count"],
                alert["official_source_count"], alert["first_published_at"], alert["title"],
                json.dumps(alert), now if should_notify else None,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM security_event_alerts WHERE fingerprint=?",
            (alert["fingerprint"],),
        ).fetchone()
        return {"id": row["id"] if row else None, "should_notify": should_notify}
    except Exception:
        logger.exception("Error persistiendo security_event_alert")
        return {"id": None, "should_notify": False}


def evaluate_open_news_predictions(horizon_minutes: int = 60) -> int:
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - horizon_minutes * 60)
        rows = conn.execute(
            "SELECT * FROM news_predictions WHERE outcome='open' AND timestamp<=? ORDER BY timestamp",
            (cutoff,),
        ).fetchall()
        updated = 0
        for row in rows:
            target_epoch = _iso_to_ts(row["timestamp"]) + int(row["horizon_minutes"] or horizon_minutes) * 60
            snapshot = conn.execute(
                """
                SELECT COALESCE(NULLIF(futures_price, 0), price) AS price
                FROM market_snapshots WHERE symbol=? AND timestamp>=?
                ORDER BY timestamp ASC, id ASC LIMIT 1
                """,
                (row["symbol"], _ts_to_iso(target_epoch)),
            ).fetchone()
            start_price = float(row["price_at_prediction"] or 0.0)
            end_price = float(snapshot["price"] or 0.0) if snapshot else 0.0
            if start_price <= 0 or end_price <= 0:
                continue
            return_pct = (end_price - start_price) / start_price * 100.0
            if row["prediction"] == "BULLISH":
                outcome = "correct" if return_pct > 0.2 else "incorrect" if return_pct < -0.2 else "neutral"
            elif row["prediction"] == "BEARISH":
                outcome = "correct" if return_pct < -0.2 else "incorrect" if return_pct > 0.2 else "neutral"
            else:
                outcome = "neutral"
            conn.execute(
                """
                UPDATE news_predictions SET evaluated_at=?, price_at_outcome=?,
                    return_pct=?, outcome=? WHERE id=?
                """,
                (_now_iso(), end_price, round(return_pct, 4), outcome, row["id"]),
            )
            updated += 1
        conn.commit()
        return updated
    except Exception:
        logger.exception("Error evaluando news_predictions")
        return 0


def get_news_report(since_hours: float = 1.0) -> Dict[str, Any]:
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - since_hours * 3600)
        predictions = conn.execute(
            """
            SELECT * FROM (
                SELECT news_predictions.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY symbol ORDER BY timestamp DESC, id DESC
                       ) AS report_rank
                FROM news_predictions
                WHERE timestamp>=?
            )
            WHERE report_rank=1
            ORDER BY ABS(sentiment_score) DESC, confidence DESC
            """,
            (cutoff,),
        ).fetchall()
        performance = conn.execute(
            "SELECT outcome, COUNT(*) total FROM news_predictions WHERE evaluated_at>=? GROUP BY outcome",
            (cutoff,),
        ).fetchall()
        return {
            "predictions": [dict(row) for row in predictions],
            "performance": {row["outcome"]: row["total"] for row in performance},
        }
    except Exception:
        logger.exception("Error generando news_report")
        return {"predictions": [], "performance": {}}


def _iso_to_ts(value: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _ts_to_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))


def count_recent_auto_losses(symbol: str, action: str, since_hours: float = 6.0) -> int:
    """Cuenta cierres perdedores consecutivos recientes para un simbolo/direccion."""
    try:
        cutoff = _ts_to_iso(time.time() - since_hours * 3600)
        rows = _get_conn().execute(
            """SELECT total_pnl_usdt FROM auto_positions
               WHERE symbol=? AND action=? AND status='closed' AND close_time>=?
               ORDER BY close_time DESC LIMIT 20""",
            (symbol, action, cutoff),
        ).fetchall()
        consecutive = 0
        for row in rows:
            if float(row["total_pnl_usdt"] or 0) < 0:
                consecutive += 1
            else:
                break
        return consecutive
    except Exception:
        logger.exception("Error contando perdidas consecutivas")
        return 0


def get_news_dashboard(since_hours: float = 24.0, event_limit: int = 40) -> Dict[str, Any]:
    """Datos compactos para mostrar noticias y tendencia estimada en dashboard."""
    empty = {"predictions": [], "events": [], "performance": {}}
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - since_hours * 3600)
        predictions = conn.execute(
            """
            SELECT * FROM (
                SELECT news_predictions.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY symbol ORDER BY timestamp DESC, id DESC
                       ) AS dashboard_rank
                FROM news_predictions
                WHERE timestamp>=?
            )
            WHERE dashboard_rank=1
            ORDER BY ABS(sentiment_score) DESC, confidence DESC
            """,
            (cutoff,),
        ).fetchall()
        events = conn.execute(
            """
            SELECT symbol, source, source_domain, title, summary, url,
                   published_at, event_type, sentiment_score, weighted_score,
                   prediction, credibility, event_types_json
            FROM news_events
            WHERE published_at>=?
            ORDER BY published_at DESC, ABS(weighted_score) DESC
            LIMIT ?
            """,
            (cutoff, max(1, int(event_limit))),
        ).fetchall()
        performance = conn.execute(
            """
            SELECT outcome, COUNT(*) total
            FROM news_predictions
            WHERE evaluated_at>=? AND outcome<>'open'
            GROUP BY outcome
            """,
            (cutoff,),
        ).fetchall()
        return {
            "predictions": [dict(row) for row in predictions],
            "events": [dict(row) for row in events],
            "performance": {row["outcome"]: row["total"] for row in performance},
        }
    except Exception:
        logger.exception("Error generando datos de noticias para dashboard")
        return empty


# ── Accumulation Watch ─────────────────────────────────────────────────────

def upsert_accumulation_watch(data: Dict[str, Any]) -> None:
    """Inserta o actualiza el estado de coiling de un símbolo.

    En conflicto (símbolo ya existe), conserva `first_seen`, `funding_at_watch`
    y `price_at_watch` originales (línea base de la "vigilancia"), y solo
    refresca las métricas de coiling y `last_scan`. El status vuelve a
    'watching' salvo que ya esté 'ignited'.
    """
    try:
        conn = _get_conn()
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO accumulation_watch (
                symbol, first_seen, last_scan, coiling_score, contraction_ratio,
                position_in_range, above_sma50, vol_ratio_7_30, quote_volume,
                funding_at_watch, price_at_watch, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'watching')
            ON CONFLICT(symbol) DO UPDATE SET
                last_scan = excluded.last_scan,
                coiling_score = excluded.coiling_score,
                contraction_ratio = excluded.contraction_ratio,
                position_in_range = excluded.position_in_range,
                above_sma50 = excluded.above_sma50,
                vol_ratio_7_30 = excluded.vol_ratio_7_30,
                quote_volume = excluded.quote_volume,
                status = CASE
                    WHEN accumulation_watch.status = 'ignited' THEN accumulation_watch.status
                    ELSE 'watching'
                END
            """,
            (
                data["symbol"], now, now,
                data.get("coiling_score", 0.0),
                data.get("contraction_ratio", 0.0),
                data.get("position_in_range", 0.0),
                int(bool(data.get("above_sma50", False))),
                data.get("vol_ratio_7_30", 0.0),
                data.get("quote_volume", 0.0),
                data.get("funding_at_watch", 0.0),
                data.get("price_at_watch", 0.0),
            ),
        )
        conn.commit()
    except Exception:
        logger.exception("Error guardando accumulation_watch para %s", data.get("symbol"))


def expire_stale_accumulation_watch(max_age_hours: float) -> int:
    """Marca como 'expired' símbolos no re-confirmados en el último scan
    (status='watching') o ignitions ya antiguas (status='ignited')."""
    try:
        conn = _get_conn()
        cutoff = _ts_to_iso(time.time() - max_age_hours * 3600)
        cur = conn.execute(
            """
            UPDATE accumulation_watch SET status='expired'
            WHERE status='watching' AND last_scan < ?
            """,
            (cutoff,),
        )
        cur2 = conn.execute(
            """
            UPDATE accumulation_watch SET status='expired'
            WHERE status='ignited' AND ignited_at IS NOT NULL AND ignited_at < ?
            """,
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount + cur2.rowcount
    except Exception:
        logger.exception("Error expirando accumulation_watch")
        return 0


def get_accumulation_watchlist_symbols(limit: int) -> List[str]:
    """Símbolos activos (watching/ignited) ordenados por coiling_score desc."""
    try:
        rows = _get_conn().execute(
            """
            SELECT symbol FROM accumulation_watch
            WHERE status IN ('watching', 'ignited')
            ORDER BY coiling_score DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [row["symbol"] for row in rows]
    except Exception:
        logger.exception("Error obteniendo accumulation watchlist")
        return []


def get_accumulation_watch_map() -> Dict[str, Dict[str, Any]]:
    """Mapa symbol -> fila completa, para chequeo de disparadores de ignición."""
    try:
        rows = _get_conn().execute(
            "SELECT * FROM accumulation_watch WHERE status IN ('watching', 'ignited')"
        ).fetchall()
        return {row["symbol"]: dict(row) for row in rows}
    except Exception:
        logger.exception("Error obteniendo accumulation_watch_map")
        return {}


def mark_accumulation_ignited(symbol: str, reason: str) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            """
            UPDATE accumulation_watch
            SET status='ignited', ignited_at=?, ignition_reason=?
            WHERE symbol=?
            """,
            (_now_iso(), reason, symbol),
        )
        conn.commit()
    except Exception:
        logger.exception("Error marcando ignition para %s", symbol)


def get_accumulation_watch_list(limit: int = 50) -> List[Dict[str, Any]]:
    """Lista completa para dashboard/diagnóstico, ordenada por relevancia."""
    try:
        rows = _get_conn().execute(
            """
            SELECT * FROM accumulation_watch
            WHERE status IN ('watching', 'ignited')
            ORDER BY (status = 'ignited') DESC, coiling_score DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        logger.exception("Error listando accumulation_watch")
        return []
