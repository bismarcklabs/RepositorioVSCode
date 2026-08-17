-- Migration 001: Initial schema (PostgreSQL)
-- Translated from migrations/sqlite/001_initial.sql using the rules
-- documented in the SSN MIGRATION_GUIDE.md.

CREATE TABLE IF NOT EXISTS market_snapshots (
    id              SERIAL PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    price           DOUBLE PRECISION,
    futures_price   DOUBLE PRECISION,
    action          TEXT,
    market          TEXT,
    confidence      INTEGER,
    score           INTEGER,
    signal          TEXT,
    risk_level      TEXT,

    delta           DOUBLE PRECISION,
    cvd             DOUBLE PRECISION,
    buy_volume      DOUBLE PRECISION,
    sell_volume     DOUBLE PRECISION,
    funding         DOUBLE PRECISION,
    open_interest   DOUBLE PRECISION,
    imbalance       DOUBLE PRECISION,
    spread_pct      DOUBLE PRECISION,

    return_3m       DOUBLE PRECISION DEFAULT 0,
    return_5m       DOUBLE PRECISION DEFAULT 0,
    return_15m      DOUBLE PRECISION DEFAULT 0,
    return_1h       DOUBLE PRECISION DEFAULT 0,
    vwap            DOUBLE PRECISION DEFAULT 0,
    vwap_distance_pct DOUBLE PRECISION DEFAULT 0,
    above_vwap      INTEGER DEFAULT 1,
    relative_volume DOUBLE PRECISION DEFAULT 1,
    trend_bias      TEXT DEFAULT 'neutral',

    poc             DOUBLE PRECISION DEFAULT 0,
    nearest_vp_level DOUBLE PRECISION DEFAULT 0,
    nearest_vp_type  TEXT DEFAULT 'NONE',
    vp_distance     DOUBLE PRECISION DEFAULT 0,

    footprint_delta      DOUBLE PRECISION DEFAULT 0,
    absorption_buy       INTEGER DEFAULT 0,
    absorption_sell      INTEGER DEFAULT 0,
    stacked_buy_imbalance  INTEGER DEFAULT 0,
    stacked_sell_imbalance INTEGER DEFAULT 0,

    gex_available   INTEGER DEFAULT 0,
    gex_score       INTEGER DEFAULT 0,
    call_wall       DOUBLE PRECISION DEFAULT 0,
    put_wall        DOUBLE PRECISION DEFAULT 0,
    gamma_flip      DOUBLE PRECISION DEFAULT 0,

    entry           DOUBLE PRECISION DEFAULT 0,
    entry_zone_low  DOUBLE PRECISION DEFAULT 0,
    entry_zone_high DOUBLE PRECISION DEFAULT 0,
    stop_loss       DOUBLE PRECISION DEFAULT 0,
    take_profit_1   DOUBLE PRECISION DEFAULT 0,
    take_profit_2   DOUBLE PRECISION DEFAULT 0,
    risk_reward_1   DOUBLE PRECISION DEFAULT 0,
    risk_reward_2   DOUBLE PRECISION DEFAULT 0,

    reasons_json    TEXT DEFAULT '[]',
    warnings_json   TEXT DEFAULT '[]',
    invalidation_json TEXT DEFAULT '[]',

    cvd_15m              DOUBLE PRECISION DEFAULT 0,
    atr                  DOUBLE PRECISION DEFAULT 0,
    atr_pct              DOUBLE PRECISION DEFAULT 0,
    htf_trend_bias       TEXT DEFAULT 'neutral',
    rsi                  DOUBLE PRECISION DEFAULT 50,
    oi_change_pct        DOUBLE PRECISION DEFAULT 0,
    flow_score           INTEGER DEFAULT 0,
    technical_score      INTEGER DEFAULT 0,
    volume_profile_score INTEGER DEFAULT 0,
    footprint_score      INTEGER DEFAULT 0,
    futures_score        INTEGER DEFAULT 0,
    risk_penalty         INTEGER DEFAULT 0,
    confluence_score     INTEGER DEFAULT 0,
    recommendation_json          TEXT DEFAULT '{}',
    signal_json                  TEXT DEFAULT '{}',
    alert_report_json            TEXT DEFAULT '{}',
    multi_exchange_score         INTEGER DEFAULT 0,
    multi_exchange_confidence    DOUBLE PRECISION,
    price_deviation_pct          DOUBLE PRECISION,
    exchange_availability_score  DOUBLE PRECISION,
    setup_valid                  INTEGER DEFAULT 0,
    setup_grade                  TEXT DEFAULT '',
    setup_score                  INTEGER DEFAULT 0,
    trigger_type                 TEXT DEFAULT '',
    ml_probability               DOUBLE PRECISION,
    ml_filtered                  INTEGER DEFAULT 0,
    trend_priority_score       INTEGER DEFAULT 0,
    momentum_continuation      INTEGER DEFAULT 0,
    momentum_persistence_count INTEGER DEFAULT 0,
    setup_route                TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_snapshots_sym_ts
    ON market_snapshots(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts
    ON market_snapshots(timestamp);

CREATE TABLE IF NOT EXISTS trade_alerts (
    id              SERIAL PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    market          TEXT    NOT NULL,
    confidence      INTEGER,
    score           INTEGER,
    price           DOUBLE PRECISION,
    entry           DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    take_profit_1   DOUBLE PRECISION,
    take_profit_2   DOUBLE PRECISION,
    risk_reward_1   DOUBLE PRECISION,
    risk_reward_2   DOUBLE PRECISION,
    status          TEXT    DEFAULT 'open',
    setup_grade    TEXT DEFAULT '',
    setup_score    INTEGER DEFAULT 0,
    trigger_type   TEXT DEFAULT '',
    ml_probability DOUBLE PRECISION,
    ml_filtered    INTEGER DEFAULT 0,
    setup_route          TEXT DEFAULT '',
    trend_priority_score INTEGER DEFAULT 0,
    original_setup_grade TEXT DEFAULT '',
    calibrated_grade     TEXT DEFAULT '',
    direction_score      INTEGER DEFAULT 0,
    entry_score          INTEGER DEFAULT 0,
    risk_score           INTEGER DEFAULT 0,
    calibration_version  TEXT DEFAULT '',
    btc_regime           TEXT DEFAULT 'NORMAL',
    watch_type           TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_alerts_sym_ts
    ON trade_alerts(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_status
    ON trade_alerts(status);

CREATE TABLE IF NOT EXISTS notification_log (
    id              SERIAL PRIMARY KEY,
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
    id                      SERIAL PRIMARY KEY,
    alert_id                INTEGER NOT NULL REFERENCES trade_alerts(id),
    checked_at              TEXT    NOT NULL,
    horizon_minutes         INTEGER NOT NULL,
    price_at_check          DOUBLE PRECISION,
    future_return_pct       DOUBLE PRECISION,
    max_favorable_excursion DOUBLE PRECISION,
    max_adverse_excursion   DOUBLE PRECISION,
    hit_tp1                 INTEGER DEFAULT 0,
    hit_tp2                 INTEGER DEFAULT 0,
    hit_stop                INTEGER DEFAULT 0,
    outcome                 TEXT    DEFAULT 'unknown',
    UNIQUE(alert_id, horizon_minutes)
);

CREATE INDEX IF NOT EXISTS idx_outcomes_alert_id
    ON alert_outcomes(alert_id);

CREATE TABLE IF NOT EXISTS auto_positions (
    id                SERIAL PRIMARY KEY,
    alert_id          INTEGER REFERENCES trade_alerts(id),
    symbol            TEXT    NOT NULL,
    action            TEXT    NOT NULL,
    mode              TEXT    NOT NULL DEFAULT 'paper',
    exchange          TEXT    NOT NULL DEFAULT 'paper',
    exchange_order_id TEXT,
    open_time         TEXT    NOT NULL,
    close_time        TEXT,
    entry_price       DOUBLE PRECISION    NOT NULL,
    size_usdt         DOUBLE PRECISION    NOT NULL,
    leverage          INTEGER NOT NULL DEFAULT 1,
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

CREATE INDEX IF NOT EXISTS idx_autopos_status
    ON auto_positions(status);
CREATE INDEX IF NOT EXISTS idx_autopos_symbol
    ON auto_positions(symbol, status);

CREATE TABLE IF NOT EXISTS exchange_market_snapshots (
    id              SERIAL PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    binance_symbol  TEXT    NOT NULL,
    exchange        TEXT    NOT NULL,
    exchange_symbol TEXT    NOT NULL DEFAULT '',
    price           DOUBLE PRECISION,
    bid             DOUBLE PRECISION,
    ask             DOUBLE PRECISION,
    spread_pct      DOUBLE PRECISION,
    volume_24h      DOUBLE PRECISION,
    ok              INTEGER DEFAULT 1,
    error           TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_exsnap_sym_ts
    ON exchange_market_snapshots(binance_symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_exsnap_ts
    ON exchange_market_snapshots(timestamp);

CREATE TABLE IF NOT EXISTS multi_exchange_metrics (
    id                          SERIAL PRIMARY KEY,
    timestamp                   TEXT    NOT NULL,
    symbol                      TEXT    NOT NULL,
    binance_symbol              TEXT    NOT NULL,
    binance_price               DOUBLE PRECISION,
    coinbase_price              DOUBLE PRECISION,
    kraken_price                DOUBLE PRECISION,
    price_deviation_pct         DOUBLE PRECISION,
    exchange_availability_score DOUBLE PRECISION,
    multi_exchange_confidence   DOUBLE PRECISION,
    multi_exchange_score        INTEGER DEFAULT 0,
    warnings_json               TEXT    DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_mexmetrics_sym_ts
    ON multi_exchange_metrics(binance_symbol, timestamp);

CREATE TABLE IF NOT EXISTS micro_scalp_alerts (
    id              SERIAL PRIMARY KEY,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    score           INTEGER NOT NULL,
    confidence      INTEGER DEFAULT 0,
    entry           DOUBLE PRECISION,
    take_profit_1   DOUBLE PRECISION,
    take_profit_2   DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    timeout_minutes INTEGER DEFAULT 10,
    return_3m       DOUBLE PRECISION DEFAULT 0,
    return_5m       DOUBLE PRECISION DEFAULT 0,
    relative_volume DOUBLE PRECISION DEFAULT 1,
    delta           DOUBLE PRECISION DEFAULT 0,
    cvd_15m         DOUBLE PRECISION DEFAULT 0,
    footprint_delta DOUBLE PRECISION DEFAULT 0,
    imbalance       DOUBLE PRECISION DEFAULT 0,
    oi_change_pct   DOUBLE PRECISION DEFAULT 0,
    funding         DOUBLE PRECISION DEFAULT 0,
    status          TEXT DEFAULT 'open',
    close_time      TEXT,
    exit_price      DOUBLE PRECISION,
    outcome         TEXT DEFAULT 'open',
    hit_tp1         INTEGER DEFAULT 0,
    hit_tp2         INTEGER DEFAULT 0,
    hit_stop        INTEGER DEFAULT 0,
    pnl_pct         DOUBLE PRECISION DEFAULT 0,
    max_favorable_pct DOUBLE PRECISION DEFAULT 0,
    max_adverse_pct DOUBLE PRECISION DEFAULT 0,
    pnl_usdt        DOUBLE PRECISION DEFAULT 0,
    reasons_json    TEXT DEFAULT '[]',
    warnings_json   TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_micro_scalp_sym_ts
    ON micro_scalp_alerts(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_micro_scalp_status
    ON micro_scalp_alerts(status);

CREATE TABLE IF NOT EXISTS micro_notification_log (
    id              SERIAL PRIMARY KEY,
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
    id              SERIAL PRIMARY KEY,
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
    sentiment_score DOUBLE PRECISION DEFAULT 0,
    weighted_score  DOUBLE PRECISION DEFAULT 0,
    prediction      TEXT DEFAULT 'NEUTRAL',
    credibility     DOUBLE PRECISION DEFAULT 0,
    event_types_json TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_news_events_sym_ts
    ON news_events(symbol, published_at);

CREATE TABLE IF NOT EXISTS news_predictions (
    id                  SERIAL PRIMARY KEY,
    timestamp           TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    prediction          TEXT NOT NULL,
    sentiment_score     DOUBLE PRECISION DEFAULT 0,
    confidence          INTEGER DEFAULT 0,
    news_count          INTEGER DEFAULT 0,
    positive_count      INTEGER DEFAULT 0,
    negative_count      INTEGER DEFAULT 0,
    contradictory       INTEGER DEFAULT 0,
    top_events_json     TEXT DEFAULT '[]',
    price_at_prediction DOUBLE PRECISION,
    horizon_minutes     INTEGER DEFAULT 60,
    evaluated_at        TEXT,
    price_at_outcome    DOUBLE PRECISION,
    return_pct          DOUBLE PRECISION,
    outcome             TEXT DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_news_predictions_status
    ON news_predictions(outcome, timestamp);
CREATE INDEX IF NOT EXISTS idx_news_predictions_sym_ts
    ON news_predictions(symbol, timestamp);

CREATE TABLE IF NOT EXISTS security_event_alerts (
    id                    SERIAL PRIMARY KEY,
    fingerprint           TEXT NOT NULL UNIQUE,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    symbol                TEXT NOT NULL,
    severity              TEXT NOT NULL,
    confirmation_status   TEXT NOT NULL,
    security_score        DOUBLE PRECISION DEFAULT 0,
    source_count          INTEGER DEFAULT 0,
    official_source_count INTEGER DEFAULT 0,
    first_published_at    TEXT,
    title                 TEXT NOT NULL,
    analysis_json         TEXT DEFAULT '{}',
    last_notified_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_alerts_sym_ts
    ON security_event_alerts(symbol, created_at);

CREATE TABLE IF NOT EXISTS accumulation_watch (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT    NOT NULL UNIQUE,
    first_seen          TEXT    NOT NULL,
    last_scan           TEXT    NOT NULL,
    coiling_score       DOUBLE PRECISION    DEFAULT 0,
    contraction_ratio   DOUBLE PRECISION    DEFAULT 0,
    position_in_range   DOUBLE PRECISION    DEFAULT 0,
    above_sma50         INTEGER DEFAULT 0,
    vol_ratio_7_30      DOUBLE PRECISION    DEFAULT 0,
    quote_volume        DOUBLE PRECISION    DEFAULT 0,
    funding_at_watch    DOUBLE PRECISION    DEFAULT 0,
    price_at_watch      DOUBLE PRECISION    DEFAULT 0,
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
    open_time  BIGINT NOT NULL,
    open       DOUBLE PRECISION    NOT NULL,
    high       DOUBLE PRECISION    NOT NULL,
    low        DOUBLE PRECISION    NOT NULL,
    close      DOUBLE PRECISION    NOT NULL,
    volume     DOUBLE PRECISION    NOT NULL,
    PRIMARY KEY (symbol, interval, open_time)
);

CREATE INDEX IF NOT EXISTS idx_hk_symbol_interval
    ON historical_klines(symbol, interval);