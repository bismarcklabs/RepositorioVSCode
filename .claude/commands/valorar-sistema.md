Ejecuta una evaluación completa del rendimiento del sistema de alertas, incluyendo calibración de grados, posiciones paper, micro-scalping y correlación con el módulo de noticias.

Usa `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')` al inicio del script para evitar errores de encoding en Windows.

El análisis debe ejecutarse como un script Python temporal que conecte a la base de datos mediante `from app import database; conn = database._get_conn()`. Al finalizar, elimina el script.

---

## 1. Estado del scanner y cobertura del grado calibrado

- Fecha del último registro en `trade_alerts`, `micro_scalp_alerts` y `market_snapshots`
- Total de alertas con `calibrated_grade != ''` vs total histórico — calcular % de cobertura
- Fecha desde la que empezó a generarse el grado calibrado (MIN timestamp donde calibrated_grade != '')
- Si la cobertura es < 10%, advertir que los datos son insuficientes para conclusiones definitivas

---

## 2. Winrate de alertas principales: pre-calibración vs post-calibración

Usa la fecha de inicio del grado calibrado como punto de corte (variable `RESTART`).

Para **ambos períodos** (antes y después del corte), calcular por acción (`LONG_FUTURES`, `SHORT_FUTURES`, `SELL_SPOT`, `BUY_SPOT`):
- Total de alertas
- Evaluadas a 60 min (join con `alert_outcomes` WHERE `horizon_minutes=60`)
- WR direccional (wins+partials) / evaluadas
- Retorno promedio
- Delta de WR entre ambos períodos

Presentar en tabla comparativa. Si el post-calibración tiene < 20 evaluaciones por acción, indicarlo como muestra pequeña.

---

## 3. Winrate por grado calibrado (solo alertas post-restart)

Para los registros con `calibrated_grade != ''`, agrupar por `calibrated_grade` y `action`:
- n alertas, n evaluadas, WR direccional, retorno promedio
- Sub-scores promedio: `AVG(direction_score)`, `AVG(entry_score)`, `AVG(risk_score)`

Presentar como tabla ordenada por grado (A → B → C → NO_TRADE → WATCH).

Hipótesis a validar: **¿el grado A tiene mayor WR que B, y B mayor que C?**
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

## 7. Resumen ejecutivo

Al final, presenta un bloque de conclusiones con:
- **¿Subió el WR tras los cambios recientes?** (comparar pre vs post con números concretos)
- **¿El grado calibrado A/B discrimina mejor que C/NO_TRADE?** (sí/no + dato)
- **¿El SL fix redujo las pérdidas ficticias en paper?** (sí/no + cuánto)
- **¿El micro-scalping tiene asimetría R:R negativa?** (advertencia si WR>50% pero PnL<0)
- **¿Las noticias predicen algo útil?** (accuracy BULLISH/BEARISH + ¿hay diferencia de WR entre alineadas y contrarias?)
- **Próximos pasos sugeridos** (máximo 3 puntos concisos)

Presenta todos los resultados en tablas markdown. Usa ⚠️ para advertencias y ✅ para confirmaciones positivas.
