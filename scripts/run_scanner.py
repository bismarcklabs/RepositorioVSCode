"""Escáner autónomo — sin Streamlit.

Replica el pipeline de main.py y persiste los snapshots en SQLite.
No muestra UI; diseñado para correr en background como un servicio.

Uso:
    python scripts/run_scanner.py
    python scripts/run_scanner.py --interval 30   # ciclo cada 30s
    python scripts/run_scanner.py --limit 20       # escanear top-20 candidatos
"""
import argparse
import datetime
import logging
import os
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

# Asegurar que el paquete 'app' sea encontrado desde scripts/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.log_setup import setup_logging

setup_logging()
logger = logging.getLogger("scanner")

from app import database, market_data
from app.config import (
    ENABLE_DATABASE,
    ENABLE_LIQUIDATIONS,
    OUTCOME_TRACKER_ENABLED,
    SCANNER_CANDIDATE_LIMIT,
    ALERT_COOLDOWN_SECONDS,
    ALERT_MIN_CONFIDENCE_DELTA_RESEND,
    MIN_ALERT_SCORE_BUY_SPOT,
    MIN_ALERT_SCORE_SELL_SPOT,
    MIN_ALERT_SCORE_LONG_FUTURES,
    MIN_ALERT_SCORE_SHORT_FUTURES,
    WINRATE_REPORT_ENABLED,
    WINRATE_REPORT_INTERVAL_HOURS,
    WINRATE_REPORT_WINDOW_HOURS,
    ENABLE_PRICE_ACTION_TRIGGER,
    ENABLE_SETUP_EVALUATION,
    ENABLE_SETUP_GATE,
    SETUP_ALERT_GRADES,
    ENABLE_TREND_CONTINUATION,
    TREND_CONTINUATION_MIN_SCORE,
    TREND_CONTINUATION_MIN_PERSISTENCE,
    TREND_CONTINUATION_LOOKBACK,
)
from app.footprint import get_footprint
from app.gex_levels import get_gex_levels
from app.indicators import calculate_metrics, update_open_interest
from app.liquidations import get_liquidations, start_liquidation_ws
from app.market_scanner import get_candidate_symbols, get_top_symbols
from app.orderbook import get_orderbook_imbalance
from app.scoring import calculate_opportunity_score
from app.signals import detect_institutional_signal
from app.technical_context import get_technical_context
from app.trade_advisor import build_trade_recommendation
from app.volume_profile import get_volume_profile
from app.websocket_client import (
    get_trades_snapshot,
    set_stream_symbols,
    start_ws_background,
)
from app.notifier import dispatch_alert
from app.outcome_tracker import run_outcome_tracker
from app.report_sender import send_winrate_report
from app.auto_trader import evaluate_alert as auto_evaluate
from app.position_monitor import check_positions, send_positions_report
from app.config import AUTO_TRADING_ENABLED, POSITION_REPORT_INTERVAL_SECONDS
from app.exchanges.aggregator import get_multi_exchange_snapshot
from app.ml_predictor import predictor as ml_predictor
from app.price_action import detect_price_action_trigger
from app.setup_rules import evaluate_trade_setup
from app.trend_continuation import (
    is_long_momentum_continuation,
    is_short_momentum_continuation,
    calculate_trend_priority_score,
)

_GEX_SYMBOLS = {"BTCUSDT", "ETHUSDT"}

_MIN_SCORE_BY_ACTION: Dict[str, int] = {
    "BUY_SPOT":      MIN_ALERT_SCORE_BUY_SPOT,
    "SELL_SPOT":     MIN_ALERT_SCORE_SELL_SPOT,
    "LONG_FUTURES":  MIN_ALERT_SCORE_LONG_FUTURES,
    "SHORT_FUTURES": MIN_ALERT_SCORE_SHORT_FUTURES,
}

# cooldown state: key = "SYMBOL:ACTION", value = (last_sent_epoch, last_confidence)
_cooldown: Dict[str, Tuple[float, int]] = {}

# ── Filtro de estancamiento ────────────────────────────────────────────────
# Detecta cuando el scanner repite alertas en la misma zona de precio sin que
# el precio avance (distribución silenciosa / techo gradual).
# key = "SYMBOL:long" | "SYMBOL:short"  value = {anchor, count}
_stag_zones: Dict[str, Dict] = {}

_STAG_ZONE_WIDTH_PCT  = 1.0   # ±1% del precio ancla = misma zona
_STAG_RESET_PCT       = 1.5   # precio avanza +1.5% → breakout, resetear zona
_STAG_MIN_COUNT       = 3     # suprimir desde la 3ª alerta en zona sin TP1 previo

# ── Historia de momentum en memoria ───────────────────────────────────────
# key = "SYMBOL:long" | "SYMBOL:short"
# Cada entrada es True/False (si ese ciclo cumplió continuación).
# maxlen = TREND_CONTINUATION_LOOKBACK (10 por defecto)
_momentum_history: Dict[str, deque] = defaultdict(
    lambda: deque(maxlen=TREND_CONTINUATION_LOOKBACK)
)


def _stag_check(symbol: str, action: str, price: float) -> Tuple[bool, str]:
    """Retorna (suprimir, motivo).

    suprimir=True cuando hay ≥3 alertas consecutivas en la misma zona de precio
    sin que ninguna alerta anterior haya tocado TP1 (precio no avanza).
    Se resetea automáticamente cuando el precio supera +1.5% el techo de zona.
    """
    is_long  = action in ("LONG_FUTURES", "BUY_SPOT")
    is_short = action in ("SHORT_FUTURES", "SELL_SPOT")
    if not (is_long or is_short):
        return False, ""

    key   = f"{symbol}:{'long' if is_long else 'short'}"
    state = _stag_zones.get(key)

    if state is None:
        _stag_zones[key] = {"anchor": price, "count": 1}
        return False, ""

    anchor = state["anchor"]
    dist   = (price - anchor) / anchor * 100   # + = por encima del ancla

    # Breakout / breakdown: precio rompió la zona → nueva zona, siempre enviar
    if is_long  and dist >  _STAG_RESET_PCT:
        _stag_zones[key] = {"anchor": price, "count": 1}
        logger.debug("STAG RESET %s long: breakout +%.1f%% → nueva zona $%.4f", symbol, dist, price)
        return False, ""
    if is_short and dist < -_STAG_RESET_PCT:
        _stag_zones[key] = {"anchor": price, "count": 1}
        logger.debug("STAG RESET %s short: breakdown %.1f%% → nueva zona $%.4f", symbol, dist, price)
        return False, ""

    # Precio fuera de la zona (±1%) pero sin breakout → nueva zona
    if abs(dist) > _STAG_ZONE_WIDTH_PCT:
        _stag_zones[key] = {"anchor": price, "count": 1}
        return False, ""

    # Precio dentro de la zona: incrementar contador
    state["count"] += 1
    count = state["count"]

    if count < _STAG_MIN_COUNT:
        return False, ""

    # count >= 3: verificar si alguna alerta previa en esta zona tocó TP1
    tp1_hits = database.get_zone_tp1_hits(symbol, action, anchor)
    if tp1_hits > 0:
        logger.debug("STAG ALLOW %s: zona activa pero %d TP1 previo(s) → tendencia real", symbol, tp1_hits)
        return False, ""

    return (
        True,
        f"alerta #{count} en zona ${anchor:.4f}±{_STAG_ZONE_WIDTH_PCT}% sin TP1 previo",
    )


def _init_cooldown_from_db() -> None:
    """Pre-popula el cooldown desde trade_alerts de las últimas 24h (ok=1 Y ok=0).

    Cargamos TODAS las alertas intentadas (no solo las exitosas) para evitar
    duplicados si el scanner se reinicia después de un fallo de Discord.
    """
    try:
        from app.database import _get_conn
        conn = _get_conn()
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        rows = conn.execute(
            """
            SELECT ta.symbol, ta.action, ta.confidence, ta.timestamp
            FROM trade_alerts ta
            WHERE ta.timestamp >= ?
            ORDER BY ta.timestamp ASC
            """,
            (cutoff_iso,),
        ).fetchall()
        for row in rows:
            key = f"{row['symbol']}:{row['action']}"
            ts = 0.0
            try:
                dt = datetime.datetime.fromisoformat(row["timestamp"])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                ts = dt.timestamp()
            except Exception:
                pass
            existing = _cooldown.get(key)
            if existing is None or ts > existing[0]:
                _cooldown[key] = (ts, int(row["confidence"] or 0))
        logger.info("Cooldown inicializado con %d entradas desde trade_alerts", len(_cooldown))
    except Exception:
        logger.exception("Error al inicializar cooldown desde DB")


def _should_send_alert(symbol: str, action: str, score: int, confidence: int) -> bool:
    """Devuelve True si la alerta debe enviarse (score umbral + cooldown)."""
    min_score = _MIN_SCORE_BY_ACTION.get(action, 999)
    if score < min_score:
        logger.debug("SKIP %s %s — score %d < umbral %d", symbol, action, score, min_score)
        return False
    key = f"{symbol}:{action}"
    entry = _cooldown.get(key)
    if entry is None:
        logger.debug("SEND %s %s — sin cooldown previo", symbol, action)
        return True
    last_ts, last_conf = entry
    elapsed = time.time() - last_ts
    if elapsed >= ALERT_COOLDOWN_SECONDS:
        logger.debug("SEND %s %s — cooldown expirado (%.0fs)", symbol, action, elapsed)
        return True
    if confidence - last_conf >= ALERT_MIN_CONFIDENCE_DELTA_RESEND:
        logger.debug("SEND %s %s — delta confianza +%d", symbol, action, confidence - last_conf)
        return True
    logger.debug("SKIP %s %s — en cooldown %.0fs/%.0fs restantes", symbol, action,
                 elapsed, ALERT_COOLDOWN_SECONDS - elapsed)
    return False


def _process_alert(result: Dict[str, Any]) -> None:
    """Persiste la alerta en DB y despacha notificaciones."""
    symbol     = result["symbol"]
    rec        = result["recommendation"]
    action     = rec["action"]
    market     = rec.get("market", "NONE")
    conf       = rec.get("confidence", 0)
    score      = result["score_data"]["score"]
    price      = result.get("price", 0.0)
    setup      = rec.get("setup") or {}
    sig        = result.get("signal", {}).get("signal", "")
    risk_level = rec.get("risk_level", "low")

    # Actualizar cooldown ANTES de dispatch para evitar duplicados si el
    # scanner se reinicia durante una llamada a Discord que falla/tarda.
    key = f"{symbol}:{action}"
    _cooldown[key] = (time.time(), conf)

    setup_eval_dict = result.get("setup_evaluation") or {}
    alert_id: Optional[int] = database.insert_trade_alert({
        "timestamp":    result.get("timestamp", ""),
        "symbol":       symbol,
        "action":       action,
        "market":       market,
        "confidence":   conf,
        "score":        score,
        "price":        price,
        "setup":        setup,
        "setup_grade":  setup_eval_dict.get("grade", ""),
        "setup_score":  setup_eval_dict.get("score", 0),
        "trigger_type": setup_eval_dict.get("trigger_type") or (result.get("trigger") or {}).get("type", ""),
        "ml_probability": result.get("ml_probability"),
        "ml_filtered":  result.get("ml_filtered", False),
        "setup_route":  setup_eval_dict.get("setup_route", ""),
        "trend_priority_score": result.get("trend_priority_score", 0),
    })

    logger.info(
        "ALERTA %-12s | %s | score=%-3d | conf=%d%%",
        symbol, action, score, conf,
    )

    dispatch_alert(
        symbol=symbol,
        action=action,
        market=market,
        confidence=conf,
        score=score,
        price=price,
        setup=setup,
        signal=sig,
        alert_id=alert_id,
        risk_level=risk_level,
    )

    if AUTO_TRADING_ENABLED:
        try:
            auto_evaluate(result, alert_id=alert_id)
        except Exception:
            logger.exception("Error en auto_evaluate para %s", symbol)


def _scan_symbol(symbol: str, candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t0 = time.monotonic()
    try:
        ws_trades = get_trades_snapshot(symbol)
        if not ws_trades:
            raw = market_data.get_agg_trades_raw(symbol, limit=100)
            ws_trades = [
                {
                    "trade_id": int(t.get("a", 0)),
                    "price": float(t.get("p", 0.0)),
                    "qty": float(t.get("q", 0.0)),
                    "maker": bool(t.get("m", False)),
                    "timestamp": int(t.get("T", 0)),
                }
                for t in raw
            ]

        with ThreadPoolExecutor(max_workers=11) as ex:
            f_funding       = ex.submit(market_data.get_funding, symbol)
            f_oi            = ex.submit(market_data.get_open_interest, symbol)
            f_ob_spot       = ex.submit(get_orderbook_imbalance, symbol, 20, "spot")
            f_ob_fut        = ex.submit(get_orderbook_imbalance, symbol, 20, "futures")
            f_technical     = ex.submit(get_technical_context, symbol)
            f_vp            = ex.submit(get_volume_profile, symbol)
            f_fp            = ex.submit(get_footprint, symbol)
            f_futures_price = ex.submit(market_data.get_futures_price, symbol)
            f_spot_price    = ex.submit(market_data.get_spot_price, symbol)
            f_multi_ex      = ex.submit(get_multi_exchange_snapshot, symbol)
            f_klines_1m     = ex.submit(market_data.get_klines, symbol, "1m", 50)

        funding           = f_funding.result()
        oi                = f_oi.result()
        ob_spot           = f_ob_spot.result()
        ob_futures        = f_ob_fut.result()
        technical         = f_technical.result()
        vp                = f_vp.result()
        fp                = f_fp.result()
        futures_price_raw = f_futures_price.result()
        price             = f_spot_price.result()
        multi_ex          = f_multi_ex.result()
        klines_1m         = f_klines_1m.result()
        orderbook_data   = ob_futures if ob_futures.get("orderbook_available") else ob_spot

        gex: Optional[Dict] = None
        if symbol in _GEX_SYMBOLS:
            try:
                gex = get_gex_levels(symbol)
            except Exception:
                pass

        liquidations  = get_liquidations(symbol, limit=50) if ENABLE_LIQUIDATIONS else []
        metrics       = calculate_metrics(symbol, ws_trades)
        oi_change_pct = update_open_interest(symbol, oi)
        futures_price = futures_price_raw or price

        signal_data = detect_institutional_signal(
            symbol=symbol,
            delta=metrics["delta"],
            cvd=metrics["cvd"],
            funding=funding,
            open_interest=oi,
            imbalance=orderbook_data["imbalance"],
            liquidations=liquidations if liquidations else None,
        )

        liquidation_summary = signal_data.get("liquidation_summary")
        alert_report = signal_data.get("alert_report") or {}

        score_data = calculate_opportunity_score(
            symbol=symbol,
            metrics=metrics,
            signal=signal_data["signal"],
            funding=funding,
            open_interest=oi,
            imbalance=orderbook_data["imbalance"],
            spread_pct=orderbook_data.get("spread_pct", 0.0),
            technical=technical,
            liquidation_summary=liquidation_summary,
            price=price,
            volume_profile=vp,
            footprint_data=fp,
            gex_data=gex,
            oi_change_pct=oi_change_pct,
            multi_exchange_data=multi_ex,
        )

        recommendation = build_trade_recommendation(
            symbol=symbol,
            signal=signal_data["signal"],
            score_data=score_data,
            technical=technical,
            funding=funding,
            open_interest=oi,
            price=price,
            alert_report=alert_report if alert_report else None,
            volume_profile=vp,
            gex_data=gex,
            multi_exchange_data=multi_ex,
        )

        # ── Price action trigger (paralelo — klines ya recuperados) ──────────
        trigger: Optional[Dict] = None
        if ENABLE_PRICE_ACTION_TRIGGER:
            try:
                trigger = detect_price_action_trigger(
                    klines_1m,
                    vwap=technical.get("vwap"),
                )
            except Exception:
                logger.debug("[%s] price action trigger no disponible", symbol)

        # ── Continuación de tendencia (siempre calculado, ambas direcciones) ───
        snap_for_cont = {"technical": technical, "metrics": metrics, "funding": funding}
        is_long_cont  = is_long_momentum_continuation(snap_for_cont)
        is_short_cont = is_short_momentum_continuation(snap_for_cont)

        _momentum_history[f"{symbol}:long"].append(is_long_cont)
        _momentum_history[f"{symbol}:short"].append(is_short_cont)

        action_cur     = recommendation.get("action", "WAIT")
        is_long_action = action_cur in ("LONG_FUTURES", "BUY_SPOT")
        is_short_action = action_cur in ("SHORT_FUTURES", "SELL_SPOT")

        if is_long_action:
            cont_val, cont_dir = is_long_cont, "long"
        elif is_short_action:
            cont_val, cont_dir = is_short_cont, "short"
        else:
            cont_val, cont_dir = False, "long"

        trend_data        = calculate_trend_priority_score(snap_for_cont, cont_dir)
        trend_score       = trend_data["trend_priority_score"]
        persistence_count = sum(_momentum_history[f"{symbol}:{cont_dir}"])

        trend_continuation_valid = (
            ENABLE_TREND_CONTINUATION
            and cont_val
            and persistence_count >= TREND_CONTINUATION_MIN_PERSISTENCE
            and trend_score >= TREND_CONTINUATION_MIN_SCORE
            and action_cur != "WAIT"
        )

        if trend_continuation_valid:
            logger.debug(
                "[%s] TREND CONT %s — score=%d persist=%d/%d",
                symbol, cont_dir, trend_score, persistence_count, TREND_CONTINUATION_LOOKBACK,
            )

        # ── Evaluación de setup (solo cuando hay señal accionable) ────────────
        setup_eval = None
        if ENABLE_SETUP_EVALUATION and action_cur != "WAIT":
            try:
                setup_eval = evaluate_trade_setup(
                    action=action_cur,
                    technical=technical,
                    metrics=metrics,
                    footprint=fp,
                    volume_profile=vp,
                    gex_data=gex,
                    setup=recommendation.get("setup"),
                    trigger=trigger,
                    multi_exchange=multi_ex,
                    trend_continuation_valid=trend_continuation_valid,
                    trend_priority_score=trend_score,
                )
                recommendation["setup_evaluation"] = setup_eval.to_dict()

                # Gate: bloquea alerta si grade no califica
                # (ENABLE_SETUP_GATE=false por defecto — no bloquea hasta validar)
                if ENABLE_SETUP_GATE and recommendation.get("action") != "WAIT":
                    if not setup_eval.valid or setup_eval.grade not in SETUP_ALERT_GRADES:
                        recommendation.setdefault("warnings", []).append(
                            f"Setup bloqueado: grado={setup_eval.grade}, score={setup_eval.score}"
                        )
                        recommendation["action"] = "WAIT"
                        recommendation["market"] = "NONE"
            except Exception:
                logger.debug("[%s] setup evaluation falló", symbol)

        result = {
            "symbol":          symbol.upper(),
            "timestamp":       time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "price":           price,
            "futures_price":   futures_price,
            "metrics":         metrics,
            "funding":         funding,
            "open_interest":   oi,
            "orderbook":       orderbook_data,
            "ob_spot":         ob_spot,
            "ob_futures":      ob_futures,
            "signal":          signal_data,
            "technical":       technical,
            "score_data":      score_data,
            "recommendation":  recommendation,
            "volume_profile":  vp,
            "footprint":       fp,
            "gex":             gex,
            "liquidations":    liquidations,
            "alert_report":    alert_report,
            "oi_change_pct":   oi_change_pct,
            "multi_exchange":  multi_ex,
            "trigger":         trigger,
            "setup_evaluation": setup_eval.to_dict() if setup_eval else None,
            # trend continuation
            "trend_priority_score":       trend_score,
            "momentum_continuation":      cont_val,
            "momentum_persistence_count": persistence_count,
            "trend_continuation_valid":   trend_continuation_valid,
        }

        ml_predictor.apply_filter(result)

        elapsed = time.monotonic() - t0
        logger.debug("[%s] %.1fs score=%d action=%s", symbol, elapsed, score_data["score"], recommendation["action"])
        return result
    except Exception:
        logger.exception("[%s] error en pipeline", symbol)
        return None


def run_scan_cycle(candidate_limit: int) -> List[Dict[str, Any]]:
    try:
        candidates = get_candidate_symbols(limit=candidate_limit)
    except Exception:
        logger.warning("get_candidate_symbols falló, usando fallback top-20")
        candidates = [{"symbol": s, "quote_volume": 0.0} for s in get_top_symbols(limit=20)]

    if not candidates:
        logger.warning("Sin candidatos — saltando ciclo")
        return []

    syms = [c["symbol"] for c in candidates[:30]]
    set_stream_symbols(syms)
    logger.info("Escaneando %d símbolos", len(candidates))

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {
            executor.submit(_scan_symbol, c["symbol"], c): c["symbol"]
            for c in candidates
        }
        for future in as_completed(future_map):
            result = future.result()
            if result:
                results.append(result)

    results.sort(
        key=lambda x: (
            x["score_data"]["score"]
            + min(20, x.get("trend_priority_score", 0) * 0.20)
        ),
        reverse=True,
    )

    if ENABLE_DATABASE:
        database.insert_snapshots_batch(results)
        database.insert_multi_exchange_batch(results)
        logger.info("Snapshots insertados: %d", len(results))

    actionable = [r for r in results if r["recommendation"]["action"] != "WAIT"]
    for r in actionable:
        action = r["recommendation"]["action"]
        score  = r["score_data"]["score"]
        conf   = r["recommendation"]["confidence"]
        logger.info(
            "SEÑAL %-12s | %s | score=%-3d | conf=%d%% | %s",
            r["symbol"], action, score, conf, r["signal"]["signal"],
        )
        if ENABLE_DATABASE and _should_send_alert(r["symbol"], action, score, conf):
            suppress, stag_reason = _stag_check(r["symbol"], action, r.get("price", 0.0))
            if suppress:
                logger.info(
                    "STAGNATION SKIP %-12s | %s | %s",
                    r["symbol"], action, stag_reason,
                )
            else:
                try:
                    _process_alert(r)
                except Exception:
                    logger.exception("Error procesando alerta %s", r["symbol"])

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Escáner de cripto autónomo")
    parser.add_argument("--interval", type=int, default=15, help="Segundos entre ciclos (default: 15)")
    parser.add_argument("--limit", type=int, default=SCANNER_CANDIDATE_LIMIT, help="Candidatos a escanear")
    args = parser.parse_args()

    logger.info("Iniciando escáner autónomo — intervalo=%ds limit=%d", args.interval, args.limit)

    if ENABLE_DATABASE:
        database.init_db()
        _init_cooldown_from_db()

    ml_predictor.load()

    start_ws_background()
    if ENABLE_LIQUIDATIONS:
        start_liquidation_ws()

    _outcome_cycle = 0
    _last_report_ts = 0.0          # epoch del último win rate report
    _last_position_report_ts = 0.0 # epoch del último reporte de posiciones

    # Primer ciclo inmediato; luego esperar entre ciclos
    while True:
        t0 = time.monotonic()
        try:
            results = run_scan_cycle(args.limit)
            logger.info("Ciclo completo: %d resultados en %.1fs", len(results), time.monotonic() - t0)
        except KeyboardInterrupt:
            logger.info("Escáner detenido por el usuario")
            break
        except Exception:
            logger.exception("Error inesperado en ciclo de scan")

        # Ejecutar outcome tracker cada 4 ciclos (~1 min con intervalo 15s)
        if ENABLE_DATABASE and OUTCOME_TRACKER_ENABLED:
            _outcome_cycle += 1
            if _outcome_cycle % 4 == 0:
                try:
                    run_outcome_tracker()
                except Exception:
                    logger.exception("Error en outcome tracker")

        # Vigilar TP/SL de posiciones abiertas (cada ciclo)
        if AUTO_TRADING_ENABLED:
            try:
                check_positions()
            except Exception:
                logger.exception("Error en check_positions")

        # Reporte de posiciones cada POSITION_REPORT_INTERVAL_SECONDS
        if AUTO_TRADING_ENABLED:
            if time.time() - _last_position_report_ts >= POSITION_REPORT_INTERVAL_SECONDS:
                try:
                    send_positions_report()
                    _last_position_report_ts = time.time()
                except Exception:
                    logger.exception("Error en send_positions_report")

        # Reporte de win rate periódico — basado en tiempo real, no en ciclos
        if ENABLE_DATABASE and WINRATE_REPORT_ENABLED:
            _report_interval_s = WINRATE_REPORT_INTERVAL_HOURS * 3600
            if time.time() - _last_report_ts >= _report_interval_s:
                try:
                    sent = send_winrate_report(since_hours=WINRATE_REPORT_WINDOW_HOURS)
                    if sent:
                        _last_report_ts = time.time()
                        logger.info(
                            "Reporte de win rate enviado (próximo en %.0fh)",
                            WINRATE_REPORT_INTERVAL_HOURS,
                        )
                except Exception:
                    logger.exception("Error en reporte de win rate")

        elapsed = time.monotonic() - t0
        sleep_time = max(0.0, args.interval - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)


if __name__ == "__main__":
    main()
