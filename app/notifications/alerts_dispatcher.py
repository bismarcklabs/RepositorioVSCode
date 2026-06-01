"""Dispatcher central de alertas.

Cooldown: in-memory (_cooldown_store) + persistente (SQLite).
Al arrancar, se precarga el store desde la DB para sobrevivir reinicios
de Streamlit sin generar spam.

Reglas de reenvío:
- Mismo (symbol, action, market): esperar ALERT_COOLDOWN_SECONDS.
- Reenviar antes si la confianza sube >= ALERT_MIN_CONFIDENCE_DELTA_RESEND.
"""
import logging
import threading
import time
from typing import Dict, Optional, Tuple

from app.config import (
    ALERT_COOLDOWN_SECONDS,
    ALERT_MIN_CONFIDENCE_DELTA_RESEND,
    ENABLE_DATABASE,
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
from app.notifications.alert_models import TradeAlert

logger = logging.getLogger(__name__)

# ── In-memory cooldown store ──────────────────────────────────────────────
# key=(symbol, action, market) → (monotonic_ts, confidence)
_cooldown_store: Dict[Tuple[str, str, str], Tuple[float, int]] = {}
_cooldown_lock = threading.Lock()
_preloaded = False


def _preload_from_db() -> None:
    """Carga alertas recientes desde SQLite al arrancar para sobrevivir reinicios."""
    global _preloaded
    if _preloaded:
        return
    if not ENABLE_DATABASE:
        _preloaded = True
        return
    try:
        from app.database import get_recent_sent_alerts
        rows = get_recent_sent_alerts(within_seconds=ALERT_COOLDOWN_SECONDS)
        now = time.monotonic()
        wall_now = time.time()
        with _cooldown_lock:
            for row in rows:
                key = (row["symbol"], row["action"], row["market"])
                if key in _cooldown_store:
                    continue
                # Convertir timestamp ISO a epoch para calcular elapsed
                try:
                    import datetime
                    dt = datetime.datetime.fromisoformat(row["timestamp"])
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    sent_wall = dt.timestamp()
                    elapsed = wall_now - sent_wall
                    if elapsed < ALERT_COOLDOWN_SECONDS:
                        # Simular en monotonic: cuánto queda de cooldown
                        synthetic_ts = now - elapsed
                        _cooldown_store[key] = (synthetic_ts, row.get("confidence", 0))
                except Exception:
                    pass
        logger.info("Cooldown precargado desde DB: %d entradas", len(rows))
    except Exception as exc:
        logger.warning("No se pudo precargar cooldown desde DB: %s", exc)
    finally:
        _preloaded = True


def _should_send(alert: TradeAlert) -> bool:
    """Retorna True si la alerta debe enviarse (cooldown o mejora de confianza)."""
    _preload_from_db()
    key = (alert.symbol, alert.action, alert.market)
    now = time.monotonic()

    with _cooldown_lock:
        entry = _cooldown_store.get(key)
        if entry is None:
            _cooldown_store[key] = (now, alert.confidence)
            return True

        last_ts, last_conf = entry
        elapsed = now - last_ts

        if elapsed >= ALERT_COOLDOWN_SECONDS:
            _cooldown_store[key] = (now, alert.confidence)
            return True

        if alert.confidence >= last_conf + ALERT_MIN_CONFIDENCE_DELTA_RESEND:
            _cooldown_store[key] = (now, alert.confidence)
            return True

        return False


def dispatch_alert(alert: TradeAlert) -> Dict[str, bool]:
    """Envía la alerta a todos los canales habilitados.

    Retorna dict canal → éxito. Nunca lanza excepción al llamador.
    """
    if not alert.is_valid():
        logger.debug("Alerta inválida para %s — sin setup operable", alert.symbol)
        return {}

    if not _should_send(alert):
        logger.debug("Alerta %s %s en cooldown", alert.action, alert.symbol)
        return {}

    results: Dict[str, bool] = {}

    if ENABLE_DISCORD_ALERTS and DISCORD_WEBHOOK_URL:
        try:
            from app.notifications.discord_notifier import send_discord_alert
            results["discord"] = send_discord_alert(alert, DISCORD_WEBHOOK_URL)
        except Exception as exc:
            logger.warning("Discord channel error: %s", exc)
            results["discord"] = False

    if ENABLE_TELEGRAM_ALERTS and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            from app.notifications.telegram_notifier import send_telegram_alert
            results["telegram"] = send_telegram_alert(
                alert, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            )
        except Exception as exc:
            logger.warning("Telegram channel error: %s", exc)
            results["telegram"] = False

    if ENABLE_EMAIL_ALERTS and SMTP_HOST and EMAIL_FROM and EMAIL_TO:
        try:
            from app.notifications.email_notifier import send_email_alert
            results["email"] = send_email_alert(
                alert,
                smtp_host=SMTP_HOST,
                smtp_port=SMTP_PORT,
                username=SMTP_USERNAME,
                password=SMTP_PASSWORD,
                email_from=EMAIL_FROM,
                email_to=EMAIL_TO,
            )
        except Exception as exc:
            logger.warning("Email channel error: %s", exc)
            results["email"] = False

    if results:
        channels_ok = [ch for ch, ok in results.items() if ok]
        logger.info("Alerta %s %s enviada → %s", alert.action, alert.symbol, channels_ok)

    return results
