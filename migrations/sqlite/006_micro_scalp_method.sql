-- Formaliza el metodo de entrada del micro-scalp ("nivel" = rebote en
-- soporte/resistencia, "momentum" = el resto) como campo explicito en vez de
-- inferirlo post-hoc del texto en reasons_json. "nivel" ya mostro mejor WR y
-- MFE/MAE mucho mas controlado en el diagnostico 2026-07-25 — se usa tambien
-- para asignar un tamano de posicion ligeramente mayor a esos setups.

ALTER TABLE micro_scalp_alerts ADD COLUMN method TEXT DEFAULT '';
ALTER TABLE micro_scalp_alerts ADD COLUMN trade_size_usdt REAL DEFAULT 0;
