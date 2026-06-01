"""Módulo de inferencia ML — filtro de probabilidad P(TP1 antes de SL).

Carga el modelo entrenado por scripts/train_model.py y lo aplica en cada
ciclo del scanner como filtro suave (no bloqueo duro).

Uso típico en run_scanner.py:
    from app.ml_predictor import predictor
    predictor.load()           # una vez al arrancar
    prob = predictor.predict(result)   # None si no hay modelo
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import ML_ENABLED, ML_MODEL_PATH, ML_THRESHOLD

logger = logging.getLogger("ml_predictor")

# Features en el mismo orden que se usaron al entrenar
FEATURE_COLUMNS = [
    # Score compuesto y sub-scores
    "score", "flow_score", "technical_score", "footprint_score",
    "futures_score", "risk_penalty", "multi_exchange_score",
    # Flujo
    "delta", "cvd", "cvd_15m", "funding", "open_interest",
    "imbalance", "spread_pct",
    # Técnico
    "return_15m", "return_1h", "vwap_distance_pct", "above_vwap",
    "relative_volume", "rsi", "oi_change_pct",
    # Footprint
    "footprint_delta", "absorption_buy", "absorption_sell",
    "stacked_buy_imbalance", "stacked_sell_imbalance",
    # Multi-exchange (nullable — imputado con mediana en entrenamiento)
    "multi_exchange_confidence", "price_deviation_pct",
    "exchange_availability_score",
    # Acción codificada (LONG_FUTURES=0, SHORT_FUTURES=1, BUY_SPOT=2, SELL_SPOT=3)
    "action_code",
]

_ACTION_CODE = {
    "LONG_FUTURES":  0,
    "SHORT_FUTURES": 1,
    "BUY_SPOT":      2,
    "SELL_SPOT":     3,
}


def extract_features(result: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extrae el vector de features de un resultado de scan.

    Retorna None si faltan datos críticos.
    """
    sd  = result.get("score_data") or {}
    m   = result.get("metrics") or {}
    t   = result.get("technical") or {}
    fp  = result.get("footprint") or {}
    ob  = result.get("orderbook") or {}
    mx  = result.get("multi_exchange") or {}
    rec = result.get("recommendation") or {}

    action = rec.get("action", "WAIT")
    if action == "WAIT":
        return None  # no hay nada que filtrar

    return {
        # Score
        "score":                    float(sd.get("score", 0)),
        "flow_score":               float(sd.get("flow_score", 0)),
        "technical_score":          float(sd.get("technical_score", 0)),
        "footprint_score":          float(sd.get("footprint_score", 0)),
        "futures_score":            float(sd.get("futures_score", 0)),
        "risk_penalty":             float(sd.get("risk_penalty", 0)),
        "multi_exchange_score":     float(sd.get("multi_exchange_score", 0)),
        # Flujo
        "delta":                    float(m.get("delta", 0.0)),
        "cvd":                      float(m.get("cvd", 0.0)),
        "cvd_15m":                  float(m.get("cvd_15m", 0.0)),
        "funding":                  float(result.get("funding", 0.0)),
        "open_interest":            float(result.get("open_interest", 0.0)),
        "imbalance":                float(ob.get("imbalance", 0.0)),
        "spread_pct":               float(ob.get("spread_pct", 0.0)),
        # Técnico
        "return_15m":               float(t.get("return_15m", 0.0)),
        "return_1h":                float(t.get("return_1h", 0.0)),
        "vwap_distance_pct":        float(t.get("vwap_distance_pct", 0.0)),
        "above_vwap":               float(bool(t.get("above_vwap", True))),
        "relative_volume":          float(t.get("relative_volume", 1.0)),
        "rsi":                      float(t.get("rsi", 50.0)),
        "oi_change_pct":            float(result.get("oi_change_pct", 0.0)),
        # Footprint
        "footprint_delta":          float(fp.get("footprint_delta", 0.0)),
        "absorption_buy":           float(bool(fp.get("absorption_buy", False))),
        "absorption_sell":          float(bool(fp.get("absorption_sell", False))),
        "stacked_buy_imbalance":    float(bool(fp.get("stacked_buy_imbalance", False))),
        "stacked_sell_imbalance":   float(bool(fp.get("stacked_sell_imbalance", False))),
        # Multi-exchange (None → imputado con mediana en el pipeline sklearn)
        "multi_exchange_confidence":  mx.get("multi_exchange_confidence"),
        "price_deviation_pct":        mx.get("price_deviation_pct"),
        "exchange_availability_score":mx.get("exchange_availability_score"),
        # Acción
        "action_code":              float(_ACTION_CODE.get(action, -1)),
    }


class MLPredictor:
    """Carga y aplica el modelo entrenado. Thread-safe (sólo lectura tras load)."""

    def __init__(self) -> None:
        self._pipeline = None
        self._loaded   = False

    def load(self) -> bool:
        """Carga el modelo desde ML_MODEL_PATH. Retorna True si exitoso."""
        if not ML_ENABLED:
            return False
        path = Path(ML_MODEL_PATH)
        if not path.exists():
            logger.info("Modelo ML no encontrado en %s — ejecuta scripts/train_model.py", ML_MODEL_PATH)
            return False
        try:
            import joblib
            self._pipeline = joblib.load(str(path))
            self._loaded   = True
            logger.info("Modelo ML cargado desde %s", ML_MODEL_PATH)
            return True
        except Exception as exc:
            logger.warning("Error al cargar modelo ML: %s", exc)
            return False

    @property
    def available(self) -> bool:
        return ML_ENABLED and self._loaded and self._pipeline is not None

    def predict(self, result: Dict[str, Any]) -> Optional[float]:
        """Retorna P(TP1 antes de SL) ∈ [0,1], o None si el modelo no está disponible."""
        if not self.available:
            return None
        try:
            feats = extract_features(result)
            if feats is None:
                return None
            # El pipeline espera una lista de dicts o una matriz; usamos lista de filas
            row = [[feats.get(col) for col in FEATURE_COLUMNS]]
            prob = self._pipeline.predict_proba(row)[0][1]  # clase 1 = win
            return round(float(prob), 4)
        except Exception as exc:
            logger.debug("Error en predict: %s", exc)
            return None

    def apply_filter(
        self,
        result: Dict[str, Any],
        threshold: float = ML_THRESHOLD,
    ) -> Optional[float]:
        """Aplica el filtro ML al resultado y modifica la recomendación si corresponde.

        Lógica de filtrado:
          prob >= threshold         → sin cambio
          threshold*0.85 ≤ prob < threshold → reducir confidence 10 pts + warning
          prob < threshold*0.85     → degradar a WAIT

        Retorna la probabilidad calculada (o None si modelo no disponible).
        """
        prob = self.predict(result)
        if prob is None:
            return None

        rec    = result.get("recommendation") or {}
        action = rec.get("action", "WAIT")
        if action == "WAIT":
            return prob

        prob_str = f"{prob:.2f}"
        low_threshold = threshold * 0.85  # zona gris

        if prob < low_threshold:
            rec["action"]   = "WAIT"
            rec["market"]   = "NONE"
            rec.setdefault("warnings", []).append(
                f"ML: prob(TP1)={prob_str} — setup filtrado (umbral {threshold:.2f})"
            )
            logger.debug("ML FILTER %s: prob=%s < %.2f → WAIT", result.get("symbol"), prob_str, low_threshold)

        elif prob < threshold:
            rec["confidence"] = max(40, rec.get("confidence", 50) - 10)
            rec.setdefault("warnings", []).append(
                f"ML: prob(TP1)={prob_str} — confianza reducida (zona de incertidumbre)"
            )

        # Añadir probabilidad al resultado para análisis posterior
        result["ml_probability"] = prob
        return prob


# Instancia global — se carga una vez en run_scanner.py con predictor.load()
predictor = MLPredictor()
