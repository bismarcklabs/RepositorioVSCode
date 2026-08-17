-- Marca filas de market_snapshots reconstruidas por snapshot_backfill.py
-- (downtime real del scanner: precio de klines + delta aproximado de
-- taker_buy_volume, no el delta exacto del tape de trades en vivo) para
-- poder distinguirlas de un ciclo real del scanner.

ALTER TABLE market_snapshots ADD COLUMN IF NOT EXISTS is_backfilled INTEGER DEFAULT 0;
