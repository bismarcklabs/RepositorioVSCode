-- Estructura chartista 3m (structure_micro compactada) por snapshot:
-- niveles S/R, breakout, patrones y rango. Alimenta el panel de setups
-- de estructura del dashboard (modo DB-display).
ALTER TABLE market_snapshots ADD COLUMN structure_json TEXT DEFAULT '{}';
