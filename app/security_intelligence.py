"""Confirmacion y alertas tempranas para incidentes criticos de protocolo."""
import hashlib
import html
import time
import calendar
from collections import defaultdict
from typing import Any, Dict, Iterable, List

from app import database
from app.config import SECURITY_ALERT_LOOKBACK_HOURS, SECURITY_ALERT_MIN_ABS_SCORE
from app.notifier import dispatch_attention_alert

_CRITICAL_TYPES = {"hack", "critical_protocol_bug", "emergency_security_response"}
_OFFICIAL_MARKERS = (
    "github.com/", "zfnd.org", "shieldedlabs.net", "electriccoin.co", "zcashcommunity.com",
)


def _is_recent(value: str) -> bool:
    try:
        published = calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%S"))
        return published >= time.time() - SECURITY_ALERT_LOOKBACK_HOURS * 3600
    except Exception:
        return True


def _is_official(event: Dict[str, Any]) -> bool:
    domain = str(event.get("source_domain") or "").lower()
    return event.get("source") in {"github_release", "github_advisory"} or any(
        marker in domain for marker in _OFFICIAL_MARKERS
    )


def build_security_alert(symbol: str, events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    relevant = [
        event for event in events
        if event.get("symbol") == symbol
        and _is_recent(event.get("published_at", ""))
        and _CRITICAL_TYPES.intersection(event.get("event_types") or [])
        and (
            float(event.get("weighted_score") or 0) <= -SECURITY_ALERT_MIN_ABS_SCORE
            or _is_official(event)
        )
    ]
    if not relevant:
        return {}

    relevant.sort(key=lambda item: item.get("published_at", ""))
    sources = list(dict.fromkeys(event.get("source_domain") or event.get("source") for event in relevant))
    official = list(dict.fromkeys(
        event.get("source_domain") or event.get("source") for event in relevant if _is_official(event)
    ))
    types = sorted(set().union(*(set(event.get("event_types") or []) for event in relevant)))
    score = max(-100.0, sum(float(event.get("weighted_score") or 0) for event in relevant))
    first_published = relevant[0].get("published_at", "")
    incident_day = first_published[:10] or time.strftime("%Y-%m-%d", time.gmtime())
    context = database.get_latest_symbol_context(symbol)
    return_1h = float(context.get("return_1h") or 0)
    market_stage = "PRICE_CONFIRMING" if return_1h <= -1 else "EARLY_ATTENTION"
    strongest = min(relevant, key=lambda event: float(event.get("weighted_score") or 0))
    impacts = []
    if "critical_protocol_bug" in types:
        impacts.append("Riesgo de integridad del protocolo, consenso o suministro.")
    if "emergency_security_response" in types:
        impacts.append("Actualizacion urgente puede causar suspensiones, forks o presion vendedora.")
    if "hack" in types:
        impacts.append("Posible explotacion, perdida de fondos o deterioro de confianza.")
    return {
        "fingerprint": hashlib.sha256(f"{symbol}|protocol_security|{incident_day}".encode()).hexdigest(),
        "symbol": symbol,
        "severity": "CRITICAL" if score <= -30 or "critical_protocol_bug" in types else "HIGH",
        "confirmation_status": "CONFIRMED" if official or len(sources) >= 2 else "UNCONFIRMED",
        "security_score": round(score, 2),
        "source_count": len(sources),
        "official_source_count": len(official),
        "first_published_at": first_published,
        "title": strongest.get("title", "Critical protocol security event"),
        "event_types": types,
        "sources": sources,
        "events": relevant[:5],
        "market_context": context,
        "market_stage": market_stage,
        "impact_assessment": impacts,
        "trade_bias": "WATCH_SHORT_AVOID_LONGS" if official or len(sources) >= 2 else "RESEARCH_ONLY",
    }


def _messages(alert: Dict[str, Any]) -> tuple:
    confirmed = alert["confirmation_status"] == "CONFIRMED"
    status = "CONFIRMADO" if confirmed else "SIN CONFIRMAR"
    context = alert.get("market_context") or {}
    action = (
        "Vigilar SHORT_FUTURES / SELL_SPOT; evitar longs hasta confirmacion tecnica."
        if confirmed else "No operar aun; revisar fuentes y esperar confirmacion independiente."
    )
    confirmation = (
        "Esperar ruptura de soporte/VWAP, CVD negativo y expansion de volumen antes de entrar."
        if confirmed else "Una segunda fuente u aviso oficial elevara automaticamente la alerta."
    )
    tg = [
        "🚨 <b>CRITICAL PROTOCOL SECURITY</b>",
        f"<b>{html.escape(alert['symbol'])}</b> · {alert['severity']} · {status}",
        f"Security score: <code>{alert['security_score']:+.1f}</code>",
        "",
        f"<b>Evento:</b> {html.escape(alert['title'][:220])}",
        f"<b>Detectado primero:</b> <code>{html.escape(alert['first_published_at'])} UTC</code>",
        f"<b>Confirmación:</b> {alert['official_source_count']} fuentes oficiales · {alert['source_count']} totales",
        f"<b>Tipos:</b> {html.escape(', '.join(alert['event_types']))}",
        f"<b>Etapa:</b> {html.escape(alert['market_stage'])}",
        "",
        "<b>Análisis de atención</b>",
        *[f"• {html.escape(impact)}" for impact in alert.get("impact_assessment", [])],
        f"• {html.escape(action)}",
        f"• {html.escape(confirmation)}",
    ]
    if context:
        tg.append(
            f"• Precio <code>{float(context.get('price') or 0):.6g}</code>"
            f" · 5m <code>{float(context.get('return_5m') or 0):+.2f}%</code>"
            f" · 1h <code>{float(context.get('return_1h') or 0):+.2f}%</code>"
            f" · señal {html.escape(str(context.get('signal') or 'N/D'))}"
        )
    tg += ["", "<b>Fuentes verificadas</b>"]
    for event in alert["events"][:4]:
        tg.append(
            f"• <a href=\"{html.escape(event.get('url') or '')}\">"
            f"{html.escape((event.get('source_domain') or event.get('source') or '')[:60])}</a>"
        )
    tg += ["", "<i>Alerta de investigación. No abre posiciones automáticamente.</i>"]

    dc = [
        "CRITICAL PROTOCOL SECURITY",
        f"{alert['symbol']} | {alert['severity']} | {status} | score {alert['security_score']:+.1f}",
        f"Evento: {alert['title']}",
        f"Primera publicación: {alert['first_published_at']} UTC",
        f"Fuentes: {alert['official_source_count']} oficiales / {alert['source_count']} totales",
        f"Acción: {action}",
        f"Confirmación técnica: {confirmation}",
    ]
    dc.extend(f"- {event.get('url')}" for event in alert["events"][:4] if event.get("url"))
    return "\n".join(dc), "\n".join(tg)


def process_security_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event.get("symbol", "")].append(event)
    emitted: List[Dict[str, Any]] = []
    for symbol, symbol_events in grouped.items():
        alert = build_security_alert(symbol, symbol_events)
        if not alert:
            continue
        stored = database.upsert_security_event_alert(alert)
        if stored.get("should_notify"):
            msg_dc, msg_tg = _messages(alert)
            dispatch_attention_alert(symbol, "CRITICAL_PROTOCOL_SECURITY", msg_dc, msg_tg)
            emitted.append(alert)
    return emitted
