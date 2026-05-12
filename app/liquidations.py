import logging
from typing import Any, Dict, List

from app.config import ENABLE_FORCEORDERS

logger = logging.getLogger(__name__)


def get_liquidations(symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Return liquidation data or an empty list if not authorized."""
    if not ENABLE_FORCEORDERS:
        # Binance `fapi/v1/forceOrders` requires signed API access with a secret key.
        # Para habilitarlo, crea un archivo .env en la raíz con BINANCE_API_KEY y
        # BINANCE_API_SECRET y completa el código de firma.
        return []

    # Si más adelante se habilita el acceso con API key + secret, se puede usar
    # el endpoint firmado de Binance Futures. Ejemplo con python-binance:
    #
    # from binance.client import Client
    # from app.config import BINANCE_API_KEY, BINANCE_API_SECRET
    # client = Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)
    # return client.futures_force_orders(symbol=symbol.upper(), limit=limit)
    #
    # También se puede construir la firma manualmente usando el endpoint:
    # https://fapi.binance.com/fapi/v1/forceOrders
    # con el parámetro `timestamp` y la firma HMAC SHA256.

    return []
