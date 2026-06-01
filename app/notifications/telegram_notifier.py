"""Envía alertas de trading vía Telegram Bot API."""
import logging

import requests

from app.notifications.alert_models import TradeAlert

logger = logging.getLogger(__name__)

_ACTION_EMOJI = {
    "LONG_FUTURES":  "🟢",
    "SHORT_FUTURES": "🔴",
    "BUY_SPOT":      "🟩",
    "SELL_SPOT":     "🟧",
}


def send_telegram_alert(alert: TradeAlert, bot_token: str, chat_id: str) -> bool:
    """Envía mensaje Markdown a Telegram. Retorna True si tuvo éxito."""
    emoji = _ACTION_EMOJI.get(alert.action, "⚪")
    reasons_text = "\n".join(f"• {r}" for r in alert.reasons[:4]) or "—"
    inv_text = "\n".join(f"• {c}" for c in alert.invalidation[:3]) or "—"

    lines = [
        f"{emoji} *{alert.action}* — `{alert.symbol}`",
        f"",
        f"💰 Precio actual: `${alert.price:,.4f}`",
        f"⏱ Timing: `{alert.timing}`",
        f"📈 Entrada: `${alert.entry:,.4f}`",
        f"🛑 Stop loss: `${alert.stop_loss:,.4f}`",
        f"🎯 TP1: `${alert.take_profit_1:,.4f}` \\(R/R {alert.risk_reward_1:.1f}×\\)",
        f"🎯 TP2: `${alert.take_profit_2:,.4f}` \\(R/R {alert.risk_reward_2:.1f}×\\)",
        f"",
        f"📊 Confluencia: `{alert.confluence_score}/100` · Confianza: `{alert.confidence}%`",
        f"",
        f"*Razones:*",
        reasons_text,
        f"",
        f"*Invalida si:*",
        inv_text,
    ]

    if alert.warnings:
        lines += ["", "⚠ " + " · ".join(alert.warnings[:2])]

    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Telegram notify failed for %s: %s", alert.symbol, exc)
        # Reintentar con texto plano si falla el formato
        try:
            plain = (
                f"{alert.action} — {alert.symbol}\n"
                f"Precio: ${alert.price:,.4f} | Entrada: ${alert.entry:,.4f}\n"
                f"Stop: ${alert.stop_loss:,.4f} | TP1: ${alert.take_profit_1:,.4f}\n"
                f"R/R: {alert.risk_reward_1:.1f}x | Score: {alert.confluence_score}/100"
            )
            resp2 = requests.post(url, json={
                "chat_id": chat_id, "text": plain,
            }, timeout=10)
            resp2.raise_for_status()
            return True
        except Exception as exc2:
            logger.warning("Telegram plain-text fallback failed: %s", exc2)
            return False
