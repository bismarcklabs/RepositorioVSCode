# Handoff — Estado del proyecto

> Documento de continuidad para retomar trabajo en otra sesión. Última actualización: 2026-06-24.
> Para arquitectura general del scanner, ver [README.md](README.md). Este documento cubre **cambios recientes, hallazgos y pendientes** que el README no refleja todavía.

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

MICRO_SCALP_TIMEOUT_MINUTES=30
```

---

## 4. Pendientes / próximos pasos sugeridos

**Prioridad alta:**
1. **Verificar la corrección de velocidad del scanner** — reiniciar y confirmar que `TIMING CICLO` baja de 255s a ~35-40s. Si sigue lento, el cuello de botella podría estar en `get_technical_context()` o `get_volume_profile()` en vez de en la concurrencia.
2. **Monitorear WR tras los nuevos thresholds direccionales** (`AUTO_TRADING_LONG_MIN_SCORE=75`, `SHORT_MIN_SCORE=80`) — correr `/diagnostico-integral` en ~1 semana para confirmar que el EV de SHORT mejora.

**Prioridad media:**
3. **Entrenar el modelo ML** (`ML_ENABLED=false` actualmente) — ya hay 4,090+ outcomes etiquetados, suficiente para `ML_MIN_SAMPLES=50`. Dado que el score lineal actual tiene correlación ~0 con WR, un modelo entrenado podría discriminar mejor que los sub-scores manuales.
4. **Cache de klines spot incompleta** — `BTCUSDT_spot`, `ETHUSDT_spot`, etc. solo tienen ~990 filas en 1h (vs 59K+ de futuros) por rate-limiting de la API spot de Binance durante la descarga inicial. No crítico (nada operacional depende de la caché) pero limita los scripts de validación para señales BUY_SPOT/SELL_SPOT.
5. **Símbolos sin datos históricos**: `INJUSDT`, `TRXUSDT`, `STXUSDT` devolvieron 0 filas al construir la caché — posible nombre distinto en Binance USDT-perp o no disponibles.

**Prioridad baja / cuando aplique:**
6. **Configurar túnel Cloudflare** para crypto-dashboard en el admin dashboard (`services.json` → agregar bloque `"tunnel"` cuando exista subdominio).
7. Considerar agregar `"SEÑAL"` explícitamente al filtro de log del admin si se quiere ver actividad por símbolo, no solo resúmenes de ciclo.

---

## 5. Comandos útiles para retomar

```powershell
# Reiniciar el scanner (después de cambios en .env o código)
# Desde el Admin Dashboard: http://127.0.0.1:8765 → tarjeta Crypto Dashboard → Scanner → Detener → Iniciar

# Ver actividad reciente del scanner (líneas relevantes)
Get-Content "C:\Users\pedro\crypto-dashboard\logs\app.log" -Tail 50 | Select-String "ALERTA|AUTO |TIMING CICLO|GAP RECOVERY|ERROR"

# Verificar tamaño de la DB
(Get-Item "C:\Users\pedro\crypto-dashboard\data\crypto_dashboard.sqlite3").Length / 1MB
```

```python
# Diagnóstico rápido de WR (desde un script temporal en el proyecto)
from app import database
conn = database._get_conn()
# Usar el patrón de scripts/validate_parameters.py o invocar el skill /diagnostico-integral
```

**Skills disponibles para seguimiento:** `/diagnostico-integral` (reporte completo WR + calibración + sesiones), `/valorar-sistema` (subconjunto sin análisis horario), `/consulta-mercado-internacional` (solo actividad por sesión UTC).
