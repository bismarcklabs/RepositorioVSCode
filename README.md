# Institutional Crypto Dashboard

Escáner institucional de oportunidades en criptomonedas en tiempo real, construido sobre la API pública de Binance Futures. El sistema evalúa hasta 50 pares USDT simultáneamente mediante un sistema de puntuación de confluencia de 6 capas, emite recomendaciones concretas (LONG_FUTURES, SHORT_FUTURES, BUY_SPOT, SELL_SPOT o WAIT) y muestra los resultados en un dashboard Streamlit con auto-refresh de 15 segundos.

---

## Propósito

El objetivo no es mostrar datos de mercado en bruto, sino **filtrar ruido y detectar confluencias institucionales**: momentos en los que el flujo de órdenes, la estructura técnica, el perfil de volumen, el footprint de trades, las métricas de futuros y (opcionalmente) el GEX de opciones apuntan en la misma dirección con suficiente convicción para justificar una acción.

---

## Arquitectura: escáner en dos pasadas

```
Pasada 1 — batch (3 llamadas API)
  get_futures_ticker_all()    → precios y volumen 24h
  get_premium_index_all()     → funding rates
  get_book_ticker_all()       → spread bid/ask

  → score preliminar = |Δprecio|×5 + |funding|×30 000 + min(10, vol/2e8)
  → seleccionar top-50 candidatos

Pasada 2 — por símbolo en paralelo (ThreadPoolExecutor)
  Para cada candidato (6 workers):
    get_open_interest()       → interés abierto
    get_orderbook_raw()       → OBI (order book imbalance)
    get_technical_context()   → EMA-20/50, VWAP, momentum, relative volume
    get_volume_profile()      → POC, HVN, LVN desde klines 1m×60
    get_footprint()           → delta, absorción, imbalance apilado (aggTrades)
    get_gex_levels()          → GEX opcional (solo BTC/ETH, Deribit público)

  → calculate_opportunity_score()   → puntuación 0-100 con sub-scores
  → build_trade_recommendation()    → acción concreta + confianza + invalidación
  → ordenar por score → top-20 al dashboard
```

Este diseño evita cientos de llamadas secuenciales: las 3 llamadas batch filtran el universo de ~300 pares a 50 candidatos antes de hacer el análisis costoso.

---

## Sistema de puntuación de confluencia (0–100)

| Componente | Peso máximo | Fuente de datos |
|---|---|---|
| Flow score | 30 pts | Señal CVD, OBI, liquidaciones |
| Technical score | 20 pts | VWAP, EMA-20/50, retorno 1h, rel. volume |
| Volume Profile score | 15 pts | POC/HVN/LVN desde klines 1m×60 |
| Footprint score | 15 pts | Absorción, imbalance apilado, delta |
| Futures score | 15 pts | OI activo, dirección funding, liquidaciones |
| GEX score | 5 pts | Put wall / call wall, gamma flip (BTC/ETH) |
| Risk penalty | −30 pts | Funding extremo, spread alto, contradicción |

### Detalle por componente

**Flow score (30 pts)**
- Señal de acumulación/distribución: +12 pts
- CVD alineado con la señal: +6 pts
- OBI alineado con la señal: +6 pts
- Confirmación por liquidaciones: +6 pts

**Technical score (20 pts)**
- Precio sobre/bajo VWAP: +6 pts
- Estructura EMA-20 > EMA-50 (o inverso): +5 pts
- Momentum 1h ≥ 1.5%: +5 pts
- Volumen relativo ≥ 2×: +4 pts

**Volume Profile score (15 pts)**
- Precio a ≤ 0.3% del POC/HVN: +15 pts
- A ≤ 0.8%: +10 pts
- A ≤ 2.0%: +5 pts
- Precio sobre LVN (soporte débil): +5 pts adicionales

**Footprint score (15 pts)**
- Absorción detectada y alineada: +5 pts
- Imbalance apilado (3+ buckets consecutivos): +5 pts
- Delta de footprint alineado: +5 pts

**Futures score (15 pts)**
- OI activo (> 0): +3 pts
- Funding en dirección favorable: +7 pts (funding negativo = favorece longs)
- Actividad de liquidaciones reciente: +5 pts

**GEX score (5 pts)** *(solo BTC/ETH)*
- Precio cerca de put wall (soporte de dealers): +3 pts
- Precio sobre gamma flip: +2 pts (régimen de tendencia)

**Risk penalty (máx −30 pts)**
- Funding extremo (|rate| > EXTREME_FUNDING_ABS): −15 pts
- Spread alto (> MAX_SPREAD_PCT): −10 pts
- Señal neutral: −10 pts
- Contradicción tendencia/señal: −5 pts

---

## Recomendaciones de trading

| Acción | Condiciones |
|---|---|
| LONG_FUTURES | Señal bullish + score ≥ 80 + OI > 0 + funding < extremo + riesgo ≤ medium + **precio sobre VWAP** |
| SHORT_FUTURES | Señal bearish + score ≥ 80 + OI > 0 + funding ≥ 0 + riesgo ≤ medium + **precio bajo VWAP** |
| BUY_SPOT | Señal bullish + score ≥ 75 + trend ≠ bearish + riesgo ≤ medium |
| SELL_SPOT | Señal bearish + score ≥ 70 + trend ≠ bullish + riesgo ≤ medium |
| WAIT | Cualquier condición no cumplida |

La puerta VWAP es obligatoria para futuros: no se abre un LONG por encima del ask si el precio está bajo VWAP, ni un SHORT si está sobre VWAP.

---

## Estructura del proyecto

```
crypto-dashboard/
├── app/
│   ├── main.py               # Dashboard Streamlit (escáner + UI)
│   ├── config.py             # Variables de entorno y umbrales
│   ├── market_scanner.py     # Escáner en dos pasadas, filtros de liquidez
│   ├── market_data.py        # Capa de acceso a Binance API (TTL cache)
│   ├── websocket_client.py   # Stream aggTrades en tiempo real
│   ├── indicators.py         # Delta, CVD, OBI (deduplicación por trade_id)
│   ├── technical_context.py  # EMA, VWAP, momentum, trend_bias
│   ├── volume_profile.py     # POC / HVN / LVN desde klines 1m×60
│   ├── footprint.py          # Delta por precio, absorción, imbalance apilado
│   ├── gex_levels.py         # GEX desde Deribit (BTC/ETH, caché 5 min)
│   ├── scoring.py            # Puntuación de confluencia 6 componentes
│   ├── trade_advisor.py      # Lógica de recomendación de acción
│   ├── signals.py            # Generación de señales institucionales
│   ├── orderbook.py          # Análisis de libro de órdenes
│   ├── futures.py            # Endpoints de futuros Binance
│   ├── liquidations.py       # WebSocket de liquidaciones forzadas
│   └── alerts.py             # Sistema de alertas de riesgo
├── tests/
│   ├── test_volume_profile.py
│   ├── test_footprint.py
│   ├── test_scoring.py
│   ├── test_trade_advisor.py
│   ├── test_indicators.py
│   ├── test_market_scanner.py
│   └── test_technical_context.py
├── requirements.txt
├── .env.example
└── setup.ps1 / setup.bat
```

---

## Instalación

### Requisitos previos
- Python 3.8+
- Git

### Pasos

```powershell
# 1. Clonar repositorio
git clone https://github.com/yourusername/crypto-dashboard.git
cd crypto-dashboard

# 2. Crear entorno virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
copy .env.example .env
# Editar .env si se quiere ajustar umbrales (ver sección Configuración)

# 5. Ejecutar dashboard
streamlit run app/main.py
```

Dashboard disponible en `http://localhost:8501`

---

## Configuración (`.env`)

Todos los parámetros tienen valores por defecto funcionales. Solo es necesario editar `.env` para calibrar umbrales.

```env
# Credenciales Binance (opcional — todos los endpoints son públicos)
BINANCE_API_KEY=
BINANCE_API_SECRET=

# URL base Binance Futures (no cambiar salvo testnet)
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com

# ── Escáner ───────────────────────────────────────────────────────────────
# Candidatos a evaluar en pasada 2 (top N por score preliminar)
SCANNER_CANDIDATE_LIMIT=50
# Pares mostrados en el dashboard tras el ranking final
SCANNER_RESULT_LIMIT=20
# Volumen mínimo 24h en USDT para incluir un par
MIN_QUOTE_VOLUME_USDT=50000000
# Spread máximo permitido en % para considerar el par líquido
MAX_SPREAD_PCT=0.08

# ── Umbrales de acción ────────────────────────────────────────────────────
MIN_ALERT_SCORE_BUY_SPOT=75
MIN_ALERT_SCORE_SELL_SPOT=70
MIN_ALERT_SCORE_LONG_FUTURES=80
MIN_ALERT_SCORE_SHORT_FUTURES=80
# Funding rate considerado extremo (bloquea futuros)
EXTREME_FUNDING_ABS=0.001

# ── Features ──────────────────────────────────────────────────────────────
ENABLE_LIQUIDATIONS=true
```

### Calibración de umbrales

El sistema está calibrado para **pocos alertas de alta convicción**. En mercados laterales es normal ver todas las acciones en WAIT. Para recibir más alertas en condiciones normales, bajar los umbrales:

```env
MIN_ALERT_SCORE_BUY_SPOT=65
MIN_ALERT_SCORE_SELL_SPOT=60
MIN_ALERT_SCORE_LONG_FUTURES=70
MIN_ALERT_SCORE_SHORT_FUTURES=70
```

Para reducir alertas en mercados muy volátiles (filtrar solo las mejores), subir a 85–90.

---

## Secciones del dashboard

1. **Tarjetas de acción**: Los pares con acción ≠ WAIT muestran acción, confianza, contexto de entrada, niveles de invalidación y breakdown de sub-scores (`Flow X/30 · Téc Y/20 · VP Z/15 · FP W/15 · Fut V/15 · GEX U/5 · Pen -N`)
2. **Tabla de ranking**: Todos los pares evaluados ordenados por score, con todas las columnas de sub-scores
3. **Near-miss**: Pares con score ≥ 55, acción=WAIT y señal no neutral — los más cercanos a generar una alerta
4. **Gráficos**: Delta, CVD, volumen y precio del símbolo seleccionado
5. **Grid compacto**: Vista rápida de los 20 pares con sus métricas principales
6. **Alertas de riesgo**: Condiciones de estrés detectadas (liquidaciones masivas, funding extremo, etc.)

---

## Módulos clave

### `volume_profile.py`
Calcula POC (Point of Control), HVN (High Volume Nodes) y LVN (Low Volume Nodes) distribuyendo el volumen en USDT de las últimas 60 velas de 1 minuto en 50 buckets de precio. No requiere llamadas API adicionales — usa el caché de klines (TTL 30 s) de `market_data.py`.

### `footprint.py`
Analiza el flujo de aggTrades para calcular:
- **Delta por precio**: `ask_vol - bid_vol` (maker=False → buy aggressor)
- **Stacked imbalance**: 3+ buckets consecutivos donde un lado supera 2× al otro
- **Absorción**: presión dominante pero el precio se mueve en sentido contrario

Usa el buffer del WebSocket (`websocket_client.py`) con fallback REST de 100 aggTrades.

### `gex_levels.py`
Obtiene datos de opciones de Deribit (API pública) para BTC y ETH, calcula GEX por strike con Black-Scholes gamma y detecta:
- **Call wall / Put wall**: strikes con mayor exposición positiva/negativa
- **Gamma flip**: nivel donde el GEX neto cambia de signo (transición dealer)

Caché de 5 minutos. Retorna `None` para cualquier otro símbolo o si Deribit no responde — el scoring usa 0 pts para GEX en ese caso sin interrumpir el flujo.

### `market_data.py`
Capa de acceso centralizada con:
- Session por thread (thread-safe)
- Caché compartida con lock y TTL por endpoint
- Funciones batch para reducir llamadas en la pasada 1

---

## Tests

```bash
pytest tests/ -v
```

61 tests distribuidos en 7 archivos. Todos los tests usan mocks para las llamadas API — no requieren conexión a Binance.

| Archivo | Tests | Cubre |
|---|---|---|
| `test_volume_profile.py` | 8 | POC, HVN, LVN, datos insuficientes |
| `test_footprint.py` | 8 | Delta, absorción, imbalance, fallback |
| `test_scoring.py` | 13 | Sub-scores, penalizaciones, rango 0-100 |
| `test_trade_advisor.py` | 14 | VWAP gate, umbrales, VP invalidation |
| `test_indicators.py` | 6 | CVD deduplicación por trade_id |
| `test_market_scanner.py` | 6 | Filtros liquidez, sorting, stablecoins |
| `test_technical_context.py` | 6 | EMA, VWAP, trend_bias |

---

## Notas de implementación

- **CVD deduplicación**: usa `aggTradeId` (campo `a`) como clave, no timestamp, para evitar doble conteo en reconexiones WebSocket
- **Python 3.8+**: usa `Optional[T]` en lugar de `T | None` por compatibilidad
- **Stablecoins**: lista negra explícita (`USDCUSDT`, `FDUSDUSDT`, `TUSDUSDT`, etc.) para evitar falsos positivos en el escáner
- **Reconexión WebSocket**: bucle `while True` con backoff, sin recursión
- **Auto-refresh**: `streamlit-autorefresh` con intervalo de 15 s vía JavaScript (no bloquea el hilo principal)

---

## Disclaimer

Este dashboard es una herramienta de análisis. Ninguna señal constituye asesoramiento financiero. El trading de criptomonedas conlleva riesgo significativo de pérdida. Siempre verifica los datos de forma independiente antes de tomar decisiones de trading.
