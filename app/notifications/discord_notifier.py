"""Envía alertas de trading como embeds a un webhook de Discord."""
import logging
from typing import Optional

import requests

from app.notifications.alert_models import TradeAlert

logger = logging.getLogger(__name__)

_ACTION_COLORS = {
    "LONG_FUTURES":  0x16A34A,   # verde oscuro
    "SHORT_FUTURES": 0xDC2626,   # rojo
    "BUY_SPOT":      0x10B981,   # esmeralda
    "SELL_SPOT":     0xF97316,   # naranja
}

_ACTION_EMOJI = {
    "LONG_FUTURES":  "🟢",
    "SHORT_FUTURES": "🔴",
    "BUY_SPOT":      "🟩",
    "SELL_SPOT":     "🟧",
}


def send_discord_alert(alert: TradeAlert, webhook_url: str) -> bool:
    """Envía un embed Discord. Retorna True si tuvo éxito."""
    color = _ACTION_COLORS.get(alert.action, 0x6B7280)
    emoji = _ACTION_EMOJI.get(alert.action, "⚪")

    reasons_text = "\n".join(f"• {r}" for r in alert.reasons[:4]) or "—"
    inv_text = "\n".join(f"• {c}" for c in alert.invalidation[:3]) or "—"
    warnings_text = "\n".join(f"⚠ {w}" for w in alert.warnings[:2]) if alert.warnings else ""

    fields = [
        {"name": "⏱ Timing",    "value": alert.timing,                       "inline": True},
        {"name": "📈 Entrada",   "value": f"${alert.entry:,.4f}",             "inline": True},
        {"name": "🛑 Stop",      "value": f"${alert.stop_loss:,.4f}",         "inline": True},
        {"name": "🎯 TP1",       "value": f"${alert.take_profit_1:,.4f} (R/R {alert.risk_reward_1:.1f}×)", "inline": True},
        {"name": "🎯 TP2",       "value": f"${alert.take_profit_2:,.4f} (R/R {alert.risk_reward_2:.1f}×)", "inline": True},
        {"name": "📊 Score",     "value": f"{alert.confluence_score}/100",    "inline": True},
        {"name": "✅ Razones",   "value": reasons_text,                       "inline": False},
        {"name": "❌ Invalida",  "value": inv_text,                           "inline": False},
    ]
    if warnings_text:
        fields.append({"name": "⚠ Advertencias", "value": warnings_text, "inline": False})
    if alert.position_note:
        fields.append({"name": "📝 Nota", "value": alert.position_note[:200], "inline": False})

    embed = {
        "title": f"{emoji} {alert.action} — {alert.symbol}",
        "description": (
            f"**Mercado:** {alert.market}  |  "
            f"**Precio actual:** ${alert.price:,.4f}  |  "
            f"**Confianza:** {alert.confidence}%"
        ),
        "color": color,
        "fields": fields,
        "footer": {"text": "Crypto Scanner — Institutional Dashboard"},
    }

    payload = {"embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Discord notify failed for %s: %s", alert.symbol, exc)
        return False
