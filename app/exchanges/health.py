"""Health check rápido para todos los providers.

Uso:
    python -m app.exchanges.health
    o: from app.exchanges.health import check_all_providers
"""
import logging
from typing import Dict, Any

from app.exchanges.binance_provider import BinanceProvider
from app.exchanges.coinbase_provider import CoinbaseProvider
from app.exchanges.kraken_provider import KrakenProvider

logger = logging.getLogger("exchanges.health")

_TEST_SYMBOLS = {
    "binance":  ("BTCUSDT", "BTC"),
    "coinbase": ("BTC-USD", "BTC"),
    "kraken":   ("XBT/USD", "BTC"),
}

_PROVIDERS = {
    "binance":  BinanceProvider(),
    "coinbase": CoinbaseProvider(),
    "kraken":   KrakenProvider(),
}


def check_all_providers() -> Dict[str, Any]:
    """Llama get_ticker en BTC para cada provider y reporta estado."""
    results = {}
    for name, provider in _PROVIDERS.items():
        sym, norm = _TEST_SYMBOLS[name]
        try:
            ticker = provider.get_ticker(sym, norm)
            results[name] = {
                "ok":       ticker.ok,
                "price":    ticker.price,
                "bid":      ticker.bid,
                "ask":      ticker.ask,
                "error":    ticker.error,
            }
        except Exception as exc:
            results[name] = {"ok": False, "price": None, "error": str(exc)}
    return results


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")

    status = check_all_providers()
    print("\n=== Exchange Health Check ===")
    all_ok = True
    for name, s in status.items():
        icon = "OK" if s["ok"] else "FAIL"
        price_str = f"${s['price']:,.2f}" if s.get("price") else "-"
        err_str = f"  error: {s['error']}" if not s["ok"] else ""
        print(f"  [{icon}] {name:<10} {price_str}{err_str}")
        if not s["ok"]:
            all_ok = False
    print()
    sys.exit(0 if all_ok else 1)
