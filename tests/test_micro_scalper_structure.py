"""Tests del método por niveles del micro-scalp (rebote en S/R + TP recortado)."""
from app.micro_scalper import _build_setup, calculate_micro_scalp_score


def _inputs():
    technical = {
        "return_3m": 0.18, "return_5m": 0.35, "relative_volume": 2.5,
        "above_vwap": True, "vwap_distance_pct": 0.4, "atr": 0.2,
    }
    metrics = {"delta": 1200, "cvd_15m": 3500}
    footprint = {"footprint_delta": 900}
    orderbook = {"imbalance": 0.22, "spread_pct": 0.02}
    return technical, metrics, footprint, orderbook


def test_support_proximity_boosts_long_score():
    technical, metrics, footprint, orderbook = _inputs()
    base, _, _, is_level_base = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0)
    structure = {"nearest_support": {"price": 99.8, "touches": 3,
                                     "strength": 35.0, "distance_pct": 0.2}}
    boosted, reasons, _, is_level_boosted = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0,
        None, structure)
    assert boosted > base
    assert any("soporte" in r.lower() for r in reasons)
    assert is_level_base is False
    assert is_level_boosted is True


def test_resistance_proximity_penalizes_long_score():
    technical, metrics, footprint, orderbook = _inputs()
    base, _, _, _ = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0)
    structure = {"nearest_resistance": {"price": 100.2, "touches": 3,
                                        "strength": 35.0, "distance_pct": 0.2}}
    penalized, _, warnings, _ = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0,
        None, structure)
    assert penalized < base
    assert any("resistencia" in w.lower() for w in warnings)


def test_broken_support_blocks_dip_buying():
    technical, metrics, footprint, orderbook = _inputs()
    structure = {"breakout": {"direction": "down", "confirmed": True,
                              "level": 99.0, "touches": 2, "margin_pct": 0.5,
                              "rvol": 2.0, "strength": 25.0}}
    base, _, _, _ = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0)
    penalized, _, warnings, _ = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0,
        None, structure)
    assert penalized < base
    assert any("roto" in w.lower() for w in warnings)


def test_tp_capped_below_resistance():
    # Sin estructura: tp2 = 100 * 0.0055 = 0.55 de distancia
    free = _build_setup("MICRO_LONG_SCALP", 100.0, 0.0)
    assert free["take_profit_2"] > 100.3
    # Con resistencia a 100.3, el TP2 se recorta antes del nivel
    structure = {"nearest_resistance": {"price": 100.3, "touches": 3,
                                        "strength": 35.0, "distance_pct": 0.3}}
    capped = _build_setup("MICRO_LONG_SCALP", 100.0, 0.0, structure)
    assert capped["take_profit_2"] < 100.3
    assert capped["take_profit_1"] <= capped["take_profit_2"]
    # El SL no cambia
    assert capped["stop_loss"] == free["stop_loss"]


def test_pattern_bounce_boosts_level_rebound_score():
    technical, metrics, footprint, orderbook = _inputs()
    structure_plain = {"nearest_support": {"price": 99.8, "touches": 3,
                                           "strength": 35.0, "distance_pct": 0.2}}
    plain, _, _, _ = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0, None, structure_plain)
    structure_pattern = {
        **structure_plain,
        "patterns": [{"pattern": "double_bottom", "direction": "long",
                      "confirmed": False, "bounce_valid": True,
                      "bounce_progress_pct": 28.0, "bounce_age_candles": 2,
                      "neckline": 103.0, "target": 117.0, "extreme": 90.0}],
    }
    boosted, reasons, _, _ = calculate_micro_scalp_score(
        "long", technical, metrics, footprint, orderbook, 0.0, 1.0, None, structure_pattern)
    assert boosted > plain
    assert any("2a pata" in r for r in reasons)


def test_tp_capped_above_support_for_short():
    structure = {"nearest_support": {"price": 99.7, "touches": 3,
                                     "strength": 35.0, "distance_pct": 0.3}}
    capped = _build_setup("MICRO_SHORT_SCALP", 100.0, 0.0, structure)
    assert capped["take_profit_2"] > 99.7
