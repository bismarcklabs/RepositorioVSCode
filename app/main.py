import datetime
import html
import json
import logging
import os
import sys
import time as _time
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="plotly")
warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd
import plotly.express as px
from typing import Any, Dict, List

from app.log_setup import setup_logging
setup_logging()
logger = logging.getLogger("dashboard")

from streamlit_autorefresh import st_autorefresh

from app.config import (
    SCANNER_CANDIDATE_LIMIT,
    SCANNER_RESULT_LIMIT,
    ENABLE_DATABASE,
    NEAR_MISS_THRESHOLD,
)
from app import database


def _utc_to_local(ts_utc: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Convierte un timestamp UTC ISO (sin zona) a hora local del sistema."""
    if not ts_utc:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(ts_utc).replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(tz=None).strftime(fmt)
    except Exception:
        return ts_utc


# ── Caché de queries DB ───────────────────────────────────────────────────
@st.cache_data(ttl=15)
def _cached_latest_snapshots(limit: int, max_age: int):
    return database.get_latest_snapshots(limit=limit, max_age_seconds=max_age)

@st.cache_data(ttl=60)
def _cached_recent_alerts(limit: int = 50):
    return database.get_recent_alerts(limit=limit)

@st.cache_data(ttl=60)
def _cached_win_rate():
    return database.get_win_rate_by_action()

@st.cache_data(ttl=60)
def _cached_symbols_by_action():
    return database.get_symbols_by_action()

@st.cache_data(ttl=60)
def _cached_channel_stats():
    return database.get_channel_stats()

@st.cache_data(ttl=30)
def _cached_snapshot_count():
    return database.get_snapshot_count()

@st.cache_data(ttl=60)
def _cached_news_dashboard(since_hours: float = 24.0, event_limit: int = 40):
    return database.get_news_dashboard(since_hours=since_hours, event_limit=event_limit)

@st.cache_data(ttl=30)
def _cached_pnl_overview():
    return database.get_pnl_overview()


def _build_rows_from_db(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reconstruye all_rows a partir de snapshots leídos de la DB."""
    rows: List[Dict[str, Any]] = []
    for s in snapshots:
        rec  = json.loads(s.get("recommendation_json") or "{}")
        sig  = json.loads(s.get("signal_json") or "{}")
        ar   = json.loads(s.get("alert_report_json") or "{}")
        setup = rec.get("setup") or {}
        rows.append({
            "symbol":               s["symbol"],
            "timestamp":            s.get("timestamp", ""),
            "price":                s.get("price", 0.0),
            "futures_price":        s.get("futures_price", 0.0),
            "score":                s.get("score", 0),
            "flow_score":           s.get("flow_score", 0),
            "technical_score":      s.get("technical_score", 0),
            "volume_profile_score": s.get("volume_profile_score", 0),
            "footprint_score":      s.get("footprint_score", 0),
            "futures_score":        s.get("futures_score", 0),
            "gex_score":            s.get("gex_score", 0),
            "risk_penalty":         s.get("risk_penalty", 0),
            "action":               s.get("action", "WAIT"),
            "market":               s.get("market", "NONE"),
            "confidence":           s.get("confidence", 0),
            "confluence_score":     s.get("confluence_score", 0),
            "signal":               s.get("signal", "neutral"),
            "signal_description":   sig.get("institutional_interpretation", ""),
            "entry_context":        rec.get("entry_context", ""),
            "reasons":              json.loads(s.get("reasons_json") or "[]"),
            "warnings":             json.loads(s.get("warnings_json") or "[]"),
            "invalidation":         json.loads(s.get("invalidation_json") or "[]"),
            "risk_level":           s.get("risk_level", "low"),
            "cvd":                  s.get("cvd", 0.0),
            "cvd_15m":              s.get("cvd_15m", 0.0),
            "delta":                s.get("delta", 0.0),
            "buy_volume":           s.get("buy_volume", 0.0),
            "sell_volume":          s.get("sell_volume", 0.0),
            "funding":              s.get("funding", 0.0),
            "open_interest":        s.get("open_interest", 0.0),
            "oi_change_pct":        s.get("oi_change_pct", 0.0),
            "imbalance":            s.get("imbalance", 0.0),
            "spread_pct":           s.get("spread_pct", 0.0),
            "return_1h":            s.get("return_1h", 0.0),
            "return_15m":           s.get("return_15m", 0.0),
            "vwap":                 s.get("vwap", 0.0),
            "trend_bias":           s.get("trend_bias", "neutral"),
            "above_vwap":           bool(s.get("above_vwap", True)),
            "vwap_distance_pct":    s.get("vwap_distance_pct", 0.0),
            "relative_volume":      s.get("relative_volume", 1.0),
            "poc":                  s.get("poc", 0.0),
            "vp_nearest":           s.get("nearest_vp_type", "NONE"),
            "vp_distance":          abs(s.get("vp_distance", 0.0)),
            "footprint_delta":      s.get("footprint_delta", 0.0),
            "absorption_buy":       bool(s.get("absorption_buy", False)),
            "absorption_sell":      bool(s.get("absorption_sell", False)),
            "stacked_buy_imbalance":  bool(s.get("stacked_buy_imbalance", False)),
            "stacked_sell_imbalance": bool(s.get("stacked_sell_imbalance", False)),
            "call_wall":            s.get("call_wall", 0.0),
            "put_wall":             s.get("put_wall", 0.0),
            "gamma_flip":           s.get("gamma_flip", 0.0),
            "gex_available":        bool(s.get("gex_available", False)),
            "trades_source":        "db",
            "setup":                setup if setup else None,
            "_alert_report":        ar,
        })
    return rows


# ── Configuración de página ───────────────────────────────────────────────
st.set_page_config(
    page_title="Institutional Crypto Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background-color: #0e1117; color: #ffffff; }
    .stMetric { background-color: #1f2937; border-radius: 10px; padding: 10px; }
    .token-card {
        background-color: #111827;
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 12px;
        margin-bottom: 16px;
    }
    .token-card h4 { margin-bottom: 6px; font-size: 16px; color: #f9fafb; }
    .token-card .lbl { color: #9ca3af; font-size: 12px; }
    .token-card .val { color: #d1d5db; font-size: 12px; }
    .action-card { border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; }
    .action-long-futures  { background-color: #052e16; border-left: 4px solid #16a34a; }
    .action-short-futures { background-color: #450a0a; border-left: 4px solid #dc2626; }
    .action-buy-spot      { background-color: #022c22; border-left: 4px solid #10b981; }
    .action-sell-spot     { background-color: #431407; border-left: 4px solid #f97316; }
    .action-wait          { background-color: #111827; border-left: 4px solid #6b7280; }
    .near-miss-card {
        background-color: #1c1f2e;
        border-left: 3px solid #4b5563;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 6px;
        font-size: 13px;
    }
    .alert-high   { background-color: #7f1d1d; border-left: 4px solid #ef4444; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; }
    .alert-medium { background-color: #78350f; border-left: 4px solid #f59e0b; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; }
    .alert-low    { background-color: #14532d; border-left: 4px solid #22c55e; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; }
    .news-card { background-color:#111827; border:1px solid #253044; border-radius:6px; padding:12px; margin-bottom:8px; }
    .news-bullish { border-left:4px solid #22c55e; }
    .news-bearish { border-left:4px solid #ef4444; }
    .news-neutral { border-left:4px solid #9ca3af; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏛️ Institutional Crypto Dashboard")
st_autorefresh(interval=15_000, limit=None, key="auto_refresh")

# ── Inicialización única ──────────────────────────────────────────────────
if "db_ready" not in st.session_state:
    if ENABLE_DATABASE:
        database.init_db()
    st.session_state["db_ready"] = True

# ── Sidebar: estado del scanner ───────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📡 Estado del scanner")
    _freshness = database.get_scanner_freshness() if ENABLE_DATABASE else None
    if _freshness:
        _dt_utc = datetime.datetime.fromisoformat(_freshness).replace(tzinfo=datetime.timezone.utc)
        _age = _time.time() - _dt_utc.timestamp()
        _local_time = _utc_to_local(_freshness, fmt="%H:%M:%S")
        if _age < 30:
            st.success(f"Scanner activo\nÚltimo dato: {_local_time}")
        elif _age < 120:
            st.warning(f"Scanner lento ({int(_age)}s)\nÚltimo dato: {_local_time}")
        else:
            st.error(f"Scanner inactivo ({int(_age)}s sin datos)\nInicia run_scanner.py")
    else:
        st.error("DB vacía — inicia run_scanner.py")
        st.code("python scripts/run_scanner.py", language="bash")

    st.markdown("---")
    st.markdown("### ⚙️ Configuración display")
    _max_age = st.slider("Antigüedad máx. datos (s)", 30, 300, 120, step=15)
    _top_n = st.slider("Top símbolos a mostrar", 5, 50, SCANNER_RESULT_LIMIT, step=5)

    st.markdown("---")
    st.markdown("### 🗄️ Base de datos")
    _snap_info = database.get_snapshot_count()
    st.caption(f"{_snap_info:,} snapshots en DB")
    st.caption("Para purgar datos usar: `python scripts/manage_db.py --help`")

_ACTION_LABELS = {
    "LONG_FUTURES":  "🟢 LONG FUTURES",
    "SHORT_FUTURES": "🔴 SHORT FUTURES",
    "BUY_SPOT":      "🟩 BUY SPOT",
    "SELL_SPOT":     "🟧 SELL SPOT",
    "WAIT":          "⚪ WAIT",
}
_ACTION_CSS = {
    "LONG_FUTURES":  "action-long-futures",
    "SHORT_FUTURES": "action-short-futures",
    "BUY_SPOT":      "action-buy-spot",
    "SELL_SPOT":     "action-sell-spot",
    "WAIT":          "action-wait",
}

# ── Leer datos de la DB ───────────────────────────────────────────────────
all_rows: List[Dict[str, Any]] = []
alert_rows: List[Dict[str, Any]] = []

if ENABLE_DATABASE:
    _snapshots = _cached_latest_snapshots(limit=SCANNER_CANDIDATE_LIMIT, max_age=_max_age)
    if _snapshots:
        all_rows = _build_rows_from_db(_snapshots)
        logger.info("DB mode: %d snapshots cargados", len(all_rows))

# Extraer alert_rows desde _alert_report serializado
for row in all_rows:
    ar = row.pop("_alert_report", {})
    if ar:
        risk    = ar.get("risk", {})
        squeeze = ar.get("squeeze_confirmation", {})
        stress  = ar.get("stress", {})
        if risk.get("risk_level") in ("medium", "high") or squeeze.get("confirmation") == "strong":
            alert_rows.append({
                "symbol":               row["symbol"],
                "risk_level":           risk.get("risk_level", "low"),
                "risk_reasons":         risk.get("risk_reasons", []),
                "squeeze_confirmation": squeeze.get("confirmation", "none"),
                "squeeze_message":      squeeze.get("message", ""),
                "stress_level":         stress.get("stress_level", "low"),
                "stress_score":         stress.get("stress_score", 0),
                "signal":               row["signal"],
            })

all_rows.sort(key=lambda x: x["score"], reverse=True)
display_rows = all_rows[:_top_n]

near_miss_rows = [
    r for r in all_rows
    if r["action"] == "WAIT"
    and r["signal"] != "neutral"
    and r["score"] >= NEAR_MISS_THRESHOLD
][:10]

# ── Header stats ──────────────────────────────────────────────────────────
if not all_rows:
    st.warning("Sin datos disponibles. Verifica que run_scanner.py esté corriendo.")
    st.stop()

action_count = sum(1 for r in display_rows if r["action"] != "WAIT")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Símbolos en DB", len(all_rows))
c2.metric("Top resultados", len(display_rows))
c3.metric("Con señal accionable", action_count)
c4.metric("Fuente", "📦 DB")
st.caption(
    f"Modo DB — scanner externo escribe, dashboard solo lee · "
    f"Antigüedad máx: {_max_age}s · TTL caché: 15s"
)

# ── PnL actual ────────────────────────────────────────────────────────────
st.markdown("### 💰 PnL acumulado")
_pnl = _cached_pnl_overview() if ENABLE_DATABASE else {"futures": {}, "spot": {}, "micro_scalp": {}}
_pf, _ps, _pm = _pnl.get("futures", {}), _pnl.get("spot", {}), _pnl.get("micro_scalp", {})

pnl_c1, pnl_c2, pnl_c3 = st.columns(3)
pnl_c1.metric(
    "📈 Futures (USDT)",
    f"{_pf.get('pnl_usdt', 0.0):+.2f}$",
    f"WR {_pf.get('winrate_pct', 0.0):.1f}% · {_pf.get('closed', 0)} cerradas / {_pf.get('open', 0)} abiertas",
    delta_color="off",
)
pnl_c2.metric(
    "🪙 Spot (USDT)",
    f"{_ps.get('pnl_usdt', 0.0):+.2f}$",
    f"WR {_ps.get('winrate_pct', 0.0):.1f}% · {_ps.get('closed', 0)} cerradas / {_ps.get('open', 0)} abiertas",
    delta_color="off",
)
pnl_c3.metric(
    "⚡ Micro-scalping (%)",
    f"{_pm.get('pnl_pct_total', 0.0):+.2f}%",
    f"WR {_pm.get('winrate_pct', 0.0):.1f}% · {_pm.get('closed', 0)} cerradas / {_pm.get('open', 0)} abiertas",
    delta_color="off",
)
st.caption("PnL realizado acumulado (histórico, paper) · Futures/Spot en USDT · Micro-scalp en % acumulado")


# ── Sección 1: Oportunidades accionables ─────────────────────────────────

# Noticias recientes y tendencia estimada. Es observacional: no abre posiciones.
st.markdown("### Noticias recientes y tendencia estimada")
news_data = _cached_news_dashboard(since_hours=24.0, event_limit=40) if ENABLE_DATABASE else {
    "predictions": [], "events": [], "performance": {}
}
news_predictions = news_data.get("predictions", [])
news_events = news_data.get("events", [])

if not news_predictions and not news_events:
    st.info("Aun no hay noticias clasificadas en las ultimas 24 horas.")
else:
    pred_by_symbol = {row.get("symbol", ""): row for row in news_predictions}
    bullish_count = sum(1 for row in news_predictions if row.get("prediction") == "BULLISH")
    bearish_count = sum(1 for row in news_predictions if row.get("prediction") == "BEARISH")
    neutral_count = sum(1 for row in news_predictions if row.get("prediction") == "NEUTRAL")
    nc1, nc2, nc3, nc4 = st.columns(4)
    nc1.metric("Tokens con noticias", len(pred_by_symbol))
    nc2.metric("Estimado bullish", bullish_count)
    nc3.metric("Estimado bearish", bearish_count)
    nc4.metric("Neutral / mixto", neutral_count)

    for prediction in news_predictions[:8]:
        symbol = prediction.get("symbol", "")
        tendency = prediction.get("prediction", "NEUTRAL")
        confidence = int(prediction.get("confidence", 0) or 0)
        score = float(prediction.get("sentiment_score", 0) or 0)
        contradictory = bool(prediction.get("contradictory", False))
        css = {"BULLISH": "news-bullish", "BEARISH": "news-bearish"}.get(tendency, "news-neutral")
        if tendency == "BULLISH" and confidence >= 65 and not contradictory:
            recommendation = "ALERTA ALCISTA: buscar confirmacion tecnica antes de una entrada long."
        elif tendency == "BEARISH" and confidence >= 65 and not contradictory:
            recommendation = "ALERTA BAJISTA: vigilar short o reducir exposicion long."
        elif contradictory:
            recommendation = "NOTICIAS CONTRADICTORIAS: esperar confirmacion; evitar entrada por noticia."
        else:
            recommendation = "OBSERVAR: evidencia informativa insuficiente para operar."

        token_events = [event for event in news_events if event.get("symbol") == symbol][:3]
        event_html = ""
        for event in token_events:
            title = html.escape(str(event.get("title", "")))
            source = html.escape(str(event.get("source_domain") or event.get("source") or "fuente"))
            url = html.escape(str(event.get("url", "")), quote=True)
            when = html.escape(_utc_to_local(event.get("published_at", ""), fmt="%d/%m %H:%M"))
            link = f"<a href='{url}' target='_blank' style='color:#93c5fd'>{title}</a>" if url else title
            event_html += f"<li>{link}<br><span style='color:#6b7280;font-size:11px'>{source} | {when}</span></li>"

        st.markdown(
            f"<div class='news-card {css}'>"
            f"<div style='display:flex;justify-content:space-between;gap:12px'>"
            f"<b style='font-size:16px;color:#f9fafb'>{html.escape(symbol)}</b>"
            f"<b>{html.escape(tendency)} | confianza {confidence}%</b></div>"
            f"<div style='font-size:12px;color:#9ca3af;margin:4px 0'>"
            f"Score noticias: {score:+.1f} | positivas: {prediction.get('positive_count', 0)} | "
            f"negativas: {prediction.get('negative_count', 0)} | total: {prediction.get('news_count', 0)}</div>"
            f"<div style='font-size:12px;color:#e5e7eb'><b>Recomendacion:</b> {html.escape(recommendation)}</div>"
            f"<ul style='font-size:12px;color:#d1d5db;margin:7px 0 0;padding-left:18px'>{event_html}</ul>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with st.expander("Ver listado completo de noticias de las ultimas 24 horas"):
        event_rows = [{
            "Hora": _utc_to_local(event.get("published_at", ""), fmt="%d/%m %H:%M"),
            "Token": event.get("symbol", ""),
            "Estimado": event.get("prediction", "NEUTRAL"),
            "Score": round(float(event.get("weighted_score", 0) or 0), 1),
            "Credibilidad %": round(float(event.get("credibility", 0) or 0) * 100, 0),
            "Fuente": event.get("source_domain") or event.get("source", ""),
            "Titular": event.get("title", ""),
            "Resumen": event.get("summary", ""),
            "URL": event.get("url", ""),
        } for event in news_events]
        st.dataframe(pd.DataFrame(event_rows), use_container_width=True, hide_index=True)

# Oportunidades accionables
st.markdown("### 🎯 Oportunidades de trading")

actionable = sorted(
    [r for r in display_rows if r["action"] != "WAIT"],
    key=lambda x: x["confidence"],
    reverse=True,
)

if not actionable:
    st.info("No hay señales de acción en este ciclo. Todos los símbolos están en WAIT.")
else:
    st.write(f"**{len(actionable)}** oportunidades detectadas.")
    for i in range(0, len(actionable), 2):
        cols = st.columns(2)
        for j, row in enumerate(actionable[i: i + 2]):
            with cols[j]:
                action = row["action"]
                css    = _ACTION_CSS.get(action, "action-wait")
                label  = _ACTION_LABELS.get(action, action)
                trend_color = (
                    "#10b981" if row["trend_bias"] == "bullish"
                    else "#ef4444" if row["trend_bias"] == "bearish"
                    else "#6b7280"
                )
                reasons_html = "".join(
                    f"<li style='font-size:12px;color:#d1d5db'>{r}</li>"
                    for r in row["reasons"][:4]
                )
                warnings_html = ""
                if row["warnings"]:
                    w_items = "".join(
                        f"<li style='font-size:12px;color:#fbbf24'>{w}</li>"
                        for w in row["warnings"][:2]
                    )
                    warnings_html = (
                        "<ul style='margin:4px 0 0 0;padding-left:16px'>"
                        + w_items + "</ul>"
                    )
                inv_items = "".join(
                    f"<li style='font-size:11px;color:#9ca3af'>{c}</li>"
                    for c in row["invalidation"][:3]
                )
                gex_badge = " ⚡GEX" if row["gex_available"] else ""
                vp_badge  = (" 📊" + row["vp_nearest"]) if row["vp_nearest"] != "NONE" else ""

                subscores = (
                    f"Flow <b>{row['flow_score']}</b>/30 · "
                    f"Técnico <b>{row['technical_score']}</b>/25 · "
                    f"VP <b>{row['volume_profile_score']}</b>/15 · "
                    f"FP <b>{row['footprint_score']}</b>/15 · "
                    f"Fut <b>{row['futures_score']}</b>/15 · "
                    f"GEX <b>{row['gex_score']}</b>/5"
                )

                setup = row.get("setup") or {}
                timing_badge = ("⏱ " + setup.get("timing", "")) if setup else ""
                levels_html = ""
                note_html = ""
                if setup:
                    entry = setup.get("entry", 0.0)
                    sl    = setup.get("stop_loss", 0.0)
                    tp1   = setup.get("take_profit_1", 0.0)
                    tp2   = setup.get("take_profit_2", 0.0)
                    rr1   = setup.get("risk_reward_1", 0.0)
                    rr2   = setup.get("risk_reward_2", 0.0)
                    ez_lo = setup.get("entry_zone_low", entry)
                    ez_hi = setup.get("entry_zone_high", entry)
                    levels_html = (
                        "<div style='background:#0d1117;border-radius:6px;padding:8px;margin:6px 0;"
                        "font-size:12px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px'>"
                        "<div>"
                        "<div style='color:#6b7280;font-size:10px'>ENTRADA</div>"
                        f"<div style='color:#f9fafb;font-weight:600'>${entry:,.4f}</div>"
                        f"<div style='color:#6b7280;font-size:10px'>${ez_lo:,.4f} – ${ez_hi:,.4f}</div>"
                        "</div>"
                        "<div>"
                        "<div style='color:#ef4444;font-size:10px'>STOP LOSS</div>"
                        f"<div style='color:#ef4444;font-weight:600'>${sl:,.4f}</div>"
                        "</div>"
                        "<div>"
                        f"<div style='color:#22c55e;font-size:10px'>TP1 · R/R {rr1:.1f}×</div>"
                        f"<div style='color:#22c55e;font-weight:600'>${tp1:,.4f}</div>"
                        f"<div style='color:#4ade80;font-size:10px'>TP2 · R/R {rr2:.1f}×</div>"
                        f"<div style='color:#4ade80'>${tp2:,.4f}</div>"
                        "</div>"
                        "</div>"
                    )
                    if setup.get("position_note"):
                        note_html = (
                            "<div style='font-size:11px;color:#6b7280;margin-top:2px'>"
                            + "📝 " + str(setup["position_note"])[:180]
                            + "</div>"
                        )

                ts_label = _utc_to_local(row.get("timestamp", ""), fmt="%H:%M") if row.get("timestamp") else ""
                header_right = label + (
                    f"&nbsp;<span style='font-size:11px;color:#9ca3af'>{timing_badge}</span>"
                    if timing_badge else ""
                )
                st.markdown(
                    "<div class='action-card " + css + "'>"
                    "<div style='display:flex;justify-content:space-between;align-items:center'>"
                    "<span style='font-size:18px;font-weight:700;color:#f9fafb'>"
                    + row["symbol"] + gex_badge + vp_badge +
                    "</span>"
                    "<span style='font-size:13px;font-weight:600'>" + header_right + "</span>"
                    "</div>"
                    "<div style='display:flex;gap:14px;margin:5px 0;font-size:13px;color:#d1d5db'>"
                    f"<span>Score: <b>{row['score']}</b></span>"
                    f"<span>Confianza: <b>{row['confidence']}%</b></span>"
                    f"<span style='color:{trend_color}'>Tendencia: {row['trend_bias']}</span>"
                    f"<span style='color:#6b7280;font-size:11px'>{ts_label}</span>"
                    "</div>"
                    f"<div style='font-size:11px;color:#6b7280;margin-bottom:4px'>{subscores}</div>"
                    f"<div style='font-size:12px;color:#9ca3af;margin-bottom:4px'>{row['entry_context']}</div>"
                    "<div style='font-size:12px;color:#9ca3af'>"
                    f"Precio: <b style='color:#f9fafb'>${row['price']:.4f}</b>"
                    f"&nbsp;|&nbsp; 1h: <b>{row['return_1h']:+.2f}%</b>"
                    f"&nbsp;|&nbsp; 15m: <b>{row['return_15m']:+.2f}%</b>"
                    f"&nbsp;|&nbsp; VWAP Δ: <b>{row['vwap_distance_pct']:+.2f}%</b>"
                    "</div>"
                    + levels_html +
                    "<ul style='margin:4px 0 0 0;padding-left:16px'>" + reasons_html + "</ul>"
                    + warnings_html + note_html +
                    "<details style='margin-top:6px'>"
                    "<summary style='font-size:11px;color:#6b7280;cursor:pointer'>"
                    "Condiciones de invalidación"
                    "</summary>"
                    "<ul style='padding-left:16px;margin:4px 0 0 0'>" + inv_items + "</ul>"
                    "</details>"
                    "</div>",
                    unsafe_allow_html=True,
                )


# ── Sección 2: Ranking completo ───────────────────────────────────────────
st.markdown("### 📊 Ranking de confluencia")

if display_rows:
    df = pd.DataFrame([
        {
            "Símbolo":   r["symbol"],
            "Score":     r["score"],
            "Flow":      r["flow_score"],
            "Técnico":   r["technical_score"],
            "VP":        r["volume_profile_score"],
            "Footprint": r["footprint_score"],
            "Futuros":   r["futures_score"],
            "GEX":       r["gex_score"],
            "Penaliz.":  r["risk_penalty"],
            "Acción":    r["action"],
            "Señal":     r["signal"],
            "Conf %":    r["confidence"],
            "Ret 1h%":   round(r["return_1h"], 2),
            "CVD 1h":    round(r["cvd"], 0),
            "CVD 15m":   round(r["cvd_15m"], 0),
            "Tendencia": r["trend_bias"],
            "Funding":   round(r["funding"], 6),
            "OI":        round(r["open_interest"], 0),
            "OI Δ%":     round(r.get("oi_change_pct", 0.0), 2),
            "Riesgo":    r["risk_level"],
            "Timestamp": _utc_to_local(r.get("timestamp", ""), fmt="%H:%M"),
        }
        for r in display_rows
    ])

    def _color_action(val: str) -> str:
        return {
            "LONG_FUTURES":  "background-color:#052e16;color:#86efac",
            "SHORT_FUTURES": "background-color:#450a0a;color:#fca5a5",
            "BUY_SPOT":      "background-color:#022c22;color:#6ee7b7",
            "SELL_SPOT":     "background-color:#431407;color:#fdba74",
            "WAIT":          "background-color:#111827;color:#9ca3af",
        }.get(val, "")

    styled = (
        df.style
        .map(_color_action, subset=["Acción"])
        .format({
            "Score": "{:.0f}", "Flow": "{:.0f}", "Técnico": "{:.0f}",
            "VP": "{:.0f}", "Footprint": "{:.0f}", "Futuros": "{:.0f}",
            "GEX": "{:.0f}", "Penaliz.": "{:.0f}",
            "Conf %": "{:.0f}", "Ret 1h%": "{:+.2f}",
            "CVD 1h": "{:,.0f}", "CVD 15m": "{:,.0f}",
            "Funding": "{:.6f}", "OI": "{:,.0f}", "OI Δ%": "{:+.2f}",
        })
    )
    st.dataframe(styled, use_container_width=True, height=520)


# ── Sección 3: Near-miss ──────────────────────────────────────────────────
st.markdown("### 🔍 En monitoreo — cerca del umbral")

if not near_miss_rows:
    st.caption("No hay símbolos cerca del umbral de alerta en este ciclo.")
else:
    st.write(
        f"**{len(near_miss_rows)}** símbolos con señal activa pero score < umbral de acción."
    )
    for row in near_miss_rows:
        trend_color = (
            "#10b981" if row["trend_bias"] == "bullish"
            else "#ef4444" if row["trend_bias"] == "bearish"
            else "#6b7280"
        )
        reasons_str = " · ".join(row["reasons"][:3]) if row["reasons"] else "—"
        warnings_str = " · ".join(row["warnings"][:2]) if row["warnings"] else ""
        w_html = (
            "<br><span style='color:#fbbf24'>⚠ " + warnings_str + "</span>"
            if warnings_str else ""
        )
        st.markdown(
            "<div class='near-miss-card'>"
            f"<b style='color:#e5e7eb'>{row['symbol']}</b>"
            f"&nbsp;·&nbsp; Score: <b>{row['score']}</b>/100"
            f"&nbsp;·&nbsp; Señal: {row['signal']}"
            f"&nbsp;·&nbsp; <span style='color:{trend_color}'>{row['trend_bias']}</span>"
            f"&nbsp;·&nbsp; 1h: {row['return_1h']:+.2f}%"
            f"&nbsp;·&nbsp; VWAP Δ: {row['vwap_distance_pct']:+.2f}%"
            f"&nbsp;·&nbsp; VP: {row['vp_nearest']}"
            f"<br><span style='color:#9ca3af'>{reasons_str}</span>"
            + w_html +
            "</div>",
            unsafe_allow_html=True,
        )


# ── Sección 4: Gráficos ───────────────────────────────────────────────────
if display_rows:
    df_c = pd.DataFrame(display_rows)
    st.markdown("### 📈 Métricas de mercado")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Score de confluencia** — puntuación compuesta 0–100.")
        fig = px.bar(
            df_c.sort_values("score", ascending=False),
            x="symbol", y="score", title="Score de confluencia",
            color="score", color_continuous_scale=["#ef4444", "#f59e0b", "#10b981"],
        )
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.markdown("**Open Interest** — posiciones abiertas en futuros.")
        fig = px.bar(
            df_c.sort_values("open_interest", ascending=False),
            x="symbol", y="open_interest", title="Open Interest",
            color="open_interest",
        )
        st.plotly_chart(fig, use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown("**Funding Rate** — positivo = presión long, negativo = presión short.")
        fig = px.bar(
            df_c.sort_values("funding", ascending=False),
            x="symbol", y="funding", title="Funding Rate",
            color="funding", color_continuous_scale=["#ef4444", "#6b7280", "#10b981"],
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_d:
        st.markdown("**CVD 1h / 15m** — flujo acumulado y aceleración reciente.")
        fig = px.bar(
            df_c.sort_values("cvd", ascending=False),
            x="symbol", y=["cvd", "cvd_15m"],
            title="CVD 1h vs CVD 15m", barmode="group",
            color_discrete_map={"cvd": "#6b7280", "cvd_15m": "#10b981"},
            labels={"value": "CVD", "variable": "Ventana"},
        )
        st.plotly_chart(fig, use_container_width=True)

    col_e, col_f = st.columns(2)
    with col_e:
        st.markdown("**Retorno 1h** — variación de precio en la última hora.")
        fig = px.bar(
            df_c.sort_values("return_1h", ascending=False),
            x="symbol", y="return_1h", title="Retorno 1h (%)",
            color="return_1h", color_continuous_scale=["#ef4444", "#6b7280", "#10b981"],
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_f:
        st.markdown("**Imbalance** — diferencia de volumen bids vs asks.")
        fig = px.bar(
            df_c.sort_values("imbalance", ascending=False),
            x="symbol", y="imbalance", title="Order Book Imbalance",
            color="imbalance", color_continuous_scale=["#ef4444", "#6b7280", "#10b981"],
        )
        st.plotly_chart(fig, use_container_width=True)

    signal_counts = df_c["signal"].value_counts().reset_index()
    signal_counts.columns = ["signal", "count"]
    fig = px.bar(
        signal_counts, x="signal", y="count",
        title="Distribución de señales institucionales",
        color="signal",
        color_discrete_map={
            "neutral": "#6b7280", "accumulation": "#10b981",
            "bullish_continuation": "#16a34a", "distribution": "#ef4444",
            "long_squeeze": "#dc2626", "short_squeeze": "#22c55e",
        },
    )
    fig.update_layout(xaxis_title="Señal", yaxis_title="Cantidad")
    st.plotly_chart(fig, use_container_width=True)


# ── Sección 5: Detalle compacto por token ────────────────────────────────
st.markdown("### 🧩 Detalle compacto por token")

if display_rows:
    for i in range(0, len(display_rows), 3):
        cols = st.columns(3)
        for idx, row in enumerate(display_rows[i: i + 3]):
            with cols[idx]:
                action = row["action"]
                css = _ACTION_CSS.get(action, "action-wait")
                trend_color = (
                    "#10b981" if row["trend_bias"] == "bullish"
                    else "#ef4444" if row["trend_bias"] == "bearish"
                    else "#6b7280"
                )
                gex_line = (
                    "<div class='val'><span class='lbl'>GEX:</span> ✓ disponible</div>"
                    if row["gex_available"] else ""
                )
                above_vwap_mark = "✓" if row["above_vwap"] else "✗"
                st.markdown(
                    "<div class='token-card " + css + "'>"
                    f"<h4>{row['symbol']}</h4>"
                    f"<div class='val'><span class='lbl'>Acción:</span> {_ACTION_LABELS.get(action, action)}</div>"
                    f"<div class='val'><span class='lbl'>Score:</span> <b>{row['score']}</b> · Confianza: {row['confidence']}%</div>"
                    "<div class='val' style='font-size:11px;color:#6b7280'>"
                    f"Flow {row['flow_score']}/30 · Téc {row['technical_score']}/25 · "
                    f"VP {row['volume_profile_score']}/15 · FP {row['footprint_score']}/15 · "
                    f"Fut {row['futures_score']}/15 · GEX {row['gex_score']}/5 · Pen -{row['risk_penalty']}"
                    "</div>"
                    f"<div class='val'><span class='lbl'>Señal:</span> {row['signal']}</div>"
                    f"<div class='val'><span class='lbl'>Tendencia:</span> <span style='color:{trend_color}'>{row['trend_bias']}</span></div>"
                    f"<div class='val'><span class='lbl'>Precio:</span> ${row['price']:.4f}</div>"
                    f"<div class='val'><span class='lbl'>Ret 1h:</span> {row['return_1h']:+.2f}% &nbsp; 15m: {row['return_15m']:+.2f}%</div>"
                    f"<div class='val'><span class='lbl'>VWAP Δ:</span> {row['vwap_distance_pct']:+.2f}% · sobre VWAP: {above_vwap_mark}</div>"
                    f"<div class='val'><span class='lbl'>CVD:</span> {row['cvd']:.2f} · Delta: {row['delta']:.2f}</div>"
                    f"<div class='val'><span class='lbl'>Funding:</span> {row['funding']:.6f}</div>"
                    f"<div class='val'><span class='lbl'>OI:</span> {row['open_interest']:,.0f}</div>"
                    f"<div class='val'><span class='lbl'>Imbalance:</span> {row['imbalance']:.4f}</div>"
                    f"<div class='val'><span class='lbl'>VP nivel:</span> {row['vp_nearest']} ({row['vp_distance']:.2f}%)</div>"
                    f"<div class='val'><span class='lbl'>Vol rel:</span> {row['relative_volume']:.2f}× · Riesgo: {row['risk_level']}</div>"
                    + gex_line +
                    "</div>",
                    unsafe_allow_html=True,
                )


# ── Sección 6: Alertas activas ────────────────────────────────────────────
st.markdown("### 🚨 Alertas activas")

if not alert_rows:
    st.success("No hay alertas activas. El mercado muestra condiciones normales.")
else:
    st.write(f"**{len(alert_rows)}** símbolos con condiciones de riesgo o squeeze.")
    for alert in sorted(alert_rows, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["risk_level"]]):
        rl = alert["risk_level"]
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(rl, "⚪")
        squeeze_txt = ""
        if alert["squeeze_confirmation"] == "strong":
            squeeze_txt = " · 💥 Squeeze: " + alert["squeeze_message"]
        reasons_txt = " · ".join(alert["risk_reasons"]) or "Sin razones específicas"
        st.markdown(
            "<div class='alert-" + rl + "'>"
            f"<strong>{emoji} {alert['symbol']}</strong>"
            f" — Riesgo: {rl.upper()} · Señal: {alert['signal']}<br>"
            f"<span style='font-size:13px'>{reasons_txt}{squeeze_txt}</span><br>"
            f"<span style='font-size:12px;color:#9ca3af'>"
            f"Estrés: {alert['stress_level']} (score: {alert['stress_score']})"
            "</span>"
            "</div>",
            unsafe_allow_html=True,
        )


# ── Sección 7: Histórico y evaluación ────────────────────────────────────
if ENABLE_DATABASE:
    st.markdown("### 📚 Histórico y evaluación")

    _db_cols = st.columns(3)
    _snap_count = _cached_snapshot_count()
    _recent_alerts = _cached_recent_alerts(limit=50)
    _wr_data = _cached_win_rate()

    _db_cols[0].metric("Snapshots guardados", f"{_snap_count:,}")
    _db_cols[1].metric("Alertas registradas", len(_recent_alerts))
    _open = sum(1 for a in _recent_alerts if a.get("status") == "open")
    _db_cols[2].metric("Alertas abiertas", _open)

    if _wr_data:
        st.markdown("**Win rate por tipo de acción** *(horizonte 1h)*")
        _sym_data = _cached_symbols_by_action()
        _ch_data  = _cached_channel_stats()

        # Agrupar símbolos top-5 por acción
        _sym_by_action: Dict[str, List[str]] = {}
        for s in _sym_data:
            act = s.get("action", "")
            if act not in _sym_by_action:
                _sym_by_action[act] = []
            if len(_sym_by_action[act]) < 5:
                _sym_by_action[act].append(s["symbol"])

        # Agrupar canales por acción
        _ch_by_action: Dict[str, List[str]] = {}
        for c in _ch_data:
            act = c.get("action", "")
            if act not in _ch_by_action:
                _ch_by_action[act] = []
            ok = c.get("ok", 0)
            if ok > 0:
                _ch_by_action[act].append(f"{c['channel']} ({ok})")

        _wr_rows = []
        for wr in _wr_data:
            total = wr.get("total") or 0
            wins  = wr.get("wins") or 0
            act   = wr.get("action", "")
            _wr_rows.append({
                "Acción":          act,
                "Total":           total,
                "Ganadoras":       wins,
                "Win rate %":      round(wins / total * 100, 1) if total else 0.0,
                "Score prom.":     round(wr.get("avg_score") or 0.0, 1),
                "Retorno % prom.": round(wr.get("avg_return_pct") or 0.0, 2),
                "Top símbolos":    ", ".join(_sym_by_action.get(act, [])) or "—",
                "Canales":         ", ".join(_ch_by_action.get(act, [])) or "—",
            })
        st.dataframe(pd.DataFrame(_wr_rows), use_container_width=True, hide_index=True)

        # Desglose por símbolo
        if _sym_data:
            with st.expander("📊 Desglose por símbolo"):
                _sym_rows = []
                for s in _sym_data:
                    total_s = s.get("total") or 0
                    wins_s  = s.get("wins") or 0
                    _sym_rows.append({
                        "Acción":      s.get("action", ""),
                        "Símbolo":     s.get("symbol", ""),
                        "Alertas":     total_s,
                        "Ganadoras":   wins_s,
                        "Win rate %":  round(wins_s / total_s * 100, 1) if total_s else 0.0,
                        "Score prom.": round(s.get("avg_score") or 0.0, 1),
                        "Retorno %":   round(s.get("avg_return_pct") or 0.0, 2),
                    })
                st.dataframe(pd.DataFrame(_sym_rows), use_container_width=True, hide_index=True)

        # Estadísticas de canales
        if _ch_data:
            with st.expander("📡 Notificaciones por canal"):
                _ch_rows = []
                for c in _ch_data:
                    _ch_rows.append({
                        "Acción":   c.get("action", ""),
                        "Canal":    c.get("channel", ""),
                        "Enviadas": c.get("total_sent", 0),
                        "OK":       c.get("ok", 0),
                        "Fallidas": c.get("failed", 0),
                    })
                st.dataframe(pd.DataFrame(_ch_rows), use_container_width=True, hide_index=True)

    if _recent_alerts:
        st.markdown("**Últimas alertas registradas**")
        _alert_df_rows = []
        for a in _recent_alerts[:20]:
            _alert_df_rows.append({
                "Timestamp":  _utc_to_local(a.get("timestamp", "")),
                "Símbolo":    a.get("symbol", ""),
                "Acción":     a.get("action", ""),
                "Conf %":     a.get("confidence", 0),
                "Score":      a.get("score", 0),
                "Entrada":    round(a.get("entry") or 0.0, 4),
                "SL":         round(a.get("stop_loss") or 0.0, 4),
                "TP1":        round(a.get("take_profit_1") or 0.0, 4),
                "Status":     a.get("status", "open"),
                "Outcome 1h": a.get("outcome") or "—",
                "Retorno %":  round(a.get("future_return_pct") or 0.0, 2),
                "Canales":    a.get("channels") or "—",
            })
        st.dataframe(pd.DataFrame(_alert_df_rows), use_container_width=True, hide_index=True)

    st.markdown("**Exportar dataset para ML**")
    if st.button("⬇️ Exportar ml_dataset.csv"):
        try:
            from app.ml_dataset import export_training_dataset
            _n = export_training_dataset("data/ml_dataset.csv")
            if _n > 0:
                st.success(f"Dataset exportado: {_n:,} filas → data/ml_dataset.csv")
            else:
                st.warning("No hay suficientes datos históricos para exportar aún.")
        except Exception as _ml_exc:
            st.error(f"Error al exportar: {_ml_exc}")

st.markdown("---")
st.caption(
    f"Dashboard actualizado cada 15 s · Símbolos display: {_top_n} · "
    "Scoring: flow(30)+técnico(25)+VP(15)+footprint(15)+futuros(15)+GEX(5)−penalización(≤30)"
)
