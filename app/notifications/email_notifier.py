"""Envía alertas de trading por email vía SMTP TLS."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.notifications.alert_models import TradeAlert

logger = logging.getLogger(__name__)

_ACTION_COLORS = {
    "LONG_FUTURES":  "#16a34a",
    "SHORT_FUTURES": "#dc2626",
    "BUY_SPOT":      "#10b981",
    "SELL_SPOT":     "#f97316",
}


def send_email_alert(
    alert: TradeAlert,
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    email_from: str,
    email_to: str,
) -> bool:
    """Envía email HTML con los niveles operables. Retorna True si tuvo éxito."""
    color = _ACTION_COLORS.get(alert.action, "#6b7280")
    reasons_html = "".join(f"<li>{r}</li>" for r in alert.reasons[:4])
    inv_html = "".join(f"<li>{c}</li>" for c in alert.invalidation[:3])
    warnings_html = (
        "<p style='color:#f59e0b'>" +
        " · ".join(f"⚠ {w}" for w in alert.warnings[:2]) +
        "</p>"
        if alert.warnings else ""
    )

    html = f"""
    <html><body style='font-family:monospace;background:#0e1117;color:#f9fafb;padding:20px'>
    <div style='max-width:600px;margin:0 auto'>
      <h2 style='color:{color}'>{alert.action} — {alert.symbol}</h2>
      <table style='width:100%;border-collapse:collapse'>
        <tr><td style='padding:4px 8px;color:#9ca3af'>Mercado</td>
            <td style='padding:4px 8px'>{alert.market}</td></tr>
        <tr><td style='padding:4px 8px;color:#9ca3af'>Precio actual</td>
            <td style='padding:4px 8px'>${alert.price:,.4f}</td></tr>
        <tr><td style='padding:4px 8px;color:#9ca3af'>Timing</td>
            <td style='padding:4px 8px'>{alert.timing}</td></tr>
        <tr style='background:#1f2937'><td style='padding:4px 8px;color:#9ca3af'>Entrada</td>
            <td style='padding:4px 8px;font-weight:bold'>${alert.entry:,.4f}</td></tr>
        <tr><td style='padding:4px 8px;color:#ef4444'>Stop loss</td>
            <td style='padding:4px 8px;color:#ef4444'>${alert.stop_loss:,.4f}</td></tr>
        <tr style='background:#1f2937'><td style='padding:4px 8px;color:#22c55e'>TP1</td>
            <td style='padding:4px 8px;color:#22c55e'>${alert.take_profit_1:,.4f}
              &nbsp;<small>(R/R {alert.risk_reward_1:.1f}×)</small></td></tr>
        <tr><td style='padding:4px 8px;color:#22c55e'>TP2</td>
            <td style='padding:4px 8px;color:#22c55e'>${alert.take_profit_2:,.4f}
              &nbsp;<small>(R/R {alert.risk_reward_2:.1f}×)</small></td></tr>
        <tr style='background:#1f2937'><td style='padding:4px 8px;color:#9ca3af'>Score</td>
            <td style='padding:4px 8px'>{alert.confluence_score}/100
              &nbsp;|&nbsp;Confianza: {alert.confidence}%</td></tr>
      </table>
      <h3 style='color:#d1d5db;margin-top:20px'>Razones</h3>
      <ul style='color:#d1d5db'>{reasons_html}</ul>
      <h3 style='color:#d1d5db'>Invalida si</h3>
      <ul style='color:#9ca3af'>{inv_html}</ul>
      {warnings_html}
      {"<p style='color:#6b7280;font-size:12px'>" + alert.position_note + "</p>" if alert.position_note else ""}
      <hr style='border-color:#1f2937;margin-top:24px'>
      <p style='color:#4b5563;font-size:11px'>Crypto Scanner — Institutional Dashboard</p>
    </div></body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = alert.subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(email_from, [email_to], msg.as_string())
        return True
    except Exception as exc:
        logger.warning("Email notify failed for %s: %s", alert.symbol, exc)
        return False
