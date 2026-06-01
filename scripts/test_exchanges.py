"""Prueba en vivo del agregador multi-exchange contra los candidatos del scanner.

Uso:
    python scripts/test_exchanges.py            # top 10 candidatos
    python scripts/test_exchanges.py --limit 20 # top 20
    python scripts/test_exchanges.py --symbol BTC ETH SOL  # simbolos especificos
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Forzar UTF-8 en consola Windows para caracteres especiales en nombres de tokens
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.market_scanner import get_candidate_symbols
from app.exchanges.aggregator import get_multi_exchange_snapshot
from app.exchanges.symbol_map import get_normalized, is_supported


def _bar(val, max_val=100, width=20, fill="#", empty="."):
    filled = int(round(val / max_val * width))
    return fill * filled + empty * (width - filled)


def run(limit: int = 10, symbols: list = None):
    if symbols:
        candidates = [{"symbol": s.upper() + ("USDT" if not s.upper().endswith("USDT") else "")}
                      for s in symbols]
    else:
        print(f"Obteniendo top {limit} candidatos del scanner...", flush=True)
        candidates = get_candidate_symbols(limit=limit)

    print()
    print("=" * 72)
    print(f"  REPORTE MULTI-EXCHANGE  ({len(candidates)} simbolos)")
    print("=" * 72)
    print(f"  {'SIMBOLO':<14} {'BINANCE':>10} {'COINBASE':>10} {'KRAKEN':>10}  {'CONF':>5}  {'DEV%':>6}")
    print("-" * 72)

    supported_count = 0
    total_latency = 0.0

    for cand in candidates:
        sym = cand["symbol"]
        norm = get_normalized(sym) or sym.replace("USDT", "")

        t0 = time.monotonic()
        snap = get_multi_exchange_snapshot(sym, norm)
        elapsed_ms = (time.monotonic() - t0) * 1000

        total_latency += elapsed_ms

        if not snap["ok"]:
            print(f"  {sym:<14} {'BINANCE FAIL':>32}")
            continue

        bin_price = snap["primary_price"]
        conf = snap["multi_exchange_confidence"]
        dev = snap["price_deviation_pct"]
        ext_sup = snap["external_supported"]

        if ext_sup:
            supported_count += 1

        exchanges = snap["exchanges"]

        def fmt_price(name):
            t = exchanges.get(name)
            if t is None:
                return "    N/A"
            if not t.ok:
                return "   FAIL"
            return f"{t.price:>10.4f}" if t.price < 1 else f"{t.price:>10.2f}"

        cb_str  = fmt_price("coinbase") if ext_sup else "    N/A"
        kr_str  = fmt_price("kraken")   if ext_sup else "    N/A"
        bin_str = f"{bin_price:>10.4f}" if bin_price < 1 else f"{bin_price:>10.2f}"

        if conf is not None:
            conf_str = f"{conf:>5.0f}"
            conf_bar = _bar(conf)
        else:
            conf_str = "  N/A"
            conf_bar = ""

        dev_str = f"{dev:>6.4f}" if dev is not None else "   N/A"

        # Marcadores de alerta
        flags = ""
        if snap["warnings"]:
            flags = " !"
        if conf is not None and conf < 60:
            flags = " !!"

        print(f"  {sym:<14} {bin_str} {cb_str} {kr_str}  {conf_str}  {dev_str}{flags}")

        # Mostrar advertencias si las hay
        for w in snap["warnings"]:
            print(f"  {'':14}   >> {w}")

    print("-" * 72)
    avg_latency = total_latency / len(candidates) if candidates else 0
    print(f"  Simbolos con soporte externo: {supported_count}/{len(candidates)}")
    print(f"  Latencia promedio por simbolo: {avg_latency:.0f}ms")
    print()
    print("Leyenda: CONF=multi_exchange_confidence (None=altcoin sin soporte, no penaliza)")
    print("         DEV%=desviacion de precio entre exchanges (>0.5% = divergencia)")
    print("         ! = advertencia  !! = confianza baja (<60)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test multi-exchange aggregator")
    parser.add_argument("--limit", type=int, default=10,
                        help="Numero de candidatos del scanner (default: 10)")
    parser.add_argument("--symbol", nargs="+",
                        help="Simbolos especificos (ej: BTC ETH SOL)")
    args = parser.parse_args()

    run(limit=args.limit, symbols=args.symbol)
