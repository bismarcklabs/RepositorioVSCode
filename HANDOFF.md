# Handoff — Estado del proyecto

> Documento de continuidad para retomar trabajo en otra sesión. Última actualización: 2026-07-27.
> Para arquitectura general del scanner, ver [README.md](README.md). Este documento cubre **cambios recientes, hallazgos y pendientes** que el README no refleja todavía.

## 0l. Actualización 2026-07-27 — Value Area + CVD en dashboard, backfill de huecos y descubrimiento de candidatos fuera del volumen

Trabajo posterior a §0k, mismo día: visibilidad de CVD en el gráfico de Value Area, reconstrucción de precio/CVD tras downtime real del scanner, y 4 canales nuevos para que el scanner deje de depender solo de volumen para elegir qué escanear.

### Gráfico Value Area + CVD (`app/main.py`)

- Nueva línea de **CVD acumulado de sesión** (eje derecho, verde punteada) sobre el gráfico VAL/VAH existente — reconstruida del `delta` por ciclo ya persistido en `market_snapshots` (`app/database.py::get_symbol_price_history` ahora también devuelve `delta`), replicando en el dashboard exactamente la lógica de `value_area_core.py`: se reinicia en 0 cada 9:30am NY, acumula hasta las 4:30pm, queda plano en 0 en la sesión overnight.
- **Bug de layout corregido**: el legend horizontal arriba (`y=1.02`) se envolvía a 2 líneas con 3-4 series y chocaba con el título — movido debajo del gráfico.
- **Corte de huecos reales**: si el gap entre dos snapshots consecutivos del símbolo supera 30 min, la línea (precio y CVD) se corta en vez de conectarse — antes Plotly dibujaba una diagonal "suave" falsa a través de huecos de cobertura, y el CVD quedaba plano en 0 leyéndose como "sin flujo" cuando en realidad era "sin datos". Verificado contra ASTERUSDT: huecos reales de 19h y 13h que cubrían sesiones de trading completas.

⚠️ **Limitación encontrada tras el hecho (usuario preguntó por qué el CVD "no se persiste como el precio")**: el CVD de sesión mostrado en el gráfico se reconstruye en el momento de renderizar (suma del historial de `delta`), no se lee de un valor ya guardado — el acumulador real y correcto (`strategy_symbol_state.cvd_session`) solo retiene el valor ACTUAL, sin historial, así que no sirve para dibujar una línea. La única fuente con historial es `market_snapshots.delta`, pero `insert_snapshots_batch` descarta filas con `score < SNAPSHOT_MIN_SCORE` (30) para controlar volumen de escritura — un hueco así es tolerable para precio (un segmento interpolado más grueso) pero **corrompe cualquier suma acumulada**: un ciclo perdido no se puede "saltar", el total queda mal el resto de la sesión. **Corregido**: `insert_snapshots_batch(records, protected_symbols=...)` ahora acepta símbolos que se insertan siempre sin importar su score; `scripts/run_scanner.py` pasa `database.get_symbols_with_open_exposure()` como protegidos — los símbolos con posición real abierta ya no pierden ciclos de `delta`. Símbolos con value area activa pero SIN posición abierta todavía pueden tener huecos ocasionales por score bajo (no se protegieron para no revertir la reducción deliberada de volumen de escritura — decisión pendiente si se quiere ampliar).

### `app/snapshot_backfill.py` (nuevo) — reconstrucción tras downtime real

`recover_gap_positions()` (existente, `position_monitor.py`) solo resuelve el desenlace de posiciones abiertas durante el downtime — no escribe nada en `market_snapshots`. Nuevo módulo que sí lo hace, ejecutado una vez al iniciar el scanner:

- Por símbolo con historial previo, si el hueco desde su último dato está entre 20 min y 20h (menos = continuidad normal; más = demasiado viejo para valer la pena), pide klines de 1m a Binance para ese rango exacto.
- **Precio**: `close` real de cada vela. **CVD/delta**: el CVD real viene del tape de trades en vivo (websocket) y no es recuperable retroactivamente trade a trade, pero cada kline de Binance trae `taker_buy_base_asset_volume` — se aproxima `delta_proxy = 2×taker_buy − volumen_total`, con `cvd_15m`/`cvd` como suma rodante del proxy.
- Migración `007` (sqlite/postgres): columna `is_backfilled` en `market_snapshots`. `database.insert_backfilled_snapshots()` es un INSERT dedicado que **no** filtra por `SNAPSHOT_MIN_SCORE` (estas filas son WAIT/score=0 por construcción).
- **Límite explícito**: cubre downtime real del proceso, NO cubre un símbolo rotando dentro/fuera de la lista de candidatos mientras el scanner sigue corriendo — para eso, ver la continuidad de exposición abajo.

### Continuidad de exposición + fix de stream del websocket (`scripts/run_scanner.py`, `app/database.py`)

- `database.get_symbols_with_open_exposure()` — símbolos con posición abierta en cualquiera de los 3 sistemas (`auto_positions`, `micro_scalp_alerts`, `strategy_positions`). Se agregan a los candidatos de cada ciclo **sin importar su volumen**, igual que ya se hacía con Accumulation Watch.
- **Bug encontrado de paso**: el stream del websocket (fuente del delta/CVD real) se armaba con `candidates[:30]`, truncando cualquier símbolo agregado después de esa posición — Accumulation Watch (y ahora exposición abierta) podían quedar en el escaneo pero **sin CVD real** porque nunca entraban al stream. Corregido: el stream ahora usa la lista completa de candidatos.

### Descubrimiento de candidatos fuera del volumen — 3 canales nuevos, watchlist generalizada

El scanner principal (top ~30 por volumen, piso $50M) y Accumulation Watch (coiling, $2M-$50M) comparten el mismo sesgo: solo consideran símbolos ya identificados por volumen o por contracción previa de volatilidad. Migración `008` generaliza `accumulation_watch` de "solo coiling" a watchlist multi-canal (`channel`, `channel_score` genérico de ranking, `metrics_json`); `get_accumulation_watchlist_symbols()` ahora ordena por `channel_score`, no por `coiling_score`.

- **`volatility_breakout`** (`app/accumulation_scanner.py::_classify_channel`) — reutiliza las MISMAS métricas que ya calcula `compute_coiling_metrics()` para el canal coiling: un `contraction_ratio` (ATR reciente/ATR base) **alto** (≥2.5x, `ACCUMULATION_VOLATILITY_BREAKOUT_RATIO`) es una expansión de volatilidad ya en marcha, en vez de la contracción previa a un breakout que mide coiling. Cero llamadas nuevas a Binance.
- **`funding_extreme`** (`app/candidate_discovery.py::scan_funding_extreme_candidates`) — reutiliza el `funding_map` ya descargado en bloque para el mismo universo $2M-$50M (`ACCUMULATION_FUNDING_EXTREME_THRESHOLD=0.003`). Cero llamadas nuevas.
- **`oi_acceleration`** (`app/candidate_discovery.py::scan_oi_acceleration_candidates`) — único canal que agrega llamadas nuevas: Binance no tiene un endpoint de OI para todos los símbolos a la vez (`app/market_data.py::get_open_interest_hist`, uno por símbolo vía `/futures/data/openInterestHist`). Flags símbolos con OI ±15% (`ACCUMULATION_OI_ACCELERATION_PCT`) en 24h (`ACCUMULATION_OI_ACCELERATION_LOOKBACK_HOURS`), mismo patrón de pool de hilos que coiling. Cadencia propia (`CANDIDATE_DISCOVERY_SCAN_INTERVAL_HOURS=6`) separada de `ACCUMULATION_SCAN_INTERVAL_HOURS`.
- `app/accumulation_scanner.py::_get_universe` renombrado a `get_extended_universe` (público) para que `candidate_discovery.py` lo reutilice sin duplicar el fetch de tickers/funding.
- Límite conocido y documentado en código: si un símbolo calificara para más de un canal en scans distintos, el último en escribir gana el campo `channel` mostrado — no se trackea atribución multi-canal, el objetivo es solo que el símbolo se siga escaneando.

### Verificación

42 tests nuevos (`test_snapshot_backfill.py`, `test_open_exposure.py`, `test_candidate_discovery.py`, + extensiones a `test_accumulation_scanner.py` y `test_database.py` para `protected_symbols`). Suite completa: **318 passed, 2 skipped**. Pendiente: reiniciar el scanner para que las migraciones `007-008` se apliquen y el nuevo código quede en vivo.

## 0k. Actualización 2026-07-27 — PnL de futuros + refuerzo de micro-scalping (4 frentes)

Diagnóstico 2026-07-25 confirmó con datos reales (no solo proxy 60m) que el pipeline principal de futuros tiene **PnL histórico neto negativo (-31.15 USDT / 1,133 posiciones paper)**: el apalancamiento de `entry_exit.py::_suggest_leverage` (hasta 5x) amplifica el SL mínimo de 2% a pérdidas de -8/-9%, mientras el movimiento real favorable en la ventana de 4h rara vez alcanza el TP1 exigido (≥1.5R). Micro-scalping es la única estrategia consistentemente positiva. Pedido explícito del usuario: mejorar futuros sin dejar de reforzar micro-scalping, con CVD monitoreado en velas de 1m (micro) y 3m (futuros), y visibilidad de órdenes activas por estrategia en el dashboard. Plan completo (aprobado) archivado en el historial de sesión; resumen de lo aplicado:

### Frente A — Correcciones quirúrgicas al pipeline principal

- **`app/setup_calibrator.py::calibrate_setup`** — `risk_score` estaba saturado en 100 para casi todos los grados (rr1≥1.5 y risk_pct≤10% ya vienen garantizados por construcción, esa dimensión no discriminaba). Reformulado para escalar con qué tan por encima de 1.5R está el rr1 real: base 20 + hasta 25 según `rr_quality=(rr1-1.5)/1.5` (cap 1.0) + 10 si hay SL + 20 si `level_ok` + 5 si `0<risk_pct≤3`. Tests existentes (`tests/test_setup_calibrator.py`, 4) siguen pasando sin cambios.
- **`app/setup_rules.py::evaluate_trade_setup`** — `level_breakout`/`pattern_break` daban el puntaje de gatillo más alto (+18/+16) sin exigir confirmación de momentum, pese a rendir peor en la realidad. Ahora el puntaje alto solo se otorga si además hay `trend_continuation_valid` (mismo criterio que ya usaba `momentum_continuation`); si no, +13/+12. Verificado contra `tests/test_setup_rules_structure.py` (10 tests).
- **`.env` / `app/config.py`**: `AUTO_TRADING_RISK_CUT_LOSS_PCT` 8→**5** (que el corte de riesgo actúe antes de acercarse a la magnitud de un SL completo).
- **`.env`**: `AUTO_TRADING_SESSION_ACTIVE_HOURS` `9-22` → **`9-15,16-21`** — excluye horas 15 y 21 UTC específicamente. Verificado con PnL real (no solo WR-proxy) por hora en `auto_positions`: esas dos horas son las peores del bloque activo (-14.51 USDT/66 trades y -11.47 USDT/69 trades respectivamente), pese a que la hora 15 mostraba el MEJOR WR-proxy en el diagnóstico — se priorizó el PnL real sobre el proxy. **No** se reabrió el bloque 00-08 UTC pese a WR-proxy "decente" (20-24%): el PnL real de ese bloque es negativo (-12.63 USDT), consistente con un estudio previo ya documentado en código (90 días × 25 símbolos, Asia con EV negativo a SL2%/TP3%).
- **`scripts/train_model.py`** — reentrenado sobre datos actuales (el `.pkl` vigente tenía ~18 días de antigüedad respecto al período post-restart). Modelo viejo respaldado en `data/ml_model.pkl.bak-2026-07-04`. Resultado: 543 muestras (265 win/278 loss), accuracy 0.679, AUC-ROC 0.698 (holdout 20%), CV 3-fold 0.605±0.051. Evaluación posterior más profunda (CV 5-fold estratificado 0.657±0.027) comparó 4 configuraciones de hiperparámetros — la actual (200 árboles/depth6/leaf4) sigue siendo la mejor; no se tocó `ML_THRESHOLD=0.52` por falta de evidencia para cambiarlo. ⚠️ Gap pendiente sin resolver: **cero muestras `BUY_SPOT`** en el training set (solo LONG_FUTURES=331, SHORT_FUTURES=148, SELL_SPOT=64) — cualquier probabilidad ML para `BUY_SPOT` es extrapolación pura del modelo.

### Frente B — Nueva estrategia paper "futuros ágil" (`agile_futures`)

Nuevo módulo dentro del framework multi-estrategia ya existente (`app/strategies/`), en paralelo al pipeline principal — no reemplaza nada, permite comparar A/B con datos reales sin arriesgar `calibrated_grade` ni el modelo ML.

- **`app/strategies/agile_futures.py`** (nuevo) — `AgileFuturesStrategy`, id `"agile_futures"`. Entrada **reactiva** (como micro-scalp: exige que el movimiento ya esté en marcha — `RVOL≥1.8` + `return_15m`/`cvd_15m`/`delta`/CVD-de-ventana-3min todos alineados), no anticipatoria como `level_breakout`. Cadencia de evaluación de señal cada 3 min por símbolo (`STRATEGY_AGILE_FUTURES_EVAL_INTERVAL_SECONDS`, throttle en memoria, mismo patrón que el preview-window de `value_area_core.py`); el CVD de esa ventana se acumula cada ciclo del scanner sin costo nuevo (ya viene del websocket). Apalancamiento **fijo y moderado** (3x por defecto, vs hasta 5x de la fórmula del pipeline principal). SL/TP conscientes de estructura: el TP se recorta contra el nivel S/R opuesto más cercano (misma idea que `micro_scalper.py::_build_setup`) en vez de exigir un R:R fijo que casi nunca se alcanza. Timeout propio ~100 min (>30min pedido, más corto que las 4h del pipeline principal). Capital/posiciones/órdenes propios, independientes de `AUTO_TRADING_CAPITAL_USDT` y `MICRO_SCALP_CAPITAL_USDT` (tablas `strategy_alerts`/`strategy_positions`, `strategy_id="agile_futures"`).
- **`app/strategies/registry.py`** — `AgileFuturesStrategy()` registrada en `STRATEGIES`.
- **`.env`** — bloque nuevo: `STRATEGY_AGILE_FUTURES_ENABLED=true`, `CAPITAL_USDT=150`, `LEVERAGE=3`, `TIMEOUT_MINUTES=100`, `EVAL_INTERVAL_SECONDS=180`.
- Verificado con tests sintéticos (señal LONG/SHORT, throttle, recorte de TP con/sin resistencia cercana) y smoke test completo a través de `strategy_engine.evaluate_all()`/`check_positions()` sobre DB temporal aislada.

### Frente C — Refuerzo de micro-scalping

El método "rebote en nivel" ya mostraba mejor WR (36.4% vs 34.0%) y MFE/MAE mucho más controlado (0.88/0.78 vs 3.9/3.54) que el momentum puro, pero solo se podía inferir post-hoc parseando texto de `reasons_json`. Ahora es explícito y se recompensa:

- **Migración `006_micro_scalp_method`** (sqlite + postgres) — `micro_scalp_alerts` gana columnas `method TEXT DEFAULT ''` y `trade_size_usdt REAL DEFAULT 0`.
- **`app/config.py`** — `MICRO_SCALP_LEVEL_METHOD_BONUS=3` (bono de score cuando el trigger es rebote/rechazo de nivel) y `MICRO_SCALP_NIVEL_SIZE_MULTIPLIER=1.2` (tamaño de posición 20% mayor solo para setups "nivel", sin tocar el capital total del módulo).
- **`app/micro_scalper.py`** — `calculate_micro_scalp_score` ahora devuelve también `is_level_trigger`; las ramas de rebote en soporte/resistencia suman `+12 + MICRO_SCALP_LEVEL_METHOD_BONUS` en vez de solo `+12`. `detect_micro_scalp` calcula `method="nivel"|"momentum"` y `trade_size_usdt` (base × multiplicador si aplica) y los persiste. Umbrales de momentum puro sin relajar.
- **`app/database.py`** / **`app/micro_outcome_tracker.py`** — `insert_micro_scalp_alert` guarda las columnas nuevas; el cálculo de `pnl_usdt` usa `trade_size_usdt` por fila con fallback al constante global para filas anteriores a la migración.
- Cadencia confirmada en velas de **1 minuto** (ya alineada 1:1 con el ciclo del scanner — sin cambios de infraestructura, decisión del usuario tras ver PnL de micro en +27 USDT).
- ⚠️ Se detectó y corrigió durante la implementación un bug de saturación de score análogo al de `risk_score` (Frente A): con el bono inicial en 6, el escenario "plain" de un test ya sumaba 101→capado en 100, haciendo imposible la diferencia esperada contra el escenario "boosted". Bajado a 3 para que ambos casos queden por debajo del cap y la comparación sea válida.

### Frente D — Dashboard: "Órdenes activas" unificado

Antes, el dashboard no mostraba ninguna tabla de posiciones abiertas del pipeline principal ni de micro-scalping — solo el resumen agregado de PnL y la tabla de `strategy_positions` (ya usada por `value_area`). El usuario no podía ver a qué estrategia pertenecía una orden activa.

- **`app/main.py`** — nueva sección **"📋 Órdenes activas"**, justo después del bloque de métricas "💰 PnL acumulado" y antes de la Sección 1 de oportunidades. Combina en un solo `st.dataframe`, DB-only (sin llamadas API nuevas): `auto_positions` abiertas (pipeline principal, futuros/spot), `micro_scalp_alerts` abiertas (micro-scalping) y `strategy_positions` abiertas (framework multi-estrategia — `value_area_range`, `value_area_volume70`, `agile_futures`), cada fila etiquetada con su estrategia real. PnL abierto calculado con la lógica de `calc_pnl` propia de cada módulo contra `get_latest_symbol_price`.
- **Bug no relacionado, encontrado durante el reinicio de verificación**: el chart "Distribución de señales institucionales" (`px.bar` con `color="signal"` discreto) crasheaba con `KeyError: 'long_squeeze'` en cada rerun — regresión confirmada de pandas 3.0.3 (`df.groupby(['col'], sort=False).get_group(valor_existente)` lanza `KeyError`; `df.groupby('col')` sin lista funciona bien), no causada por este trabajo. Corregido reemplazando el `px.bar` por `go.Figure()` + un `go.Bar` por valor de señal.

### Verificación y estado

Suite de tests actualizada (`test_setup_rules_structure.py`, `test_micro_scalper_structure.py`) y pasando. Scanner y dashboard reiniciados con todo el código anterior en vivo (confirmado sin excepciones tras varios ciclos de autorefresh). **Pendiente natural**: diagnóstico integral de seguimiento en unos días para comparar `agile_futures` vs. pipeline principal con datos reales antes de decidir si se reemplaza el pipeline o se mantienen ambos en paralelo.

## 0j. Actualización 2026-07-18 — panel "Setups de estructura (3m)" en el dashboard

El usuario quiere ver en el dashboard qué tokens presentan entrada por estructura (breakouts confirmados, H-C-H, dobles techos/pisos) con confirmación de órdenes/volumen, **trabajando con velas 3m por ahora** para evaluar el rendimiento del timeframe.

- **Migración 002** (`migrations/{sqlite,postgres}/002_structure_json.sql`): columna `structure_json TEXT DEFAULT '{}'` en `market_snapshots`. Se aplica sola en el próximo arranque de scanner o dashboard (`init_db` → `apply_migrations`).
- `app/database.py`: `_compact_structure()` serializa `result["structure_micro"]` acotada (~1 KB: levels top-6 sin metadatos internos, nearest S/R, breakout, patterns, range) → `structure_json` en `_snapshot_row`/`_SNAPSHOT_INSERT`.
- `scripts/run_scanner.py`: el fetch de klines 3m ya no depende de `MICRO_SCALP_ENABLED` (solo de `ENABLE_STRUCTURE_ANALYSIS`).
- `app/main.py`: sección nueva **"📐 Setups de estructura (3m)"** entre Oportunidades y Ranking. Muestra tabla de señales confirmadas (breakout ↑/↓ con nivel/toques/margen; patrón roto con neckline) ordenadas por confirmación de flujo — 4 checks direccionales sobre columnas ya persistidas: **Δ delta > 0, CVD 15m > 0, |OB imbalance| ≥ 0.08, RVOL ≥ 1.5** (con signo invertido para SHORT) — más expander "Patrones en formación" (neckline sin romper). `_build_rows_from_db` ahora mapea `structure`, `return_3m`, `return_5m`.
- Tests: round-trip `structure_json` + cap de `_compact_structure` en `tests/test_database.py`. Suite: 270 passed.
- Límites conocidos: solo aparecen símbolos con `score >= SNAPSHOT_MIN_SCORE` (filtro existente de `insert_snapshots_batch`) y la ventana del panel es la del slider "max_age" del sidebar. **La columna se llena solo cuando el scanner corre con este código** — reinicio pendiente.

## 0i. Actualización 2026-07-18 — matching de noticias corregido + purga total del histórico

El matching símbolo↔noticia por substring generaba miles de falsos positivos (AUSDT con 4,327 "noticias" porque el artículo inglés "a" matcheaba todo; POWERUSDT con notas de Anker; TRUMPUSDT política; SAMSUNGUSDT teléfonos) y contaminaba `security_event_alerts` con falsos CRITICAL. Accuracy medida (46-49%) no era interpretable con ese ruido.

**Fix** en `app/news_intelligence.py` `_matches_symbol` — jerarquía estricta (cualquiera basta):
1. Alias del proyecto (`_ALIASES`) con word-boundary (antes substring).
2. Notación de mercado: `$BASE`, `BASE/USDT`, `BASEUSDT`, `BASE-USD`.
3. Ticker en MAYÚSCULAS exactas + palabra de contexto cripto (solo len≥3) — los titulares en Title Case producen "Power", no "POWER".
4. Bigrama adyacente `base token|coin|price|crypto` (solo len≥3).
Tickers de 1-2 letras solo matchean por reglas 1-2. Los fetchers GDELT/Google ya no incluyen tickers <3 letras sin alias como término de búsqueda. Tests de regresión con los falsos positivos reales en `tests/test_news_intelligence.py` (267 passed).

**Purga (2026-07-18, aprobada por el usuario)**: `scripts/purge_news_data.py --apply` borró **38,281 filas** (26,732 news_events + 11,482 news_predictions + 67 security_event_alerts) con respaldo en `outputs/news_backup_20260718_040245.json.gz` (13.9 MB). **Las métricas de accuracy de noticias arrancan de cero desde esta fecha** — no comparar con históricos previos.

⚠️ **Requiere reiniciar el scanner**: el proceso en ejecución tiene el matching viejo en memoria y siguió insertando entre la corrección y la purga.

## 0h. Actualización 2026-07-17 — estrategia de estructura: S/R, patrones chartistas y breakouts

Reorganización de estrategia solicitada por el usuario: fundamentales de análisis técnico (niveles S/R, H-C-H, dobles techos/pisos, entradas por breakout confirmado) con métodos separados para futuros (breakout + gestión conservadora) y micro-scalp (rebotes en nivel con TP ajustado).

**Módulos nuevos:**
- `app/structure_levels.py` — `find_pivots()` (swing highs/lows, ventana 3), `build_levels()` (clustering de pivots por proximidad 0.35%, mín. 2 toques), `analyze_structure()` (API principal: niveles + soporte/resistencia más cercanos + breakout con confirmación por margen ATR y RVOL≥1.5). Opera sobre klines 15m×200 (~50h).
- `app/chart_patterns.py` — `detect_chart_patterns()`: H-C-H, H-C-H invertido, doble techo/piso sobre los pivots; cada patrón reporta neckline y `confirmed` (cierre más allá de la neckline = señal de entrada; sin confirmar = solo advertencia).

**Integración:**
- `scripts/run_scanner.py` `_scan_symbol`: fetch paralelo de klines 15m (12ª llamada del executor), `result["structure"]` con niveles+breakout+patterns.
- `app/setup_rules.py`: dos rutas de gatillo nuevas con prioridad sobre las existentes — `level_breakout` (+18, trigger_type `level_breakout_up/down`) y `pattern_break` (+16, p.ej. `head_and_shoulders_break`); nivel estructural ≤1.5% cuenta para `level_ok` (+12); breakout/patrón confirmado EN CONTRA resta 10 c/u. `trigger_type`/`setup_route` se persisten en `trade_alerts` → medible por winrate igual que las rutas previas.
- `app/micro_scalper.py`: método por niveles — long +12 en rebote de soporte (≤0.4%), −10 pegado a resistencia, −12 si el soporte se acaba de romper (no comprar el cuchillo); espejo para short. `_build_setup()` recorta TP1/TP2 para no pedir atravesar el nivel opuesto (85%/95% de la distancia al nivel). SL sin cambios.
- Config: bloque `ENABLE_STRUCTURE_ANALYSIS` (default true) + `STRUCTURE_*`, `PATTERN_*`, `MICRO_SCALP_LEVEL_PROXIMITY_PCT` en `app/config.py`.
- Tests nuevos: `test_structure_levels.py`, `test_chart_patterns.py`, `test_setup_rules_structure.py`, `test_micro_scalper_structure.py`. Suite completa: 254 passed.

Todo es aditivo/observacional: sin gate nuevo, los triggers nuevos solo compiten en el scoring del setup. Validar por winrate de `setup_route='level_breakout'`/`'pattern_break'` tras ~1-2 semanas.

**Ampliación (mismo día, feedback del usuario "debería ser la base, y multi-timeframe"):** la estructura pasó de ser solo un gatillo del setup a ser insumo del análisis completo:
- `scoring.py`: nuevo componente `_structure_score` (−8 a +15) en `calculate_opportunity_score` — ruptura confirmada alineada con la señal +10, patrón confirmado +6, precio en soporte/resistencia alineado +5, estructura confirmada en contra −8. Se expone como `structure_score` en score_data y sus razones van primero en el reporte.
- `entry_exit.py`: los niveles S/R (`structure["levels"]`) entran como candidatos junto a VWAP/POC/HVN/GEX en: objetivo de pullback (entrada), stop (bajo soporte / sobre resistencia) y TP1/TP2 (siguiente nivel opuesto). ⚠️ Los pisos vigentes (`_MIN_SL_PCT_FUTURES` 2%, TP1 ≥1.5R) siguen mandando — un SL estructural más ajustado que 2% o un TP más cercano que 1.5R se ven anulados por el piso. Relajarlos es la decisión estratégica pendiente del backtest §0g.
- `trade_advisor.py`: pasa `structure` a `calculate_entry_exit`.
- **Multi-timeframe**: `run_scanner._scan_symbol` calcula la estructura ANTES del scoring y en dos marcos — 15m×200 (futuros/spot, `result["structure"]`) y 3m×200 (~10h, `result["structure_micro"]`, config `STRUCTURE_MICRO_KLINES_*`). El micro-scalp usa la de 3m (niveles y patrones a su horizonte real); fallback a 15m si 3m no está.
- Tests: `test_structure_in_scoring.py`, `test_entry_exit_structure.py`. Suite: 264 passed.
- Costo: 2 llamadas de klines extra por símbolo/ciclo (13 en total en el executor paralelo — impacto marginal en t_api).

## 0h-bis. 2026-07-17 — fixture de tests escribía en la DB REAL (corregido; limpieza pendiente)

Tras el refactor a `app/db/` (sesión PG, sin commitear), `app/db/sqlite.py` congela `DATABASE_PATH` al importar y el monkeypatch de `fresh_db` dejó de redirigir → los tests escribieron ~36 filas sintéticas en `data/crypto_dashboard.sqlite3` (12 trade_alerts BTCUSDT price=100000, 2 alert_outcomes que contaminan winrate, 11 snapshots, 2 micro, noticias/seguridad/accumulation de prueba).

- ✅ **Corregido**: `database._get_conn()` ahora pasa `DATABASE_PATH` explícito a `_db_connect()` (restaura el punto de parcheo). Verificado: la suite ya no agrega filas a la DB real.
- ⏳ **Pendiente**: ejecutar `python scripts/cleanup_test_junk.py --apply` (dry-run ya validado: 36 filas, respaldo JSON automático a `outputs/`). Requiere confirmación del usuario por ser borrado en la DB real.

## 0g. Actualización 2026-07-17 — fees simulados en auto-trading paper

El PnL de `auto_positions` no descontaba comisiones, inflando el paper (~0.38% del margen por trade con leverage promedio 3.8x; los fees estimados de 789 cierres post-restart eran $16.83 vs un PnL neto de −$2.29).

- `app/config.py`: nuevo `AUTO_TRADING_FEE_RATE` (default 0.0005 = 0.05% taker por lado sobre notional `size*leverage`).
- `app/auto_trader.py` `calc_pnl()`: descuenta fee de entrada + fee de la salida parcial TP1 (si aplica) + fee de la salida de la porción abierta. Devuelve campo nuevo `fees_usdt`. Como todos los caminos de cierre (SL/TP2/timeout/risk_cut/hard_cap/gap recovery) pasan por `calc_pnl`, todos quedan netos de fees automáticamente. `tp1_pnl_usdt` se sigue guardando bruto; su fee se descuenta en `calc_pnl`.
- `app/position_monitor.py`: los dos cierres `tp1_only` (monitor y gap recovery) ahora escriben `total_pnl_usdt/pct` de `calc_pnl` (neto) en vez del `tp1_pnl_usdt` bruto.
- ⚠️ Los registros históricos en DB siguen siendo brutos — comparar pre/post 2026-07-17 con eso en mente. El hard cap y risk_cut ahora disparan ~0.4% antes (el umbral compara PnL neto), intencional.

Contexto (diagnóstico 2026-07-17, ver `outputs/diagnosticos/`): el WR ajustado 60% del grado A no se refleja en paper porque el edge medido es de ~0.5R a 60m mientras la gestión exige TP1=1.5R — el 68% de las posiciones paper vienen de alertas con outcome 60m `neutral` y el 55% de esas termina perdiendo (el movimiento favorable se revierte antes del TP).

**Backtest TP/SL (mismo día, ver `outputs/diagnosticos/2026-07-17-backtest-tpsl.md`)**: replay de las 789 posiciones paper contra klines 5m reales con fees — **ninguna de las 14 configuraciones TP/SL probadas es rentable** (PF 0.80–0.94). El edge bruto de las entradas (~+0.1%/trade) no cubre los fees (~0.38%). Hallazgos: SL 1.5R > SL 1.0R (el SL actual es cazado), el breakeven post-TP1 destruye valor, SHORT pierde en todas las configs. Único subconjunto positivo: **grado A + LONG con TP0.5R/SL1.5R → +0.38%/trade, WR 72.7% (n=117, muestra pequeña)**. Conclusión: el ajuste necesario es de selección de entradas (A+LONG only), no solo de gestión. Propuesta pendiente de decisión del usuario.

## 0f. Actualización 2026-07-13 — plan de rendimiento (4 items): 2 aplicados, 2 descartados con evidencia

Se validó e implementó (parcialmente) un plan de 4 mejoras de rendimiento. Decisiones finales:

### ✅ Aplicado: `init_db()` ahora usa `apply_migrations()` (Item 4)

`app/database.py` — las ~350 líneas de DDL inline + el mecanismo `_migrate_schema()` fueron reemplazadas por `_db_apply_migrations(conn)` (sistema de `migrations/{sqlite,postgres}/*.sql` + tabla `schema_migrations`). Verificado que `001_initial.sql` es superset exacto del DDL inline + las 59 columnas de `_migrate_schema` (comparación 1:1).

- **Nueva convención: cambios de esquema van como archivos `migrations/{sqlite,postgres}/00N_*.sql`**, ya NO en la lista `new_columns` de `_migrate_schema()`.
- `_migrate_schema()` se mantiene como red de seguridad post-migraciones (típicamente 0 ALTERs gracias al fix de `PRAGMA table_info`). Retirar en 1-2 releases si sigue en 0.
- La DB real ya tiene `schema_migrations` con `001_initial.sql` registrada.

### ✅ Aplicado: `signal_json` ya no se persiste (Item 3, versión mínima)

`app/database.py` `_snapshot_row()` — escribe `'{}'` en vez de serializar el dict `signal`. Verificado por grep: su único consumidor era `signal_description` en `main.py`, que nunca se renderiza. Las filas históricas conservan su JSON; la lectura en `main.py:86` funciona con ambos.

### ❌ Descartado con evidencia: índice `(symbol, id DESC)` (Item 2)

Se implementó, se midió y **se revirtió**. Benchmark sobre la DB real (107K filas en `market_snapshots`):

| Configuración | Tiempo query `get_latest_snapshots` |
|---|---|
| Planner libre (usa `idx_snapshots_sym_ts`) | **5.36 ms** |
| Forzando `idx_snapshots_sym_id` (INDEXED BY) | **503.83 ms** (94× peor) |

**Por qué:** en SQLite todo índice incluye implícitamente el rowid, y `id` ES el rowid (INTEGER PRIMARY KEY) — así que `idx_snapshots_sym_ts (symbol, timestamp)` ya es **covering** para la subquery `SELECT symbol, MAX(id) WHERE timestamp >= ? GROUP BY symbol`. El índice propuesto no puede aplicar el filtro de timestamp y obliga a escanear todos los ids por símbolo. El planner nunca lo elegiría, y su único efecto real sería encarecer cada INSERT del scanner. **No reintroducir.**

### ❌ Descartado: cachear figuras Plotly con `st.cache_data` (Item 1)

Dos razones: (1) la propuesta era buggy — el prefijo `_` en `_df_json` hace que Streamlit NO hashee el parámetro, sirviendo figuras stale y rompiendo la reactividad del slider "Top símbolos"; (2) aun corregida, el beneficio es ~nulo: autorefresh (15s) = TTL de datos (15s) y los únicos 2 widgets del dashboard cambian los datos al moverse — no existen reruns "sin cambio de datos" que amortizar.

### ❌ Descartado previamente (ver §0e para no re-evaluar): vaciar `recommendation_json`/`alert_report_json`

Romperían silenciosamente el panel de niveles (que lee `rec["setup"]`, no las columnas nativas), `entry_context`/`timing`/`position_note` (sin columna nativa) y toda la sección de alertas riesgo/squeeze/stress (vive solo en `alert_report_json`).

---

## 0e. Actualización 2026-07-12 — validación de informe de rendimiento externo + veredicto RAM

Se validó un informe de 13 afirmaciones de rendimiento contra el código real. **Conclusión: el informe describía una versión del código que ya no existe** — las "soluciones" que proponía (ThreadPoolExecutor, paralelismo, caché de queries) ya estaban implementadas. NO re-evaluar este informe en el futuro; los veredictos quedan aquí.

### Veredicto RAM (pregunta del usuario)

Medido 2026-07-12: **15.7 GB totales, 2.3 GB libres, commit charge 53.4/58.7 GB** (sobrecompromiso ~3.4× → paginación constante). Consumidores principales: LM Studio, VS Code (~1.5 GB en procesos), WSL, Brave. Scanner ~1.2 GB, dashboard ~0.5 GB.

- ✅ Subir a 32 GB (o 64 GB si se usa LM Studio con modelos grandes) **sí mejora la productividad general** de la máquina.
- ⚠️ **NO mejorará el ciclo del scanner (~95s)** — está acotado por latencia de red de exchanges externos (timeouts 4s KuCoin/Coinbase/Kraken), no por memoria.

### Resumen de los 13 claims

| Claims | Veredicto |
|---|---|
| #1 HTTP serial, #2 SQLite sin pooling, #6 scanner secuencial | ❌ FALSOS — ya hay concurrencia 6×66 (`run_scanner.py:115,721`), conexión por hilo + WAL + busy_timeout (`database.py:23-47`) |
| #3 migración 100+ ALTER, #5 Plotly sin caché, #8 lock contención, #9 json.loads, #10 subquery | 🟡 PARCIALES — costos reales despreciables (59 ALTER una vez/proceso; queries sí cacheadas con `st.cache_data`; lock solo protege dict ops) |
| #4 market_snapshots 77 cols, #11 Streamlit re-render, #12 database.py 2210 líneas | ✅ VERDADEROS pero sin acción — purga 7d los mitiga / inherente / mantenibilidad no rendimiento |
| #7 WS reconexión completa, #13 trade_store sin límite | ✅ VERDADEROS — #13 corregido esta sesión; #7 gap 1-5s solo al rotar símbolos, no justifica complejidad |

### Fixes aplicados

1. **`app/websocket_client.py` — poda de `trade_store`** (claim #13): nuevo `prune_inactive_symbols()` + tracking `_symbol_last_seen`; elimina símbolos fuera del stream actual sin trades en >5 min. Corre cada 5 min en el loop del WS y al reconectar por cambio de símbolos. Log: `WS PRUNE: N símbolos inactivos eliminados`.
2. **`app/database.py` — `_migrate_schema()` con `PRAGMA table_info`** (claim #3): consulta columnas existentes una vez por tabla y solo ejecuta los ALTER faltantes (0 tras el primer arranque). El try/except queda como red de seguridad ante carreras entre procesos.

Ambos verificados con tests en DB temporal: migración idempotente (0 ALTERs en segunda corrida, columna dropeada se recrea) y poda selectiva correcta.

⚠️ **Gotcha descubierto durante la verificación:** `app/config.py:10` usa `load_dotenv(override=True)` — setear `DATABASE_PATH` como variable de entorno NO sirve para aislar tests (el `.env` la pisa). Para tests, parchear `database.DATABASE_PATH` a nivel de módulo **antes** de abrir conexiones. Un test corrió contra la DB real e hizo DROP de `trade_alerts.watch_type`; se restauró al 100% con `UPDATE trade_alerts SET watch_type = calibrated_grade WHERE calibrated_grade IN ('BULLISH_WATCH','BEARISH_WATCH')` (480 filas — `watch_type` es derivable de `calibrated_grade` por construcción, ver `setup_calibrator.py:53-63`).

### Palanca real de rendimiento (pendiente, no implementada)

Si se quiere bajar el ciclo de ~95s: **negative caching de pares inexistentes en exchanges externos** — los símbolos sin par en KuCoin/Coinbase/Kraken pagan el timeout completo de 4s en cada ciclo. Cachear "símbolo no existe en exchange X" por 24h eliminaría esos 4s recurrentes.

---

## 0d. Actualización 2026-07-11 — diagnóstico integral (calibración, SL fix, micro-scalp, noticias, sesiones)

Corrido `/diagnostico-integral` completo. Dataset: 9,290 alertas históricas, 69.8% con `calibrated_grade` (cobertura suficiente). `RESTART` = 2026-06-08T05:42:37.

### WR pre vs post-calibración (todo el período, no solo últimos 7d)

| Acción | Δ WR oficial | Δ WR ajustado (R=0.5) | Lectura |
|---|---|---|---|
| LONG_FUTURES | -13.5pp | -2.5pp | Casi estable — la caída oficial es artefacto de distancia TP1 |
| **SHORT_FUTURES** | -10.5pp | **-6.1pp** | **Degradación real**, no solo artefacto de volatilidad |
| SELL_SPOT | +2.0pp | +4.6pp | Mejoró en ambas métricas |
| BUY_SPOT | +2.8pp | +4.4pp | Mejoró en ambas métricas |

⚠️ A diferencia del snapshot de "últimos 7 días" reportado en la sección 0c (SHORT 80.3%), el promedio de **todo** el período post-restart muestra que SHORT_FUTURES sí empeoró de forma sostenida frente al período pre-calibración — no es solo el efecto TP1/volatilidad que sí explica la caída de LONG. Pendiente investigar qué cambio de la calibración afectó específicamente a SHORT.

### Grado calibrado — A > B se confirma con muestra robusta; C no es confiable todavía

| Grado | n (evaluadas) | WR ajustado agregado |
|---|---|---|
| A | 1,015 | 61.9% |
| B | 4,227 | 54.7% |
| C | 47 | 70.2% (n insuficiente) |

A > B se sostiene con buena muestra. C aparenta superar a B pero con n=47 es ruido estadístico — no recalibrar basándose en ese dato hasta acumular más muestra.

### SL fix (posiciones paper) — confirmado, elimina el slippage ficticio por completo

| Periodo | n cierres SL | AVG pnl real | AVG esperado (config) | Diferencia |
|---|---|---|---|---|
| PRE | 76 | -12.50% | -8.50% | -4.00pp |
| POST | 216 | -7.33% | -7.33% | **0.00pp exacto** |

✅ El fix de SL aplicado en sesiones previas eliminó completamente la brecha entre pérdida real y pérdida esperada por configuración.

### Micro-scalping (últimas 72h) — sin asimetría R:R crítica

WR direccional ~35% en ambas direcciones (por debajo de 50%), pero PnL promedio se mantiene positivo porque MFE≈MAE (~2.2-2.4% cada uno) — los ganadores compensan en magnitud a los perdedores. No es el patrón de alarma "WR>50% con PnL<0"; el margen de mejora está en subir la tasa de acierto, no el tamaño del TP.

### Módulo de noticias — señal débil, no listo como gate

Accuracy BULLISH 47.0% / BEARISH 49.2% (básicamente azar), 48% de predicciones NEUTRAL. Alertas ALINEADAS con la predicción de noticias tienen mejor WR que CONTRARIAS (17.6% vs 12.8%) pero la diferencia de retorno es marginal (0.31% vs 0.26%) — usar como mucho como señal auxiliar, no como filtro duro todavía.

### Actividad por sesión UTC

| Bloque | Mejor para | Dato |
|---|---|---|
| Asia profunda (00-07 UTC = 18-01h MX) | Alertas normales | WR 57.8%, mejor bloque global |
| Europa sola (09-13 UTC = 03-07h MX) | Micro-scalp | WR 40.4%, mejor bloque para micro |
| **US sola (17-22 UTC = 11-16h MX)** | — | Peor bloque para micro-scalp: WR 32.7%, PnL negativo |

⚠️ **Apertura Wall Street (13:30-15:30 UTC / 07:30-09:30h MX) rinde por debajo del promedio**: la hora 14 UTC es de las peores del día completo (WR 46.0%, retorno -0.06%), con SHORT_FUTURES particularmente negativo (-0.76% en esa hora). Candidato a blackout adicional si se confirma en próximos análisis.

### Alertas de seguridad activas destacadas

CONFIRMED CRITICAL: **ADAUSDT** (Ctrl Wallet shutdown), **AUSDT** (Zcash counterfeiting bug, x3), **ZECUSDT** (Orchard vulnerability, x2), **HUSDT** (Humanity Protocol hack -87%), **TAIKOUSDT** (bridge exploit, score -71.25, la más severa del histórico), **SOLUSDT** (Raydium exploit x2).

### Pendientes añadidos de esta sesión
- Investigar por qué SHORT_FUTURES es la única acción con degradación real (no artefacto) en WR ajustado post-calibración
- Acumular más muestra en grado C (n=47) antes de confiar en que supera a B
- Evaluar blackout adicional en 13-15 UTC (apertura Wall Street) — WR y retorno por debajo del promedio, SHORT especialmente débil
- Noticias: no usar como gate todavía — accuracy ~48%, diferencia ALINEADA/CONTRARIA marginal

---

## 0c. Actualización 2026-07-07 — análisis WR completo y recuperación de micro-scalping

### WR actual por tipo de operación (horizon 60m, datos al 07-Jul)

Análisis con dataset `trade_alerts JOIN alert_outcomes WHERE horizon=60`. Métricas clave:

| Módulo | WR_adj últimos 7d | WR_adj histórico | Tendencia |
|---|---|---|---|
| LONG_FUTURES | **78.5% ✅** | 72.6% | Mejorando |
| SHORT_FUTURES | **80.3% ✅** | 72.4% | Mejorando — mejor semana registrada |
| SELL_SPOT | **73.1% ✅** | 73.5% | Estable |
| **BUY_SPOT** | **36.4% ⚠️** | 51.7% | **Deteriorándose: -1.41%/trade últimos 7d** |

**Nota de interpretación:** el WR oficial (WR_off) aparece ~55% para futures, lo que parece mediocre. Pero WR_adj (¿se movió el precio ≥0.5R en nuestra dirección?) está en 78-80%. La brecha se debe a que el TP1 está lejos y muchos trades terminan en neutral antes de alcanzarlo. El WR_adj es el indicador relevante para medir dirección.

**BUY_SPOT es el problema real:** 36.4% WR adj, -1.41% avg return en últimas dos semanas. No se trata de un periodo puntual malo — el deterioro es sostenido desde la calibración. Acción sugerida: subir umbral de alerta para BUY_SPOT o suspender temporalmente.

### Grado calibrado — funciona correctamente

| Grado | LONG WR_adj | SHORT WR_adj | SELL_SPOT WR_adj |
|---|---|---|---|
| **A** | 78.9% ✅ | 62.7% ✅ | **87.3% ✅** |
| **B** | 71.7% ✅ | 70.9% ✅ | 80.1% ✅ |
| NO_TRADE | — | 63.9% | 56.5% |

El grado A discrimina correctamente sobre B en todas las acciones. Grado C tiene muestras insuficientes (<10) para conclusiones.

### Micro-scalping — recuperación de PnL confirmada (no es artefacto)

**Hallazgo clave:** el usuario vio el PnL pasar de -22% a -0.68% en un día. Esto es real — no es un reset ni recálculo.

PnL acumulado (suma aritmética de `pnl_pct` de todas las cerradas):

| Fecha | Trades | WR | PnL del día | PnL acumulado |
|---|---|---|---|---|
| 2026-07-03 | 155 | 31.6% | +4.97% | -44.86% |
| 2026-07-04 | 209 | 37.3% | +10.34% | -34.52% |
| 2026-07-05 | 548 | 32.8% | -8.37% ⚠️ | -42.90% |
| **2026-07-06** | 344 | 37.8% | **+26.45% ✅** | -16.44% |
| 2026-07-07 (parcial) | 144 | 38.9% | +16.17% ✅ | **-0.28%** |

El 06-Jul fue el mejor día registrado: +26.45% PnL sum con 344 trades. Desglose:
- MICRO_SHORT_SCALP: 300 trades, WR=37.0%, PnL=**+20.57%** ← motor principal
- MICRO_LONG_SCALP: 44 trades, WR=43.2%, PnL=+5.89%

**Por qué WR 37% genera PnL positivo:** la relación ganancia/pérdida implícita es ~2:1. El sistema captura movimientos más grandes en los wins que lo que pierde en los losses. 344 trades × +0.077% promedio = +26.45% — los números son consistentes. El WR bajo no es suficiente para determinar si un sistema pierde dinero; la asimetría R:R es la otra mitad de la ecuación.

**Riesgo de reversión:** un día malo como el 05-Jul (-8.37% con 548 trades) puede revertir rápido lo ganado. El volumen de MICRO_SHORT (6-7× el de MICRO_LONG) amplifica todo en ambas direcciones.

**Hipótesis de mejora:** los blackouts horarios activados el 06-Jul (MICRO_SHORT bloqueado a 07h y 20h) podrían estar contribuyendo. Se necesita 1 semana más de datos para confirmar o descartar.

**Dato estructural preocupante:** MICRO_SHORT genera 6-7× más señales que MICRO_LONG en un mercado estructuralmente alcista. Lo esperado sería lo inverso. Podría indicar sobreseñalización en SHORT o que los parámetros de detección son más sensibles en esa dirección.

### Pendientes añadidos de esta sesión
- Monitorear si PnL diario de micro-scalp se mantiene positivo la semana del 07-Jul
- Investigar por qué MICRO_SHORT genera 6-7× más señales que MICRO_LONG
- Decisión pendiente: subir umbral BUY_SPOT o suspender hasta que cambie el régimen

---

## 0b. Actualización 2026-07-06 — ML activado, blackouts horarios y análisis de cobertura

### ML model — entrenamiento, activación y fix de bug

El modelo ML estaba desactivado (`ML_ENABLED=false`) desde su creación — nunca había filtrado nada en producción. Se reentrenó y activó completamente en esta sesión.

**Entrenamiento (`scripts/train_model.py`):**
- Dataset: 139 samples tras filtrar ambiguos (tp1==stop) de 159 filas brutas
- Distribución: LONG_FUTURES=70, SHORT_FUTURES=42, SELL_SPOT=19, BUY_SPOT=8
- Pipeline: `SimpleImputer(strategy="median") → RandomForestClassifier(n_estimators=200, max_depth=6, min_samples_leaf=4, class_weight="balanced")`
- Accuracy: **71.4%**, AUC-ROC: **0.719**, CV AUC: 0.666 ± 0.044
- Top features: `return_1h` (10.3%), `rsi` (9.9%), `vwap_distance_pct` (6.7%), `oi_change_pct` (5.6%)
- Modelo guardado en `data/ml_model.pkl` (440.5 KB). sklearn 1.8.0 en ambos lados (sin mismatch).

**Activación (`.env`):**
```
ML_ENABLED=true
ML_THRESHOLD=0.52
```

**Bug fix (`app/ml_predictor.py:183`):** `apply_filter()` degradaba la acción a WAIT cuando `prob < low_threshold` pero **nunca seteaba `result["ml_filtered"] = True`**, lo que impedía rastrear cuántas alertas eran filtradas por el modelo. Corregido añadiendo la línea faltante.

Lógica actual del filtro:
- `prob >= 0.52` → sin cambio
- `0.442 ≤ prob < 0.52` (zona gris, 85% del umbral) → confidence −10 pts + warning
- `prob < 0.442` → degradar a WAIT + `ml_filtered=True`

### Análisis de WR por score (hallazgo contraintuitivo en SHORT)

Derivado del diagnóstico integral, se analizó si subir el umbral de score mejora SHORT_FUTURES:

| Score | WR adj SHORT | n |
|---|---|---|
| 70-74 | 50.7% | 943 |
| 80-84 | 51.3% | 339 |
| 85-89 | 49.1% | 212 |
| **90-100** | **43.9%** | 107 |

**Conclusión: subir el threshold de score NO mejora SHORT — lo empeora.** Un SHORT con score 90+ implica momentum bajista extremo que tiende a revertirse. La discriminación real viene de la hora UTC y del grado calibrado, no del score.

### Blackouts horarios por tipo de operación

Implementado sistema configurable de blackouts por hora UTC en `app/config.py` y `scripts/run_scanner.py`, derivado de análisis de WR ajustado post-calibración (26 días, n≥5/hora).

**Patrón encontrado:**
- **SHORT** funciona bien en sesión US (13-21h UTC), falla en sesión europea temprana (09-12h) y madrugada
- **LONG** tiene debilidad en la reversión de cierre de sesión US (20h, 22h)
- **BUY_SPOT** falla en iliquidez nocturna asiática (02h, 06h)
- **MICRO SHORT** tiene su peor hora a las 20h UTC (WR=11%, PnL=-1.34%)

**Horas bloqueadas (defaults, configurables via `.env`):**

| Variable | Horas UTC | Equivalencia MX (UTC-6) | Motivo |
|---|---|---|---|
| `SHORT_FUTURES_BLACKOUT_HOURS` | 6, 9, 10, 11, 12, 23 | 00, 03, 04, 05, 06, 17h | WR adj < 43% — sesión europea alcista |
| `LONG_FUTURES_BLACKOUT_HOURS` | 20, 22 | 14, 16h | WR adj < 44% — reversión cierre US |
| `BUY_SPOT_BLACKOUT_HOURS` | 2, 6 | 20, 00h | WR adj < 31% — iliquidez nocturna |
| `MICRO_SCALP_BLACKOUT_HOURS_LONG` | 1, 18, 22 | 19, 12, 16h | WR < 30%, PnL negativo |
| `MICRO_SCALP_BLACKOUT_HOURS_SHORT` | 7, 20 | 01, 14h | WR 29% y 11%, -1.34% PnL |

**Archivos modificados:**

`app/config.py` — helper `_parse_hour_set()` + 5 frozensets nuevos al final del bloque de alert thresholds.

`scripts/run_scanner.py`:
- Importa los 5 nuevos nombres desde `app.config`
- `_BLACKOUT_BY_ACTION` dict (SHORT/LONG/BUY_SPOT)
- En `_should_send_alert()`: check de hora antes del cooldown — si `utc_hour in blackout_hours` → `return False` + log `BLACKOUT`
- En el loop de micro-scalp: reemplazó el hardcode `_utc_hour == 20` con dos checks por dirección usando `MICRO_SCALP_BLACKOUT_HOURS_LONG` / `_SHORT`

Para ajustar horas sin tocar código: editar la variable correspondiente en `.env`, p.ej.:
```
SHORT_FUTURES_BLACKOUT_HOURS=6,9,10,11,12,23
MICRO_SCALP_BLACKOUT_HOURS_SHORT=7,20
```

### Análisis de cobertura de tokens (sin cambios de código)

Se analizó si el sistema puede operar tokens específicos de KuCoin y Binance:

**KuCoin (ISLAND, P, SAROS, HMSTR, CRTR, XOX, CYPR, DCK, ITHACA, NRN):**
- Solo `HMSTR` tiene futuros en Binance ($20M/24h, por debajo del umbral actual de $50M)
- El resto: 0 futuros en Binance, volumen spot insignificante (<$2M)
- **Vía KuCoin Futures**: la mayoría no están listados o tienen volumen indetectable
- Conclusión: no operables algorítmicamente con el sistema actual

**Binance (TLM, EPIC, ARPA, MIRA — ganadores; NFP, SYN, HEU, ALCX — perdedores analizados):**
- ARPA, TLM, SYN: ya pasan el filtro de $50M y son escaneados
- EPIC ($25M), MIRA ($34M): accesibles bajando `MIN_QUOTE_VOLUME_USDT=20000000` en `.env`
- NFP, HEU, ALCX: bajo volumen (<$20M), no recomendables
- **Pendiente de decisión del usuario**: ¿bajar el mínimo a $20M para incluir EPIC/MIRA?

---

## 0. Actualización 2026-06-30 — diagnóstico y ajuste de velocidad del scanner

Se verificó en vivo el fix de velocidad de la sección 2.4 (`max_workers` 10→4, aplicado en sesión previa). Resultado: **el ciclo bajó de 255s a ~88-112s (promedio ~95s) mostrado en 20 ciclos consecutivos — mejoró pero NO llegó al objetivo de 35-40s, y se estancó ahí.**

**Causa raíz real (corrige la hipótesis de la sección 2.4, que apuntaba a `get_technical_context()`/`get_volume_profile()`):** no es la lógica de pipeline (`pipeline=0.17-0.45s` consistentemente rápido en los logs). Es latencia honesta de `api` por símbolo:
- Símbolos sin par en exchanges externos: `api≈4.3-4.5s` (timeout de 4s configurado en sección 2.4, cumplido completo cuando el par no existe en KuCoin/Coinbase/Kraken)
- Símbolos con confirmación multi-exchange: `api≈7-8s` (Binance ~3-4s + exchanges externos en paralelo vía `ThreadPoolExecutor` en `app/exchanges/aggregator.py:245`, acotado por el más lento ~4s)

Aritmética que explica el estancamiento: hay **dos niveles de concurrencia**, no uno — el outer `ThreadPoolExecutor(max_workers=4)` en `scripts/run_scanner.py:676` (símbolos en paralelo) y un inner `ThreadPoolExecutor(max_workers=11)` en `scripts/run_scanner.py:373` (timeframes/endpoints de Binance por símbolo). Con 4 workers externos, el pico real eran `4×11=44` requests simultáneos a Binance — sin throttling, pero `49 símbolos ÷ 4 ≈ 12 lotes × ~7.5s promedio ≈ 92s`, que coincide casi exacto con lo observado.

**Cambio aplicado:** `scripts/run_scanner.py:676` — `max_workers=4 → 6` (66 requests simultáneos a Binance, con margen frente al umbral de ~110 que causó el throttling original de 30-39s/símbolo). **Pendiente de verificar en vivo tras el próximo reinicio** — si el `TOTAL` de `TIMING CICLO` baja claramente de los ~95s sin que `api=` por símbolo se dispare de nuevo (señal de throttling), funcionó; si vuelve a verse `api` alto (20-30s+), bajar a 5 en vez de seguir subiendo.

```powershell
# Confirmar tras reiniciar el scanner:
Get-Content "C:\Users\pedro\crypto-dashboard\logs\app.log" -Tail 5 | Select-String "TIMING CICLO"
```

---

---

## 1. Qué es el sistema (resumen rápido)

- **Scanner** (`scripts/run_scanner.py`): proceso en background, escanea pares USDT en Binance, calcula scores, genera alertas, opera en paper trading automático. Sin puerto HTTP — escribe a SQLite.
- **Dashboard Streamlit** (`app/main.py`): UI en `http://localhost:8501`, lee de la misma DB.
- **DB**: SQLite en `data/crypto_dashboard.sqlite3`.
- **Admin Dashboard externo** (`C:\Users\pedro\Documents\admin-dashboard-global`, puerto 8765): supervisa el arranque/parada de ambos procesos (UI + scanner) de este proyecto junto con otros servicios del usuario. Ver sección 7.

---

## 2. Cambios aplicados en esta sesión (orden cronológico)

### 2.1 Recuperación de datos tras downtime (gap recovery)
**Problema que resolvía:** si el scanner estaba offline, `outcome_tracker.py` evaluaba alertas viejas con velas equivocadas (pedía "últimas N velas desde ahora" en vez de la ventana exacta), y `position_monitor.py` no detectaba TP/SL tocados durante el apagón.

- `app/outcome_tracker.py` — `_evaluate_alert()` ahora pide `start_time_ms`/`end_time_ms` exactos a `get_klines()` en vez de "últimas N velas".
- `app/position_monitor.py` — nueva función `recover_gap_positions()`: al iniciar el scanner, hace replay de velas de 15m (vía API, con tiempos exactos) para cada posición abierta y determina si tocó TP1/TP2/SL/timeout/risk_cut mientras el sistema estaba offline. Cierra y notifica igual que el monitor en vivo.
- `scripts/run_scanner.py` — llama `recover_gap_positions()` al inicio (antes del primer ciclo) y refresca la caché histórica incremental de los 10 símbolos principales (1h/4h/1d) vía `ensure_history()`.
- **Importante:** ningún componente operacional (outcome tracker, position monitor, auto trader) depende de la caché local `historical_klines` — todos golpean la API de Binance directo con ventanas de tiempo exactas. La caché solo la usan los scripts de análisis (`validate_parameters.py`).

### 2.2 Limpieza de base de datos
- `database.purge_old_snapshots()` existía pero **nunca se llamaba**. Resultado: 307K filas de `market_snapshots` + tablas relacionadas acumuladas desde mayo, DB de **1,102 MB**.
- Se ejecutó manualmente + `VACUUM` → DB bajó a **339 MB**.
- Cableado en `run_scanner.py`: corre cada 6h dentro del loop principal (`SNAPSHOT_RETENTION_DAYS=7` en `.env`).

### 2.3 Calibración score vs win rate (hallazgo clave)
Análisis de 4,090 alertas evaluadas a 60min post-calibración (`scripts/validate_parameters.py` + queries ad-hoc):

| Hallazgo | Dato |
|---|---|
| Correlación score global ↔ WR ajustado | **−0.020** (prácticamente nula) |
| LONG_FUTURES WR_adj por bucket | 52-60%, mejor en 75-89 |
| SHORT_FUTURES WR_adj por bucket | 41-53%, **peor en score 90+ (41.5%)** |
| SELL_SPOT WR_adj | **66-75%** — el mejor con diferencia |
| EV estimado LONG (paper) | **+0.66%/trade** |
| EV estimado SHORT (paper) | **−0.64%/trade** |

**Causa raíz de SHORT negativo:** mercado crypto 2026 estructuralmente alcista — incluso shorts de alta confianza (score 90+) tienden a revertir.

**Cambios aplicados:**
- `app/config.py` — nuevos `AUTO_TRADING_LONG_MIN_SCORE=75`, `AUTO_TRADING_SHORT_MIN_SCORE=80` (antes: un solo `AUTO_TRADING_MIN_SCORE=70` para ambos).
- `app/auto_trader.py` — `_passes_gates()` usa el máximo entre el threshold global y el específico de dirección.
- `.env` / `.env.example` actualizados.

### 2.4 Velocidad del scanner (255s/ciclo → objetivo ~35-40s)
**Diagnóstico:** con `SCANNER_CANDIDATE_LIMIT=50` (→ 70 símbolos reales con accumulation watchlist) y outer `ThreadPoolExecutor(max_workers=10)` × inner `max_workers=11`, se generaban **110 requests HTTP simultáneos a Binance** → throttling → 30-39s por símbolo (visto en logs: `api=30-39s` para casi todos los símbolos, incluso los que no usan exchanges externos).

**Cambios:**
- `scripts/run_scanner.py:676` — outer executor `max_workers=10 → 4` (44 requests simultáneos en vez de 110).
- `.env` — `SCANNER_CANDIDATE_LIMIT=50 → 30`.
- `app/exchanges/{kucoin,coinbase,kraken}_provider.py` — timeout `10s → 4s` (si no responden en 4s, no van a responder).
- **Pendiente de verificar:** estos cambios no se han confirmado en producción todavía — requiere reiniciar el scanner y revisar `TIMING CICLO` en el log por unos ciclos.

### 2.5 Fix Streamlit (pandas 3.0 compatibility)
- Se actualizó `pandas` a 3.0.3 (compatibilidad con numpy 2.4.6, que causaba `ValueError: numpy.dtype size changed`).
- Esto rompió `px.bar(y=["cvd","cvd_15m"])` en `app/main.py:673` (plotly express hace `melt()` interno incompatible con la nueva API de pandas groupby).
- **Fix:** pre-melt manual del DataFrame antes de pasarlo a `px.bar()`. Ver `app/main.py` sección "CVD 1h / 15m".
- ⚠️ Si aparecen errores similares en otros gráficos `px.bar(y=[lista])` o `px.line(y=[lista])`, aplicar el mismo patrón (melt manual).

### 2.6 Integración con Admin Dashboard Global
Proyecto: `C:\Users\pedro\Documents\admin-dashboard-global` (servidor HTTP propio, sin frameworks, puerto 8765).

- `app.py` extendido: nuevo tipo de componente `"scanner"` (antes solo `"app"` + `"tunnel"`). `tunnel` y `public_url` ahora son opcionales (antes obligatorios) — necesario porque crypto-dashboard no tiene túnel Cloudflare configurado aún.
- `services.json` — nueva entrada `crypto-dashboard`:
  - `app` → `powershell -File scripts\start_dashboard.ps1` (Streamlit, puerto 8501)
  - `scanner` → `venv\Scripts\python.exe scripts\run_scanner.py`
  - `scanner.log_file` → apunta directo a `C:\Users\pedro\crypto-dashboard\logs\app.log` (el log real del scanner, no uno nuevo)
  - Sin `tunnel` todavía.
- Nueva función `tail_filtered()` en `app.py` del admin: filtra el log del scanner para mostrar solo líneas relevantes (`ALERTA`, `SEÑAL`, `AUTO `, `GAP RECOVERY`, `[pnl]`, `ERROR`, `WARNING`, `TIMING CICLO`, `REGIMEN`, `MICRO `) en vez de las 2.3MB de ruido crudo.
- **Gotcha resuelto:** tras editar `app.py` del admin, había **dos procesos duplicados** escuchando el puerto 8765 simultáneamente (uno con código viejo que explotaba al leer el `services.json` nuevo sin campo `tunnel`). Si el admin dashboard vuelve a no responder, verificar `netstat -ano | findstr :8765` por duplicados antes de asumir un bug de código.

---

## 3. Configuración actual relevante (`.env`)

```
SCANNER_CANDIDATE_LIMIT=30
MIN_QUOTE_VOLUME_USDT=50000000
MIN_ALERT_SCORE_BUY_SPOT=72
MIN_ALERT_SCORE_SELL_SPOT=68
MIN_ALERT_SCORE_LONG_FUTURES=70
MIN_ALERT_SCORE_SHORT_FUTURES=70

AUTO_TRADING_ENABLED=true
AUTO_TRADING_MODE=paper
AUTO_TRADING_CAPITAL_USDT=250
AUTO_TRADING_MAX_POSITIONS=5
AUTO_TRADING_MARKETS=both
AUTO_TRADING_MIN_SCORE=70
AUTO_TRADING_LONG_MIN_SCORE=75
AUTO_TRADING_SHORT_MIN_SCORE=80
AUTO_TRADING_TIMEOUT_HOURS=6
AUTO_TRADING_SESSION_GATE_ENABLED=true
AUTO_TRADING_SESSION_ACTIVE_HOURS=9-22

MICRO_SCALP_ENABLED=true
MICRO_SCALP_MIN_SCORE=75
MICRO_SCALP_STRONG_SCORE=85
MICRO_SCALP_TIMEOUT_MINUTES=30

# ML — activado 2026-07-06, modelo entrenado con 139 samples, AUC=0.719
ML_ENABLED=true
ML_THRESHOLD=0.52

# Blackouts horarios — activados 2026-07-06 (ver sección 0b para análisis de WR)
# Editar para ajustar horas sin tocar código:
SHORT_FUTURES_BLACKOUT_HOURS=6,9,10,11,12,23
LONG_FUTURES_BLACKOUT_HOURS=20,22
BUY_SPOT_BLACKOUT_HOURS=2,6
MICRO_SCALP_BLACKOUT_HOURS_LONG=1,18,22
MICRO_SCALP_BLACKOUT_HOURS_SHORT=7,20
```

> ⚠️ Las variables de blackout NO están en `.env` todavía — el scanner usa los defaults definidos en `app/config.py`. Si se quieren ajustar, añadirlas explícitamente al `.env`.

---

## 4. Pendientes / próximos pasos sugeridos

**Prioridad alta:**
1. **Reiniciar el scanner** para que los blackouts horarios y el ML activo surtan efecto. Verificar en el log:
   - `ML FILTER` / `ML:` — confirma que el modelo está filtrando
   - `BLACKOUT` — confirma que las horas bloqueadas se aplican
   - `MICRO BLACKOUT` — confirma blackouts de micro-scalp por dirección
2. **Verificar el ajuste de velocidad del scanner** (`max_workers` 4→6, ver sección 0) — confirmar que `TIMING CICLO` baja de ~95s sin que `api=` por símbolo suba a 20-30s+ (señal de throttling).
3. **Investigar degradación real de SHORT_FUTURES post-calibración** (ver sección 0d, 2026-07-11) — WR ajustado cayó -6.1pp comparando todo el período pre/post-restart, a diferencia de LONG que se mantuvo casi estable. No es artefacto de TP1/volatilidad como en LONG.
4. **Evaluar blackout adicional en la ventana 13-15 UTC** (apertura Wall Street) — ver sección 0d, WR y retorno por debajo del promedio, SHORT particularmente negativo (-0.76% en hora 14 UTC).

**Prioridad media:**
4. **Monitorear `ml_probability` y `ml_filtered`** en los próximos ciclos — actualmente hay 0 registros históricos de estos campos en la DB (el modelo nunca había estado activo). Tras 2-3 días, correr: `SELECT AVG(ml_probability), COUNT(*) FILTER (WHERE ml_filtered=1) FROM trade_alerts WHERE timestamp > datetime('now','-3 days')`.
5. **Decisión pendiente: bajar `MIN_QUOTE_VOLUME_USDT=20000000`** para incluir EPIC ($25M) y MIRA ($34M) — el usuario no confirmó. Si se baja, monitorear si aparecen señales espurias por iliquidez.
6. **Cache de klines spot incompleta** — `BTCUSDT_spot`, etc. con ~990 filas (vs 59K+ futuros). No crítico para nada operacional.
7. **Símbolos sin datos históricos**: `INJUSDT`, `TRXUSDT`, `STXUSDT` — 0 filas en caché. Posible nombre distinto en Binance USDT-perp.

**Prioridad baja / cuando aplique:**
8. **Configurar túnel Cloudflare** para crypto-dashboard en el admin dashboard.
9. Agregar `"SEÑAL"` al filtro de log del admin para ver actividad por símbolo.
10. **Fix ZECUSDT/news keyword matching** — falsos positivos en HYPEUSDT, POWERUSDT, BEATUSDT por keywords demasiado amplias.
11. **Validar KuCoin trader en sandbox** (`KUCOIN_SANDBOX=true`).
12. **Validar `accumulation_scanner.py`** en producción — primer ciclo completo de detección.

---

## 5. Comandos útiles para retomar

```powershell
# Reiniciar el scanner (necesario para activar ML y blackouts)
# Desde el Admin Dashboard: http://127.0.0.1:8765 → tarjeta Crypto Dashboard → Scanner → Detener → Iniciar

# Ver actividad reciente (incluye ML, blackouts, MICRO)
Get-Content "C:\Users\pedro\crypto-dashboard\logs\app.log" -Tail 100 | Select-String "ALERTA|AUTO |TIMING CICLO|GAP RECOVERY|ERROR|ML FILTER|ML:|BLACKOUT|MICRO BLACKOUT"

# Verificar que el ML está activo y filtrando
Get-Content "C:\Users\pedro\crypto-dashboard\logs\app.log" -Tail 500 | Select-String "Modelo ML cargado|ML FILTER|ML_ENABLED"

# Verificar tamaño de la DB
(Get-Item "C:\Users\pedro\crypto-dashboard\data\crypto_dashboard.sqlite3").Length / 1MB

# Confirmar blackout horario actual (muestra la hora UTC actual y si está en algún blackout)
python -c "import time; from app.config import *; h=time.gmtime().tm_hour; print(f'UTC={h}h | SHORT_block={h in SHORT_FUTURES_BLACKOUT_HOURS} | LONG_block={h in LONG_FUTURES_BLACKOUT_HOURS} | MicroL_block={h in MICRO_SCALP_BLACKOUT_HOURS_LONG} | MicroS_block={h in MICRO_SCALP_BLACKOUT_HOURS_SHORT}')"
```

```python
# Monitorear ml_probability y ml_filtered tras activación (ejecutar desde raíz del proyecto)
from app import database
conn = database._get_conn()
rows = conn.execute("""
    SELECT
        action,
        COUNT(*) as n,
        AVG(ml_probability) as avg_prob,
        SUM(CASE WHEN ml_filtered=1 THEN 1 ELSE 0 END) as n_filtered
    FROM trade_alerts
    WHERE timestamp > datetime('now','-3 days')
      AND ml_probability IS NOT NULL
    GROUP BY action
""").fetchall()
for r in rows: print(r)
```

**Skills disponibles para seguimiento:** `/diagnostico-integral` (reporte completo WR + calibración + sesiones), `/valorar-sistema` (subconjunto sin análisis horario), `/consulta-mercado-internacional` (solo actividad por sesión UTC).
