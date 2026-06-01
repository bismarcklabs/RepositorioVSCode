import asyncio
import json
import logging
import threading
from collections import deque
from typing import Any, Dict, List, Optional

import websockets

from app.market_scanner import get_top_symbols

trade_store: Dict[str, deque] = {}
_trade_lock = threading.Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_ws_thread: Optional[threading.Thread] = None
_ws_loop: Optional[asyncio.AbstractEventLoop] = None

# ── Símbolos del stream — protegidos con lock ─────────────────────────────
_stream_symbols: List[str] = []
_stream_symbols_lock = threading.Lock()
_symbols_changed = threading.Event()   # señal thread-safe (no asyncio.Event)


def set_stream_symbols(symbols: List[str]) -> None:
    """Actualiza los símbolos del WebSocket. Si cambian, marca reconexión."""
    global _stream_symbols
    upper = [s.upper() for s in symbols if s]
    with _stream_symbols_lock:
        if set(upper) == set(_stream_symbols):
            return
        _stream_symbols = upper
        logger.info("Símbolos WebSocket actualizados: %d símbolos", len(upper))
    _symbols_changed.set()


def _get_stream_symbols() -> List[str]:
    with _stream_symbols_lock:
        return list(_stream_symbols)


def build_stream_url(symbols: List[str]) -> str:
    streams = "/".join(f"{s.lower()}@aggTrade" for s in symbols)
    return f"wss://stream.binance.com:9443/stream?streams={streams}"


async def process_message(message: str) -> None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return

    data = payload.get("data", {})
    symbol = data.get("s")
    if not symbol:
        return

    trade: Dict[str, Any] = {
        "trade_id": int(data.get("a", 0)),
        "price":    float(data.get("p", 0.0)),
        "qty":      float(data.get("q", 0.0)),
        "maker":    bool(data.get("m", False)),
        "timestamp": int(data.get("T", 0)),
    }

    with _trade_lock:
        if symbol not in trade_store:
            trade_store[symbol] = deque(maxlen=1000)
        trade_store[symbol].append(trade)


def get_trades_snapshot(symbol: str) -> List[Dict[str, Any]]:
    """Retorna una copia segura (thread-safe) de los trades del símbolo."""
    with _trade_lock:
        dq = trade_store.get(symbol.upper())
        return list(dq) if dq is not None else []


async def stream_trades() -> None:
    while True:
        # Resolver símbolos: configurados o fallback top-20 spot
        symbols = _get_stream_symbols()
        if not symbols:
            try:
                symbols = get_top_symbols(limit=20)
                with _stream_symbols_lock:
                    _stream_symbols[:] = symbols
            except Exception as exc:
                logger.warning("Error obteniendo símbolos fallback: %s. Reintentando en 10s...", exc)
                await asyncio.sleep(10)
                continue

        if not symbols:
            await asyncio.sleep(10)
            continue

        _symbols_changed.clear()
        url = build_stream_url(symbols)
        logger.info("Conectando WebSocket de Binance: %d símbolos...", len(symbols))

        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                logger.info("WebSocket conectado.")
                while True:
                    # Recibir con timeout corto para poder verificar cambio de símbolos
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        await process_message(msg)
                    except asyncio.TimeoutError:
                        # Verificar si hay cambio de símbolos (threading.Event, no asyncio)
                        if _symbols_changed.is_set():
                            logger.info("Símbolos cambiados — reconectando WebSocket.")
                            break
                    except (websockets.exceptions.ConnectionClosedError,
                            websockets.exceptions.ConnectionClosedOK):
                        break

        except (websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK) as exc:
            logger.warning("WebSocket desconectado: %s. Reconectando en 5s...", exc)
            await asyncio.sleep(5)
        except Exception as exc:
            logger.exception("Error en WebSocket: %s. Reconectando en 5s...", exc)
            await asyncio.sleep(5)


def _run_ws_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_until_complete(stream_trades())


def start_ws_background() -> None:
    global _ws_thread, _ws_loop
    if _ws_thread is not None and _ws_thread.is_alive():
        return
    _ws_loop = asyncio.new_event_loop()
    _ws_thread = threading.Thread(
        target=_run_ws_loop, args=(_ws_loop,), daemon=True, name="BinanceWS"
    )
    _ws_thread.start()
    logger.info("Hilo WebSocket de Binance iniciado.")


def main() -> None:
    asyncio.run(stream_trades())


if __name__ == "__main__":
    main()
