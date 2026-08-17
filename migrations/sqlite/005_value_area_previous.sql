-- Guarda el value area de la sesion overnight recien completada (la "anterior"
-- respecto a la que se esta construyendo ahora) para que el dashboard pueda
-- graficar ambos rectangulos (dia anterior + dia en curso) sin recalcular ni
-- volver a pedir velas a Binance.

ALTER TABLE strategy_symbol_state ADD COLUMN previous_value_area_json TEXT DEFAULT '{}';
