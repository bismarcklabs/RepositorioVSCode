"""KuCoin trading — órdenes reales en spot y futuros perpetuos.

Requiere API key de KuCoin con permisos:
  - Spot:    "Trade" (General)
  - Futures: "Trade" (KuCoin Futures)

Configuración en .env:
  KUCOIN_API_KEY=
  KUCOIN_API_SECRET=
  KUCOIN_PASSPHRASE=
  KUCOIN_SANDBOX=false   # true = usa endpoints sandbox para pruebas

Autenticación (KC-API-KEY-VERSION=3):
  - KC-API-TIMESTAMP:  epoch ms (str)
  - KC-API-SIGN:       HMAC-SHA256(secret, timestamp+method+path+body) → base64
  - KC-API-PASSPHRASE: HMAC-SHA256(secret, passphrase) → base64
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger("exchanges.kucoin_trader")


# ── Configuración (lazy-import para no romper si las keys no están) ────────

def _get_cfg():
    from app import config as cfg
    return cfg


_SPOT_LIVE    = "https://api.kucoin.com"
_SPOT_SANDBOX = "https://openapi-sandbox.kucoin.com"
_FUT_LIVE     = "https://api-futures.kucoin.com"
_FUT_SANDBOX  = "https://api-sandbox-futures.kucoin.com"


# ── Multiplicador de lote por símbolo en KuCoin Futures ─────────────────────
# Valor = USD por contrato.  size_contratos = floor(usdt_amount / lot_value)
# Fuente: KuCoin GET /api/v1/contracts/{symbol} → multiplier
_LOT_VALUE_USD: dict[str, float] = {
    "XBTUSDTM":   1.0,     # 1 contrato = 1 USD en BTC (0.001 BTC aprox)
    "ETHUSDTM":   1.0,
    "SOLUSDTM":   1.0,
    "XRPUSDTM":   1.0,
    "ADAUSDTM":   1.0,
    "DOGEUSDTM":  1.0,
    "AVAXUSDTM":  1.0,
    "LINKUSDTM":  1.0,
    "DOTUSDTM":   1.0,
    "LTCUSDTM":   1.0,
    "ATOMUSDTM":  1.0,
    "UNIUSDTM":   1.0,
    "NEARUSDTM":  1.0,
    "MATICUSDTM": 1.0,
    "FILUSDTM":   1.0,
    "AAVEUSDTM":  1.0,
    "CRVUSDTM":   1.0,
    "MKRUSDTM":   1.0,
    "COMPUSDTM":  1.0,
    "SNXUSDTM":   1.0,
    "BCHUSDTM":   1.0,
    "ETCUSDTM":   1.0,
    "ICPUSDTM":   1.0,
    "OPUSDTM":    1.0,
    "ARBUSDTM":   1.0,
    "INJUSDTM":   1.0,
    "SUIUSDTM":   1.0,
    "APTUSDTM":   1.0,
    "TRXUSDTM":   1.0,
}

# Spot: base normalizado → símbolo KuCoin Futures
_FUTURES_SYMBOL: dict[str, str] = {
    "BTC":   "XBTUSDTM",
    "ETH":   "ETHUSDTM",
    "SOL":   "SOLUSDTM",
    "XRP":   "XRPUSDTM",
    "ADA":   "ADAUSDTM",
    "DOGE":  "DOGEUSDTM",
    "AVAX":  "AVAXUSDTM",
    "LINK":  "LINKUSDTM",
    "DOT":   "DOTUSDTM",
    "LTC":   "LTCUSDTM",
    "ATOM":  "ATOMUSDTM",
    "UNI":   "UNIUSDTM",
    "NEAR":  "NEARUSDTM",
    "MATIC": "MATICUSDTM",
    "FIL":   "FILUSDTM",
    "AAVE":  "AAVEUSDTM",
    "CRV":   "CRVUSDTM",
    "MKR":   "MKRUSDTM",
    "COMP":  "COMPUSDTM",
    "SNX":   "SNXUSDTM",
    "BCH":   "BCHUSDTM",
    "ETC":   "ETCUSDTM",
    "ICP":   "ICPUSDTM",
    "OP":    "OPUSDTM",
    "ARB":   "ARBUSDTM",
    "INJ":   "INJUSDTM",
    "SUI":   "SUIUSDTM",
    "APT":   "APTUSDTM",
    "TRX":   "TRXUSDTM",
}


@dataclass
class KuCoinOrderResult:
    ok: bool
    order_id: Optional[str] = None
    error:    Optional[str] = None


# ── Auth helpers ───────────────────────────────────────────────────────────

def _sign(secret: str, timestamp: str, method: str, path: str, body: str = "") -> str:
    msg = f"{timestamp}{method}{path}{body}"
    raw = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(raw).decode()


def _sign_passphrase(secret: str, passphrase: str) -> str:
    raw = hmac.new(secret.encode(), passphrase.encode(), hashlib.sha256).digest()
    return base64.b64encode(raw).decode()


def _auth_headers(api_key: str, api_secret: str, passphrase: str,
                  method: str, path: str, body: str = "") -> dict:
    ts = str(int(time.time() * 1000))
    return {
        "KC-API-KEY":          api_key,
        "KC-API-SIGN":         _sign(api_secret, ts, method, path, body),
        "KC-API-TIMESTAMP":    ts,
        "KC-API-PASSPHRASE":   _sign_passphrase(api_secret, passphrase),
        "KC-API-KEY-VERSION":  "3",
        "Content-Type":        "application/json",
    }


# ── Spot orders ────────────────────────────────────────────────────────────

def place_spot_order(
    kc_symbol: str,       # ej. "BTC-USDT"
    side: str,            # "buy" | "sell"
    size_usdt: float,     # capital en USDT
    *,
    base_qty: Optional[float] = None,   # si se quiere vender por cantidad base
) -> KuCoinOrderResult:
    """
    Orden de mercado en spot.
    - side=buy  → usa `funds` (USDT a gastar)
    - side=sell → usa `size` (cantidad de base a vender; requiere base_qty)
    """
    cfg = _get_cfg()
    sandbox = getattr(cfg, "KUCOIN_SANDBOX", False)
    base_url = _SPOT_SANDBOX if sandbox else _SPOT_LIVE
    path = "/api/v1/orders"

    body_dict: dict = {
        "clientOid": str(uuid.uuid4()),
        "symbol":    kc_symbol,
        "side":      side,
        "type":      "market",
    }
    if side == "buy":
        body_dict["funds"] = str(round(size_usdt, 4))
    else:
        if base_qty is None:
            return KuCoinOrderResult(ok=False, error="sell requires base_qty")
        body_dict["size"] = str(round(base_qty, 8))

    body_str = json.dumps(body_dict)
    headers = _auth_headers(
        cfg.KUCOIN_API_KEY, cfg.KUCOIN_API_SECRET, cfg.KUCOIN_PASSPHRASE,
        "POST", path, body_str,
    )
    try:
        resp = requests.post(f"{base_url}{path}", headers=headers,
                             data=body_str, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "200000":
            msg = data.get("msg", "unknown error")
            logger.error("kucoin spot order failed %s: %s", kc_symbol, msg)
            return KuCoinOrderResult(ok=False, error=msg)
        order_id = data["data"]["orderId"]
        logger.info("kucoin spot %s %s $%.2f → order_id=%s", side, kc_symbol, size_usdt, order_id)
        return KuCoinOrderResult(ok=True, order_id=order_id)
    except Exception as exc:
        logger.error("kucoin spot order exception %s: %s", kc_symbol, exc)
        return KuCoinOrderResult(ok=False, error=str(exc))


def close_spot_position(
    kc_symbol: str,
    base_qty: float,
    original_side: str,  # lado original del trade: "buy" → cerrar con "sell"
) -> KuCoinOrderResult:
    """Cierra posición spot vendiendo la cantidad base."""
    close_side = "sell" if original_side == "buy" else "buy"
    return place_spot_order(kc_symbol, close_side, 0, base_qty=base_qty)


# ── Futures orders ─────────────────────────────────────────────────────────

def _get_futures_symbol(normalized: str) -> Optional[str]:
    """Convierte base normalizado → símbolo KuCoin Futures. None si no mapeado."""
    return _FUTURES_SYMBOL.get(normalized.upper())


def place_futures_order(
    normalized_symbol: str,   # ej. "BTC", "ETH"
    side: str,                # "buy" | "sell"
    size_usdt: float,
    price: float,             # precio actual (para calcular contratos)
    leverage: int = 1,
    *,
    close_order: bool = False,
    lot_override: Optional[float] = None,
) -> KuCoinOrderResult:
    """
    Orden de mercado en KuCoin Futures (USDT-M perpetuo).
    - side=buy  → long (o cierre de short)
    - side=sell → short (o cierre de long)
    - close_order=True → reduce-only (cierre de posición)
    """
    cfg = _get_cfg()
    sandbox = getattr(cfg, "KUCOIN_SANDBOX", False)
    base_url = _FUT_SANDBOX if sandbox else _FUT_LIVE

    fut_symbol = _get_futures_symbol(normalized_symbol)
    if not fut_symbol:
        return KuCoinOrderResult(
            ok=False, error=f"simbolo futures no mapeado: {normalized_symbol}")

    path = "/api/v1/orders"
    lot_val = lot_override or _LOT_VALUE_USD.get(fut_symbol, 1.0)
    # Número de contratos: capital × leverage / valor_por_contrato
    n_contracts = max(1, int(size_usdt * leverage / lot_val))

    body_dict: dict = {
        "clientOid":   str(uuid.uuid4()),
        "symbol":      fut_symbol,
        "side":        side,
        "type":        "market",
        "size":        n_contracts,
        "leverage":    str(leverage),
    }
    if close_order:
        body_dict["closeOrder"] = True

    body_str = json.dumps(body_dict)
    headers = _auth_headers(
        cfg.KUCOIN_API_KEY, cfg.KUCOIN_API_SECRET, cfg.KUCOIN_PASSPHRASE,
        "POST", path, body_str,
    )
    try:
        resp = requests.post(f"{base_url}{path}", headers=headers,
                             data=body_str, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "200000":
            msg = data.get("msg", "unknown error")
            logger.error("kucoin futures order failed %s: %s", fut_symbol, msg)
            return KuCoinOrderResult(ok=False, error=msg)
        order_id = data["data"]["orderId"]
        logger.info(
            "kucoin futures %s %s ×%d (%s) lev=%dx → order_id=%s",
            side, fut_symbol, n_contracts, ("close" if close_order else "open"),
            leverage, order_id,
        )
        return KuCoinOrderResult(ok=True, order_id=order_id)
    except Exception as exc:
        logger.error("kucoin futures order exception %s: %s", fut_symbol, exc)
        return KuCoinOrderResult(ok=False, error=str(exc))


def close_futures_position(
    normalized_symbol: str,
    original_action: str,    # "LONG_FUTURES" → close side = "sell"
    size_usdt: float,
    price: float,
    leverage: int = 1,
) -> KuCoinOrderResult:
    """Cierra posición futures con orden de mercado reduce-only."""
    close_side = "sell" if original_action == "LONG_FUTURES" else "buy"
    return place_futures_order(
        normalized_symbol, close_side, size_usdt, price,
        leverage=leverage, close_order=True,
    )


# ── Dispatcher público (selecciona spot vs futures según action) ────────────

def open_order(
    action: str,              # "LONG_FUTURES" | "SHORT_FUTURES" | "BUY_SPOT" | "SELL_SPOT"
    binance_symbol: str,      # ej. "BTCUSDT"
    normalized_symbol: str,   # ej. "BTC"
    kc_spot_symbol: str,      # ej. "BTC-USDT"
    size_usdt: float,
    price: float,
    leverage: int = 1,
) -> KuCoinOrderResult:
    """Despacha la orden de apertura al mercado correcto."""
    if action in ("LONG_FUTURES", "SHORT_FUTURES"):
        side = "buy" if action == "LONG_FUTURES" else "sell"
        return place_futures_order(normalized_symbol, side, size_usdt, price, leverage)

    if action in ("BUY_SPOT", "SELL_SPOT"):
        side = "buy" if action == "BUY_SPOT" else "sell"
        return place_spot_order(kc_spot_symbol, side, size_usdt)

    return KuCoinOrderResult(ok=False, error=f"action desconocida: {action}")


def close_order(
    action: str,
    normalized_symbol: str,
    kc_spot_symbol: str,
    size_usdt: float,
    price: float,
    leverage: int = 1,
    base_qty: Optional[float] = None,
) -> KuCoinOrderResult:
    """Cierra la posición en KuCoin según el tipo de mercado."""
    if action in ("LONG_FUTURES", "SHORT_FUTURES"):
        return close_futures_position(
            normalized_symbol, action, size_usdt, price, leverage)

    if action in ("BUY_SPOT", "SELL_SPOT"):
        original_side = "buy" if action == "BUY_SPOT" else "sell"
        if base_qty is None:
            base_qty = size_usdt / price if price > 0 else 0.0
        return close_spot_position(kc_spot_symbol, base_qty, original_side)

    return KuCoinOrderResult(ok=False, error=f"action desconocida: {action}")


# ── Verificación de credenciales ──────────────────────────────────────────

def verify_credentials() -> tuple[bool, str]:
    """Verifica que las credenciales de KuCoin sean válidas haciendo GET /api/v1/accounts."""
    cfg = _get_cfg()
    if not cfg.KUCOIN_API_KEY or not cfg.KUCOIN_API_SECRET or not cfg.KUCOIN_PASSPHRASE:
        return False, "KUCOIN_API_KEY / SECRET / PASSPHRASE no configuradas"

    sandbox  = getattr(cfg, "KUCOIN_SANDBOX", False)
    base_url = _SPOT_SANDBOX if sandbox else _SPOT_LIVE
    path     = "/api/v1/accounts"
    headers  = _auth_headers(
        cfg.KUCOIN_API_KEY, cfg.KUCOIN_API_SECRET, cfg.KUCOIN_PASSPHRASE,
        "GET", path,
    )
    try:
        resp = requests.get(f"{base_url}{path}", headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "200000":
            return True, "credenciales válidas"
        return False, data.get("msg", "error desconocido")
    except Exception as exc:
        return False, str(exc)
