"""Dispatcher de notificaciones para alertas accionables.

Canales soportados: Discord (webhook), Telegram (bot), Email (SMTP).
Cada canal es independiente — un fallo no bloquea los demás.
Registra cada intento en notification_log vía database.insert_notification_log().
"""

import logging
import smtplib
import urllib.request
import urllib.error
import json as _json
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

from app.config import (
    ENABLE_DISCORD_ALERTS,
    DISCORD_WEBHOOK_URL,
    ENABLE_TELEGRAM_ALERTS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ENABLE_EMAIL_ALERTS,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    EMAIL_FROM,
    EMAIL_TO,
)
from app import database

logger = logging.getLogger("notifier")

_ACTION_EMOJI = {
    "LONG_FUTURES":  "📈",
    "SHORT_FUTURES": "📉",
    "BUY_SPOT":      "🟢",
    "SELL_SPOT":     "🔴",
}


def _build_message_discord(
    symbol: str,
    action: str,
    market: str,
    confidence: int,
    score: int,
    price: float,
    setup: Dict[str, Any],
    signal: str = "",
) -> str:
    """Mensaje para Discord usando formato Markdown de Discord (**bold**)."""
    emoji = _ACTION_EMOJI.get(action, "⚠️")
    entry = setup.get("entry", 0.0)
    sl    = setup.get("stop_loss", 0.0)
    tp1   = setup.get("take_profit_1", 0.0)
    tp2   = setup.get("take_profit_2", 0.0)
    rr1   = setup.get("risk_reward_1", 0.0)
    rr2   = setup.get("risk_reward_2", 0.0)

    leverage  = setup.get("suggested_leverage", 0)
    risk_pct  = setup.get("risk_pct", 0.0)

    lines = [
        f"{emoji} **{action}** — {symbol}",
        f"Mercado: {market} | Confianza: {confidence}% | Score: {score}",
        f"Precio actual: {price:.6g}",
    ]
    if entry: lines.append(f"Entrada: {entry:.6g}")
    if sl:
        sl_info = f"Stop Loss: {sl:.6g}"
        if risk_pct: sl_info += f"  ({risk_pct:.2f}%)"
        lines.append(sl_info)
    if tp1:
        lines.append(f"TP1: {tp1:.6g}" + (f"  (R:R {rr1:.1f})" if rr1 else ""))
    if tp2:
        lines.append(f"TP2: {tp2:.6g}" + (f"  (R:R {rr2:.1f})" if rr2 else ""))
    if leverage and "FUTURES" in action:
        lines.append(f"Apalancamiento sugerido: {leverage}x")
    if signal: lines.append(f"Señal: {signal}")
    return "\n".join(lines)


_TIMING_LABEL = {
    "NOW":               "🟢 <b>ENTRAR AHORA</b>",
    "WAIT_FOR_PULLBACK": "⏳ <b>Esperar pullback</b>",
    "WAIT_FOR_BREAKOUT": "⏳ <b>Esperar breakout</b>",
    "WAIT":              "⏳ <b>Sin timing definido</b>",
}

_RISK_LABEL = {
    "low":    "🟢 bajo",
    "medium": "🟡 medio",
    "high":   "🔴 alto",
}


def _build_message_telegram(
    symbol: str,
    action: str,
    market: str,
    confidence: int,
    score: int,
    price: float,
    setup: Dict[str, Any],
    signal: str = "",
    risk_level: str = "low",
) -> str:
    """Mensaje para Telegram usando HTML (evita problemas de escape en Markdown)."""
    emoji      = _ACTION_EMOJI.get(action, "⚠️")
    timing     = setup.get("timing", "")
    entry      = setup.get("entry", 0.0)
    zone_low   = setup.get("entry_zone_low", 0.0)
    zone_high  = setup.get("entry_zone_high", 0.0)
    sl         = setup.get("stop_loss", 0.0)
    tp1        = setup.get("take_profit_1", 0.0)
    tp2        = setup.get("take_profit_2", 0.0)
    rr1        = setup.get("risk_reward_1", 0.0)
    rr2        = setup.get("risk_reward_2", 0.0)
    note       = setup.get("position_note", "")
    leverage   = setup.get("suggested_leverage", 0)
    risk_pct   = setup.get("risk_pct", 0.0)

    timing_str = _TIMING_LABEL.get(timing, f"⏳ <b>{timing}</b>") if timing else ""
    risk_str   = _RISK_LABEL.get(risk_level, risk_level)

    lines = [
        f"{emoji} <b>{action}</b> — {symbol}",
        "",
    ]
    if timing_str:
        lines.append(timing_str)
        lines.append("")

    lines += [
        f"Score: {score} | Confianza: {confidence}% | Riesgo: {risk_str}",
    ]
    if signal:
        lines.append(f"Señal: {signal}")
    lines.append("")

    lines.append(f"💰 Precio actual: <code>{price:.6g}</code>")
    if zone_low and zone_high:
        lines.append(f"📍 Zona entrada: <code>{zone_low:.6g} — {zone_high:.6g}</code>")
    if entry:
        lines.append(f"🎯 Entrada: <code>{entry:.6g}</code>")
    if sl:
        sl_dist = risk_pct if risk_pct else (abs((sl - entry) / entry * 100) if entry else 0)
        sl_dir = "+" if sl > entry else "-"
        lines.append(f"🛑 Stop Loss: <code>{sl:.6g}</code>  ({sl_dir}{sl_dist:.2f}%)")
    if tp1:
        lines.append(f"✅ TP1: <code>{tp1:.6g}</code>" + (f"  R:R {rr1:.1f}x" if rr1 else ""))
    if tp2:
        lines.append(f"✅ TP2: <code>{tp2:.6g}</code>" + (f"  R:R {rr2:.1f}x" if rr2 else ""))
    if leverage and "FUTURES" in action:
        lines.append(f"")
        lines.append(f"⚡ Apalancamiento sugerido: <b>{leverage}x</b>")
        lines.append(f"<i>(SL = {sl_dist:.1f}% del margen × {leverage}x = {sl_dist * leverage:.1f}% riesgo en posición)</i>")

    if note:
        lines.append("")
        lines.append(f"📝 {note[:200]}")

    return "\n".join(lines)


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 8) -> None:
    data = _json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"HTTP {resp.status}")


def _send_discord(
    alert_id: Optional[int],
    symbol: str,
    action: str,
    message: str,
) -> None:
    if not ENABLE_DISCORD_ALERTS or not DISCORD_WEBHOOK_URL:
        return
    try:
        _post_json(DISCORD_WEBHOOK_URL, {"content": message})
        database.insert_notification_log(alert_id, symbol, action, "discord", ok=True)
        logger.info("[discord] alerta enviada: %s %s", symbol, action)
    except Exception as exc:
        database.insert_notification_log(alert_id, symbol, action, "discord", ok=False, error=str(exc))
        logger.warning("[discord] error: %s", exc)


def _send_telegram(
    alert_id: Optional[int],
    symbol: str,
    action: str,
    message: str,
) -> None:
    if not ENABLE_TELEGRAM_ALERTS or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        _post_json(url, {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        })
        database.insert_notification_log(alert_id, symbol, action, "telegram", ok=True)
        logger.info("[telegram] alerta enviada: %s %s", symbol, action)
    except Exception as exc:
        database.insert_notification_log(alert_id, symbol, action, "telegram", ok=False, error=str(exc))
        logger.warning("[telegram] error: %s", exc)


def _send_email(
    alert_id: Optional[int],
    symbol: str,
    action: str,
    message: str,
) -> None:
    if not ENABLE_EMAIL_ALERTS or not SMTP_HOST or not EMAIL_FROM or not EMAIL_TO:
        return
    try:
        msg = MIMEText(message.replace("*", ""), "plain", "utf-8")
        msg["Subject"] = f"[Crypto Alert] {action} {symbol}"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())
        database.insert_notification_log(alert_id, symbol, action, "email", ok=True)
        logger.info("[email] alerta enviada: %s %s", symbol, action)
    except Exception as exc:
        database.insert_notification_log(alert_id, symbol, action, "email", ok=False, error=str(exc))
        logger.warning("[email] error: %s", exc)


def dispatch_report(msg_discord: str, msg_telegram: str) -> None:
    """Envía un mensaje de reporte (no alerta) a todos los canales configurados."""
    if ENABLE_DISCORD_ALERTS and DISCORD_WEBHOOK_URL:
        try:
            _post_json(DISCORD_WEBHOOK_URL, {"content": msg_discord})
            logger.info("[discord] reporte enviado")
        except Exception as exc:
            logger.warning("[discord] error enviando reporte: %s", exc)

    if ENABLE_TELEGRAM_ALERTS and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            _post_json(url, {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg_telegram,
                "parse_mode": "HTML",
            })
            logger.info("[telegram] reporte enviado")
        except Exception as exc:
            logger.warning("[telegram] error enviando reporte: %s", exc)


def dispatch_alert(
    symbol: str,
    action: str,
    market: str,
    confidence: int,
    score: int,
    price: float,
    setup: Dict[str, Any],
    signal: str = "",
    alert_id: Optional[int] = None,
    risk_level: str = "low",
) -> None:
    """Envía la alerta a todos los canales configurados."""
    msg_discord  = _build_message_discord(symbol, action, market, confidence, score, price, setup, signal)
    msg_telegram = _build_message_telegram(symbol, action, market, confidence, score, price, setup, signal, risk_level)
    _send_discord(alert_id, symbol, action, msg_discord)
    _send_telegram(alert_id, symbol, action, msg_telegram)
    _send_email(alert_id, symbol, action, msg_discord)
