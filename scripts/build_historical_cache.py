"""Construye la caché histórica de klines para todos los símbolos relevantes.

Ejecutar una vez (tarda ~5-10 min la primera vez):
    python scripts/build_historical_cache.py

Ejecuciones posteriores solo descargan las velas nuevas (incremental, ~segundos).

Cobertura:
  - BTC, ETH: desde el inicio de Binance spot (2017-08) + futuros (2019-09)
  - SOL, XRP, BNB, ADA, DOGE, AVAX, LINK, DOT, LTC, NEAR, UNI, AAVE, OP,
    ARB, SUI, APT, SEI, STX, TIA, INJ: desde su lanzamiento en futuros
  - Intervalos: 1h (evaluación de trades), 4h (contexto tendencia), 1d (macro)
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import database
from app.historical_cache import ensure_history, count_klines

database.init_db()

# ── Fechas de inicio en ms ────────────────────────────────────────────────────
def _ms(year, month, day):
    import calendar
    return int(calendar.timegm((year, month, day, 0, 0, 0, 0, 0, 0))) * 1000

# Futuros perpetuos USDT — fecha de lanzamiento aproximada en Binance Futures
FUTURES_SYMBOLS = {
    "BTCUSDT":   _ms(2019, 9, 25),
    "ETHUSDT":   _ms(2019, 11, 27),
    "XRPUSDT":   _ms(2020, 1,  6),
    "BNBUSDT":   _ms(2020, 6,  25),
    "ADAUSDT":   _ms(2020, 7,  10),
    "SOLUSDT":   _ms(2020, 9,  10),
    "DOGEUSDT":  _ms(2021, 5,  6),
    "DOTUSDT":   _ms(2020, 8,  20),
    "LTCUSDT":   _ms(2020, 1,  9),
    "LINKUSDT":  _ms(2019, 12, 11),
    "AVAXUSDT":  _ms(2020, 9,  23),
    "NEARUSDT":  _ms(2020, 11, 12),
    "UNIUSDT":   _ms(2020, 9,  18),
    "AAVEUSDT":  _ms(2020, 11, 9),
    "INJUSDT":   _ms(2021, 9,  15),
    "OPUSDT":    _ms(2022, 6,  1),
    "ARBUSDT":   _ms(2023, 3,  31),
    "SUIUSDT":   _ms(2023, 5,  4),
    "APTUSDT":   _ms(2022, 10, 19),
    "SEIUSDT":   _ms(2023, 8,  16),
    "STXUSDT":   _ms(2021, 3,  2),
    "TIAUSDT":   _ms(2023, 10, 27),
    "ATOMUSDT":  _ms(2020, 1,  31),
    "TRXUSDT":   _ms(2019, 11, 27),
    "MATICUSDT": _ms(2020, 10, 22),
}

# Spot — para BTC y ETH se completa el historial desde 2017 (antes de perps)
SPOT_SYMBOLS = {
    "BTCUSDT": _ms(2017, 8, 17),
    "ETHUSDT": _ms(2017, 8, 17),
    "SOLUSDT": _ms(2020, 8, 11),
    "XRPUSDT": _ms(2018, 1, 28),
    "BNBUSDT":  _ms(2017, 11, 6),
    "ADAUSDT":  _ms(2018, 4, 17),
    "DOGEUSDT": _ms(2019, 7, 5),
    "LTCUSDT":  _ms(2017, 12, 13),
    "LINKUSDT": _ms(2019, 1, 16),
    "DOTUSDT":  _ms(2020, 8, 18),
    "AVAXUSDT": _ms(2020, 9, 23),
}

INTERVALS = ["1h", "4h", "1d"]

print("=" * 60)
print("  BUILD HISTORICAL KLINES CACHE")
print("=" * 60)

t0 = time.time()
total_rows = 0

print(f"\n[FUTUROS] {len(FUTURES_SYMBOLS)} símbolos × {len(INTERVALS)} intervalos\n")
for symbol, since in FUTURES_SYMBOLS.items():
    for interval in INTERVALS:
        before = count_klines(symbol, interval)
        n = ensure_history(symbol, interval, source="futures", since_ms=since)
        after = count_klines(symbol, interval)
        total_rows += n
        status = f"+{n} nuevas" if n else "ya al día"
        print(f"  {symbol:12s} {interval:4s}  {after:6,} filas total  [{status}]")
    time.sleep(0.1)

print(f"\n[SPOT] {len(SPOT_SYMBOLS)} símbolos × {len(INTERVALS)} intervalos\n")
for symbol, since in SPOT_SYMBOLS.items():
    for interval in INTERVALS:
        # Spot usa "BTCUSDT_spot" como clave para no mezclar con futuros
        sym_key = f"{symbol}_spot"
        before = count_klines(sym_key, interval)
        n = ensure_history(sym_key, interval, source="spot", since_ms=since)
        after = count_klines(sym_key, interval)
        total_rows += n
        status = f"+{n} nuevas" if n else "ya al día"
        print(f"  {sym_key:16s} {interval:4s}  {after:6,} filas total  [{status}]")
    time.sleep(0.1)

elapsed = time.time() - t0
print(f"\n{'='*60}")
print(f"  Total filas insertadas: {total_rows:,}")
print(f"  Tiempo: {elapsed:.1f}s")
print(f"{'='*60}")
