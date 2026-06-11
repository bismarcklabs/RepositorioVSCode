"""Regimen global de mercado liderado por BTC.

La idea es usar BTC como filtro de contexto: si BTC cae fuerte, penalizar longs
debiles; si BTC sube fuerte, penalizar shorts/ventas debiles.
"""
from typing import Any, Dict

from app.config import (
    BTC_REGIME_ENABLED,
    BTC_RISK_OFF_RETURN_1H,
    BTC_RISK_OFF_RETURN_15M,
    BTC_RISK_OFF_RETURN_5M,
    BTC_RISK_ON_RETURN_1H,
    BTC_RISK_ON_RETURN_15M,
    BTC_RISK_ON_RETURN_5M,
)


def detect_btc_market_regime(btc_technical: Dict[str, Any]) -> Dict[str, Any]:
    """Retorna el regimen global basado en BTC 1h/15m/5m."""
    r1h = float(btc_technical.get("return_1h", 0.0) or 0.0)
    r15m = float(btc_technical.get("return_15m", 0.0) or 0.0)
    r5m = float(btc_technical.get("return_5m", 0.0) or 0.0)
    trend = btc_technical.get("trend_bias", "neutral")
    htf_trend = btc_technical.get("htf_trend_bias", "neutral")

    base = {
        "enabled": BTC_REGIME_ENABLED,
        "regime": "NORMAL",
        "active": False,
        "btc_return_1h": r1h,
        "btc_return_15m": r15m,
        "btc_return_5m": r5m,
        "btc_trend": trend,
        "btc_htf_trend": htf_trend,
        "state": "normal",
    }
    if not BTC_REGIME_ENABLED:
        return base

    risk_off = (
        r1h <= BTC_RISK_OFF_RETURN_1H
        and r15m <= BTC_RISK_OFF_RETURN_15M
        and r5m <= BTC_RISK_OFF_RETURN_5M
        and trend == "bearish"
    )
    risk_on = (
        r1h >= BTC_RISK_ON_RETURN_1H
        and r15m >= BTC_RISK_ON_RETURN_15M
        and r5m >= BTC_RISK_ON_RETURN_5M
        and trend == "bullish"
    )

    if risk_off:
        return {
            **base,
            "regime": "BTC_RISK_OFF",
            "active": True,
            "state": "active_selloff",
        }

    if risk_on:
        return {
            **base,
            "regime": "BTC_RISK_ON",
            "active": True,
            "state": "active_rally",
        }

    if r1h <= BTC_RISK_OFF_RETURN_1H and r15m <= BTC_RISK_OFF_RETURN_15M and r5m > 0:
        return {**base, "regime": "BTC_RISK_OFF", "active": True, "state": "cooling_or_rebound"}

    if r1h >= BTC_RISK_ON_RETURN_1H and r15m >= BTC_RISK_ON_RETURN_15M and r5m < 0:
        return {**base, "regime": "BTC_RISK_ON", "active": True, "state": "cooling_or_pullback"}

    return base


def is_countertrend_action(action: str, regime: Dict[str, Any]) -> bool:
    name = (regime or {}).get("regime", "NORMAL")
    if name == "BTC_RISK_OFF":
        return action in ("LONG_FUTURES", "BUY_SPOT")
    if name == "BTC_RISK_ON":
        return action in ("SHORT_FUTURES", "SELL_SPOT")
    return False


def is_aligned_action(action: str, regime: Dict[str, Any]) -> bool:
    name = (regime or {}).get("regime", "NORMAL")
    if name == "BTC_RISK_OFF":
        return action in ("SHORT_FUTURES", "SELL_SPOT")
    if name == "BTC_RISK_ON":
        return action in ("LONG_FUTURES", "BUY_SPOT")
    return False
