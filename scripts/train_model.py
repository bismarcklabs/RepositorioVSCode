"""Entrenamiento del modelo ML para filtro de probabilidad de TP1.

Uso:
    python scripts/train_model.py [--db PATH] [--out PATH] [--horizon N] [--min-samples N]

Lee trade_alerts + market_snapshots + alert_outcomes de la base local,
construye un RandomForestClassifier y lo guarda en data/ml_model.pkl.
"""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATABASE_PATH, ML_MODEL_PATH, ML_MIN_SAMPLES
from app.ml_predictor import FEATURE_COLUMNS, _ACTION_CODE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("train_model")

_INV_ACTION = {v: k for k, v in _ACTION_CODE.items()}


# ── Carga de datos ────────────────────────────────────────────────────────

_QUERY = """
SELECT
    -- alert
    ta.id               AS alert_id,
    ta.action,
    ta.timestamp        AS alert_ts,
    ta.symbol,
    -- snapshot features (snapshot más cercano al momento de la alerta)
    ms.score,
    ms.flow_score,
    ms.technical_score,
    ms.footprint_score,
    ms.futures_score,
    ms.risk_penalty,
    ms.multi_exchange_score,
    ms.delta,
    ms.cvd,
    ms.cvd_15m,
    ms.funding,
    ms.open_interest,
    ms.imbalance,
    ms.spread_pct,
    ms.return_15m,
    ms.return_1h,
    ms.vwap_distance_pct,
    ms.above_vwap,
    ms.relative_volume,
    ms.rsi,
    ms.oi_change_pct,
    ms.footprint_delta,
    ms.absorption_buy,
    ms.absorption_sell,
    ms.stacked_buy_imbalance,
    ms.stacked_sell_imbalance,
    ms.multi_exchange_confidence,
    ms.price_deviation_pct,
    ms.exchange_availability_score,
    -- outcomes
    ao.hit_tp1,
    ao.hit_stop,
    ao.outcome
FROM trade_alerts ta
JOIN market_snapshots ms ON ms.id = (
    SELECT ms2.id
    FROM market_snapshots ms2
    WHERE ms2.symbol = ta.symbol
      AND ms2.timestamp <= ta.timestamp
    ORDER BY ms2.timestamp DESC
    LIMIT 1
)
JOIN alert_outcomes ao ON ao.alert_id = ta.id
WHERE ta.action != 'WAIT'
  AND (ao.hit_tp1 = 1 OR ao.hit_stop = 1)
"""


def load_training_data(db_path: str, horizon: int) -> list:
    """Carga filas de entrenamiento para el horizonte dado."""
    query = _QUERY + f"\n  AND ao.horizon_minutes = {horizon}"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def build_dataset(rows: list):
    """Construye X (features) e y (labels) desde las filas de la DB.

    Label: 1 = hit_tp1 llegó primero (win), 0 = hit_stop llegó primero (loss).
    Filas donde ambos son 1 (improbable pero posible) se excluyen.
    """
    X, y, meta = [], [], []

    for r in rows:
        tp1   = int(r["hit_tp1"] or 0)
        stop  = int(r["hit_stop"] or 0)

        # Excluir ambiguous (ambos 1 o ninguno, aunque el filtro WHERE ya los acota)
        if tp1 == stop:
            continue

        label = 1 if tp1 else 0

        action_code = float(_ACTION_CODE.get(r["action"], -1))
        if action_code < 0:
            continue  # acción desconocida

        feats = []
        valid = True
        for col in FEATURE_COLUMNS:
            if col == "action_code":
                feats.append(action_code)
            else:
                val = r.get(col)
                # None → NaN para que el imputer lo maneje
                feats.append(float(val) if val is not None else float("nan"))
                # Si un feature crítico falta totalmente, no es NaN sino que
                # simplemente será imputado — no necesitamos descartar la fila
        if not valid:
            continue

        X.append(feats)
        y.append(label)
        meta.append({"alert_id": r["alert_id"], "symbol": r["symbol"], "action": r["action"]})

    return X, y, meta


# ── Entrenamiento ─────────────────────────────────────────────────────────

def train(X, y, n_estimators: int = 200, max_depth: int = 6):
    try:
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            roc_auc_score,
        )
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.pipeline import Pipeline
    except ImportError as e:
        logger.error("Faltan dependencias: %s — instala con: pip install scikit-learn", e)
        sys.exit(1)

    Xa = np.array(X, dtype=float)
    ya = np.array(y, dtype=int)

    n_wins  = int(ya.sum())
    n_loss  = len(ya) - n_wins
    logger.info("Dataset: %d muestras (%d wins / %d losses)", len(ya), n_wins, n_loss)

    X_train, X_test, y_train, y_test = train_test_split(
        Xa, ya, test_size=0.2, random_state=42, stratify=ya
    )

    pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf",     RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=4,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )),
    ])

    pipeline.fit(X_train, y_train)

    y_pred  = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    auc = roc_auc_score(y_test, y_proba) if len(set(y_test)) > 1 else float("nan")

    print("\n" + "=" * 60)
    print(f"  Accuracy:  {acc:.3f}    AUC-ROC: {auc:.3f}")
    print("=" * 60)
    print(classification_report(y_test, y_pred, target_names=["loss", "win"]))

    # CV score (3-fold — robusto para datasets pequeños)
    cv_scores = cross_val_score(pipeline, Xa, ya, cv=3, scoring="roc_auc")
    print(f"  CV AUC (3-fold): {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")

    # Feature importance
    clf = pipeline.named_steps["clf"]
    importances = sorted(
        zip(FEATURE_COLUMNS, clf.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    print("\n  Top-15 features por importancia:")
    for feat, imp in importances[:15]:
        bar = "#" * int(imp * 200)
        print(f"    {feat:<35} {imp:.4f}  {bar}")

    return pipeline


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena el modelo ML del scanner")
    parser.add_argument("--db",          default=str(ROOT / DATABASE_PATH))
    parser.add_argument("--out",         default=str(ROOT / ML_MODEL_PATH))
    parser.add_argument("--horizon",     type=int, default=60,
                        help="Horizonte en minutos para la etiqueta (default: 60)")
    parser.add_argument("--min-samples", type=int, default=ML_MIN_SAMPLES)
    parser.add_argument("--estimators",  type=int, default=200)
    parser.add_argument("--depth",       type=int, default=6)
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        logger.error("Base de datos no encontrada: %s", db_path)
        sys.exit(1)

    logger.info("Cargando datos desde %s (horizonte=%dm)...", db_path, args.horizon)
    rows = load_training_data(db_path, args.horizon)
    if not rows:
        logger.warning("Sin datos — necesitas alertas con outcomes registrados.")
        logger.warning("Deja correr el scanner + outcome_tracker al menos %d horas.", args.horizon // 60 + 1)
        sys.exit(0)

    X, y, meta = build_dataset(rows)

    if len(y) < args.min_samples:
        logger.warning(
            "Solo %d muestras etiquetadas (mínimo: %d). Modelo no entrenado.",
            len(y), args.min_samples,
        )
        logger.warning("Distribución de acciones en los datos crudos:")
        from collections import Counter
        actions = Counter(r["action"] for r in rows)
        for action, count in actions.most_common():
            logger.warning("  %-20s %d", action, count)
        sys.exit(0)

    print(f"\nEntrando RandomForest con {len(y)} muestras etiquetadas "
          f"({args.estimators} árboles, depth={args.depth})...")

    pipeline = train(X, y, n_estimators=args.estimators, max_depth=args.depth)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump(pipeline, str(out_path))
        print(f"\n  Modelo guardado en: {out_path}")
    except Exception as exc:
        logger.error("Error al guardar el modelo: %s", exc)
        sys.exit(1)

    # Estadística de acciones en training set
    from collections import Counter
    action_dist = Counter(m["action"] for m in meta)
    print("\n  Distribucion de acciones en dataset:")
    for action, count in action_dist.most_common():
        print(f"    {action:<20} {count}")

    print("\n  Para activar el filtro ML:")
    print("    export ML_ENABLED=true")
    print(f"   export ML_MODEL_PATH={out_path}")
    print("    (o agrega estas variables en tu .env)")


if __name__ == "__main__":
    main()
