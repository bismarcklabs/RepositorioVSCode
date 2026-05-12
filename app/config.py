import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DOTENV_PATH = ROOT_DIR / ".env"

if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH)

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
ENABLE_FORCEORDERS = bool(BINANCE_API_KEY and BINANCE_API_SECRET)

# Public Binance Futures endpoints
BINANCE_FUTURES_BASE_URL = os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com")


def is_forceorders_enabled() -> bool:
    return ENABLE_FORCEORDERS
