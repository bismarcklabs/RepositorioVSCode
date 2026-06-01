import logging
import threading
import time
import json
from collections import deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_liquidation_store: Dict[str, deque] = {}
_liq_ws_thread: Optional[threading.Thread] = None
_liq_lock = threading.Lock()

_ALL_LIQUIDATIONS_STREAM = "wss://fstream.binance.com/ws/!forceOrder@arr"


def _run_liquidation_ws() -> None:
    """Conecta al stream público de liquidaciones y reconecta con bucle, sin recursión."""
    import websocket

    def on_message(ws, message):
        try:
            payload = json.loads(message)
            data = payload.get("data", payload)
            order = data.get("o", data)

            symbol = str(order.get("s", "")).upper()
            if not symbol:
                return

            side = str(order.get("S", "")).upper()
            # side="SELL" → el exchange vende para cerrar un LONG liquidado
            # side="BUY"  → el exchange compra para cerrar un SHORT liquidado
            position_side = "LONG" if side == "SELL" else "SHORT"

            event: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "positionSide": position_side,
                "origQty": float(order.get("q", 0.0)),
                "executedQty": float(order.get("l", order.get("q", 0.0))),
                "price": float(order.get("p", 0.0)),
                "averagePrice": float(order.get("ap", order.get("p", 0.0))),
                "status": str(order.get("X", "")),
                "time": int(order.get("T", 0)),
            }

            with _liq_lock:
                if symbol not in _liquidation_store:
                    _liquidation_store[symbol] = deque(maxlen=100)
                _liquidation_store[symbol].appendleft(event)

        except Exception as exc:
            logger.debug("Error procesando liquidación: %s", exc)

    def on_error(ws, error):
        logger.warning("Error en WebSocket de liquidaciones: %s", error)

    def on_close(ws, code, msg):
        logger.info("WebSocket de liquidaciones cerrado (%s).", code)

    def on_open(ws):
        logger.info("WebSocket de liquidaciones conectado.")

    # Bucle de reconexión — sin recursión, sin riesgo de stack overflow
    while True:
        ws = websocket.WebSocketApp(
            _ALL_LIQUIDATIONS_STREAM,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        ws.run_forever(ping_interval=30, ping_timeout=10)
        logger.info("Reconectando WebSocket de liquidaciones en 5s...")
        time.sleep(5)


def start_liquidation_ws() -> None:
    """Inicia el WebSocket de liquidaciones en un hilo daemon de background."""
    global _liq_ws_thread
    if _liq_ws_thread is not None and _liq_ws_thread.is_alive():
        return
    _liq_ws_thread = threading.Thread(
        target=_run_liquidation_ws,
        daemon=True,
        name="BinanceLiquidationsWS",
    )
    _liq_ws_thread.start()
    logger.info("Hilo WebSocket de liquidaciones iniciado.")


def get_liquidations(symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retorna las últimas liquidaciones en memoria para un símbolo (sin HTTP)."""
    with _liq_lock:
        events = list(_liquidation_store.get(symbol.upper(), []))
    return events[:limit]
