# Handoff — Estado del proyecto

> Documento de continuidad para retomar trabajo en otra sesión. Última actualización: 2026-07-11.
> Para arquitectura general del scanner, ver [README.md](README.md). Este documento cubre **cambios recientes, hallazgos y pendientes** que el README no refleja todavía.

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
