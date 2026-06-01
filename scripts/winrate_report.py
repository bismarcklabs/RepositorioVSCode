import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3, datetime

conn = sqlite3.connect("data/crypto_dashboard.sqlite3")
conn.row_factory = sqlite3.Row

now = datetime.datetime.now(datetime.timezone.utc)

print("=" * 65)
print("ESTADO ACTUAL DE LA BASE DE DATOS")
print("=" * 65)
for tbl in ["trade_alerts", "alert_outcomes", "notification_log", "market_snapshots"]:
    n = conn.execute(f"SELECT COUNT(*) as n FROM {tbl}").fetchone()["n"]
    print(f"  {tbl:<22}: {n:,}")

row = conn.execute("SELECT MIN(timestamp) as mn, MAX(timestamp) as mx FROM trade_alerts").fetchone()
print(f"\n  Alertas desde: {row['mn']}")
print(f"  Alertas hasta: {row['mx']}")

print()
print("DISTRIBUCION DE SCORES (trade_alerts):")
for r in conn.execute("""
    SELECT
        CASE WHEN score < 60 THEN '<60'
             WHEN score < 65 THEN '60-64'
             WHEN score < 70 THEN '65-69'
             WHEN score < 75 THEN '70-74'
             WHEN score < 80 THEN '75-79'
             ELSE '80+' END as rango,
        COUNT(*) as cnt
    FROM trade_alerts GROUP BY rango ORDER BY rango
""").fetchall():
    print(f"  {r['rango']}: {r['cnt']}")

# Win rate por periodo con metricas corregidas
for hours in [1, 4, 8, 24]:
    cutoff = (now - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute("""
        SELECT
            ta.action,
            COUNT(DISTINCT ta.id) as total,
            SUM(CASE WHEN ao.outcome = 'win'     AND ao.horizon_minutes = 60 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN ao.outcome = 'partial'  AND ao.horizon_minutes = 60 THEN 1 ELSE 0 END) as partials,
            SUM(CASE WHEN ao.outcome = 'loss'     AND ao.horizon_minutes = 60 THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN ao.outcome = 'neutral'  AND ao.horizon_minutes = 60 THEN 1 ELSE 0 END) as neutrals,
            AVG(CASE WHEN ao.outcome IN ('win','partial','loss') AND ao.horizon_minutes = 60
                     THEN MAX(-50.0, MIN(50.0, ao.future_return_pct)) END) as avg_ret,
            AVG(CASE WHEN ao.outcome IN ('win','partial','loss') AND ao.horizon_minutes = 60
                     THEN ao.max_favorable_excursion END) as avg_mfe,
            AVG(CASE WHEN ao.outcome IN ('win','partial','loss') AND ao.horizon_minutes = 60
                     THEN ao.max_adverse_excursion END) as avg_mae
        FROM trade_alerts ta
        LEFT JOIN alert_outcomes ao ON ao.alert_id = ta.id
        WHERE ta.timestamp >= ?
        GROUP BY ta.action ORDER BY ta.action
    """, (cutoff,)).fetchall()

    if not rows:
        continue

    total_a = total_w = total_p = total_l = total_n = 0
    print(f"\n{'='*65}")
    print(f"WINRATE ULTIMAS {hours}h (horizonte 1h)")
    print(f"{'='*65}")
    print(f"  {'Accion':<16} {'Alerts':>6} {'Eval':>5} {'W':>4} {'P':>4} {'L':>4} {'N':>4} | {'WR%':>5} {'Dir%':>5} | {'AvgRet':>7} {'MFE':>6} {'MAE':>6}")
    print(f"  {'-'*60}")
    for r in rows:
        w=r['wins'] or 0; p=r['partials'] or 0; l=r['losses'] or 0; n=r['neutrals'] or 0
        ev = w+p+l
        wr  = round(w/ev*100,1) if ev else 0
        dir_wr = round((w+p)/ev*100,1) if ev else 0
        ret = f"{r['avg_ret']:+.2f}%" if r['avg_ret'] is not None else "  N/A "
        mfe = f"{r['avg_mfe']:+.2f}%" if r['avg_mfe'] is not None else "  N/A "
        mae = f"{r['avg_mae']:+.2f}%" if r['avg_mae'] is not None else "  N/A "
        total_a+=r['total']; total_w+=w; total_p+=p; total_l+=l; total_n+=n
        print(f"  {r['action']:<16} {r['total']:>6} {ev:>5} {w:>4} {p:>4} {l:>4} {n:>4} | {wr:>5.1f} {dir_wr:>5.1f} | {ret:>7} {mfe:>6} {mae:>6}")
    tev = total_w+total_p+total_l
    twr = round(total_w/tev*100,1) if tev else 0
    tdir = round((total_w+total_p)/tev*100,1) if tev else 0
    print(f"  {'-'*60}")
    print(f"  {'GLOBAL':<16} {total_a:>6} {tev:>5} {total_w:>4} {total_p:>4} {total_l:>4} {total_n:>4} | {twr:>5.1f} {tdir:>5.1f}")

# Top simbolos ultimas 24h
print(f"\n{'='*65}")
print("TOP SIMBOLOS (ultimas 24h, horizonte 1h, min 3 eval.)")
print("="*65)
cutoff24 = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
for r in conn.execute("""
    SELECT ta.symbol, ta.action,
           COUNT(DISTINCT ta.id) as total,
           SUM(CASE WHEN ao.outcome = 'win'    AND ao.horizon_minutes=60 THEN 1 ELSE 0 END) as wins,
           SUM(CASE WHEN ao.outcome = 'partial' AND ao.horizon_minutes=60 THEN 1 ELSE 0 END) as partials,
           SUM(CASE WHEN ao.outcome = 'loss'    AND ao.horizon_minutes=60 THEN 1 ELSE 0 END) as losses,
           AVG(CASE WHEN ao.outcome IN ('win','partial','loss') AND ao.horizon_minutes=60
                    THEN MAX(-50.0, MIN(50.0, ao.future_return_pct)) END) as avg_ret
    FROM trade_alerts ta
    LEFT JOIN alert_outcomes ao ON ao.alert_id = ta.id
    WHERE ta.timestamp >= ?
    GROUP BY ta.symbol, ta.action
    HAVING (wins+partials+losses) >= 3
    ORDER BY (wins+partials)*1.0/(wins+partials+losses) DESC, total DESC
    LIMIT 10
""", (cutoff24,)).fetchall():
    ev = (r['wins'] or 0)+(r['partials'] or 0)+(r['losses'] or 0)
    dir_wr = round(((r['wins'] or 0)+(r['partials'] or 0))/ev*100,1) if ev else 0
    ret = f"{r['avg_ret']:+.2f}%" if r['avg_ret'] is not None else "N/A"
    print(f"  {r['symbol']:<12} {r['action']:<16} eval={ev:>3} W={r['wins'] or 0} P={r['partials'] or 0} L={r['losses'] or 0} | Dir={dir_wr:.0f}% | ret={ret}")
