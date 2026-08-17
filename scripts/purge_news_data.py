# -*- coding: utf-8 -*-
"""Purga total de datos de noticias para empezar de cero.

Contexto (2026-07-17): el matching símbolo↔noticia por substring generó miles
de asociaciones falsas (AUSDT con 4,327 "noticias", POWERUSDT con notas de
estaciones de energía, etc.), contaminando news_events, news_predictions y las
security_event_alerts derivadas. El matching ya fue corregido en
app/news_intelligence.py; este script borra el histórico contaminado con
respaldo comprimido previo. Aprobado por el usuario: purgar todo y reiniciar.

Uso:  python scripts/purge_news_data.py            (dry-run: solo conteos)
      python scripts/purge_news_data.py --apply    (respalda y borra)
"""
import gzip
import io
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DATABASE_PATH  # noqa: E402

TABLES = ("news_events", "news_predictions", "security_event_alerts")
APPLY = "--apply" in sys.argv


def main() -> None:
    conn = sqlite3.connect(str(ROOT / DATABASE_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    for table, n in counts.items():
        print(f"{table}: {n} filas")
    total = sum(counts.values())
    print(f"TOTAL: {total} filas")

    if not APPLY:
        print("\nDry-run — nada borrado. Ejecutar con --apply para purgar.")
        return

    if total:
        out = ROOT / "outputs" / f"news_backup_{time.strftime('%Y%m%d_%H%M%S')}.json.gz"
        out.parent.mkdir(exist_ok=True)
        backup = {t: [dict(r) for r in c.execute(f"SELECT * FROM {t}").fetchall()] for t in TABLES}
        with gzip.open(out, "wt", encoding="utf-8") as f:
            json.dump(backup, f, default=str)
        print(f"\nRespaldo: {out} ({out.stat().st_size / 1e6:.1f} MB)")

    for table in TABLES:
        c.execute(f"DELETE FROM {table}")
    conn.commit()
    remaining = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    print(f"Purga aplicada. Filas restantes: {remaining}")
    conn.close()


if __name__ == "__main__":
    main()
