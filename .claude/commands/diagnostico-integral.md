Ejecuta un diagnóstico integral del sistema, combinando en un solo informe lo que cubren por separado `valorar-sistema` (rendimiento del scanner, calibración, paper trading, micro-scalping y noticias) y `consulta-mercado-internacional` (actividad por sesión horaria UTC), sin duplicar configuración, consultas ni conclusiones.

El análisis debe ejecutarse como **un único** script Python temporal que:
- Use `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')` al inicio para evitar errores de encoding en Windows.
- Conecte a la base de datos mediante `from app import database; conn = database._get_conn()` (o `app/config.DATABASE_PATH` si se necesita acceso crudo).
- Reutilice los mismos DataFrames/consultas base (p. ej. `trade_alerts` + `alert_outcomes` a 60m, `micro_scalp_alerts`) entre las secciones que los necesiten, en vez de re-consultarlos.
- Se elimine al finalizar.

Presenta todos los resultados en tablas markdown. Usa ⚠️ para advertencias y ✅ para confirmaciones positivas.

---

## 0. Histórico de diagnósticos (leer ANTES de ejecutar el análisis)

Los diagnósticos anteriores viven en `outputs/diagnosticos/YYYY-MM-DD.md`. Cada archivo termina con un bloque `## Métricas clave (JSON — para comparación automática entre diagnósticos)` con las cifras del run.

Antes de correr el script:
1. Lista `outputs/diagnosticos/*.md` y lee el **más reciente** (si existe alguno además del de hoy).
2. Extrae su bloque JSON de métricas clave.

En el informe, incluye una sección **"Comparativa con el diagnóstico anterior (fecha)"** con los deltas contra ese JSON: WR ajustado post por acción, WR ajustado por grado (A/B/NO_TRADE), slippage SL paper, WR direccional micro 72h, accuracy de noticias, y — si el JSON previo trae la clave `estructura` — WR ajustado por ruta chartista, retorno forward de setups 3m y WR del micro por niveles vs momentum. Marca con ✅ las métricas que mejoran y con ⚠️ las que se deterioran >2 pp. Si no hay histórico previo, indícalo y omite la sección.

---

## 1. Estado del scanner y cobertura del grado calibrado

- Fecha del último registro en `trade_alerts`, `micro_scalp_alerts` y `market_snapshots`
- Total de alertas con `calibrated_grade != ''` vs total histórico — calcular % de cobertura
- Fecha desde la que empezó a generarse el grado calibrado (MIN timestamp donde calibrated_grade != '')
- Si la cobertura es < 10%, advertir que los datos son insuficientes para conclusiones definitivas

---

## 2. Winrate de alertas principales: pre-calibración vs post-calibración

Usa la fecha de inicio del grado calibrado como punto de corte (variable `RESTART`).

Al construir el dataset de alertas evaluadas a 60m, incluye también de `alert_outcomes`
`max_favorable_excursion`, `hit_tp2`, `hit_stop`, y de `trade_alerts` `entry`, `stop_loss`.
Calcula `risk_pct = ABS(entry - stop_loss) / entry * 100` por alerta.

Para **ambos períodos** (antes y después del corte), calcular por acción (`LONG_FUTURES`, `SHORT_FUTURES`, `SELL_SPOT`, `BUY_SPOT`):
- Total de alertas
- Evaluadas a 60 min (join con `alert_outcomes` WHERE `horizon_minutes=60`)
- **WR oficial**: (wins+partials) / evaluadas, según `outcome`
- **WR ajustado por volatilidad** (R=0.5): `is_win_adj = hit_tp2 OR (max_favorable_excursion >= 0.5 * risk_pct)`. Mide lo mismo pero contra un objetivo proporcional al movimiento típico de 60m, en vez del TP1 fijo (≥1.5R)
- Retorno promedio
- Delta de ambos WR (oficial y ajustado) entre ambos períodos

Presentar en tabla comparativa con columnas para WR oficial y WR ajustado. Si el post-calibración tiene < 20 evaluaciones por acción, indicarlo como muestra pequeña.

⚠️ **Nota de interpretación**: si el WR oficial cae pero el WR ajustado se mantiene o sube (y `%outcome='loss'` no aumenta), la caída es un artefacto de la distancia TP1/régimen de volatilidad — no recalibrar el scoring de esa acción basándose solo en el WR oficial. (Validado: tras subir `_MIN_SL_PCT_FUTURES` de 1.5%→2.0%, el TP1 mínimo pasó de 2.25%→3.0% mientras el movimiento real de 60m bajó, inflando `outcome='neutral'`.)

---

## 3. Winrate por grado calibrado (solo alertas post-restart)

Para los registros con `calibrated_grade != ''`, agrupar por `calibrated_grade` y `action`:
- n alertas, n evaluadas
- **WR oficial** y **WR ajustado** (R=0.5, ver §2 — mismo cálculo de `risk_pct`/`max_favorable_excursion`/`hit_tp2`/`hit_stop`)
- Retorno promedio
- Sub-scores promedio: `AVG(direction_score)`, `AVG(entry_score)`, `AVG(risk_score)`

Presentar como tabla ordenada por grado (A → B → C → NO_TRADE → WATCH), con ambas columnas de WR.

Hipótesis a validar: **¿el grado A tiene mayor WR que B, y B mayor que C?** Evaluar principalmente con el **WR ajustado** (más representativo a 60m); mencionar el WR oficial como referencia.
- Si se cumple: confirmar que la calibración discrimina correctamente
- Si no se cumple: señalar el grado que rompe el patrón y en qué acción

---

## 3b. Estrategia de estructura: rutas chartistas, setups 3m y micro por niveles

Fecha de activación: `RESTART_STRUCT = '2026-07-18'` (primer despliegue de `level_breakout`/`pattern_break`/`structure_json`). Si existen alertas con `setup_route='level_breakout'`, usar `MIN(timestamp)` de esas como fecha real y reportarla. Si el scanner aún no se ha reiniciado con este código, indicarlo y omitir las tablas vacías.

### 3b-i. WR por ruta de setup (chartista vs flujo)

Sobre el dataset de §2 (alertas + outcomes 60m), agrupar por `setup_route` de `trade_alerts` (`level_breakout`, `pattern_break`, `classic_trigger`, `momentum_continuation`, `none`/vacío):
- n, evaluadas, **WR oficial**, **WR ajustado** (R=0.5, ver §2), retorno promedio
- Desglose por `trigger_type` para las rutas nuevas (`level_breakout_up/down`, `*_break`)

**Hipótesis**: ¿las rutas chartistas superan a `classic_trigger`/`momentum_continuation` en WR ajustado? ⚠️ Marcar muestra pequeña si evaluadas < 20 por ruta — no concluir con menos.

### 3b-ii. Setups de estructura 3m (los del panel del dashboard)

De `market_snapshots` WHERE `structure_json != '{}'` (columna creada 2026-07-18):
- Cobertura: n filas con estructura, rango de fechas, % sobre el total del período
- Conteo de señales: breakouts confirmados (up/down), patrones confirmados por tipo (`head_and_shoulders`, `double_top`, etc.), patrones en formación
- **Confirmación de flujo** (los mismos 4 checks del panel, con las columnas de la misma fila): delta alineado, cvd_15m alineado, |imbalance| ≥ 0.08 alineado, relative_volume ≥ 1.5 — distribución de checks (0-4) entre los setups confirmados
- **Rendimiento forward aproximado (DB-only)**: por cada snapshot con breakout o patrón confirmado, buscar el siguiente snapshot del MISMO símbolo con timestamp ≥ +55 min y calcular retorno con signo según la dirección de la señal (`(precio_fwd − precio)/precio × dir`). Reportar n medibles, retorno promedio, % positivo — separado por tipo de señal y dirección, y también segmentado por checks de flujo (0-2 vs 3-4) para validar si la confirmación por órdenes/volumen discrimina. Indicar cuántas señales quedaron sin snapshot posterior (excluidas).
- ⚠️ Es aproximación: los snapshots solo existen con `score >= SNAPSHOT_MIN_SCORE` y el forward depende de que el símbolo re-aparezca — tratar como tendencia, no como WR exacto.

### 3b-iii. Micro-scalp: método por niveles vs momentum puro

De `micro_scalp_alerts` con `timestamp >= RESTART_STRUCT`, clasificar por `reasons_json`:
- **nivel**: contiene "Rebote en soporte" o "Rechazo en resistencia"
- **momentum**: el resto

Comparar por grupo (y por acción): n, WR direccional, PnL promedio, MFE/MAE promedio.
**Hipótesis**: ¿el método de rebote en nivel mejora el WR direccional del micro-scalp (base histórica: 24-30%)?

---

## 4. Análisis de posiciones paper: impacto del SL fix

Separar `auto_positions` cerradas (mode='paper') en **antes y después del restart**:

Para **cierres por `close_reason='sl'`** en ambos períodos, calcular:
- n cierres
- `AVG(total_pnl_pct)` (pérdida promedio registrada)
- Pérdida "esperada" según distancia configurada: `AVG(ABS(sl - entry_price) / entry_price * 100 * leverage)`
- Diferencia entre real y esperado (= slippage ficticio promedio)
- PnL total acumulado

Para **todos los cierres** agrupados por `close_reason`:
- n, avg_pct, PnL total acumulado por razón

Si la media de pérdida por SL bajó post-restart, confirmar que el fix redujo las pérdidas ficticias.
Si aparece `close_reason='paper_hard_cap'`, reportarlo como evidencia del hard cap actuando.

---

## 5. Micro-scalping: últimas 72h ancladas al último timestamp real

Usar `MAX(timestamp)` de `micro_scalp_alerts` como ancla y restar 72h.

Por acción (`MICRO_LONG_SCALP`, `MICRO_SHORT_SCALP`):
- Total, cerradas, abiertas
- W/P/L (outcome = 'win' / 'partial' / 'loss')
- WR direccional (wins / (wins+losses))
- PnL promedio de los cerrados evaluados
- MFE promedio (max_favorable_pct) y MAE promedio (max_adverse_pct)

**Diagnóstico de asimetría R:R**: si WR > 50% pero PnL promedio es negativo, advertir que las pérdidas superan las ganancias en magnitud — el timeout/SL puede estar demasiado ajustado o el TP demasiado lejano para el horizonte.

---

## 6. Módulo de noticias: accuracy y correlación con alertas

⚠️ **Nota**: el 2026-07-18 se purgó TODO el histórico de noticias (matching por substring corregido — ver HANDOFF §0i). Solo evaluar datos con `timestamp >= '2026-07-18'`; no comparar accuracy con diagnósticos previos a esa fecha. Si hay pocas predicciones resueltas, reportar "recolectando datos" en vez de conclusiones.

### 6a. Accuracy de predicciones de noticias

De `news_predictions` WHERE `outcome != 'open'`, calcular:
- Por combinación (`prediction`, `outcome`): n, avg_return_pct, avg_confidence
- Accuracy global BULLISH: corrects / (corrects + incorrects)
- Accuracy global BEARISH: corrects / (corrects + incorrects)
- Tasa de predicciones NEUTRAL (señal de que el módulo no discrimina bien cuando hay pocas noticias)

### 6b. Correlación noticia → alerta

Join aproximado: `trade_alerts` con `news_predictions` WHERE `np.symbol = ta.symbol` AND `np.timestamp <= ta.timestamp` AND `np.timestamp >= datetime(ta.timestamp, '-6 hours')`.

Clasificar cada alerta como:
- **ALINEADA**: acción bullish + predicción BULLISH, o acción bearish + predicción BEARISH
- **CONTRARIA**: acción bullish + predicción BEARISH, o viceversa
- **NEUTRAL**: predicción NEUTRAL

Por clasificación, reportar: n alertas, n evaluadas (join alert_outcomes 60min), WR, retorno promedio.

**Hipótesis a validar**: ¿alertas ALINEADAS tienen WR/retorno mayor que CONTRARIAS?
- Si sí: el módulo de noticias tiene valor predictivo y podría usarse como gate o bonus de score
- Si no hay diferencia estadística: señalarlo — puede necesitar más datos o mejor fuente de noticias

### 6c. Símbolos más cubiertos por noticias

Top 10 símbolos por `COUNT(*)` en `news_events`, con su accuracy de predicción si tienen datos en `news_predictions`.

### 6d. Alertas de seguridad activas

De `security_event_alerts`, listar: symbol, severity, confirmation_status, security_score, title (truncado a 80 chars), created_at.
Si hay 0 registros, indicarlo brevemente.

---

## 7. Actividad de mercado por sesión horaria UTC

Reutiliza el dataset de alertas evaluadas a 60m de la sección 2 y el de `micro_scalp_alerts` de la sección 5 — no vuelvas a consultarlos desde cero, solo agrúpalos también por `strftime('%H', timestamp)`.

### 7a. Win rate y retorno promedio por hora UTC (alertas normales, horizon 60m, outcomes win/partial/loss)

### 7b. Win rate y PnL promedio por hora UTC (micro-scalping)

### 7c. Resumen por bloque de sesión institucional

- Asia profunda (00-07 UTC) — Tokio/Shanghái
- Overlap Asia-Europa (07-09 UTC) — cierre Asia + apertura Europa
- Europa sola (09-13 UTC) — Frankfurt/Londres sin NY
- Overlap Europa-US (13-17 UTC) — apertura Wall Street
- US sola (17-22 UTC) — sesión americana
- Dead zone (22-00 UTC) — madrugada global

### 7d. Retorno por hora desglosado entre LONG_FUTURES y SHORT_FUTURES

### 7e. Top símbolos por sesión (min 3 alertas, ordenados por avg retorno)

---

## 8. Resumen ejecutivo

Presenta un único bloque de conclusiones combinando ambos análisis:

- **¿Subió el WR tras los cambios recientes?** (comparar pre vs post con números concretos)
- **¿El grado calibrado A/B discrimina mejor que C/NO_TRADE?** (sí/no + dato)
- **¿El SL fix redujo las pérdidas ficticias en paper?** (sí/no + cuánto)
- **¿El micro-scalping tiene asimetría R:R negativa?** (advertencia si WR>50% pero PnL<0)
- **¿Las rutas chartistas rinden mejor que las de flujo?** (WR ajustado de `level_breakout`/`pattern_break` vs `classic_trigger`/`momentum_continuation`, con n)
- **¿El timeframe 3m de estructura muestra edge?** (retorno forward de setups confirmados por checks de flujo 3-4 vs 0-2, y micro por niveles vs momentum)
- **¿Las noticias predicen algo útil?** (accuracy BULLISH/BEARISH + ¿hay diferencia de WR entre alineadas y contrarias?; solo datos post-purga 2026-07-18)
- **¿Qué hora UTC tiene el mayor WR y retorno, y qué bloque es mejor/peor para micro-scalp?** (incluir equivalencia en hora México, UTC-6)
- **Comportamiento en la apertura de Wall Street (13:30-15:30 UTC)**
- **¿Qué cambió desde el diagnóstico anterior?** (resumen de la comparativa de la sección 0; omitir si no hay histórico)
- **Próximos pasos sugeridos** (máximo 3 puntos concisos)

---

## 9. Persistencia del diagnóstico (paso final obligatorio)

Guarda el informe completo en `outputs/diagnosticos/YYYY-MM-DD.md` (fecha de hoy; sobrescribir si ya existe uno del mismo día). El archivo debe:

- Empezar con un encabezado que incluya la fecha, el valor de RESTART y el último timestamp de `trade_alerts`.
- Contener todas las secciones y tablas del informe.
- Terminar con un bloque de código JSON bajo el encabezado exacto `## Métricas clave (JSON — para comparación automática entre diagnósticos)` con esta estructura (es la que leerán los diagnósticos futuros — mantener claves estables):

```json
{
  "fecha": "YYYY-MM-DD",
  "restart": "...",
  "cobertura_grado_pct": 0.0,
  "total_alertas": 0,
  "wr_post": {"<ACCION>": {"n_eval": 0, "wr_oficial": 0.0, "wr_ajustado": 0.0, "pct_loss": 0.0, "ret_avg": 0.0}},
  "wr_por_grado_ajustado": {"A": 0.0, "B": 0.0, "C": 0.0, "NO_TRADE": 0.0},
  "n_por_grado": {"A": 0, "B": 0, "C": 0, "NO_TRADE": 0},
  "paper": {"sl_slippage_pp_post": 0.0, "sl_n_post": 0, "sl_avg_pct_post": 0.0, "pnl_neto_post_usdt": 0.0, "hard_cap_n": 0},
  "micro_72h": {"<ACCION>": {"n": 0, "wr_dir": 0.0, "pnl_avg": 0.0, "mfe": 0.0, "mae": 0.0}},
  "estructura": {
    "restart_struct": "2026-07-18",
    "por_ruta": {"<RUTA>": {"n_eval": 0, "wr_oficial": 0.0, "wr_ajustado": 0.0, "ret_avg": 0.0}},
    "setups_3m": {"n_confirmados": 0, "n_forward_medibles": 0, "ret_fwd_avg": 0.0, "pct_positivo": 0.0,
                  "ret_fwd_flujo_alto": 0.0, "ret_fwd_flujo_bajo": 0.0},
    "micro_metodo": {"nivel": {"n": 0, "wr_dir": 0.0, "pnl_avg": 0.0},
                     "momentum": {"n": 0, "wr_dir": 0.0, "pnl_avg": 0.0}}
  },
  "noticias": {"acc_bullish": 0.0, "acc_bearish": 0.0, "tasa_neutral": 0.0, "wr_alineada": 0.0, "wr_contraria": 0.0},
  "sesiones": {"mejor_hora_wr": "", "mejor_hora_ret": "", "peor_hora_wr": "", "mejor_bloque_alertas": "", "mejor_bloque_micro": "", "peor_bloque_micro": ""}
}
```
