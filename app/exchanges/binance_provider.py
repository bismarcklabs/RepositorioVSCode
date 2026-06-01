"""Provider Binance — envuelve app.market_data sin duplicar lógica."""
import logging
from typing import List

from app import market_data
from app.exchanges.base import (
    ExchangeKline,
    ExchangeOrderBook,
    ExchangeTicker,
    _failed_orderbook,
    _failed_ticker,
)

logger = logging.getLogger("exchanges.binance")


class BinanceProvider:
    name = "binance"

    def get_ticker(self, symbol: str, normalized_symbol: str) -> ExchangeTicker:
        try:
            price = market_data.get_futures_price(symbol)
            if not price:
                return _failed_ticker(self.name, symbol, normalized_symbol, "price=0")

            # Bid/ask del order book de futuros
            ob = market_data.get_futures_orderbook_raw(symbol, limit=5)
            bids_raw = ob.get("bids", [])
            asks_raw = ob.get("asks", [])
            bid = float(bids_raw[0][0]) if bids_raw else None
            ask = float(asks_raw[0][0]) if asks_raw else None
            spread_pct = (ask - bid) / bid * 100 if bid and ask else None

            # Volumen 24h: buscamos en el batch cacheado (sin llamada extra)
            ticker_all = {t["symbol"]: t for t in market_data.get_futures_ticker_all()}
            t24 = ticker_all.get(symbol, {})
            volume_24h = float(t24.get("quoteVolume", 0)) or None

            return ExchangeTicker(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                price=price,
                volume_24h=volume_24h,
                bid=bid,
                ask=ask,
                spread_pct=round(spread_pct, 4) if spread_pct is not None else None,
            )
        except Exception as exc:
            logger.debug("binance ticker error %s: %s", symbol, exc)
            return _failed_ticker(self.name, symbol, normalized_symbol, str(exc))

    def get_orderbook(self, symbol: str, normalized_symbol: str,
                      limit: int = 50) -> ExchangeOrderBook:
        try:
            raw = market_data.get_futures_orderbook_raw(symbol, limit=limit)
            bids = [(float(p), float(s)) for p, s in raw.get("bids", [])]
            asks = [(float(p), float(s)) for p, s in raw.get("asks", [])]
            return ExchangeOrderBook(
                exchange=self.name,
                symbol=symbol,
                normalized_symbol=normalized_symbol,
                bids=bids,
                asks=asks,
            )
        except Exception as exc:
            logger.debug("binance orderbook error %s: %s", symbol, exc)
            return _failed_orderbook(self.name, symbol, normalized_symbol, str(exc))

    def get_klines(self, symbol: str, interval: str = "1m",
                   limit: int = 100) -> List[ExchangeKline]:
        try:
            raw = market_data.get_klines(symbol, interval=interval, limit=limit)
            result = []
            for k in raw:
                result.append(ExchangeKline(
                    open_time_ms=int(k[0]),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                ))
            return result
        except Exception as exc:
            logger.debug("binance klines error %s: %s", symbol, exc)
            return []
