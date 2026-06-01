import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlite3

conn = sqlite3.connect("data/crypto_dashboard.sqlite3")
conn.row_factory = sqlite3.Row

for tbl in ["trade_alerts", "alert_outcomes", "notification_log", "market_snapshots"]:
    n = conn.execute(f"SELECT COUNT(*) as n FROM {tbl}").fetchone()["n"]
    print(f"{tbl}: {n:,} registros")

print()
row = conn.execute("SELECT MIN(timestamp) as mn, MAX(timestamp) as mx FROM trade_alerts").fetchone()
print(f"trade_alerts rango: {row['mn']} -> {row['mx']}")

print()
print("Distribucion de scores en trade_alerts:")
for r in conn.execute("""
    SELECT
        CASE WHEN score < 60 THEN '<60'
             WHEN score < 65 THEN '60-64'
             WHEN score < 70 THEN '65-69'
             WHEN score < 75 THEN '70-74'
             ELSE '75+' END as rango,
        COUNT(*) as cnt
    FROM trade_alerts
    GROUP BY rango ORDER BY rango
""").fetchall():
    print(f"  {r['rango']}: {r['cnt']}")

print()
print("Alertas por hora (ultimas 24h):")
for r in conn.execute("""
    SELECT substr(timestamp, 1, 13) as hora, COUNT(*) as cnt
    FROM trade_alerts
    WHERE timestamp >= datetime('now', '-24 hours')
    GROUP BY hora ORDER BY hora
""").fetchall():
    print(f"  {r['hora']}: {r['cnt']}")
