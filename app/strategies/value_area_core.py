"""Nucleo compartido de la estrategia Value Area + CVD.

Implementa los 3 criterios que definiste:
  1. Value area de la sesion overnight (4:30pm-9:30am America/New_York). Se
     va marcando EN VIVO desde que arranca la sesion overnight (4:30pm) —
     no solo al terminar — para que el dashboard muestre en todo momento
     en que punto va la construccion y cuanto falta para completarse.
  2. Sesgo direccional: precio vs value area, confirmado por el signo del CVD
     acumulado de la sesion de trading (9:30am-4:30pm). Solo se opera (se
     emiten señales) una vez que el value area quedo completo/bloqueado.
  3. Divergencia precio/CVD: si el precio hace un nuevo extremo de sesion sin
     que el CVD confirme, se marca una posible reversion; se confirma la
     entrada cuando el CVD "rebota" (boost) en la direccion contraria y el
     precio vuelve a cruzar el punto medio del value area.

Dos variantes de calculo de value area (VAH/VAL) comparten esta misma logica
de sesgo/breakout/divergencia — ver value_area_strategies.py:
  - "range":     high/low simple de la sesion overnight.
  - "volume70":  70% del volumen alrededor del POC (auction market theory).

Los umbrales de divergencia/boost son un primer ajuste razonable, no
calibrado con datos historicos todavia — documentados como env vars para
poder afinarlos una vez que haya suficientes trades evaluados (mismo patron
que otros modulos del repo, ej. micro_scalper.py).
"""
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app import database, market_data
from app.strategies.base import StrategyContext, StrategySignal

NY_TZ = ZoneInfo("America/New_York")

_SESSION_START_NY = dt_time(16, 30)   # 4:30pm — inicio de la sesion overnight
_SESSION_END_NY = dt_time(9, 30)      # 9:30am — fin de la sesion overnight / inicio de trading
_SESSION_HOURS = 17.0                 # 4:30pm -> 9:30am siguiente dia

_VALUE_AREA_TARGET_PCT = float(os.getenv("VALUE_AREA_VOLUME70_TARGET_PCT", "0.70"))
_VALUE_AREA_BINS = int(os.getenv("VALUE_AREA_VOLUME70_BINS", "50"))
_CVD_BOOST_FACTOR = float(os.getenv("VALUE_AREA_CVD_BOOST_FACTOR", "0.10"))
_SL_FLOOR_PCT = float(os.getenv("VALUE_AREA_SL_FLOOR_PCT", "0.015"))
_TP1_R = float(os.getenv("VALUE_AREA_TP1_R", "1.5"))
_TP2_R = float(os.getenv("VALUE_AREA_TP2_R", "3.0"))
# El value area NO se calcula durante toda la sesion overnight (evita fetches
# de klines innecesarios durante ~17h) — solo se empieza a previsualizar en
# los ultimos N minutos antes de las 9:30am, cuando el perfil de volumen ya
# es casi el definitivo. El % completado / cuenta regresiva SI se muestran
# desde el inicio porque son puro calculo de fechas (sin costo de red).
_PREVIEW_WINDOW_MINUTES = float(os.getenv("VALUE_AREA_PREVIEW_MINUTES", "30"))
_PREVIEW_REFRESH_SECONDS = float(os.getenv("VALUE_AREA_PREVIEW_REFRESH_SECONDS", "300"))
# Cache de klines compartida entre ambas variantes (range/volume70): piden la
# misma ventana de velas para el mismo simbolo, no tiene sentido duplicar el
# fetch a Binance solo porque las consume una estrategia distinta.
_KLINES_CACHE_TTL_SECONDS = 120.0
_KLINES_CACHE_MAX_ENTRIES = 500
_klines_cache: Dict[Tuple[str, str], Tuple[float, List[Any]]] = {}

METHOD_DESCRIPTIONS = {
    "range": "VAH/VAL = máximo/mínimo de precio alcanzado durante la sesión overnight (4:30pm-9:30am NY).",
    "volume70": "VAH/VAL = borde de la zona que concentra el 70% del volumen alrededor del POC "
                "(precio de mayor volumen), expandiendo desde el POC hacia el lado con más volumen "
                "en cada paso — sesión overnight (4:30pm-9:30am NY).",
}


# ── Sesion overnight ────────────────────────────────────────────────────────

def is_trading_window(now_ny: datetime) -> bool:
    """True entre 9:30am y 4:30pm NY — unica ventana en la que se opera
    (criterio 2: "after 9:30am for trading")."""
    return _SESSION_END_NY <= now_ny.time() < _SESSION_START_NY


def get_reference_session(now_ny: datetime) -> Tuple[datetime, datetime, bool]:
    """Sesion overnight de referencia para 'now_ny': la que esta en
    construccion (si estamos entre 4:30pm y 9:30am) o la que acaba de
    completarse (si ya estamos en la ventana de trading 9:30am-4:30pm).

    Devuelve (inicio_ny, fin_programado_ny, esta_completa). El fin_programado
    es siempre el mismo (el 9:30am objetivo) durante toda la noche + el dia
    de trading siguiente — eso es lo que permite usar un unico "session_key"
    para todo ese ciclo de 24h sin resetear el estado a mitad de camino.
    """
    if now_ny.time() >= _SESSION_START_NY:
        start = now_ny.replace(hour=16, minute=30, second=0, microsecond=0)
    else:
        start = (now_ny - timedelta(days=1)).replace(hour=16, minute=30, second=0, microsecond=0)
    end = start + timedelta(hours=_SESSION_HOURS)
    return start, end, now_ny >= end


def session_key(session_end_ny: datetime) -> str:
    """Identificador unico del ciclo overnight+trading actual (para saber
    cuando resetear el estado al empezar una sesion nueva a las 4:30pm)."""
    return session_end_ny.strftime("%Y-%m-%dT%H:%M")


def fetch_session_klines(symbol: str, session_start_utc: datetime,
                         until_utc: datetime, interval: str = "15m") -> List[Any]:
    start_ms = int(session_start_utc.timestamp() * 1000)
    end_ms = int(until_utc.timestamp() * 1000)
    try:
        return market_data.get_klines(symbol, interval=interval, limit=100,
                                      start_time_ms=start_ms, end_time_ms=end_ms)
    except Exception:
        return []


def _fetch_session_klines_shared(symbol: str, key: str, session_start_utc: datetime,
                                 until_utc: datetime, interval: str) -> List[Any]:
    """Igual que fetch_session_klines, pero cacheada por (symbol, session_key)
    durante _KLINES_CACHE_TTL_SECONDS — asi las dos variantes (range/volume70)
    que piden la misma ventana para el mismo simbolo en el mismo ciclo no
    disparan dos llamadas identicas a Binance."""
    cache_key = (symbol, key)
    now_wall = time.time()
    cached = _klines_cache.get(cache_key)
    if cached and (now_wall - cached[0]) < _KLINES_CACHE_TTL_SECONDS:
        return cached[1]

    klines = fetch_session_klines(symbol, session_start_utc, until_utc, interval)
    if len(_klines_cache) >= _KLINES_CACHE_MAX_ENTRIES:
        oldest_key = min(_klines_cache, key=lambda k: _klines_cache[k][0])
        _klines_cache.pop(oldest_key, None)
    _klines_cache[cache_key] = (now_wall, klines)
    return klines


# ── Value area: dos metodos ─────────────────────────────────────────────────

def compute_value_area_range(klines: List[Any]) -> Optional[Dict[str, Any]]:
    """Metodo simple: high/low de la sesion overnight (hasta ahora, si aun
    esta en construccion)."""
    if not klines:
        return None
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    val, vah = min(lows), max(highs)
    if vah <= val:
        return None
    return {"val": round(val, 8), "vah": round(vah, 8), "poc": None, "method": "range"}


def compute_value_area_volume70(klines: List[Any], bins: int = _VALUE_AREA_BINS,
                                target_pct: float = _VALUE_AREA_TARGET_PCT) -> Optional[Dict[str, Any]]:
    """Metodo estandar (auction market theory): POC + expansion hasta cubrir
    target_pct (70%) del volumen, agregando en cada paso el bin adyacente
    (izquierda o derecha) con mas volumen. Mismo binning que volume_profile.py."""
    if not klines:
        return None
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    quote_vols = [float(k[7]) for k in klines]

    price_min, price_max = min(lows), max(highs)
    if price_max <= price_min:
        return None

    bucket_size = (price_max - price_min) / bins
    volume_at = [0.0] * bins
    for h, lo, qv in zip(highs, lows, quote_vols):
        lo_idx = max(0, int((lo - price_min) / bucket_size))
        hi_idx = min(bins - 1, int((h - price_min) / bucket_size))
        n = hi_idx - lo_idx + 1
        if n <= 0:
            continue
        share = qv / n
        for i in range(lo_idx, hi_idx + 1):
            volume_at[i] += share

    total_volume = sum(volume_at)
    if total_volume <= 0:
        return None

    poc_idx = max(range(bins), key=lambda i: volume_at[i])
    poc = price_min + (poc_idx + 0.5) * bucket_size

    lo_bound = hi_bound = poc_idx
    acc_volume = volume_at[poc_idx]
    while acc_volume / total_volume < target_pct and (lo_bound > 0 or hi_bound < bins - 1):
        left_idx = lo_bound - 1 if lo_bound > 0 else None
        right_idx = hi_bound + 1 if hi_bound < bins - 1 else None
        left_vol = volume_at[left_idx] if left_idx is not None else -1.0
        right_vol = volume_at[right_idx] if right_idx is not None else -1.0
        if left_vol >= right_vol:
            lo_bound = left_idx
            acc_volume += left_vol
        else:
            hi_bound = right_idx
            acc_volume += right_vol

    val = price_min + lo_bound * bucket_size
    vah = price_min + (hi_bound + 1) * bucket_size
    return {"val": round(val, 8), "vah": round(vah, 8), "poc": round(poc, 8), "method": "volume70"}


ValueAreaFn = Callable[[List[Any]], Optional[Dict[str, Any]]]


# ── Estado por simbolo + logica compartida de sesgo/breakout/divergencia ────

@dataclass
class _SymbolState:
    session_key: str = ""
    value_area: Optional[Dict[str, Any]] = None
    locked: bool = False              # True una vez que el value area quedo fijo (9:30am)
    last_refresh_ts: float = 0.0      # time.time() del ultimo fetch de klines (throttle)
    cvd_session: float = 0.0
    peak_price: float = 0.0
    trough_price: float = 0.0
    peak_cvd: float = 0.0
    trough_cvd: float = 0.0
    divergence_pending: str = ""     # "" | "LONG" | "SHORT"
    divergence_ref_cvd: float = 0.0
    last_bias: str = ""


def _build_signal(direction: str, entry: float, reasons: List[str],
                  warnings: Optional[List[str]] = None) -> StrategySignal:
    sign = 1 if direction == "LONG" else -1
    sl_pct = _SL_FLOOR_PCT
    sl = entry * (1 - sign * sl_pct)
    tp1 = entry * (1 + sign * sl_pct * _TP1_R)
    tp2 = entry * (1 + sign * sl_pct * _TP2_R)
    return StrategySignal(
        direction=direction,
        entry=round(entry, 8),
        stop_loss=round(sl, 8),
        take_profit_1=round(tp1, 8),
        take_profit_2=round(tp2, 8),
        leverage=1,
        confidence=60,
        score=60,
        reasons=reasons,
        warnings=warnings or [],
    )


def evaluate_value_area_cvd(strategy_id: str, ctx: StrategyContext,
                           state: Dict[str, _SymbolState],
                           compute_va: ValueAreaFn,
                           va_interval: str = "15m") -> Optional[StrategySignal]:
    """Logica compartida por ambas variantes (range/volume70). Persiste el
    estado de cada simbolo en strategy_symbol_state EN CADA CICLO (incluso
    durante la construccion overnight, sin operar todavia) para que el
    dashboard lo muestre (proceso separado, solo lee DB)."""
    try:
        now_utc = datetime.fromisoformat(ctx.timestamp).replace(tzinfo=timezone.utc)
    except Exception:
        now_utc = datetime.now(timezone.utc)
    now_ny = now_utc.astimezone(NY_TZ)

    # El value area se construye con velas de FUTUROS (market_data.get_klines) y las
    # posiciones llevan leverage, asi que el precio de referencia debe ser el de
    # futuros, no el spot (ctx.price) — para la mayoria de simbolos son casi iguales,
    # pero en algunos (ej. XMRUSDT) divergen fuertemente y mezclarlos genera breakouts
    # y stops falsos. Mismo patron que auto_trader.py usa para acciones FUTURES.
    price = ctx.futures_price or ctx.price
    if price <= 0:
        return None

    session_start_ny, session_end_ny, is_complete = get_reference_session(now_ny)
    key = session_key(session_end_ny)
    total_seconds = _SESSION_HOURS * 3600.0
    elapsed_seconds = min(total_seconds, max(0.0, (now_ny - session_start_ny).total_seconds()))
    pct_complete = round(elapsed_seconds / total_seconds * 100.0, 1)

    sym_state = state.setdefault(ctx.symbol, _SymbolState())
    is_new_cycle = sym_state.session_key != key
    if is_new_cycle:
        # Antes de resetear, guardar el value area de la sesion que acaba de
        # quedar atras como "anterior" — asi el dashboard puede mostrarla junto
        # a la que se esta construyendo ahora, sin recalcular ni pedir velas.
        if sym_state.value_area and sym_state.session_key:
            try:
                old_end_ny = datetime.fromisoformat(sym_state.session_key).replace(tzinfo=NY_TZ)
                old_start_ny = old_end_ny - timedelta(hours=_SESSION_HOURS)
                prev_va = dict(sym_state.value_area)
                prev_va.update({
                    "session_start": old_start_ny.isoformat(),
                    "session_end": old_end_ny.isoformat(),
                    "method_description": METHOD_DESCRIPTIONS.get(prev_va.get("method", ""), ""),
                })
                database.set_previous_value_area(strategy_id, ctx.symbol, _dumps(prev_va))
            except Exception:
                pass
        sym_state.__init__()
        sym_state.session_key = key
        sym_state.peak_price = price
        sym_state.trough_price = price

    minutes_remaining = 0.0 if is_complete else max(0.0, (session_end_ny - now_ny).total_seconds() / 60.0)
    in_preview_window = (not is_complete) and (minutes_remaining <= _PREVIEW_WINDOW_MINUTES)

    # Fuera de la ventana de preview no se pide nada a Binance — el value area
    # solo se calcula en los ultimos _PREVIEW_WINDOW_MINUTES antes de las
    # 9:30am (o al completarse), no durante las ~17h de la sesion overnight.
    need_refresh = (
        (in_preview_window and (time.time() - sym_state.last_refresh_ts) >= _PREVIEW_REFRESH_SECONDS)
        or (is_complete and not sym_state.locked)
    )

    if need_refresh:
        session_start_utc = session_start_ny.astimezone(timezone.utc)
        until_utc = (session_end_ny if is_complete else now_ny).astimezone(timezone.utc)
        klines = _fetch_session_klines_shared(ctx.symbol, key, session_start_utc, until_utc, va_interval)
        va = compute_va(klines)
        if va is not None:
            sym_state.value_area = va
        sym_state.last_refresh_ts = time.time()
        if is_complete and not sym_state.locked:
            sym_state.locked = True
            # value area recien bloqueado -> arranca el dia de trading limpio
            sym_state.cvd_session = 0.0
            sym_state.peak_price = price
            sym_state.trough_price = price
            sym_state.peak_cvd = 0.0
            sym_state.trough_cvd = 0.0
            sym_state.divergence_pending = ""
            sym_state.last_bias = ""

    va = sym_state.value_area
    signal: Optional[StrategySignal] = None
    bias = ""
    status_note = ""

    if not is_complete:
        # ── Criterio 1 en vivo: todavia construyendo el value area ─────────
        cvd = sym_state.cvd_session
        if va is not None:
            status_note = (
                f"Vista previa del value area ({pct_complete:.0f}% de la sesión — "
                f"últimos {_PREVIEW_WINDOW_MINUTES:.0f} min antes de las 9:30am NY)"
            )
        else:
            status_note = (
                f"Construyendo sesión overnight ({pct_complete:.0f}%, faltan {minutes_remaining:.0f} min) — "
                f"el value area se calcula recién en los últimos {_PREVIEW_WINDOW_MINUTES:.0f} min"
            )
    else:
        vah, val = va["vah"], va["val"]

        # CVD acumulado desde el inicio de la sesion de trading (9:30am) — no
        # el cvd rodante de 1h/15m de indicators.py, que es para momentum de
        # corto plazo.
        sym_state.cvd_session += float(ctx.metrics.get("delta", 0.0) or 0.0)
        cvd = sym_state.cvd_session

        # ── Criterio 2: sesgo por precio vs value area, confirmado por CVD ──
        if price > vah and cvd > 0:
            bias = "LONG"
        elif price < val and cvd < 0:
            bias = "SHORT"

        reasons: List[str] = []
        warnings: List[str] = []

        # ── Criterio 3: divergencia precio/CVD en los extremos de sesion ───
        new_price_high = price > sym_state.peak_price
        new_price_low = price < sym_state.trough_price

        if new_price_high:
            if cvd <= sym_state.peak_cvd:
                sym_state.divergence_pending = "SHORT"
                sym_state.divergence_ref_cvd = cvd
                warnings.append("Nuevo máximo de sesión sin confirmación de CVD — posible reversión bajista")
            elif sym_state.divergence_pending == "SHORT":
                sym_state.divergence_pending = ""
            sym_state.peak_price = price
            sym_state.peak_cvd = max(sym_state.peak_cvd, cvd)

        if new_price_low:
            if cvd >= sym_state.trough_cvd:
                sym_state.divergence_pending = "LONG"
                sym_state.divergence_ref_cvd = cvd
                warnings.append("Nuevo mínimo de sesión sin confirmación de CVD — posible reversión alcista")
            elif sym_state.divergence_pending == "LONG":
                sym_state.divergence_pending = ""
            sym_state.trough_price = price
            sym_state.trough_cvd = min(sym_state.trough_cvd, cvd)

        cvd_range = max(abs(sym_state.peak_cvd), abs(sym_state.trough_cvd), 1e-9)
        va_mid = (vah + val) / 2.0

        if sym_state.divergence_pending == "SHORT":
            boost = (sym_state.divergence_ref_cvd - cvd) >= cvd_range * _CVD_BOOST_FACTOR
            if boost and price < va_mid:
                signal = _build_signal("SHORT", price, reasons=[
                    "Reversión bajista: divergencia precio/CVD confirmada por caída de CVD y ruptura de vuelta al value area",
                ])
                sym_state.divergence_pending = ""
        elif sym_state.divergence_pending == "LONG":
            boost = (cvd - sym_state.divergence_ref_cvd) >= cvd_range * _CVD_BOOST_FACTOR
            if boost and price > va_mid:
                signal = _build_signal("LONG", price, reasons=[
                    "Reversión alcista: divergencia precio/CVD confirmada por repunte de CVD y ruptura de vuelta al value area",
                ])
                sym_state.divergence_pending = ""

        # ── Breakout confirmado (solo si no hay ya una reversion disparada) ─
        if signal is None and bias and bias != sym_state.last_bias:
            if bias == "LONG":
                reasons.append(f"Breakout sobre VAH ({vah:.6g}) confirmado por CVD positivo ({cvd:+.2f})")
            else:
                reasons.append(f"Breakdown bajo VAL ({val:.6g}) confirmado por CVD negativo ({cvd:+.2f})")
            signal = _build_signal(bias, price, reasons=reasons, warnings=warnings)

        sym_state.last_bias = bias
        status_note = "Sesión de trading activa — esperando breakout" if not bias else ""

    va_out = dict(va) if va else {}
    va_out.update({
        "status": "complete" if is_complete else "building",
        "pct_complete": pct_complete,
        "minutes_remaining": round(minutes_remaining, 1),
        "session_start": session_start_ny.isoformat(),
        "session_end": session_end_ny.isoformat(),
        "method_description": METHOD_DESCRIPTIONS.get(va_out.get("method", ""), ""),
    })

    database.upsert_strategy_symbol_state({
        "strategy_id": strategy_id,
        "symbol": ctx.symbol,
        "updated_at": ctx.timestamp,
        "value_area_json": _dumps(va_out),
        "cvd_session": sym_state.cvd_session,
        "bias": bias,
        "divergence_pending": sym_state.divergence_pending,
        "last_signal_reason": (signal.reasons[0] if signal and signal.reasons else status_note),
    })

    return signal


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value)
    except Exception:
        return "{}"
