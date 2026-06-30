"""Caché persistente de klines históricas en SQLite.

Soporta tanto el endpoint de futuros perpetuos (/fapi/v1/klines) como el
endpoint spot (/api/v3/klines) de Binance, permitiendo cubrir el historial
completo desde el lanzamiento de cada activo.

Uso típico:
    from app.historical_cache import ensure_history, get_klines_df
    ensure_history("BTCUSDT", "1h", source="spot")   # descarga si falta
    df = get_klines_df("BTCUSDT", "1h")               # lee desde DB
"""
import logging
import time
from typing import List, Optional

import requests

from app import database

logger = logging.getLogger("historical_cache")

_FUTURES_BASE = "https://fapi.binance.com"
_SPOT_BASE    = "https://api.binance.com"

_MS_PER_INTERVAL = {
    "1m":  60_000,
    "3m":  180_000,
    "5m":  300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h":  3_600_000,
    "2h":  7_200_000,
    "4h":  14_400_000,
    "6h":  21_600_000,
    "8h":  28_800_000,
    "12h": 43_200_000,
    "1d":  86_400_000,
    "3d":  259_200_000,
    "1w":  604_800_000,
}


def _fetch_raw(symbol: str, interval: str, start_ms: int, end_ms: int,
               source: str = "futures") -> List:
    """Descarga hasta 1000 velas desde Binance."""
    base = _FUTURES_BASE if source == "futures" else _SPOT_BASE
    path = "/fapi/v1/klines" if source == "futures" else "/api/v3/klines"
    params = {
        "symbol":    symbol.upper(),
        "interval":  interval,
        "startTime": start_ms,
        "endTime":   end_ms,
        "limit":     1000,
    }
    try:
        resp = requests.get(f"{base}{path}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("[%s %s] error al descargar klines: %s", symbol, interval, exc)
        return []


def _upsert_batch(conn, rows: List) -> int:
    if not rows:
        return 0
    conn.executemany(
        """INSERT OR IGNORE INTO historical_klines
           (symbol, interval, open_time, open, high, low, close, volume)
           VALUES (?,?,?,?,?,?,?,?)""",
        rows,
    )
    conn.commit()
    return len(rows)


def _get_latest_open_time(conn, symbol: str, interval: str) -> Optional[int]:
    row = conn.execute(
        "SELECT MAX(open_time) FROM historical_klines WHERE symbol=? AND interval=?",
        (symbol, interval),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _get_earliest_open_time(conn, symbol: str, interval: str) -> Optional[int]:
    row = conn.execute(
        "SELECT MIN(open_time) FROM historical_klines WHERE symbol=? AND interval=?",
        (symbol, interval),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def ensure_history(
    symbol: str,
    interval: str = "1h",
    source: str = "futures",
    since_ms: Optional[int] = None,
) -> int:
    """Descarga y almacena klines faltantes para (symbol, interval).

    - Si la tabla está vacía para ese par, descarga desde `since_ms` (o el
      máximo histórico disponible en Binance).
    - Si ya hay datos, solo descarga las velas nuevas (incremental).

    Retorna el número de filas insertadas.
    """
    conn = database._get_conn()
    ms_per = _MS_PER_INTERVAL.get(interval, 3_600_000)
    now_ms = int(time.time() * 1000) - ms_per  # excluye vela en curso

    latest = _get_latest_open_time(conn, symbol, interval)
    earliest = _get_earliest_open_time(conn, symbol, interval)

    total_inserted = 0

    # ── Descarga hacia adelante (desde el último dato hasta ahora) ──────────
    if latest is None:
        # Primera vez: descarga desde since_ms o desde el inicio de Binance
        cursor = since_ms if since_ms else 1_420_070_400_000  # 2015-01-01
    else:
        cursor = latest + ms_per

    while cursor <= now_ms:
        end_window = min(cursor + 999 * ms_per, now_ms)
        batch = _fetch_raw(symbol, interval, cursor, end_window, source)
        if not batch:
            break
        rows = [
            (symbol, interval, int(k[0]),
             float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]))
            for k in batch
        ]
        total_inserted += _upsert_batch(conn, rows)
        last_ts = int(batch[-1][0])
        cursor = last_ts + ms_per
        if len(batch) < 1000:
            break
        time.sleep(0.05)

    if total_inserted:
        logger.info("[%s %s %s] +%d velas insertadas", symbol, interval, source, total_inserted)
    return total_inserted


def get_klines_df(symbol: str, interval: str, limit: Optional[int] = None):
    """Retorna un DataFrame con las klines históricas almacenadas.

    Columnas: open_time (datetime UTC), open, high, low, close, volume.
    """
    import pandas as pd

    conn = database._get_conn()
    sql = """
        SELECT open_time, open, high, low, close, volume
        FROM historical_klines
        WHERE symbol=? AND interval=?
        ORDER BY open_time
    """
    params = [symbol, interval]
    if limit:
        sql = sql.rstrip() + f" DESC LIMIT {int(limit)}"
        df = pd.read_sql_query(sql, conn, params=params)
        df = df.sort_values("open_time").reset_index(drop=True)
    else:
        df = pd.read_sql_query(sql, conn, params=params)

    if df.empty:
        return df
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


def count_klines(symbol: str, interval: str) -> int:
    conn = database._get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM historical_klines WHERE symbol=? AND interval=?",
        (symbol, interval),
    ).fetchone()
    return row[0] if row else 0
