Ejecuta un diagnóstico integral del sistema, combinando en un solo informe lo que cubren por separado `valorar-sistema` (rendimiento del scanner, calibración, paper trading, micro-scalping y noticias) y `consulta-mercado-internacional` (actividad por sesión horaria UTC), sin duplicar configuración, consultas ni conclusiones.

El análisis debe ejecutarse como **un único** script Python temporal que:
- Use `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')` al inicio para evitar errores de encoding en Windows.
- Conecte a la base de datos mediante `from app import database; conn = database._get_conn()` (o `app/config.DATABASE_PATH` si se necesita acceso crudo).
- Reutilice los mismos DataFrames/consultas base (p. ej. `trade_alerts` + `alert_outcomes` a 60m, `micro_scalp_alerts`) entre las secciones que los necesiten, en vez de re-consultarlos.
- Se elimine al finalizar.

Presenta todos los resultados en tablas markdown. Usa ⚠️ para advertencias y ✅ para confirmaciones positivas.

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
- **¿Las noticias predicen algo útil?** (accuracy BULLISH/BEARISH + ¿hay diferencia de WR entre alineadas y contrarias?)
- **¿Qué hora UTC tiene el mayor WR y retorno, y qué bloque es mejor/peor para micro-scalp?** (incluir equivalencia en hora México, UTC-6)
- **Comportamiento en la apertura de Wall Street (13:30-15:30 UTC)**
- **Próximos pasos sugeridos** (máximo 3 puntos concisos)
