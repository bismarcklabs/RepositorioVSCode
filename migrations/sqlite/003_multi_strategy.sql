-- Framework multi-estrategia: alertas y posiciones paper de estrategias
-- adicionales al pipeline institucional (trade_alerts/auto_positions) y al
-- micro-scalper (micro_scalp_alerts). Cada estrategia es un modulo
-- independiente identificado por strategy_id; nunca se mezcla con las
-- tablas existentes. direction es explicito (LONG/SHORT), nunca inferido
-- de un string de action arbitrario.

CREATE TABLE IF NOT EXISTS strategy_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    strategy_id     TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,        -- LONG | SHORT
    score           INTEGER DEFAULT 0,
    confidence      INTEGER DEFAULT 0,
    entry           REAL,
    take_profit_1   REAL,
    take_profit_2   REAL,
    stop_loss       REAL,
    leverage        INTEGER DEFAULT 1,
    timeout_hours   REAL DEFAULT 4,
    reasons_json    TEXT DEFAULT '[]',
    warnings_json   TEXT DEFAULT '[]',
    status          TEXT DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_strategy_alerts_sid_sym_ts
    ON strategy_alerts(strategy_id, symbol, timestamp);

CREATE TABLE IF NOT EXISTS strategy_positions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id          INTEGER REFERENCES strategy_alerts(id),
    strategy_id       TEXT    NOT NULL,
    symbol            TEXT    NOT NULL,
    direction         TEXT    NOT NULL,      -- LONG | SHORT
    mode              TEXT    NOT NULL DEFAULT 'paper',
    open_time         TEXT    NOT NULL,
    close_time        TEXT,
    entry_price       REAL    NOT NULL,
    size_usdt         REAL    NOT NULL,
    leverage          INTEGER NOT NULL DEFAULT 1,
    timeout_hours     REAL    NOT NULL DEFAULT 4,
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

CREATE INDEX IF NOT EXISTS idx_strategy_pos_sid_status
    ON strategy_positions(strategy_id, status);
CREATE INDEX IF NOT EXISTS idx_strategy_pos_sid_symbol
    ON strategy_positions(strategy_id, symbol, status);
