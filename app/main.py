import datetime
import html
import json
import logging
import os
import sys
import time as _time
import warnings
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")

warnings.filterwarnings("ignore", category=FutureWarning, module="plotly")
warnings.filterwarnings("ignore", category=FutureWarning, module="pandas")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Any, Dict, List, Optional

from app.log_setup import setup_logging
setup_logging()
logger = logging.getLogger("dashboard")

from streamlit_autorefresh import st_autorefresh

from app.config import (
    SCANNER_CANDIDATE_LIMIT,
    SCANNER_RESULT_LIMIT,
    ENABLE_DATABASE,
    NEAR_MISS_THRESHOLD,
    MULTI_STRATEGY_ENABLED,
    MICRO_SCALP_TRADE_SIZE_USDT,
    ACCUMULATION_WATCH_ENABLED,
)
from app import database
from app.auto_trader import calc_pnl as _calc_pnl_auto
from app.strategies import engine as _strategy_engine
from app.strategies.value_area_core import METHOD_DESCRIPTIONS as _METHOD_DESCRIPTIONS_MAIN


def _utc_to_local(ts_utc: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Convierte un timestamp UTC ISO (sin zona) a hora local del sistema."""
    if not ts_utc:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(ts_utc).replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(tz=None).strftime(fmt)
    except Exception:
        return ts_utc


def _color_dir(val: str) -> str:
    return {
        "LONG":  "background-color:#052e16;color:#86efac",
        "SHORT": "background-color:#450a0a;color:#fca5a5",
    }.get(val, "")


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

@st.cache_data(ttl=30)
def _cached_strategy_positions(limit: int = 50):
    return database.get_recent_strategy_positions(limit=limit)

@st.cache_data(ttl=30)
def _cached_strategy_symbol_states():
    return database.get_strategy_symbol_states()

@st.cache_data(ttl=30)
def _cached_symbol_price_history(symbol: str, since_iso: str):
    return database.get_symbol_price_history(symbol, since_iso)

@st.cache_data(ttl=30)
def _cached_symbol_price_history_with_cvd(symbol: str, since_iso: str):
    return database.get_symbol_price_history(symbol, since_iso, include_cvd_15m=True)

@st.cache_data(ttl=60)
def _cached_accumulation_watch_list(limit: int = 50):
    return database.get_accumulation_watch_list(limit=limit)

@st.cache_data(ttl=120)
def _cached_latest_news_predictions(symbols: tuple):
    return database.get_latest_news_predictions(list(symbols))

@st.cache_data(ttl=15)
def _cached_open_auto_positions():
    return database.get_open_auto_positions()

@st.cache_data(ttl=15)
def _cached_open_micro_scalp_alerts():
    return database.get_open_micro_scalp_alerts()

@st.cache_data(ttl=15)
def _cached_open_strategy_positions():
    return database.get_open_strategy_positions()

@st.cache_data(ttl=15)
def _cached_latest_price(symbol: str):
    return database.get_latest_symbol_price(symbol)


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
            "return_5m":            s.get("return_5m", 0.0),
            "return_3m":            s.get("return_3m", 0.0),
            "structure":            json.loads(s.get("structure_json") or "{}"),
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
    "⚡ Micro-scalping (USDT)",
    f"{_pm.get('pnl_usdt', 0.0):+.2f}$",
    f"WR {_pm.get('winrate_pct', 0.0):.1f}% · {_pm.get('closed', 0)} cerradas / {_pm.get('open', 0)} abiertas · {_pm.get('pnl_pct_total', 0.0):+.2f}% acum",
    delta_color="off",
)
st.caption("PnL realizado acumulado (histórico, paper) · 25 USDT/trade micro · Futures/Spot en USDT")


# ── Órdenes activas (unificado: futuros/spot, micro-scalp, framework) ─────
st.markdown("### 📋 Órdenes activas")

if ENABLE_DATABASE:
    _active_rows: List[Dict[str, Any]] = []

    for _p in _cached_open_auto_positions():
        _price = _cached_latest_price(_p["symbol"]) or _p["entry_price"]
        _pnl = _calc_pnl_auto(_p, _price)
        _direction = "LONG" if _p["action"] in ("LONG_FUTURES", "BUY_SPOT") else "SHORT"
        _mercado = "Futuros" if "FUTURES" in _p["action"] else "Spot"
        _active_rows.append({
            "Estrategia":  f"{_mercado} (pipeline principal)",
            "Símbolo":     _p["symbol"],
            "Dirección":   _direction,
            "Entrada":     _p["entry_price"],
            "SL":          _p.get("sl_current") or _p.get("sl"),
            "TP1":         _p.get("tp1"),
            "TP2":         _p.get("tp2"),
            "PnL abierto": _pnl["total_pnl_usdt"],
            "PnL %":       _pnl["total_pnl_pct"],
            "Apalanc.":    f"{_p.get('leverage') or 1}x",
            "Abierta":     _utc_to_local(_p.get("open_time", ""), fmt="%m-%d %H:%M"),
        })

    for _m in _cached_open_micro_scalp_alerts():
        _price = _cached_latest_price(_m["symbol"]) or _m["entry"]
        _sign = 1 if _m["action"] == "MICRO_LONG_SCALP" else -1
        _pnl_pct = _sign * (_price - _m["entry"]) / _m["entry"] * 100 if _m["entry"] else 0.0
        _trade_size = _m.get("trade_size_usdt") or MICRO_SCALP_TRADE_SIZE_USDT
        _active_rows.append({
            "Estrategia":  f"Micro-scalping ({_m.get('method') or 'momentum'})",
            "Símbolo":     _m["symbol"],
            "Dirección":   "LONG" if _sign == 1 else "SHORT",
            "Entrada":     _m["entry"],
            "SL":          _m.get("stop_loss"),
            "TP1":         _m.get("take_profit_1"),
            "TP2":         _m.get("take_profit_2"),
            "PnL abierto": round(_pnl_pct / 100 * _trade_size, 4),
            "PnL %":       round(_pnl_pct, 2),
            "Apalanc.":    "1x",
            "Abierta":     _utc_to_local(_m.get("timestamp", ""), fmt="%m-%d %H:%M"),
        })

    for _s in _cached_open_strategy_positions():
        _price = _cached_latest_price(_s["symbol"]) or _s["entry_price"]
        _pnl = _strategy_engine.calc_pnl(_s, _price)
        _active_rows.append({
            "Estrategia":  _s["strategy_id"],
            "Símbolo":     _s["symbol"],
            "Dirección":   _s["direction"],
            "Entrada":     _s["entry_price"],
            "SL":          _s.get("sl_current") or _s.get("sl"),
            "TP1":         _s.get("tp1"),
            "TP2":         _s.get("tp2"),
            "PnL abierto": _pnl["total_pnl_usdt"],
            "PnL %":       _pnl["total_pnl_pct"],
            "Apalanc.":    f"{_s.get('leverage') or 1}x",
            "Abierta":     _utc_to_local(_s.get("open_time", ""), fmt="%m-%d %H:%M"),
        })

    if _active_rows:
        _df_active = pd.DataFrame(_active_rows)
        st.dataframe(
            _df_active.style
            .map(_color_dir, subset=["Dirección"])
            .format({
                "Entrada": "{:.6g}", "SL": "{:.6g}", "TP1": "{:.6g}", "TP2": "{:.6g}",
                "PnL abierto": "{:+.2f}", "PnL %": "{:+.2f}",
            }, na_rep="—"),
            use_container_width=True,
            height=min(420, 60 + 35 * len(_df_active)),
        )
        st.caption(
            f"{len(_active_rows)} posiciones abiertas en total — pipeline principal, "
            "micro-scalping y framework multi-estrategia. PnL abierto estimado con el "
            "último precio guardado (market_snapshots), no en tiempo real."
        )
    else:
        st.info("No hay órdenes activas en ningún módulo (futuros, spot, micro-scalping o multi-estrategia).")


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


# ── Sección: Setups de estructura (3m) ─────────────────────────────────────
st.markdown("### 📐 Setups de estructura (3m)")
st.caption(
    "Breakouts de nivel y patrones chartistas (H-C-H, dobles techos/pisos) "
    "confirmados en velas de 3 minutos, con confirmación de flujo: "
    "Δ delta · CVD 15m · OB orderbook · RVOL volumen relativo."
)

_PATTERN_LABELS = {
    "head_and_shoulders":         "H-C-H",
    "inverse_head_and_shoulders": "H-C-H invertido",
    "double_top":                 "Doble techo",
    "double_bottom":              "Doble piso",
}


def _flow_checks(row: Dict[str, Any], direction: str) -> Dict[str, bool]:
    """4 checks direccionales de órdenes/volumen sobre columnas ya persistidas."""
    sign = 1 if direction == "LONG" else -1
    return {
        "Δ":    sign * float(row.get("delta", 0.0) or 0.0) > 0,
        "CVD":  sign * float(row.get("cvd_15m", 0.0) or 0.0) > 0,
        "OB":   sign * float(row.get("imbalance", 0.0) or 0.0) >= 0.08,
        "RVOL": float(row.get("relative_volume", 1.0) or 1.0) >= 1.5,
    }


def _mk(v: bool) -> str:
    return "✓" if v else "✗"


_setups: List[Dict[str, Any]] = []
_bouncing: List[Dict[str, Any]] = []
_forming: List[Dict[str, Any]] = []
for r in all_rows:
    _struct = r.get("structure") or {}
    if not _struct:
        continue
    _brk = _struct.get("breakout") or {}
    _pats = _struct.get("patterns") or []

    if _brk.get("confirmed"):
        _dir = "LONG" if _brk.get("direction") == "up" else "SHORT"
        _chk = _flow_checks(r, _dir)
        _setups.append({
            "Símbolo":   r["symbol"],
            "Señal":     "Breakout ↑" if _dir == "LONG" else "Breakout ↓",
            "Dirección": _dir,
            "Nivel":     _brk.get("level", 0.0),
            "Dist %":    _brk.get("margin_pct", 0.0),
            "Toques":    _brk.get("touches", 0),
            "RVOL":      round(float(r.get("relative_volume", 1.0) or 1.0), 1),
            "Δ":         _mk(_chk["Δ"]),
            "CVD":       _mk(_chk["CVD"]),
            "OB":        _mk(_chk["OB"]),
            "Flujo":     f"{sum(_chk.values())}/4",
            "Score":     r["score"],
            "Hora":      _utc_to_local(r.get("timestamp", ""), fmt="%H:%M"),
            "_n":        sum(_chk.values()),
        })
    for _p in _pats:
        _label = _PATTERN_LABELS.get(_p.get("pattern", ""), _p.get("pattern", "?"))
        _dir = "LONG" if _p.get("direction") == "long" else "SHORT"
        if _p.get("confirmed"):
            _chk = _flow_checks(r, _dir)
            _setups.append({
                "Símbolo":   r["symbol"],
                "Señal":     f"{_label} roto",
                "Dirección": _dir,
                "Nivel":     _p.get("neckline", 0.0),
                "Dist %":    _p.get("distance_to_neckline_pct", 0.0),
                "Toques":    "—",
                "RVOL":      round(float(r.get("relative_volume", 1.0) or 1.0), 1),
                "Δ":         _mk(_chk["Δ"]),
                "CVD":       _mk(_chk["CVD"]),
                "OB":        _mk(_chk["OB"]),
                "Flujo":     f"{sum(_chk.values())}/4",
                "Score":     r["score"],
                "Hora":      _utc_to_local(r.get("timestamp", ""), fmt="%H:%M"),
                "_n":        sum(_chk.values()),
            })
        elif _p.get("bounce_valid"):
            _chk = _flow_checks(r, _dir)
            _bouncing.append({
                "Símbolo":   r["symbol"],
                "Patrón":    f"{_label} (2a pata)",
                "Dirección": _dir,
                "Progreso %": _p.get("bounce_progress_pct", 0.0),
                "Velas desde extremo": _p.get("bounce_age_candles", 0),
                "Neckline":  _p.get("neckline", 0.0),
                "Δ":         _mk(_chk["Δ"]),
                "CVD":       _mk(_chk["CVD"]),
                "OB":        _mk(_chk["OB"]),
                "Flujo":     f"{sum(_chk.values())}/4",
                "Score":     r["score"],
                "Hora":      _utc_to_local(r.get("timestamp", ""), fmt="%H:%M"),
                "_n":        sum(_chk.values()),
            })
        else:
            _forming.append({
                "Símbolo":   r["symbol"],
                "Patrón":    _label,
                "Dirección": _dir,
                "Neckline":  _p.get("neckline", 0.0),
                "Dist. a neckline %": _p.get("distance_to_neckline_pct", 0.0),
                "Target":    _p.get("target", 0.0),
                "Score":     r["score"],
            })

if _setups:
    _setups.sort(key=lambda x: (-x["_n"], -x["Score"]))
    _df_setups = pd.DataFrame(_setups).drop(columns=["_n"])

    st.dataframe(
        _df_setups.style
        .map(_color_dir, subset=["Dirección"])
        .format({"Nivel": "{:.6g}", "Dist %": "{:+.2f}", "RVOL": "{:.1f}", "Score": "{:.0f}"}),
        use_container_width=True,
        height=min(420, 60 + 35 * len(_df_setups)),
    )
else:
    st.info(
        "Sin setups de estructura confirmados en este momento. "
        "Si esta sección nunca muestra datos, el scanner necesita reiniciarse "
        "para empezar a persistir la estructura 3m (columna structure_json)."
    )

if _bouncing:
    st.markdown("**Rebote en 2a pata (pre-ruptura)** — entrada temprana antes de la neckline")
    _bouncing.sort(key=lambda x: (-x["_n"], -x["Score"]))
    _df_bouncing = pd.DataFrame(_bouncing).drop(columns=["_n"])
    st.dataframe(
        _df_bouncing.style
        .map(_color_dir, subset=["Dirección"])
        .format({"Progreso %": "{:.0f}", "Neckline": "{:.6g}", "Score": "{:.0f}"}),
        use_container_width=True,
        height=min(320, 60 + 35 * len(_df_bouncing)),
    )

if _forming:
    with st.expander(f"⏳ Patrones en formación ({len(_forming)}) — neckline aún sin romper"):
        _df_forming = pd.DataFrame(_forming)
        st.dataframe(
            _df_forming.style.format({
                "Neckline": "{:.6g}", "Dist. a neckline %": "{:+.2f}",
                "Target": "{:.6g}", "Score": "{:.0f}",
            }),
            use_container_width=True,
            height=min(320, 60 + 35 * len(_df_forming)),
        )


# ── Sección: Accumulation Watch (watchlist de acumulación profunda) ──────
if ENABLE_DATABASE and ACCUMULATION_WATCH_ENABLED:
    st.markdown("### 🌱 Accumulation Watch — watchlist de acumulación profunda")
    st.caption(
        "Tokens en fase de coiling/acumulación fuera del top de volumen, con "
        "distancia al mínimo histórico real (ATL), tiempo en zona, contexto de "
        "noticias (informativo, no descarta candidatos) y confirmación de "
        "ignición por estructura + CVD + order flow. Solo watchlist — no "
        "genera alertas de trading ni posiciones."
    )

    _watch_rows = _cached_accumulation_watch_list(limit=50)
    if not _watch_rows:
        st.info("Sin símbolos activos en la watchlist de acumulación.")
    else:
        _watch_symbols = [w["symbol"] for w in _watch_rows]
        _news_map = _cached_latest_news_predictions(tuple(sorted(_watch_symbols)))

        _watch_table = []
        for w in _watch_rows:
            _news = _news_map.get(w["symbol"], {})
            _dist_atl = w.get("dist_to_atl_pct")
            _sentiment = _news.get("sentiment_score")
            _watch_table.append({
                "Símbolo":        w["symbol"],
                "Canal":          w.get("channel") or "coiling",
                "Score":          float(w.get("channel_score") or 0.0),
                # Preformateadas a texto (no numéricas + na_rep): st.dataframe
                # no respeta Styler.format(na_rep=...) para nulos, los muestra
                # como "None" — mismo patrón que Noticias/Razón ignición abajo.
                "Dist. ATL %":    f"{float(_dist_atl):+.1f}" if _dist_atl is not None else "—",
                "Días en zona":   w.get("days_in_atl_zone"),
                "Noticias":       _news.get("prediction", "—"),
                "Sentimiento":    f"{float(_sentiment):+.1f}" if _sentiment is not None else "—",
                "Estado":         w.get("status") or "watching",
                "Razón ignición": w.get("ignition_reason") or "—",
                "Desde":          _utc_to_local(w.get("first_seen", ""), fmt="%d/%m %H:%M"),
            })
        _df_watch = pd.DataFrame(_watch_table)
        st.dataframe(
            _df_watch.style
            .map(lambda v: "background-color:#052e16;color:#86efac" if v == "ignited" else "", subset=["Estado"])
            .format({"Score": "{:.1f}"}),
            use_container_width=True,
            height=min(420, 60 + 35 * len(_df_watch)),
        )

        _sel_watch_symbol = st.selectbox("Símbolo", _watch_symbols, key="accum_watch_chart_symbol")
        _sel_watch_row = next(w for w in _watch_rows if w["symbol"] == _sel_watch_symbol)

        _since_iso = _sel_watch_row.get("first_seen") or ""
        _hist_w = _cached_symbol_price_history_with_cvd(_sel_watch_symbol, _since_iso) if _since_iso else []

        if not _hist_w:
            st.info("Sin historial de precio guardado todavía para este símbolo.")
        else:
            _hw_x: List[Any] = []
            for _h in _hist_w:
                try:
                    _hw_x.append(datetime.datetime.fromisoformat(_h["timestamp"]))
                except Exception:
                    _hw_x.append(None)

            # Corte de huecos >30min (mismo criterio que el panel Value Area+CVD
            # más arriba) — sin esto Plotly conecta con una diagonal falsa un
            # tramo donde el símbolo salió temporalmente de los candidatos.
            _GAP_MIN = 30.0
            _wx: List[Any] = []
            _wy_price: List[Optional[float]] = []
            _wy_cvd: List[Optional[float]] = []
            _wprev: Optional[datetime.datetime] = None
            for _x, _h in zip(_hw_x, _hist_w):
                if _x is not None and _wprev is not None:
                    _gap_min = (_x - _wprev).total_seconds() / 60.0
                    if _gap_min > _GAP_MIN:
                        _wx.append(_wprev + (_x - _wprev) / 2)
                        _wy_price.append(None)
                        _wy_cvd.append(None)
                _wx.append(_x)
                _wy_price.append(_h.get("price"))
                _wy_cvd.append(_h.get("cvd_15m"))
                if _x is not None:
                    _wprev = _x

            fig_watch = go.Figure()
            fig_watch.add_trace(go.Scatter(
                x=_wx, y=_wy_price, mode="lines",
                line=dict(color="#e5e7eb", width=1.5), name="Precio (futuros)",
                connectgaps=False,
            ))
            fig_watch.add_trace(go.Scatter(
                x=_wx, y=_wy_cvd, mode="lines",
                line=dict(color="#22c55e", width=1.5, dash="dot"),
                name="CVD 15m", yaxis="y2", connectgaps=False,
            ))
            _atl_price = _sel_watch_row.get("atl_price")
            if _atl_price:
                fig_watch.add_hline(
                    y=_atl_price, line=dict(color="#ef4444", width=1, dash="dot"),
                    annotation_text=f"ATL ({_sel_watch_row.get('atl_date', '')})",
                    annotation_position="bottom right",
                )
            if _sel_watch_row.get("status") == "ignited" and _sel_watch_row.get("ignited_at"):
                try:
                    _ignited_x = datetime.datetime.fromisoformat(_sel_watch_row["ignited_at"])
                    fig_watch.add_vline(
                        x=_ignited_x, line=dict(color="#facc15", width=1.5),
                        annotation_text="Ignición", annotation_position="top",
                    )
                except Exception:
                    pass
            fig_watch.update_layout(
                title=dict(text=f"{_sel_watch_symbol} — precio + CVD 15m desde entrada a watchlist", y=0.98),
                xaxis_title="Hora UTC", yaxis_title="Precio",
                yaxis2=dict(title="CVD 15m", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", yanchor="top", y=-0.22, x=0.5, xanchor="center"),
                margin=dict(t=70, b=110),
                height=440,
            )
            st.plotly_chart(fig_watch, use_container_width=True)
            st.caption(
                "Línea roja punteada: mínimo histórico real (ATL), calculado sobre el "
                "histórico diario completo del símbolo. Línea amarilla vertical: momento "
                "de ignición (breakout de estructura confirmado con CVD/order flow, o "
                "pico de volumen/funding). Los huecos en las líneas marcan tramos sin "
                "snapshots — el símbolo salió temporalmente de los candidatos del scanner."
            )


# ── Framework multi-estrategia: trades y anticipación de tendencia ───────
if ENABLE_DATABASE and MULTI_STRATEGY_ENABLED:
    st.markdown("### 🧠 Framework multi-estrategia")
    st.caption(
        "Estrategias adicionales, paper trading, independientes del pipeline institucional. "
        "Cada fila indica a qué estrategia (strategy_id) pertenece la operación."
    )

    _strat_positions = _cached_strategy_positions(limit=50)
    if _strat_positions:
        _sp_rows = []
        for p in _strat_positions:
            _sp_rows.append({
                "Estrategia":  p.get("strategy_id", ""),
                "Símbolo":     p.get("symbol", ""),
                "Dirección":   p.get("direction", ""),
                "Estado":      p.get("status", ""),
                "Entrada":     p.get("entry_price", 0.0),
                "Salida":      p.get("exit_price"),
                "SL":          p.get("sl_current") or p.get("sl"),
                "TP1":         p.get("tp1"),
                "TP2":         p.get("tp2"),
                "PnL $":       p.get("total_pnl_usdt"),
                "PnL %":       p.get("total_pnl_pct"),
                "Razón cierre": p.get("close_reason") or "—",
                "Abierta":     _utc_to_local(p.get("open_time", ""), fmt="%m-%d %H:%M"),
            })
        _df_sp = pd.DataFrame(_sp_rows)
        st.dataframe(
            _df_sp.style
            .map(_color_dir, subset=["Dirección"])
            .format({
                "Entrada": "{:.6g}", "Salida": "{:.6g}", "SL": "{:.6g}",
                "TP1": "{:.6g}", "TP2": "{:.6g}",
                "PnL $": "{:+.2f}", "PnL %": "{:+.2f}",
            }, na_rep="—"),
            use_container_width=True,
            height=min(420, 60 + 35 * len(_df_sp)),
        )
    else:
        st.info("Sin operaciones registradas todavía en el framework multi-estrategia.")

    _va_states = [
        s for s in _cached_strategy_symbol_states()
        if s.get("strategy_id", "").startswith("value_area")
    ]
    if _va_states:
        st.markdown("**Value Area + CVD** — anticipación de tendencia, breakout y falso breakout por símbolo")
        st.caption(
            "Zona de valor de la sesión overnight (4:30pm-9:30am NY). El % completado y el tiempo "
            "restante se muestran desde el inicio de la sesión (sin costo); el VAH/VAL/POC recién se "
            "calcula en los últimos 30 min antes de las 9:30am para no pedir datos de mercado toda la noche."
        )
        with st.expander("¿Cómo se forma la zona de valor? (2 métodos corriendo en paralelo)"):
            st.markdown(
                "- **value_area_range**: " + _METHOD_DESCRIPTIONS_MAIN.get("range", "") + "\n"
                "- **value_area_volume70**: " + _METHOD_DESCRIPTIONS_MAIN.get("volume70", "") + "\n\n"
                "Ambas corren en paralelo para comparar cuál rinde mejor. Una vez formada (9:30am NY), "
                "el sesgo direccional se confirma con CVD: precio arriba del VAH + CVD positivo → largos; "
                "precio abajo del VAL + CVD negativo → cortos. Si el precio hace un nuevo extremo de sesión "
                "sin que el CVD lo confirme, se marca una posible reversión (falso breakout) que se "
                "confirma cuando el CVD 'rebota' y el precio vuelve a cruzar el punto medio del value area."
            )
        _va_rows = []
        for s in _va_states:
            _va = json.loads(s.get("value_area_json") or "{}") or {}
            _status = _va.get("status", "")
            _pct = _va.get("pct_complete")
            _has_levels = _va.get("val") is not None
            if _status == "complete":
                _status_label = "🟢 Completa"
            elif _has_levels:
                _status_label = "🟠 Vista previa"
            elif _status == "building":
                _status_label = "🟡 Construyendo (sin datos aún)"
            else:
                _status_label = "—"

            _remaining_txt = "—"
            _session_end = _va.get("session_end")
            if _session_end:
                try:
                    _end_dt = datetime.datetime.fromisoformat(_session_end)
                    _now_ny = datetime.datetime.now(_NY_TZ)
                    _delta_s = (_end_dt - _now_ny).total_seconds()
                    if _delta_s > 0:
                        _h, _rem = divmod(int(_delta_s), 3600)
                        _m = _rem // 60
                        _remaining_txt = f"{_h}h {_m}m para completarse"
                    else:
                        _remaining_txt = "completada"
                except Exception:
                    pass

            _div = s.get("divergence_pending") or "—"
            _div_label = {
                "LONG":  "⚠️ posible reversión alcista",
                "SHORT": "⚠️ posible reversión bajista",
            }.get(_div, "—")
            _va_rows.append({
                "Estrategia":  s.get("strategy_id", ""),
                "Símbolo":     s.get("symbol", ""),
                "Método":      _va.get("method") or "—",
                "Estado":      _status_label,
                "% completado": _pct,
                "Restante":    _remaining_txt,
                "VAL":         _va.get("val"),
                "VAH":         _va.get("vah"),
                "POC":         _va.get("poc"),
                "CVD sesión":  s.get("cvd_session", 0.0),
                "Sesgo":       s.get("bias") or "—",
                "Divergencia": _div_label,
                "Última señal": s.get("last_signal_reason") or "—",
                "Actualizado": _utc_to_local(s.get("updated_at", ""), fmt="%H:%M:%S"),
            })
        _df_va = pd.DataFrame(_va_rows)
        st.dataframe(
            _df_va.style
            .map(_color_dir, subset=["Sesgo"])
            .format({
                "% completado": "{:.0f}%", "VAL": "{:.6g}", "VAH": "{:.6g}",
                "POC": "{:.6g}", "CVD sesión": "{:+.2f}",
            }, na_rep="—"),
            use_container_width=True,
            height=min(420, 60 + 35 * len(_df_va)),
        )

        # ── Rectángulo del value area sobre la serie de precio ────────────
        _va_symbols = sorted({s.get("symbol", "") for s in _va_states})
        st.markdown(
            "**Gráfico del value area** — rectángulo VAL-VAH sobre la sesión overnight, "
            "dibujado sobre la serie de precio de futuros ya guardada por el scanner "
            "(`market_snapshots`, sin llamadas nuevas a Binance)."
        )
        _sel_symbol = st.selectbox("Símbolo", _va_symbols, key="va_chart_symbol")
        _sel_states = [s for s in _va_states if s.get("symbol") == _sel_symbol]

        _va_by_strategy: Dict[str, Dict[str, Any]] = {}
        _va_prev_by_strategy: Dict[str, Dict[str, Any]] = {}
        _earliest_start_ny = None
        for s in _sel_states:
            _sid = s.get("strategy_id", "")
            _va = json.loads(s.get("value_area_json") or "{}") or {}
            _va_prev = json.loads(s.get("previous_value_area_json") or "{}") or {}
            if _va.get("val") is not None and _va.get("vah") is not None:
                _va_by_strategy[_sid] = _va
            if _va_prev.get("val") is not None and _va_prev.get("vah") is not None:
                _va_prev_by_strategy[_sid] = _va_prev
            for _cand in (_va, _va_prev):
                if _cand.get("val") is None:
                    continue
                try:
                    _start_ny = datetime.datetime.fromisoformat(_cand["session_start"])
                    if _earliest_start_ny is None or _start_ny < _earliest_start_ny:
                        _earliest_start_ny = _start_ny
                except Exception:
                    pass

        if not _va_by_strategy and not _va_prev_by_strategy:
            st.info("El value area de este símbolo todavía no tiene niveles (sigue en construcción overnight).")
        else:
            _since_utc = _earliest_start_ny.astimezone(datetime.timezone.utc)
            _hist = _cached_symbol_price_history(_sel_symbol, _since_utc.strftime("%Y-%m-%dT%H:%M:%S"))
            if not _hist:
                st.info("Sin historial de precio guardado todavía para este símbolo en el rango de la sesión.")
            else:
                _hist_x = []
                for _h in _hist:
                    try:
                        _dt_ny = (
                            datetime.datetime.fromisoformat(_h["timestamp"])
                            .replace(tzinfo=datetime.timezone.utc)
                            .astimezone(_NY_TZ)
                            .replace(tzinfo=None)
                        )
                        _hist_x.append(_dt_ny)
                    except Exception:
                        _hist_x.append(None)
                _hist_y = [h["price"] for h in _hist]

                # ── CVD de sesión reconstruido (misma lógica que value_area_core.py:
                # cvd_session arranca en 0 en cada apertura 9:30am NY, acumula el
                # delta de cada ciclo hasta las 4:30pm, y se mantiene en 0 durante
                # la sesión overnight — no se reconstruye desde un estado en
                # memoria, se recalcula del historial de `delta` ya persistido) ──
                _TRADING_START = datetime.time(9, 30)
                _TRADING_END = datetime.time(16, 30)
                _cvd_y: List[Optional[float]] = []
                _cvd_running = 0.0
                _cvd_session_date = None
                for _x, _h in zip(_hist_x, _hist):
                    if _x is None:
                        _cvd_y.append(None)
                        continue
                    _t = _x.time()
                    if _TRADING_START <= _t < _TRADING_END:
                        if _cvd_session_date != _x.date():
                            _cvd_session_date = _x.date()
                            _cvd_running = 0.0
                        _cvd_running += float(_h.get("delta", 0.0) or 0.0)
                        _cvd_y.append(_cvd_running)
                    else:
                        _cvd_session_date = None
                        _cvd_running = 0.0
                        _cvd_y.append(0.0)

                # ── Cortar la línea en huecos reales de cobertura ──────────
                # El scanner corre cada ~60-95s; un hueco >15min significa que
                # el símbolo salió temporalmente de la lista de candidatos (o
                # falló el fetch), no que el flujo/precio se haya quedado
                # quieto. Sin este corte, Plotly conecta los dos puntos con
                # una línea recta (falso "movimiento suave") y el CVD queda
                # plano en 0 dentro del hueco, que se lee como "sin flujo
                # institucional" cuando en realidad es "sin datos".
                _GAP_THRESHOLD_MINUTES = 30.0
                _plot_x: List[Any] = []
                _plot_price_y: List[Optional[float]] = []
                _plot_cvd_y: List[Optional[float]] = []
                _prev_x: Optional[datetime.datetime] = None
                for _x, _py, _cy in zip(_hist_x, _hist_y, _cvd_y):
                    if _x is not None and _prev_x is not None:
                        _gap_min = (_x - _prev_x).total_seconds() / 60.0
                        if _gap_min > _GAP_THRESHOLD_MINUTES:
                            _plot_x.append(_prev_x + (_x - _prev_x) / 2)
                            _plot_price_y.append(None)
                            _plot_cvd_y.append(None)
                    _plot_x.append(_x)
                    _plot_price_y.append(_py)
                    _plot_cvd_y.append(_cy)
                    if _x is not None:
                        _prev_x = _x

                _va_colors = {"range": "#3b82f6", "volume70": "#f59e0b"}
                fig_va = go.Figure()

                def _add_va_rect(_sid: str, _va: Dict[str, Any], _is_prev: bool) -> None:
                    try:
                        _sx0 = datetime.datetime.fromisoformat(_va["session_start"]).replace(tzinfo=None)
                        _sx1 = datetime.datetime.fromisoformat(_va["session_end"]).replace(tzinfo=None)
                    except Exception:
                        return
                    _color = _va_colors.get(_va.get("method", ""), "#9ca3af")
                    _label = f"{_sid} ({_va.get('method', '')}) VAL-VAH" + (" — día anterior" if _is_prev else "")
                    fig_va.add_trace(go.Scatter(
                        x=[_sx0, _sx1, _sx1, _sx0, _sx0],
                        y=[_va["val"], _va["val"], _va["vah"], _va["vah"], _va["val"]],
                        fill="toself", mode="lines",
                        fillcolor=_color, opacity=0.12 if _is_prev else 0.22,
                        line=dict(color=_color, width=1, dash="dash" if _is_prev else "solid"),
                        name=_label,
                    ))
                    fig_va.add_vline(
                        x=_sx1, line=dict(color=_color, width=1, dash="dot"),
                    )

                for _sid, _va in _va_prev_by_strategy.items():
                    _add_va_rect(_sid, _va, _is_prev=True)
                for _sid, _va in _va_by_strategy.items():
                    _add_va_rect(_sid, _va, _is_prev=False)

                fig_va.add_trace(go.Scatter(
                    x=_plot_x, y=_plot_price_y, mode="lines",
                    line=dict(color="#e5e7eb", width=1.5),
                    name="Precio (futuros)",
                    connectgaps=False,
                ))
                fig_va.add_trace(go.Scatter(
                    x=_plot_x, y=_plot_cvd_y, mode="lines",
                    line=dict(color="#22c55e", width=1.5, dash="dot"),
                    name="CVD sesión (acumulado)",
                    yaxis="y2",
                    connectgaps=False,
                ))
                fig_va.add_hline(y=0, line=dict(color="#22c55e", width=0.5, dash="dot"), yref="y2")
                fig_va.update_layout(
                    title=dict(text=f"{_sel_symbol} — value area + CVD vs precio (hora NY)", y=0.98),
                    xaxis_title="Hora NY", yaxis_title="Precio",
                    yaxis2=dict(title="CVD sesión", overlaying="y", side="right", showgrid=False),
                    # Legend abajo del grafico, no arriba: con 3-4 series (2 VA +
                    # precio + CVD) las etiquetas envuelven a 2 lineas y chocan
                    # con el titulo si se dejan arriba (y=1.02).
                    legend=dict(orientation="h", yanchor="top", y=-0.22, x=0.5, xanchor="center"),
                    margin=dict(t=70, b=110),
                    height=480,
                )
                st.plotly_chart(fig_va, use_container_width=True)
                st.caption(
                    "La línea punteada vertical marca el fin de la sesión overnight (9:30am NY) — "
                    "donde el value area queda fijo y arranca el día de trading. La línea verde "
                    "punteada (eje derecho) es el CVD acumulado de la sesión de trading (9:30am-4:30pm NY) "
                    "reconstruido del `delta` por ciclo ya guardado en `market_snapshots` — el mismo que "
                    "usa la estrategia para confirmar el sesgo (precio sobre VAH + CVD>0 → largos, "
                    "precio bajo VAL + CVD<0 → cortos). Se reinicia en 0 cada 9:30am y queda plano en 0 "
                    "durante la sesión overnight, igual que el cálculo interno de la estrategia. "
                    "Los huecos en las líneas (sin conectar) marcan tramos de más de 30 min sin "
                    "snapshots del símbolo — el token salió temporalmente de la lista de candidatos "
                    "del scanner; no interpretar esos tramos como precio estable o flujo neutro."
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
        _df_cvd_src = df_c.sort_values("cvd", ascending=False)
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="cvd 1h", x=_df_cvd_src["symbol"], y=_df_cvd_src["cvd"],
            marker_color="#6b7280",
        ))
        fig.add_trace(go.Bar(
            name="cvd 15m", x=_df_cvd_src["symbol"], y=_df_cvd_src["cvd_15m"],
            marker_color="#10b981",
        ))
        fig.update_layout(barmode="group", title="CVD 1h vs CVD 15m")
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
    _signal_colors = {
        "neutral": "#6b7280", "accumulation": "#10b981",
        "bullish_continuation": "#16a34a", "distribution": "#ef4444",
        "long_squeeze": "#dc2626", "short_squeeze": "#22c55e",
    }
    # px.bar con color discreto rompe aqui: pandas 3.0.3 tiene una regresion
    # donde groupby(['col'], sort=False).get_group(valor) lanza KeyError aunque
    # el valor exista (groupby('col') sin lista si funciona) — Plotly Express
    # usa la forma con lista internamente. Se evita construyendo el bar chart
    # directo con go.Bar (una traza por señal), sin pasar por ese codigo.
    fig = go.Figure()
    for _sig, _cnt in zip(signal_counts["signal"], signal_counts["count"]):
        fig.add_trace(go.Bar(
            x=[_sig], y=[_cnt], name=_sig,
            marker_color=_signal_colors.get(_sig, "#6b7280"),
        ))
    fig.update_layout(
        title="Distribución de señales institucionales",
        xaxis_title="Señal", yaxis_title="Cantidad",
    )
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
