-- Framework multi-estrategia: alertas y posiciones paper de estrategias
-- adicionales al pipeline institucional (trade_alerts/auto_positions) y al
-- micro-scalper (micro_scalp_alerts). Cada estrategia es un modulo
-- independiente identificado por strategy_id; nunca se mezcla con las
-- tablas existentes. direction es explicito (LONG/SHORT), nunca inferido
-- de un string de action arbitrario.

CREATE TABLE IF NOT EXISTS strategy_alerts (
    id              SERIAL PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    strategy_id     TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    direction       TEXT    NOT NULL,        -- LONG | SHORT
    score           INTEGER DEFAULT 0,
    confidence      INTEGER DEFAULT 0,
    entry           DOUBLE PRECISION,
    take_profit_1   DOUBLE PRECISION,
    take_profit_2   DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    leverage        INTEGER DEFAULT 1,
    timeout_hours   DOUBLE PRECISION DEFAULT 4,
    reasons_json    TEXT DEFAULT '[]',
    warnings_json   TEXT DEFAULT '[]',
    status          TEXT DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_strategy_alerts_sid_sym_ts
    ON strategy_alerts(strategy_id, symbol, timestamp);

CREATE TABLE IF NOT EXISTS strategy_positions (
    id                SERIAL PRIMARY KEY,
    alert_id          INTEGER REFERENCES strategy_alerts(id),
    strategy_id       TEXT    NOT NULL,
    symbol            TEXT    NOT NULL,
    direction         TEXT    NOT NULL,      -- LONG | SHORT
    mode              TEXT    NOT NULL DEFAULT 'paper',
    open_time         TEXT    NOT NULL,
    close_time        TEXT,
    entry_price       DOUBLE PRECISION    NOT NULL,
    size_usdt         DOUBLE PRECISION    NOT NULL,
    leverage          INTEGER NOT NULL DEFAULT 1,
    timeout_hours     DOUBLE PRECISION NOT NULL DEFAULT 4,
    tp1               DOUBLE PRECISION,
    tp2               DOUBLE PRECISION,
    sl                DOUBLE PRECISION    NOT NULL,
    sl_current        DOUBLE PRECISION    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'open',
    tp1_hit           INTEGER NOT NULL DEFAULT 0,
    tp1_pnl_usdt      DOUBLE PRECISION    NOT NULL DEFAULT 0.0,
    close_reason      TEXT,
    exit_price        DOUBLE PRECISION,
    final_pnl_usdt    DOUBLE PRECISION,
    total_pnl_usdt    DOUBLE PRECISION,
    total_pnl_pct     DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_strategy_pos_sid_status
    ON strategy_positions(strategy_id, status);
CREATE INDEX IF NOT EXISTS idx_strategy_pos_sid_symbol
    ON strategy_positions(strategy_id, symbol, status);
