import asyncio
import json
import logging
from collections import deque
from typing import Any, Dict, List

import websockets

from app.market_scanner import get_top_symbols

trade_store: Dict[str, deque] = {}
logging.basicConfig(level=logging.INFO)


def build_stream_url(symbols: List[str]) -> str:
    """Build a Binance combined stream URL using aggTrade streams."""
    streams = "/".join([f"{symbol.lower()}@aggTrade" for symbol in symbols])
    return f"wss://stream.binance.com:9443/stream?streams={streams}"


async def process_message(message: str) -> None:
    """Parse an aggTrade event message and store the latest trade data."""
    payload = json.loads(message)
    data = payload.get("data", {})
    symbol = data.get("s")
    if symbol is None:
        return

    trade = {
        "price": float(data.get("p", 0.0)),
        "qty": float(data.get("q", 0.0)),
        "maker": bool(data.get("m", False)),
        "timestamp": int(data.get("T", 0)),
    }

    if symbol not in trade_store:
        trade_store[symbol] = deque(maxlen=1000)

    trade_store[symbol].append(trade)


async def stream_trades() -> None:
    """Continuously connect to Binance combined aggTrade streams and store trades."""
    while True:
        symbols = get_top_symbols(limit=20)
        url = build_stream_url(symbols)

        logging.info("Connecting to Binance WebSocket for symbols: %s", symbols)

        try:
            async with websockets.connect(url) as websocket:
                while True:
                    message = await websocket.recv()
                    await process_message(message)

        except (websockets.exceptions.ConnectionClosedError, websockets.exceptions.ConnectionClosedOK) as exc:
            logging.warning("WebSocket disconnected: %s. Reconnecting in 5 seconds...", exc)
            await asyncio.sleep(5)
        except Exception as exc:
            logging.exception("WebSocket error: %s. Reconnecting in 5 seconds...", exc)
            await asyncio.sleep(5)


def main() -> None:
    """Start the realtime aggTrade stream client."""
    asyncio.run(stream_trades())


if __name__ == "__main__":
    main()
