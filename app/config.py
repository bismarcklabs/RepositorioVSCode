import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DOTENV_PATH = ROOT_DIR / ".env"

if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH, override=True)

# ── Binance credentials (optional — public endpoints work without them) ────
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ── KuCoin credentials (requeridas solo para AUTO_TRADING_EXCHANGE=kucoin real) ─
KUCOIN_API_KEY    = os.getenv("KUCOIN_API_KEY", "")
KUCOIN_API_SECRET = os.getenv("KUCOIN_API_SECRET", "")
KUCOIN_PASSPHRASE = os.getenv("KUCOIN_PASSPHRASE", "")
KUCOIN_SANDBOX    = os.getenv("KUCOIN_SANDBOX", "false").lower() == "true"

# ── Binance base URLs ──────────────────────────────────────────────────────
BINANCE_FUTURES_BASE_URL = os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com")

# ── Scanner configuration ──────────────────────────────────────────────────
SCANNER_CANDIDATE_LIMIT = int(os.getenv("SCANNER_CANDIDATE_LIMIT", "50"))
SCANNER_RESULT_LIMIT = int(os.getenv("SCANNER_RESULT_LIMIT", "20"))
MIN_QUOTE_VOLUME_USDT = float(os.getenv("MIN_QUOTE_VOLUME_USDT", "50000000"))   # $50M
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.08"))                      # 0.08%

# ── Alert thresholds (por tipo de acción) ─────────────────────────────────
MIN_ALERT_SCORE_BUY_SPOT = int(os.getenv("MIN_ALERT_SCORE_BUY_SPOT", "85"))
MIN_ALERT_SCORE_SELL_SPOT = int(os.getenv("MIN_ALERT_SCORE_SELL_SPOT", "70"))
MIN_ALERT_SCORE_LONG_FUTURES = int(os.getenv("MIN_ALERT_SCORE_LONG_FUTURES", "80"))
MIN_ALERT_SCORE_SHORT_FUTURES = int(os.getenv("MIN_ALERT_SCORE_SHORT_FUTURES", "80"))
EXTREME_FUNDING_ABS = float(os.getenv("EXTREME_FUNDING_ABS", "0.001"))
NEAR_MISS_THRESHOLD = int(os.getenv("NEAR_MISS_THRESHOLD", "55"))


def _parse_hour_set(env_key: str, default: str = "") -> frozenset:
    """Parsea una lista de horas UTC separadas por coma desde una variable de entorno."""
    val = os.getenv(env_key, default)
    if not val.strip():
        return frozenset()
    return frozenset(int(h.strip()) for h in val.split(",") if h.strip().isdigit())

# ── Blackout horario por tipo de operación (UTC) ──────────────────────────
# Horas derivadas del análisis de WR ajustado post-calibración (26 días, n≥5/hora).
# SHORT: bloques 09-12h y 23h tienen WR adj < 43% → mercado alcista sesión Europa.
# LONG: 20h y 22h presentan WR adj < 44% → posiblemente reversión final de sesión US.
# BUY_SPOT: 02h y 06h con < 31% → illiquidez nocturna asiática extrema.
# Micro-scalp LONG: 01h, 18h, 22h con WR < 31% y PnL negativo.
# Micro-scalp SHORT: 07h y 20h con WR < 30% (20h: 11% WR, -1.34% PnL histórico).
SHORT_FUTURES_BLACKOUT_HOURS     = _parse_hour_set("SHORT_FUTURES_BLACKOUT_HOURS",     "6,9,10,11,12,23")
LONG_FUTURES_BLACKOUT_HOURS      = _parse_hour_set("LONG_FUTURES_BLACKOUT_HOURS",      "20,22")
BUY_SPOT_BLACKOUT_HOURS          = _parse_hour_set("BUY_SPOT_BLACKOUT_HOURS",          "2,6")
MICRO_SCALP_BLACKOUT_HOURS_LONG  = _parse_hour_set("MICRO_SCALP_BLACKOUT_HOURS_LONG",  "1,18,22")
MICRO_SCALP_BLACKOUT_HOURS_SHORT = _parse_hour_set("MICRO_SCALP_BLACKOUT_HOURS_SHORT", "7,20")

# ── Feature flags ──────────────────────────────────────────────────────────
ENABLE_LIQUIDATIONS = os.getenv("ENABLE_LIQUIDATIONS", "true").lower() == "true"

# ── Base de datos ──────────────────────────────────────────────────────────
ENABLE_DATABASE = os.getenv("ENABLE_DATABASE", "true").lower() == "true"

# ── PostgreSQL (activar con USE_POSTGRESQL=true) ───────────────────────────
PG_HOST     = os.getenv("PG_HOST",     "localhost")
PG_PORT     = int(os.getenv("PG_PORT", "5434"))
PG_DB       = os.getenv("PG_DB",       "crypto_dashboard")
PG_USER     = os.getenv("PG_USER",     "crypto")
PG_PASSWORD = os.getenv("PG_PASSWORD", "crypto_local")

# ── SQLite (default) ───────────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/crypto_dashboard.sqlite3")
SNAPSHOT_RETENTION_DAYS = int(os.getenv("SNAPSHOT_RETENTION_DAYS", "7"))
# Score mínimo para guardar snapshot — filtra ruido y reduce volumen de escritura
SNAPSHOT_MIN_SCORE = int(os.getenv("SNAPSHOT_MIN_SCORE", "30"))

# ── Reporte periódico de win rate ─────────────────────────────────────────
WINRATE_REPORT_ENABLED = os.getenv("WINRATE_REPORT_ENABLED", "true").lower() == "true"
WINRATE_REPORT_INTERVAL_HOURS = float(os.getenv("WINRATE_REPORT_INTERVAL_HOURS", "6"))
WINRATE_REPORT_WINDOW_HOURS = float(os.getenv("WINRATE_REPORT_WINDOW_HOURS", "24"))

# ── Outcome tracker ────────────────────────────────────────────────────────
OUTCOME_TRACKER_ENABLED = os.getenv("OUTCOME_TRACKER_ENABLED", "true").lower() == "true"
_raw_horizons = os.getenv("OUTCOME_HORIZONS_MINUTES", "15,60,240,1440")
OUTCOME_HORIZONS_MINUTES: list = [int(x) for x in _raw_horizons.split(",") if x.strip()]

# News intelligence observacional
NEWS_INTELLIGENCE_ENABLED = os.getenv("NEWS_INTELLIGENCE_ENABLED", "false").lower() == "true"
NEWS_GDELT_ENABLED = os.getenv("NEWS_GDELT_ENABLED", "true").lower() == "true"
NEWS_GOOGLE_RSS_ENABLED = os.getenv("NEWS_GOOGLE_RSS_ENABLED", "true").lower() == "true"
CRYPTOPANIC_AUTH_TOKEN = os.getenv("CRYPTOPANIC_AUTH_TOKEN", "")
NEWS_RSS_FEEDS = [
    value.strip()
    for value in os.getenv(
        "NEWS_RSS_FEEDS",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    ).split(",")
    if value.strip()
]
NEWS_COLLECTION_INTERVAL_SECONDS = int(os.getenv("NEWS_COLLECTION_INTERVAL_SECONDS", "900"))
NEWS_REPORT_INTERVAL_SECONDS = int(os.getenv("NEWS_REPORT_INTERVAL_SECONDS", "3600"))
NEWS_LOOKBACK_HOURS = float(os.getenv("NEWS_LOOKBACK_HOURS", "6"))
NEWS_MAX_SYMBOLS = int(os.getenv("NEWS_MAX_SYMBOLS", "20"))
NEWS_WATCH_SYMBOLS = [
    value.strip().upper()
    for value in os.getenv("NEWS_WATCH_SYMBOLS", "").split(",")
    if value.strip()
]
NEWS_MIN_ABS_SCORE = float(os.getenv("NEWS_MIN_ABS_SCORE", "5"))
NEWS_OUTCOME_HORIZON_MINUTES = int(os.getenv("NEWS_OUTCOME_HORIZON_MINUTES", "60"))

# Alertas tempranas de seguridad de protocolo (solo atencion; nunca opera)
SECURITY_ALERTS_ENABLED = os.getenv("SECURITY_ALERTS_ENABLED", "true").lower() == "true"
SECURITY_ALERT_MIN_ABS_SCORE = float(os.getenv("SECURITY_ALERT_MIN_ABS_SCORE", "15"))
SECURITY_ALERT_LOOKBACK_HOURS = float(os.getenv("SECURITY_ALERT_LOOKBACK_HOURS", "168"))
SECURITY_COLLECTION_INTERVAL_SECONDS = int(os.getenv("SECURITY_COLLECTION_INTERVAL_SECONDS", "1800"))
SECURITY_GITHUB_REPOS = [
    tuple(part.strip() for part in value.split("|", 1))
    for value in os.getenv(
        "SECURITY_GITHUB_REPOS",
        "zcash/zcash|ZECUSDT,ZcashFoundation/zebra|ZECUSDT",
    ).split(",")
    if "|" in value
]

# ── Notificaciones — Discord ───────────────────────────────────────────────
ENABLE_DISCORD_ALERTS = os.getenv("ENABLE_DISCORD_ALERTS", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "900"))
ALERT_MIN_CONFIDENCE_DELTA_RESEND = int(os.getenv("ALERT_MIN_CONFIDENCE_DELTA_RESEND", "10"))

# ── Notificaciones — Telegram ─────────────────────────────────────────────
ENABLE_TELEGRAM_ALERTS = os.getenv("ENABLE_TELEGRAM_ALERTS", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Auto-trading ──────────────────────────────────────────────────────────
AUTO_TRADING_ENABLED       = os.getenv("AUTO_TRADING_ENABLED", "false").lower() == "true"
AUTO_TRADING_MODE          = os.getenv("AUTO_TRADING_MODE", "paper")          # paper | real
AUTO_TRADING_EXCHANGE      = os.getenv("AUTO_TRADING_EXCHANGE", "kucoin")     # kucoin (único soportado)
AUTO_TRADING_CAPITAL_USDT  = float(os.getenv("AUTO_TRADING_CAPITAL_USDT", "100"))
AUTO_TRADING_MAX_POSITIONS = int(os.getenv("AUTO_TRADING_MAX_POSITIONS", "5"))
AUTO_TRADING_MARKETS       = os.getenv("AUTO_TRADING_MARKETS", "futures")     # futures | spot | both
AUTO_TRADING_MIN_SCORE     = int(os.getenv("AUTO_TRADING_MIN_SCORE", "70"))
AUTO_TRADING_TIMEOUT_HOURS = float(os.getenv("AUTO_TRADING_TIMEOUT_HOURS", "4"))
AUTO_TRADING_RISK_CUT_ENABLED = os.getenv("AUTO_TRADING_RISK_CUT_ENABLED", "true").lower() == "true"
AUTO_TRADING_RISK_CUT_MIN_HOURS = float(os.getenv("AUTO_TRADING_RISK_CUT_MIN_HOURS", "1"))
AUTO_TRADING_RISK_CUT_LOSS_PCT = float(os.getenv("AUTO_TRADING_RISK_CUT_LOSS_PCT", "5"))
AUTO_TRADING_PAPER_MAX_LOSS_PCT = float(os.getenv("AUTO_TRADING_PAPER_MAX_LOSS_PCT", "12"))
# Fee taker simulado por lado sobre el notional (size * leverage). 0.0005 = 0.05%
# (taker de futuros KuCoin/Binance). Se descuenta en calc_pnl: entrada + cada salida.
AUTO_TRADING_FEE_RATE = float(os.getenv("AUTO_TRADING_FEE_RATE", "0.0005"))
AUTO_TRADING_USE_CALIBRATED_GRADE = os.getenv("AUTO_TRADING_USE_CALIBRATED_GRADE", "true").lower() == "true"
AUTO_TRADING_ALLOWED_CALIBRATED_GRADES: set = {
    x.strip().upper() for x in os.getenv("AUTO_TRADING_ALLOWED_CALIBRATED_GRADES", "A,B,C").split(",") if x.strip()
}
AUTO_TRADING_C_SHORT_MIN_SCORE = int(os.getenv("AUTO_TRADING_C_SHORT_MIN_SCORE", "75"))
AUTO_TRADING_C_LONG_MIN_SCORE = int(os.getenv("AUTO_TRADING_C_LONG_MIN_SCORE", "85"))
AUTO_TRADING_COUNTERTREND_MIN_SCORE = int(os.getenv("AUTO_TRADING_COUNTERTREND_MIN_SCORE", "90"))
# Score mínimo diferenciado por dirección (datos históricos: SHORT EV negativo, LONG positivo)
# LONG 75+ → WR_adj 55-60%; SHORT necesita convicción mayor para compensar mercado alcista
AUTO_TRADING_LONG_MIN_SCORE  = int(os.getenv("AUTO_TRADING_LONG_MIN_SCORE",  "75"))
AUTO_TRADING_SHORT_MIN_SCORE = int(os.getenv("AUTO_TRADING_SHORT_MIN_SCORE", "80"))
AUTO_TRADING_LOSS_COOLDOWN_COUNT = int(os.getenv("AUTO_TRADING_LOSS_COOLDOWN_COUNT", "2"))
AUTO_TRADING_LOSS_COOLDOWN_HOURS = float(os.getenv("AUTO_TRADING_LOSS_COOLDOWN_HOURS", "6"))
# Gate de sesión horaria UTC: bloquea entradas en horas de baja volatilidad
# Validado con 90 días × 25 símbolos: Asia (00-08h) tiene EV negativo con SL2%/TP3%
# (reconfirmado 2026-07-26 con PnL real de auto_positions: bloque 00-07 UTC
# -12.63 USDT neto — NO reabrir esa ventana con el proxy de WR a 60min, que
# sobrestima esas horas). Dentro de la ventana activa, PnL real por hora
# (2026-07-26) mostró 15h UTC y 21h UTC como las peores por lejos (-14.51 y
# -11.47 USDT pese a que el proxy de 60min marcaba 15h como la "mejor hora")
# — se excluyen explícitamente.
# Formato: "HH-HH" (inclusive inicio, exclusivo fin) combinables con coma, vacío = sin gate
AUTO_TRADING_SESSION_GATE_ENABLED = os.getenv("AUTO_TRADING_SESSION_GATE_ENABLED", "true").lower() == "true"
AUTO_TRADING_SESSION_ACTIVE_HOURS: set = {
    h for part in os.getenv("AUTO_TRADING_SESSION_ACTIVE_HOURS", "9-15,16-21").split(",")
    for h in (range(int(part.split("-")[0]), int(part.split("-")[1])) if "-" in part else [int(part)])
}
# Tiers de sizing: score >= umbral → % del capital
AUTO_TRADING_TIER1_SCORE   = int(os.getenv("AUTO_TRADING_TIER1_SCORE", "80"))   # 3%
AUTO_TRADING_TIER2_SCORE   = int(os.getenv("AUTO_TRADING_TIER2_SCORE", "75"))   # 2%
AUTO_TRADING_TIER3_SCORE   = int(os.getenv("AUTO_TRADING_TIER3_SCORE", "70"))   # 1%
# Intervalo del reporte de posiciones a Telegram (segundos)
POSITION_REPORT_INTERVAL_SECONDS = int(os.getenv("POSITION_REPORT_INTERVAL_SECONDS", "600"))

# ── Machine Learning (filtro de probabilidad de TP1) ─────────────────────
ML_ENABLED       = os.getenv("ML_ENABLED", "false").lower() == "true"
ML_THRESHOLD     = float(os.getenv("ML_THRESHOLD", "0.52"))       # prob mínima para no filtrar
ML_MODEL_PATH    = os.getenv("ML_MODEL_PATH", "data/ml_model.pkl")
ML_MIN_SAMPLES   = int(os.getenv("ML_MIN_SAMPLES", "50"))         # muestras mínimas para entrenar

# ── Setup evaluation (sistema de decisión disciplinado) ───────────────────
ENABLE_PRICE_ACTION_TRIGGER = os.getenv("ENABLE_PRICE_ACTION_TRIGGER", "true").lower() == "true"
ENABLE_SETUP_EVALUATION     = os.getenv("ENABLE_SETUP_EVALUATION",     "true").lower() == "true"
# IMPORTANTE: empieza en false — calcula y guarda sin bloquear alertas actuales
ENABLE_SETUP_GATE           = os.getenv("ENABLE_SETUP_GATE",           "false").lower() == "true"
SETUP_MIN_SCORE             = int(os.getenv("SETUP_MIN_SCORE", "70"))
SETUP_ALERT_GRADES: set = {
    x.strip().upper()
    for x in os.getenv("SETUP_ALERT_GRADES", "A,B").split(",")
    if x.strip()
}
CALIBRATED_SETUP_ENABLED = os.getenv("CALIBRATED_SETUP_ENABLED", "true").lower() == "true"
CALIBRATION_VERSION = os.getenv("CALIBRATION_VERSION", "rules-v1-observe")

# ── Trend continuation (segunda vía de alerta sin gatillo clásico) ────────
# Activa detección de tendencias fuertes sostenidas (JTO/STG/WLD style).
# Empieza en true para observar — sin bloqueo hasta que ENABLE_SETUP_GATE=true.
ENABLE_TREND_CONTINUATION           = os.getenv("ENABLE_TREND_CONTINUATION",           "true").lower() == "true"
TREND_CONTINUATION_MIN_SCORE        = int(os.getenv("TREND_CONTINUATION_MIN_SCORE",     "75"))
TREND_CONTINUATION_MIN_PERSISTENCE  = int(os.getenv("TREND_CONTINUATION_MIN_PERSISTENCE", "3"))
TREND_CONTINUATION_LOOKBACK         = int(os.getenv("TREND_CONTINUATION_LOOKBACK",      "10"))

# ── Micro-scalping agresivo (alertas separadas) ────────────────────────────
MICRO_SCALP_ENABLED = os.getenv("MICRO_SCALP_ENABLED", "true").lower() == "true"
MICRO_SCALP_MIN_SCORE = int(os.getenv("MICRO_SCALP_MIN_SCORE", "75"))
MICRO_LONG_MIN_SCORE = int(os.getenv("MICRO_LONG_MIN_SCORE", "80"))
MICRO_SCALP_STRONG_SCORE = int(os.getenv("MICRO_SCALP_STRONG_SCORE", "85"))
MICRO_SCALP_MIN_RVOL = float(os.getenv("MICRO_SCALP_MIN_RVOL", "2.0"))
MICRO_SCALP_MIN_RETURN_5M = float(os.getenv("MICRO_SCALP_MIN_RETURN_5M", "0.20"))
MICRO_SCALP_MIN_RETURN_3M = float(os.getenv("MICRO_SCALP_MIN_RETURN_3M", "0.10"))
MICRO_SCALP_MAX_SPREAD_PCT = float(os.getenv("MICRO_SCALP_MAX_SPREAD_PCT", "0.06"))
MICRO_SCALP_TIMEOUT_MINUTES = int(os.getenv("MICRO_SCALP_TIMEOUT_MINUTES", "10"))
MICRO_SCALP_FORCE_CLOSE_AFTER_MINUTES = int(os.getenv("MICRO_SCALP_FORCE_CLOSE_AFTER_MINUTES", "60"))
MICRO_SCALP_ALERT_COOLDOWN_SECONDS = int(os.getenv("MICRO_SCALP_ALERT_COOLDOWN_SECONDS", "180"))
MICRO_SCALP_CAPITAL_USDT    = float(os.getenv("MICRO_SCALP_CAPITAL_USDT",    "250"))
MICRO_SCALP_TRADE_SIZE_USDT = float(os.getenv("MICRO_SCALP_TRADE_SIZE_USDT", "25"))
# Metodo "nivel" (rebote en soporte/resistencia) vs "momentum" puro — nivel
# mostro mejor WR y MFE/MAE mucho mas controlado en el diagnostico 2026-07-25.
# Bono de score adicional (encima del +12 estructural ya existente) y tamano
# de posicion mayor para setups de nivel, sin tocar el capital total del modulo.
MICRO_SCALP_LEVEL_METHOD_BONUS    = int(os.getenv("MICRO_SCALP_LEVEL_METHOD_BONUS", "3"))
MICRO_SCALP_NIVEL_SIZE_MULTIPLIER = float(os.getenv("MICRO_SCALP_NIVEL_SIZE_MULTIPLIER", "1.2"))

# ── Multi-strategy framework (paper trading, modulos independientes) ──────
# Flag maestro unico. La config de cada estrategia individual (capital,
# tamaño, timeout) vive en el constructor de su propia clase Strategy
# (app/strategies/*.py), no aqui — asi agregar una estrategia no requiere
# editar este archivo.
MULTI_STRATEGY_ENABLED = os.getenv("MULTI_STRATEGY_ENABLED", "false").lower() == "true"

# ── Estructura de mercado: S/R, patrones chartistas y breakouts ────────────
# Niveles horizontales por clustering de pivots en velas 15m; alimenta el
# gatillo level_breakout (futuros) y el método de rebote en nivel (micro-scalp).
ENABLE_STRUCTURE_ANALYSIS     = os.getenv("ENABLE_STRUCTURE_ANALYSIS", "true").lower() == "true"
STRUCTURE_KLINES_INTERVAL     = os.getenv("STRUCTURE_KLINES_INTERVAL", "15m")
STRUCTURE_KLINES_LIMIT        = int(os.getenv("STRUCTURE_KLINES_LIMIT", "200"))       # ~50h de 15m
# Timeframe corto para micro-scalp: los mismos patrones/niveles se forman en 3m
STRUCTURE_MICRO_KLINES_INTERVAL = os.getenv("STRUCTURE_MICRO_KLINES_INTERVAL", "3m")
STRUCTURE_MICRO_KLINES_LIMIT    = int(os.getenv("STRUCTURE_MICRO_KLINES_LIMIT", "200"))  # ~10h de 3m
STRUCTURE_PIVOT_WINDOW        = int(os.getenv("STRUCTURE_PIVOT_WINDOW", "3"))
STRUCTURE_LEVEL_TOLERANCE_PCT = float(os.getenv("STRUCTURE_LEVEL_TOLERANCE_PCT", "0.35"))
STRUCTURE_MIN_TOUCHES         = int(os.getenv("STRUCTURE_MIN_TOUCHES", "2"))
STRUCTURE_MAX_LEVELS          = int(os.getenv("STRUCTURE_MAX_LEVELS", "8"))
STRUCTURE_BREAKOUT_MIN_RVOL   = float(os.getenv("STRUCTURE_BREAKOUT_MIN_RVOL", "1.5"))
STRUCTURE_BREAKOUT_LOOKBACK   = int(os.getenv("STRUCTURE_BREAKOUT_LOOKBACK", "3"))    # velas 15m
# Patrones chartistas (H-C-H, dobles techos/pisos)
PATTERN_SHOULDER_TOLERANCE_PCT   = float(os.getenv("PATTERN_SHOULDER_TOLERANCE_PCT", "1.5"))
PATTERN_DOUBLE_TOLERANCE_PCT     = float(os.getenv("PATTERN_DOUBLE_TOLERANCE_PCT", "0.6"))
PATTERN_MIN_HEAD_PROMINENCE_PCT  = float(os.getenv("PATTERN_MIN_HEAD_PROMINENCE_PCT", "1.0"))
# Rebote en la 2a pata de un doble techo/piso (W/M) antes de romper la neckline:
# entrada temprana alternativa a esperar la ruptura confirmada (pattern_break).
PATTERN_BOUNCE_MAX_AGE_CANDLES   = int(os.getenv("PATTERN_BOUNCE_MAX_AGE_CANDLES", "4"))
PATTERN_BOUNCE_MIN_PROGRESS_PCT  = float(os.getenv("PATTERN_BOUNCE_MIN_PROGRESS_PCT", "8.0"))
PATTERN_BOUNCE_MAX_PROGRESS_PCT  = float(os.getenv("PATTERN_BOUNCE_MAX_PROGRESS_PCT", "65.0"))
# Micro-scalp: proximidad a nivel para el método de rebote (en % del precio)
MICRO_SCALP_LEVEL_PROXIMITY_PCT  = float(os.getenv("MICRO_SCALP_LEVEL_PROXIMITY_PCT", "0.4"))
MICRO_SCALP_PATTERN_BOUNCE_BONUS = int(os.getenv("MICRO_SCALP_PATTERN_BOUNCE_BONUS", "8"))

# ── Regimen global BTC (filtro direccional de mercado) ────────────────────
BTC_REGIME_ENABLED = os.getenv("BTC_REGIME_ENABLED", "true").lower() == "true"
BTC_RISK_OFF_RETURN_1H = float(os.getenv("BTC_RISK_OFF_RETURN_1H", "-1.0"))
BTC_RISK_OFF_RETURN_15M = float(os.getenv("BTC_RISK_OFF_RETURN_15M", "-0.5"))
BTC_RISK_OFF_RETURN_5M = float(os.getenv("BTC_RISK_OFF_RETURN_5M", "-0.15"))
BTC_RISK_ON_RETURN_1H = float(os.getenv("BTC_RISK_ON_RETURN_1H", "1.0"))
BTC_RISK_ON_RETURN_15M = float(os.getenv("BTC_RISK_ON_RETURN_15M", "0.5"))
BTC_RISK_ON_RETURN_5M = float(os.getenv("BTC_RISK_ON_RETURN_5M", "0.15"))
BTC_REGIME_BLOCK_COUNTERTREND_BELOW_SCORE = int(os.getenv("BTC_REGIME_BLOCK_COUNTERTREND_BELOW_SCORE", "85"))
BTC_REGIME_COUNTERTREND_CONFIDENCE_PENALTY = int(os.getenv("BTC_REGIME_COUNTERTREND_CONFIDENCE_PENALTY", "10"))
BTC_REGIME_ALIGNED_CONFIDENCE_BOOST = int(os.getenv("BTC_REGIME_ALIGNED_CONFIDENCE_BOOST", "5"))

# ── Accumulation Watch (canal para tokens fuera del top-50 por volumen) ──
# Detecta tokens en fase de "coiling" (contracción de volatilidad + acumulación
# de volumen) que aún no califican para el scanner principal ($50M+), antes de
# su "ignición" (breakout tipo FOMO observado en HOME/ID/LAB/BEAT/RAVE, etc.)
ACCUMULATION_WATCH_ENABLED = os.getenv("ACCUMULATION_WATCH_ENABLED", "true").lower() == "true"
ACCUMULATION_MIN_QUOTE_VOLUME_USDT = float(os.getenv("ACCUMULATION_MIN_QUOTE_VOLUME_USDT", "2000000"))  # $2M
ACCUMULATION_COILING_SCORE_THRESHOLD = float(os.getenv("ACCUMULATION_COILING_SCORE_THRESHOLD", "45"))
ACCUMULATION_SCAN_INTERVAL_HOURS = float(os.getenv("ACCUMULATION_SCAN_INTERVAL_HOURS", "6"))
ACCUMULATION_WATCHLIST_MAX_SIZE = int(os.getenv("ACCUMULATION_WATCHLIST_MAX_SIZE", "20"))
ACCUMULATION_WATCH_EXPIRE_HOURS = float(os.getenv("ACCUMULATION_WATCH_EXPIRE_HOURS", "48"))
# Disparadores de "ignición" para símbolos en watchlist (volumen relativo del
# pipeline principal, o funding cruzando hacia/por debajo de cero)
ACCUMULATION_IGNITION_VOLUME_MULT = float(os.getenv("ACCUMULATION_IGNITION_VOLUME_MULT", "2.5"))
ACCUMULATION_FUNDING_DROP_THRESHOLD = float(os.getenv("ACCUMULATION_FUNDING_DROP_THRESHOLD", "0.0001"))
# Horarios UTC ancla (30 min antes de apertura Europa 07-08h y sesión US 14h,
# donde se concentró el 60% de las igniciones observadas) — corren ADEMÁS de
# la cadencia regular de ACCUMULATION_SCAN_INTERVAL_HOURS, no en su lugar.
ACCUMULATION_ANCHOR_TIMES_UTC: list = []
for _part in os.getenv("ACCUMULATION_ANCHOR_TIMES_UTC", "06:30,13:30").split(","):
    _part = _part.strip()
    if not _part:
        continue
    try:
        _h, _m = _part.split(":")
        ACCUMULATION_ANCHOR_TIMES_UTC.append((int(_h), int(_m)))
    except ValueError:
        continue

# ── Descubrimiento de candidatos fuera del volumen (3 canales adicionales) ──
# El scanner principal (top ~30 por preliminary_score, piso $50M) y
# Accumulation Watch (coiling, $2M-$50M) comparten el mismo sesgo: solo
# consideran simbolos ya identificados por volumen o por contraccion previa
# de volatilidad. Estos 3 canales reutilizan la misma tabla accumulation_watch
# (generalizada con channel/channel_score) para sumar simbolos que ninguno de
# los dos detectaria a tiempo.

# Canal 1 — volatility_breakout: reutiliza las MISMAS metricas ya calculadas
# por compute_coiling_metrics() (contraction_ratio = ATR reciente/ATR base)
# — un valor ALTO (expansion) en vez de bajo (contraccion) es un breakout de
# volatilidad ya en marcha. Cero llamadas nuevas a Binance.
ACCUMULATION_VOLATILITY_BREAKOUT_ENABLED = os.getenv("ACCUMULATION_VOLATILITY_BREAKOUT_ENABLED", "true").lower() == "true"
ACCUMULATION_VOLATILITY_BREAKOUT_RATIO = float(os.getenv("ACCUMULATION_VOLATILITY_BREAKOUT_RATIO", "2.5"))

# Canal 2 — funding_extreme: reutiliza el funding_map ya descargado en bloque
# (get_premium_index_all) para el mismo universo $2M-$50M. Cero llamadas nuevas.
ACCUMULATION_FUNDING_EXTREME_ENABLED = os.getenv("ACCUMULATION_FUNDING_EXTREME_ENABLED", "true").lower() == "true"
ACCUMULATION_FUNDING_EXTREME_THRESHOLD = float(os.getenv("ACCUMULATION_FUNDING_EXTREME_THRESHOLD", "0.003"))  # 0.3%

# Canal 3 — oi_acceleration: Binance no tiene un endpoint de OI para todos los
# simbolos a la vez (solo por simbolo, /futures/data/openInterestHist) — este
# canal SI agrega llamadas nuevas, una por simbolo del universo, con el mismo
# patron de pool de hilos que ya usa el scan de coiling.
ACCUMULATION_OI_ACCELERATION_ENABLED = os.getenv("ACCUMULATION_OI_ACCELERATION_ENABLED", "true").lower() == "true"
ACCUMULATION_OI_ACCELERATION_PCT = float(os.getenv("ACCUMULATION_OI_ACCELERATION_PCT", "15.0"))  # % cambio
ACCUMULATION_OI_ACCELERATION_LOOKBACK_HOURS = float(os.getenv("ACCUMULATION_OI_ACCELERATION_LOOKBACK_HOURS", "24"))
# Cadencia propia (separada de ACCUMULATION_SCAN_INTERVAL_HOURS) porque el
# barrido de OI por simbolo es el mas costoso de los 3 canales.
CANDIDATE_DISCOVERY_SCAN_INTERVAL_HOURS = float(os.getenv("CANDIDATE_DISCOVERY_SCAN_INTERVAL_HOURS", "6"))

# ── Notificaciones — Email ────────────────────────────────────────────────
ENABLE_EMAIL_ALERTS = os.getenv("ENABLE_EMAIL_ALERTS", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
