"""Mapeo de símbolo normalizado → símbolo específico por exchange.

Normalizado: "BTC", "ETH", "SOL", etc.
Binance:     "BTCUSDT", "ETHUSDT", "SOLUSDT"  (futures endpoint)
Coinbase:    "BTC-USD", "ETH-USD", "SOL-USD"  (Exchange REST)
Kraken:      "XBT/USD", "ETH/USD", "SOL/USD"  (public REST)
KuCoin:      "BTC-USDT", "ETH-USDT", "SOL-USDT"  (spot REST, sin auth)
"""
from typing import Dict, Optional

# Clave = símbolo normalizado (base asset en mayúsculas).
# Valor = dict con símbolo específico de cada exchange, o None si no listado.
SYMBOL_MAP: Dict[str, Dict[str, Optional[str]]] = {
    "BTC":  {"binance": "BTCUSDT",  "coinbase": "BTC-USD",  "kraken": "XBT/USD",  "kucoin": "BTC-USDT"},
    "ETH":  {"binance": "ETHUSDT",  "coinbase": "ETH-USD",  "kraken": "ETH/USD",  "kucoin": "ETH-USDT"},
    "SOL":  {"binance": "SOLUSDT",  "coinbase": "SOL-USD",  "kraken": "SOL/USD",  "kucoin": "SOL-USDT"},
    "XRP":  {"binance": "XRPUSDT",  "coinbase": "XRP-USD",  "kraken": "XRP/USD",  "kucoin": "XRP-USDT"},
    "ADA":  {"binance": "ADAUSDT",  "coinbase": "ADA-USD",  "kraken": "ADA/USD",  "kucoin": "ADA-USDT"},
    "DOGE": {"binance": "DOGEUSDT", "coinbase": "DOGE-USD", "kraken": "DOGE/USD", "kucoin": "DOGE-USDT"},
    "AVAX": {"binance": "AVAXUSDT", "coinbase": "AVAX-USD", "kraken": "AVAX/USD", "kucoin": "AVAX-USDT"},
    "LINK": {"binance": "LINKUSDT", "coinbase": "LINK-USD", "kraken": "LINK/USD", "kucoin": "LINK-USDT"},
    "DOT":  {"binance": "DOTUSDT",  "coinbase": "DOT-USD",  "kraken": "DOT/USD",  "kucoin": "DOT-USDT"},
    "LTC":  {"binance": "LTCUSDT",  "coinbase": "LTC-USD",  "kraken": "LTC/USD",  "kucoin": "LTC-USDT"},
    "ATOM": {"binance": "ATOMUSDT", "coinbase": "ATOM-USD", "kraken": "ATOM/USD", "kucoin": "ATOM-USDT"},
    "UNI":  {"binance": "UNIUSDT",  "coinbase": "UNI-USD",  "kraken": "UNI/USD",  "kucoin": "UNI-USDT"},
    "NEAR": {"binance": "NEARUSDT", "coinbase": "NEAR-USD", "kraken": "NEAR/USD", "kucoin": "NEAR-USDT"},
    "MATIC":{"binance": "MATICUSDT","coinbase": "MATIC-USD","kraken": "MATIC/USD","kucoin": "MATIC-USDT"},
    "FIL":  {"binance": "FILUSDT",  "coinbase": "FIL-USD",  "kraken": "FIL/USD",  "kucoin": "FIL-USDT"},
    "AAVE": {"binance": "AAVEUSDT", "coinbase": "AAVE-USD", "kraken": "AAVE/USD", "kucoin": "AAVE-USDT"},
    "CRV":  {"binance": "CRVUSDT",  "coinbase": "CRV-USD",  "kraken": "CRV/USD",  "kucoin": "CRV-USDT"},
    "MKR":  {"binance": "MKRUSDT",  "coinbase": "MKR-USD",  "kraken": "MKR/USD",  "kucoin": "MKR-USDT"},
    "COMP": {"binance": "COMPUSDT", "coinbase": "COMP-USD", "kraken": "COMP/USD", "kucoin": "COMP-USDT"},
    "SNX":  {"binance": "SNXUSDT",  "coinbase": "SNX-USD",  "kraken": "SNX/USD",  "kucoin": "SNX-USDT"},
    "BCH":  {"binance": "BCHUSDT",  "coinbase": "BCH-USD",  "kraken": "BCH/USD",  "kucoin": "BCH-USDT"},
    "ETC":  {"binance": "ETCUSDT",  "coinbase": "ETC-USD",  "kraken": "ETC/USD",  "kucoin": "ETC-USDT"},
    "ICP":  {"binance": "ICPUSDT",  "coinbase": "ICP-USD",  "kraken": "ICP/USD",  "kucoin": "ICP-USDT"},
    "OP":   {"binance": "OPUSDT",   "coinbase": "OP-USD",   "kraken": None,        "kucoin": "OP-USDT"},
    "ARB":  {"binance": "ARBUSDT",  "coinbase": "ARB-USD",  "kraken": "ARB/USD",  "kucoin": "ARB-USDT"},
    "INJ":  {"binance": "INJUSDT",  "coinbase": "INJ-USD",  "kraken": None,        "kucoin": "INJ-USDT"},
    "SUI":  {"binance": "SUIUSDT",  "coinbase": "SUI-USD",  "kraken": None,        "kucoin": "SUI-USDT"},
    "APT":  {"binance": "APTUSDT",  "coinbase": "APT-USD",  "kraken": "APT/USD",  "kucoin": "APT-USDT"},
    "TRX":  {"binance": "TRXUSDT",  "coinbase": None,        "kraken": "TRX/USD",  "kucoin": "TRX-USDT"},
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
    return bool(entry.get("coinbase") or entry.get("kraken") or entry.get("kucoin"))


def get_kucoin_spot_symbol(normalized: str) -> Optional[str]:
    """Retorna símbolo spot de KuCoin (BTC-USDT) o None si no mapeado."""
    return SYMBOL_MAP.get(normalized.upper(), {}).get("kucoin")
