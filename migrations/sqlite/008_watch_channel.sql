-- Generaliza accumulation_watch de "solo coiling" a una watchlist
-- multi-canal: coiling (contraccion de volatilidad), volatility_breakout
-- (expansion ya en marcha, mismo contraction_ratio pero invertido),
-- funding_extreme y oi_acceleration. channel_score es la columna generica
-- de ranking entre canales (coiling_score se mantiene solo para no romper
-- lecturas existentes de ese canal especifico).

ALTER TABLE accumulation_watch ADD COLUMN channel TEXT DEFAULT 'coiling';
ALTER TABLE accumulation_watch ADD COLUMN channel_score REAL DEFAULT 0;
ALTER TABLE accumulation_watch ADD COLUMN metrics_json TEXT DEFAULT '{}';
