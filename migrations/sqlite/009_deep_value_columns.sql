-- Distancia al minimo historico real (ATL, via historical_cache/klines 1d
-- completas) y tiempo en zona de acumulacion cerca de esos minimos.
-- Columnas dedicadas (no metrics_json) porque el ATL no depende del canal
-- que detecto al simbolo (coiling/volatility_breakout/funding_extreme/
-- oi_acceleration) y el panel del dashboard necesita ordenar/filtrar por
-- dist_to_atl_pct en SQL.

ALTER TABLE accumulation_watch ADD COLUMN atl_price REAL;
ALTER TABLE accumulation_watch ADD COLUMN atl_date TEXT;
ALTER TABLE accumulation_watch ADD COLUMN dist_to_atl_pct REAL;
ALTER TABLE accumulation_watch ADD COLUMN days_in_atl_zone INTEGER DEFAULT 0;
ALTER TABLE accumulation_watch ADD COLUMN deep_value_checked_at TEXT;

CREATE INDEX IF NOT EXISTS idx_accum_watch_dist_atl ON accumulation_watch(dist_to_atl_pct);
