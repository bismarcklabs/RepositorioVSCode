-- Estado por (strategy_id, symbol) del framework multi-estrategia: value area
-- de la sesion, CVD acumulado de sesion, sesgo y divergencia pendiente. Se
-- actualiza cada ciclo (upsert) para que el dashboard (proceso separado,
-- solo lee DB) pueda mostrar anticipacion de tendencia / breakout / falso
-- breakout sin acceder al estado en memoria del scanner.

CREATE TABLE IF NOT EXISTS strategy_symbol_state (
    strategy_id        TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    value_area_json    TEXT DEFAULT '{}',
    cvd_session        REAL DEFAULT 0.0,
    bias               TEXT DEFAULT '',
    divergence_pending TEXT DEFAULT '',
    last_signal_reason TEXT DEFAULT '',
    PRIMARY KEY (strategy_id, symbol)
);
