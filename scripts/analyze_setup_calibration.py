"""Compara el grado original contra el calibrado usando outcomes a 60 minutos."""
from app import database


def main() -> None:
    database.init_db()
    rows = database._get_conn().execute(
        """SELECT original_setup_grade, calibrated_grade, ta.action,
                  COUNT(*) total,
                  SUM(CASE WHEN ao.outcome IN ('win','partial') THEN 1 ELSE 0 END) wins,
                  AVG(ao.future_return_pct) avg_return
           FROM trade_alerts ta
           LEFT JOIN alert_outcomes ao ON ao.alert_id=ta.id AND ao.horizon_minutes=60
           WHERE calibrated_grade <> ''
           GROUP BY original_setup_grade, calibrated_grade, ta.action
           ORDER BY total DESC"""
    ).fetchall()
    for row in rows:
        total = row["total"] or 0
        wins = row["wins"] or 0
        print(dict(row), "directional_wr=", round(100 * wins / total, 1) if total else 0)


if __name__ == "__main__":
    main()