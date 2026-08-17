"""Reconstruccion de precio y un proxy de CVD para huecos de downtime real
del scanner en market_snapshots, usando klines historicas de Binance.

Se ejecuta UNA VEZ al iniciar el scanner (mismo momento que
position_monitor.recover_gap_positions) — cubre el tiempo en que el proceso
estuvo apagado. No corre durante el ciclo normal: no cubre huecos por un
simbolo rotando dentro/fuera de la lista de candidatos mientras el scanner
sigue corriendo (esos requieren que el simbolo vuelva a ser candidato para
que el scanner lo escanee de nuevo).

El CVD real se calcula en vivo del tape de trades del websocket
(app/websocket_client.py + app/indicators.py) y no es recuperable
retroactivamente trade a trade. Cada vela de Binance SI trae
taker_buy_base_asset_volume (indice 9 del array de kline) — con eso se
aproxima un delta por vela: delta_proxy = 2*taker_buy_volume - volume_total.
No es identico al delta en vivo (que opera sobre trades individuales), pero
es una reconstruccion legitima agregada del mismo tape de esa vela.
"""
import datetime as _dt
import logging
from collections import deque
from typing import Any, Dict, List

from app import database, market_data
from app.config import ENABLE_DATABASE

logger = logging.getLogger("snapshot_backfill")

_INTERVAL = "1m"
# Continuidad normal del scanner: ciclo de ~60-95s, asi que cualquier hueco
# mayor a esto ya indica downtime real (mismo orden de magnitud que el corte
# de 30min usado en el grafico de Value Area del dashboard).
_MIN_GAP_MINUTES = 20.0
# Limite de una sola llamada a Binance (klines de 1m, max 1500 por request) —
# tambien actua como corte de "demasiado viejo para reconstruir": un simbolo
# sin datos desde hace dias/semanas no vale la pena backfillearlo al arrancar.
_MAX_BACKFILL_HOURS = 20.0


def _delta_proxy(kline: List[Any]) -> float:
    """Aproxima el delta (compra-venta) de una vela con el campo
    taker_buy_base_asset_volume que Binance ya incluye en cada kline
    (indice 9): delta = compras del agresor - ventas del agresor."""
    volume = float(kline[5])
    taker_buy = float(kline[9])
    return 2.0 * taker_buy - volume


def _rolling_sum(values: List[float], window: int) -> List[float]:
    """Suma acumulada de los ultimos `window` elementos, por posicion —
    reconstruye cvd_15m/cvd(1h) igual que indicators.py lo hace en vivo con
    una ventana rodante, pero aplicado al historial de klines ya bajado."""
    out: List[float] = []
    acc = 0.0
    dq: deque = deque()
    for v in values:
        dq.append(v)
        acc += v
        if len(dq) > window:
            acc -= dq.popleft()
        out.append(acc)
    return out


def backfill_snapshot_gaps() -> None:
    """Ejecutar una vez al iniciar el scanner, antes del primer ciclo."""
    if not ENABLE_DATABASE:
        return

    try:
        last_seen = database.get_symbols_last_snapshot_time()
    except Exception:
        logger.exception("Error leyendo ultimo timestamp por simbolo")
        return
    if not last_seen:
        return

    now_utc = _dt.datetime.now(_dt.timezone.utc)
    filled_symbols = 0
    filled_rows = 0

    for symbol, last_ts_str in last_seen.items():
        try:
            last_dt = _dt.datetime.fromisoformat(last_ts_str).replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue

        gap_hours = (now_utc - last_dt).total_seconds() / 3600.0
        if gap_hours < (_MIN_GAP_MINUTES / 60.0):
            continue   # continuidad normal, nada que reconstruir
        if gap_hours > _MAX_BACKFILL_HOURS:
            continue   # demasiado viejo/abandonado — no vale la pena

        start_ms = int(last_dt.timestamp() * 1000) + 60_000   # vela siguiente al ultimo dato real
        end_ms = int(now_utc.timestamp() * 1000)

        try:
            klines = market_data.get_klines(
                symbol, interval=_INTERVAL, limit=1500,
                start_time_ms=start_ms, end_time_ms=end_ms,
            )
        except Exception:
            klines = []
        if not klines:
            continue

        deltas = [_delta_proxy(k) for k in klines]
        cvd_15m_series = _rolling_sum(deltas, 15)
        cvd_1h_series = _rolling_sum(deltas, 60)

        rows: List[Dict[str, Any]] = []
        for k, delta, cvd15, cvd1h in zip(klines, deltas, cvd_15m_series, cvd_1h_series):
            open_ms = int(k[0])
            close_price = float(k[4])
            ts_iso = _dt.datetime.fromtimestamp(
                open_ms / 1000.0, tz=_dt.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S")
            rows.append({
                "timestamp": ts_iso,
                "symbol": symbol,
                "price": close_price,
                "futures_price": close_price,
                "metrics": {"delta": delta, "cvd": cvd1h, "cvd_15m": cvd15},
            })

        try:
            n = database.insert_backfilled_snapshots(rows)
        except Exception:
            logger.exception("Error insertando backfill de %s", symbol)
            continue
        if n:
            filled_symbols += 1
            filled_rows += n

    if filled_rows:
        logger.info(
            "SNAPSHOT BACKFILL: %d simbolo(s), %d fila(s) reconstruidas "
            "(precio real + delta aproximado de taker_buy_volume)",
            filled_symbols, filled_rows,
        )
    else:
        logger.info("SNAPSHOT BACKFILL: sin huecos de downtime que reconstruir")
