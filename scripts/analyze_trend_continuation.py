"""Análisis histórico: classic_trigger vs momentum_continuation.

Responde:
  - ¿Cuántas alertas salieron por cada ruta?
  - ¿Cuál fue el win rate por ruta?
  - ¿Cuál fue el retorno promedio por ruta?
  - ¿Qué símbolos funcionaron mejor en cada ruta?

Uso:
    python scripts/analyze_trend_continuation.py [--horizon 60] [--min-samples 3]

Nota: lee de trade_alerts (no market_snapshots) para sobrevivir la purga de 7 días.
"""
import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sqlite3
from app.config import DATABASE_PATH


# ── Resumen global por ruta ───────────────────────────────────────────────

_ROUTE_SUMMARY = """
SELECT
    COALESCE(NULLIF(ta.setup_route, ''), 'sin_ruta') AS ruta,
    COUNT(*)                                           AS total,
    SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN ao.outcome = 'loss'             THEN 1 ELSE 0 END) AS losses,
    ROUND(AVG(ao.future_return_pct), 2)                AS avg_return_pct,
    ROUND(AVG(ta.trend_priority_score), 1)             AS avg_trend_score,
    ROUND(AVG(ta.score), 1)                            AS avg_score
FROM trade_alerts ta
JOIN alert_outcomes ao
    ON ao.alert_id = ta.id
    AND ao.horizon_minutes = ?
    AND ao.outcome IN ('win', 'partial', 'loss')
GROUP BY ruta
ORDER BY
    CASE ruta
        WHEN 'classic_trigger'      THEN 1
        WHEN 'momentum_continuation' THEN 2
        ELSE 3
    END
"""

# ── Desglose por símbolo + ruta ────────────────────────────────────────────

_SYMBOL_ROUTE = """
SELECT
    ta.symbol,
    COALESCE(NULLIF(ta.setup_route, ''), 'sin_ruta') AS ruta,
    COUNT(*)  AS n,
    SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
    ROUND(AVG(ta.trend_priority_score), 0) AS avg_trend_score,
    ROUND(AVG(ao.future_return_pct), 2)    AS avg_return_pct
FROM trade_alerts ta
JOIN alert_outcomes ao
    ON ao.alert_id = ta.id
    AND ao.horizon_minutes = ?
    AND ao.outcome IN ('win', 'partial', 'loss')
WHERE ta.setup_route IN ('classic_trigger', 'momentum_continuation')
GROUP BY ta.symbol, ruta
HAVING n >= ?
ORDER BY avg_return_pct DESC
"""

# ── Evolución temporal (por día) ─────────────────────────────────────────

_DAILY = """
SELECT
    substr(ta.timestamp, 1, 10)                        AS dia,
    COALESCE(NULLIF(ta.setup_route, ''), 'sin_ruta') AS ruta,
    COUNT(*)                                           AS total,
    SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins
FROM trade_alerts ta
JOIN alert_outcomes ao
    ON ao.alert_id = ta.id
    AND ao.horizon_minutes = ?
    AND ao.outcome IN ('win', 'partial', 'loss')
WHERE ta.setup_route IN ('classic_trigger', 'momentum_continuation')
GROUP BY dia, ruta
ORDER BY dia DESC, ruta
LIMIT 60
"""


def _pct(wins: int, total: int) -> str:
    if total == 0:
        return "  -  "
    return f"{wins / total * 100:5.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",          default=str(ROOT / DATABASE_PATH))
    parser.add_argument("--horizon",     type=int, default=60,
                        help="Horizonte de outcome en minutos (default: 60)")
    parser.add_argument("--min-samples", type=int, default=3,
                        help="Minimo de muestras para mostrar fila (default: 3)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"[!] DB no encontrada: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Verificar columnas necesarias
    existing = {r[1] for r in conn.execute("PRAGMA table_info(trade_alerts)").fetchall()}
    missing  = {"setup_route", "trend_priority_score"} - existing
    if missing:
        print(f"[!] Columnas faltantes en trade_alerts: {missing}")
        print("    Aplica la migracion: python -c \"from app.database import init_db; init_db()\"")
        conn.close()
        sys.exit(0)

    total_with_route = conn.execute(
        """SELECT COUNT(*) FROM trade_alerts ta
           JOIN alert_outcomes ao ON ao.alert_id=ta.id AND ao.horizon_minutes=?
              AND ao.outcome IN ('win','partial','loss')
           WHERE ta.setup_route IN ('classic_trigger','momentum_continuation')""",
        (args.horizon,),
    ).fetchone()[0]

    print()
    print("=" * 68)
    print(f"  ANALISIS DE RUTAS DE ALERTA  (horizonte={args.horizon}m)")
    print("=" * 68)
    print(f"  Alertas con ruta + outcome evaluado: {total_with_route}")
    print()

    if total_with_route == 0:
        print("  Sin datos. Necesitas alertas con setup_route registrado y outcomes.")
        print("  Espera al menos 1-2 horas con el scanner corriendo.")
        conn.close()
        return

    # ── Resumen por ruta ─────────────────────────────────────────────────
    rows = conn.execute(_ROUTE_SUMMARY, (args.horizon,)).fetchall()
    print(f"  {'Ruta':<25} {'Total':>6} {'WR%':>6}  {'AvgRet%':>8}  {'AvgTrend':>9}  {'AvgScore':>9}")
    print("  " + "-" * 66)
    for r in rows:
        print(
            f"  {r['ruta']:<25} {r['total']:>6} {_pct(r['wins'], r['total']):>6}"
            f"  {(r['avg_return_pct'] or 0.0):>+8.2f}%"
            f"  {(r['avg_trend_score'] or 0.0):>9.1f}"
            f"  {(r['avg_score'] or 0.0):>9.1f}"
        )

    # ── Veredicto ────────────────────────────────────────────────────────
    route_map = {r["ruta"]: r for r in rows}
    classic = route_map.get("classic_trigger")
    cont    = route_map.get("momentum_continuation")
    print()
    if classic and cont:
        diff_wr  = (cont["wins"] / cont["total"] * 100) - (classic["wins"] / classic["total"] * 100) if classic["total"] and cont["total"] else 0
        diff_ret = (cont["avg_return_pct"] or 0.0) - (classic["avg_return_pct"] or 0.0)
        print(f"  Diferencia momentum_continuation vs classic_trigger:")
        print(f"    WR%:  {diff_wr:+.1f} pp   AvgRet%: {diff_ret:+.2f}%")
        if diff_wr >= 5 and diff_ret >= 0:
            print("  [POSITIVO] Continuacion supera al gatillo clasico — ruta util.")
        elif diff_wr < -10:
            print("  [REVISAR]  Continuacion con WR significativamente inferior — ajustar umbrales.")
        else:
            print("  [NEUTRAL]  Diferencia pequeña — acumula mas datos antes de concluir.")
    elif cont:
        print(f"  Continuacion: {cont['total']} alertas evaluadas, WR {_pct(cont['wins'], cont['total'])}.")
    else:
        print("  Sin alertas de momentum_continuation con outcome aun.")

    # ── Desglose por símbolo ─────────────────────────────────────────────
    sym_rows = conn.execute(_SYMBOL_ROUTE, (args.horizon, args.min_samples)).fetchall()
    if sym_rows:
        print()
        print("-" * 68)
        print("  WIN RATE POR SIMBOLO + RUTA  (>= {} muestras)".format(args.min_samples))
        print("-" * 68)
        print(f"  {'Simbolo':<14} {'Ruta':<25} {'N':>4} {'WR%':>6}  {'AvgRet%':>8}  {'TrendSc':>8}")
        print("  " + "-" * 62)
        for r in sym_rows:
            print(
                f"  {r['symbol']:<14} {r['ruta']:<25} {r['n']:>4}"
                f" {_pct(r['wins'], r['n']):>6}"
                f"  {(r['avg_return_pct'] or 0.0):>+8.2f}%"
                f"  {(r['avg_trend_score'] or 0.0):>8.0f}"
            )

    # ── Evolución diaria ─────────────────────────────────────────────────
    daily_rows = conn.execute(_DAILY, (args.horizon,)).fetchall()
    if daily_rows:
        print()
        print("-" * 68)
        print("  EVOLUCION DIARIA (ultimos 30 dias)")
        print("-" * 68)
        print(f"  {'Dia':<12} {'Ruta':<25} {'Total':>6} {'WR%':>6}")
        print("  " + "-" * 50)
        for r in daily_rows:
            print(
                f"  {r['dia']:<12} {r['ruta']:<25} {r['total']:>6}"
                f" {_pct(r['wins'], r['total']):>6}"
            )

    print()
    print("  Para activar ENABLE_SETUP_GATE=true (bloqueo estricto):")
    print("    Espera a que momentum_continuation tenga WR >= classic_trigger")
    print("    Y al menos 20+ muestras por ruta.")
    print("=" * 68)
    print()

    conn.close()


if __name__ == "__main__":
    main()
