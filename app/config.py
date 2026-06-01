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

# ── Binance base URLs ──────────────────────────────────────────────────────
BINANCE_FUTURES_BASE_URL = os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com")

# ── Scanner configuration ──────────────────────────────────────────────────
SCANNER_CANDIDATE_LIMIT = int(os.getenv("SCANNER_CANDIDATE_LIMIT", "50"))
SCANNER_RESULT_LIMIT = int(os.getenv("SCANNER_RESULT_LIMIT", "20"))
MIN_QUOTE_VOLUME_USDT = float(os.getenv("MIN_QUOTE_VOLUME_USDT", "50000000"))   # $50M
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.08"))                      # 0.08%

# ── Alert thresholds (por tipo de acción) ─────────────────────────────────
MIN_ALERT_SCORE_BUY_SPOT = int(os.getenv("MIN_ALERT_SCORE_BUY_SPOT", "75"))
MIN_ALERT_SCORE_SELL_SPOT = int(os.getenv("MIN_ALERT_SCORE_SELL_SPOT", "70"))
MIN_ALERT_SCORE_LONG_FUTURES = int(os.getenv("MIN_ALERT_SCORE_LONG_FUTURES", "80"))
MIN_ALERT_SCORE_SHORT_FUTURES = int(os.getenv("MIN_ALERT_SCORE_SHORT_FUTURES", "80"))
EXTREME_FUNDING_ABS = float(os.getenv("EXTREME_FUNDING_ABS", "0.001"))
NEAR_MISS_THRESHOLD = int(os.getenv("NEAR_MISS_THRESHOLD", "55"))

# ── Feature flags ──────────────────────────────────────────────────────────
ENABLE_LIQUIDATIONS = os.getenv("ENABLE_LIQUIDATIONS", "true").lower() == "true"

# ── Base de datos local (SQLite) ───────────────────────────────────────────
ENABLE_DATABASE = os.getenv("ENABLE_DATABASE", "true").lower() == "true"
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
AUTO_TRADING_CAPITAL_USDT  = float(os.getenv("AUTO_TRADING_CAPITAL_USDT", "1000"))
AUTO_TRADING_MAX_POSITIONS = int(os.getenv("AUTO_TRADING_MAX_POSITIONS", "3"))
AUTO_TRADING_MARKETS       = os.getenv("AUTO_TRADING_MARKETS", "futures")     # futures | spot | both
AUTO_TRADING_MIN_SCORE     = int(os.getenv("AUTO_TRADING_MIN_SCORE", "70"))
AUTO_TRADING_TIMEOUT_HOURS = float(os.getenv("AUTO_TRADING_TIMEOUT_HOURS", "4"))
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

# ── Notificaciones — Email ────────────────────────────────────────────────
ENABLE_EMAIL_ALERTS = os.getenv("ENABLE_EMAIL_ALERTS", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
