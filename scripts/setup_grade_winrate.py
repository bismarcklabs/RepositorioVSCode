"""Compara win rate por setup grade (A/B vs C/NO_TRADE).

Uso:
    python scripts/setup_grade_winrate.py [--horizon 60] [--min-samples 5]

Necesitas al menos unas horas de scanner corriendo con ENABLE_SETUP_EVALUATION=true
y alert_outcomes registrados para que los números sean significativos.
"""
import argparse
import io
import os
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATABASE_PATH


# ── Query principal: win rate por grade ───────────────────────────────────

_GRADE_QUERY = """
SELECT
    COALESCE(NULLIF(ta.setup_grade, ''), 'sin_grade') AS grade,
    COUNT(*)                                           AS total,
    SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN ao.outcome = 'win'              THEN 1 ELSE 0 END) AS strict_wins,
    SUM(CASE WHEN ao.outcome = 'loss'             THEN 1 ELSE 0 END) AS losses,
    ROUND(AVG(ta.score), 1)                            AS avg_score,
    ROUND(AVG(ao.future_return_pct), 2)                AS avg_return_pct
FROM trade_alerts ta
JOIN alert_outcomes ao
    ON ao.alert_id = ta.id
    AND ao.horizon_minutes = ?
    AND ao.outcome IN ('win', 'partial', 'loss')
GROUP BY grade
ORDER BY
    CASE grade
        WHEN 'A'        THEN 1
        WHEN 'B'        THEN 2
        WHEN 'C'        THEN 3
        WHEN 'NO_TRADE' THEN 4
        ELSE 5
    END
"""

# ── Query secundaria: win rate por trigger type ────────────────────────────

_TRIGGER_QUERY = """
SELECT
    COALESCE(NULLIF(ta.trigger_type, ''), 'sin_gatillo') AS trigger,
    COUNT(*)                                              AS total,
    SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
    ROUND(AVG(ao.future_return_pct), 2)                   AS avg_return_pct
FROM trade_alerts ta
JOIN alert_outcomes ao
    ON ao.alert_id = ta.id
    AND ao.horizon_minutes = ?
    AND ao.outcome IN ('win', 'partial', 'loss')
GROUP BY trigger
ORDER BY total DESC
"""

# ── Query por acción + grade ───────────────────────────────────────────────

_ACTION_GRADE_QUERY = """
SELECT
    ta.action,
    COALESCE(NULLIF(ta.setup_grade, ''), 'sin_grade') AS grade,
    COUNT(*)  AS total,
    SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) AS wins,
    ROUND(AVG(ao.future_return_pct), 2) AS avg_return_pct
FROM trade_alerts ta
JOIN alert_outcomes ao
    ON ao.alert_id = ta.id
    AND ao.horizon_minutes = ?
    AND ao.outcome IN ('win', 'partial', 'loss')
GROUP BY ta.action, grade
ORDER BY ta.action, grade
"""


def _pct(wins: int, total: int) -> str:
    if total == 0:
        return "  -  "
    return f"{wins / total * 100:5.1f}%"


def _bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100 * width)
    return "#" * filled + "-" * (width - filled)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db",          default=str(ROOT / DATABASE_PATH))
    parser.add_argument("--horizon",     type=int, default=60,
                        help="Horizonte de outcome en minutos (default: 60)")
    parser.add_argument("--min-samples", type=int, default=5,
                        help="Minimo de muestras para mostrar fila (default: 5)")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"[!] DB no encontrada: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # ── Verificar que las columnas existen en trade_alerts ───────────────
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(trade_alerts)").fetchall()}
    required = {"setup_grade", "trigger_type"}
    missing = required - existing_cols
    if missing:
        print(f"[!] Columnas aun no migradas en trade_alerts: {missing}")
        print("    Aplica la migracion ejecutando:")
        print("    .\\venv\\Scripts\\python.exe -c \"from app.database import init_db; init_db()\"")
        conn.close()
        sys.exit(0)

    # ── Total de alertas con outcome evaluado ─────────────────────────────
    total_evaluated = conn.execute(
        "SELECT COUNT(*) FROM alert_outcomes WHERE horizon_minutes=? AND outcome IN ('win','partial','loss')",
        (args.horizon,),
    ).fetchone()[0]

    print()
    print("=" * 65)
    print(f"  WIN RATE POR SETUP GRADE  (horizonte={args.horizon}m)")
    print("=" * 65)
    print(f"  Alertas evaluadas: {total_evaluated}")
    print()

    if total_evaluated == 0:
        print("  Sin datos aun. Necesitas alertas con outcomes registrados.")
        print("  Espera al menos 1-2 horas con el scanner corriendo.")
        conn.close()
        return

    # ── Tabla por grade ───────────────────────────────────────────────────
    rows = conn.execute(_GRADE_QUERY, (args.horizon,)).fetchall()

    print(f"  {'Grade':<12} {'Total':>6} {'Wins':>5} {'WR%':>6}  {'Bar (win%)':22} {'AvgScore':>8} {'AvgRet%':>8}")
    print("  " + "-" * 63)

    grade_data = {}
    for r in rows:
        if r["total"] < args.min_samples:
            continue
        wr = r["wins"] / r["total"] * 100
        ret = r["avg_return_pct"] or 0.0
        grade_data[r["grade"]] = wr
        print(
            f"  {r['grade']:<12} {r['total']:>6} {r['wins']:>5} {_pct(r['wins'], r['total']):>6}"
            f"  {_bar(wr):22} {r['avg_score']:>8.1f} {ret:>+8.2f}%"
        )

    # ── Dictamen ──────────────────────────────────────────────────────────
    print()
    ab_wr  = grade_data.get("A", grade_data.get("B", None))
    c_wr   = grade_data.get("C", None)
    nt_wr  = grade_data.get("NO_TRADE", None)

    if ab_wr is not None and (c_wr is not None or nt_wr is not None):
        low_wr = max(x for x in [c_wr, nt_wr] if x is not None)
        diff   = ab_wr - low_wr
        print(f"  Diferencia A/B vs peores grades: {diff:+.1f} puntos porcentuales")
        if diff >= 10:
            print("  [RECOMENDACION] Diferencia >= 10pp -> activar ENABLE_SETUP_GATE=true")
        elif diff >= 5:
            print("  [OBSERVAR] Diferencia 5-10pp -> acumula mas datos antes de activar gate")
        else:
            print("  [ESPERAR] Diferencia < 5pp -> setup grade aun no es discriminatorio")
            print("            Puede necesitar mas datos o revision del modelo de scoring")
    else:
        print("  (insuficientes grades con muestras >= {})".format(args.min_samples))

    # ── Tabla por trigger ─────────────────────────────────────────────────
    trigger_rows = conn.execute(_TRIGGER_QUERY, (args.horizon,)).fetchall()
    trigger_rows = [r for r in trigger_rows if r["total"] >= args.min_samples]

    if trigger_rows:
        print()
        print("-" * 65)
        print("  WIN RATE POR TIPO DE GATILLO")
        print("-" * 65)
        print(f"  {'Trigger':<25} {'Total':>6} {'WR%':>6}  {'AvgRet%':>8}")
        print("  " + "-" * 47)
        for r in trigger_rows:
            print(
                f"  {r['trigger']:<25} {r['total']:>6} {_pct(r['wins'], r['total']):>6}"
                f"  {(r['avg_return_pct'] or 0.0):>+8.2f}%"
            )

    # ── Tabla por accion + grade ──────────────────────────────────────────
    action_rows = conn.execute(_ACTION_GRADE_QUERY, (args.horizon,)).fetchall()
    action_rows = [r for r in action_rows if r["total"] >= args.min_samples]

    if action_rows:
        print()
        print("-" * 65)
        print("  WIN RATE POR ACCION + GRADE")
        print("-" * 65)
        print(f"  {'Accion':<16} {'Grade':<10} {'Total':>6} {'WR%':>6}  {'AvgRet%':>8}")
        print("  " + "-" * 48)
        for r in action_rows:
            print(
                f"  {r['action']:<16} {r['grade']:<10} {r['total']:>6}"
                f" {_pct(r['wins'], r['total']):>6}  {(r['avg_return_pct'] or 0.0):>+8.2f}%"
            )

    print()
    print("  Para activar el gate cuando A/B supera C/NO_TRADE por >= 10pp:")
    print("    Agrega en .env:  ENABLE_SETUP_GATE=true")
    print("=" * 65)
    print()

    conn.close()


if __name__ == "__main__":
    main()
