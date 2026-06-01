"""Mapeo de símbolo normalizado → símbolo específico por exchange.

Normalizado: "BTC", "ETH", "SOL", etc.
Binance:     "BTCUSDT", "ETHUSDT", "SOLUSDT"  (futures endpoint)
Coinbase:    "BTC-USD", "ETH-USD", "SOL-USD"  (Exchange REST)
Kraken:      "XBT/USD", "ETH/USD", "SOL/USD"  (public REST)
"""
from typing import Dict, Optional

# Clave = símbolo normalizado (base asset en mayúsculas).
# Valor = dict con símbolo específico de cada exchange, o None si no listado.
SYMBOL_MAP: Dict[str, Dict[str, Optional[str]]] = {
    "BTC":  {"binance": "BTCUSDT",  "coinbase": "BTC-USD",  "kraken": "XBT/USD"},
    "ETH":  {"binance": "ETHUSDT",  "coinbase": "ETH-USD",  "kraken": "ETH/USD"},
    "SOL":  {"binance": "SOLUSDT",  "coinbase": "SOL-USD",  "kraken": "SOL/USD"},
    "XRP":  {"binance": "XRPUSDT",  "coinbase": "XRP-USD",  "kraken": "XRP/USD"},
    "ADA":  {"binance": "ADAUSDT",  "coinbase": "ADA-USD",  "kraken": "ADA/USD"},
    "DOGE": {"binance": "DOGEUSDT", "coinbase": "DOGE-USD", "kraken": "DOGE/USD"},
    "AVAX": {"binance": "AVAXUSDT", "coinbase": "AVAX-USD", "kraken": "AVAX/USD"},
    "LINK": {"binance": "LINKUSDT", "coinbase": "LINK-USD", "kraken": "LINK/USD"},
    "DOT":  {"binance": "DOTUSDT",  "coinbase": "DOT-USD",  "kraken": "DOT/USD"},
    "LTC":  {"binance": "LTCUSDT",  "coinbase": "LTC-USD",  "kraken": "LTC/USD"},
    "ATOM": {"binance": "ATOMUSDT", "coinbase": "ATOM-USD", "kraken": "ATOM/USD"},
    "UNI":  {"binance": "UNIUSDT",  "coinbase": "UNI-USD",  "kraken": "UNI/USD"},
    "NEAR": {"binance": "NEARUSDT", "coinbase": "NEAR-USD", "kraken": "NEAR/USD"},
    "MATIC":{"binance": "MATICUSDT","coinbase": "MATIC-USD","kraken": "MATIC/USD"},
    "FIL":  {"binance": "FILUSDT",  "coinbase": "FIL-USD",  "kraken": "FIL/USD"},
    "AAVE": {"binance": "AAVEUSDT", "coinbase": "AAVE-USD", "kraken": "AAVE/USD"},
    "CRV":  {"binance": "CRVUSDT",  "coinbase": "CRV-USD",  "kraken": "CRV/USD"},
    "MKR":  {"binance": "MKRUSDT",  "coinbase": "MKR-USD",  "kraken": "MKR/USD"},
    "COMP": {"binance": "COMPUSDT", "coinbase": "COMP-USD", "kraken": "COMP/USD"},
    "SNX":  {"binance": "SNXUSDT",  "coinbase": "SNX-USD",  "kraken": "SNX/USD"},
    "BCH":  {"binance": "BCHUSDT",  "coinbase": "BCH-USD",  "kraken": "BCH/USD"},
    "ETC":  {"binance": "ETCUSDT",  "coinbase": "ETC-USD",  "kraken": "ETC/USD"},
    "ICP":  {"binance": "ICPUSDT",  "coinbase": "ICP-USD",  "kraken": "ICP/USD"},
    "OP":   {"binance": "OPUSDT",   "coinbase": "OP-USD",   "kraken": None},
    "ARB":  {"binance": "ARBUSDT",  "coinbase": "ARB-USD",  "kraken": "ARB/USD"},
    "INJ":  {"binance": "INJUSDT",  "coinbase": "INJ-USD",  "kraken": None},
    "SUI":  {"binance": "SUIUSDT",  "coinbase": "SUI-USD",  "kraken": None},
    "APT":  {"binance": "APTUSDT",  "coinbase": "APT-USD",  "kraken": "APT/USD"},
    "TRX":  {"binance": "TRXUSDT",  "coinbase": None,        "kraken": "TRX/USD"},
}

# Índice inverso: Binance symbol → normalized.
_BINANCE_TO_BASE: Dict[str, str] = {
    v["binance"]: base
    for base, v in SYMBOL_MAP.items()
    if v.get("binance")
}


def get_exchange_symbol(normalized: str, exchange: str) -> Optional[str]:
    """Retorna símbolo específico del exchange, o None si no está listado."""
    return SYMBOL_MAP.get(normalized.upper(), {}).get(exchange)


def get_normalized(binance_symbol: str) -> Optional[str]:
    """Convierte símbolo Binance (BTCUSDT) → normalizado (BTC). None si no mapeado."""
    return _BINANCE_TO_BASE.get(binance_symbol.upper())


def is_supported(normalized: str) -> bool:
    """True si el símbolo tiene al menos un exchange externo listado."""
    entry = SYMBOL_MAP.get(normalized.upper(), {})
    return bool(entry.get("coinbase") or entry.get("kraken"))
