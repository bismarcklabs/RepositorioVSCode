"""Tests de niveles S/R estructurales en el constructor de entry/SL/TP."""
from app.entry_exit import calculate_entry_exit


def _structure(levels):
    return {"levels": [{"price": p, "touches": 3, "strength": 35.0} for p in levels]}


def test_pullback_entry_targets_structural_support():
    technical = {"vwap": 98.0, "vwap_distance_pct": 2.0, "above_vwap": True, "atr": 1.0}
    # Sin estructura el pullback apunta al VWAP (98)
    base = calculate_entry_exit("LONG_FUTURES", 100.0, technical, None, None)
    assert base["timing"] == "WAIT_FOR_PULLBACK"
    assert base["entry"] == 98.0
    # Con soporte estructural en 99 (más cercano que el VWAP), el pullback es al soporte
    with_struct = calculate_entry_exit(
        "LONG_FUTURES", 100.0, technical, None, None, structure=_structure([99.0]))
    assert with_struct["entry"] == 99.0


def test_tp1_at_structural_resistance():
    technical = {"vwap": 99.9, "vwap_distance_pct": 0.1, "above_vwap": True, "atr": 0.0}
    setup = calculate_entry_exit(
        "LONG_FUTURES", 100.0, technical, None, None,
        structure=_structure([103.5, 97.0]))
    assert setup["timing"] == "NOW"
    # min TP1 = entry + 1.5R = 103 (stop en el piso de 2%); la resistencia 103.5 lo supera
    assert setup["take_profit_1"] == 103.5


def test_short_pullback_targets_structural_resistance():
    technical = {"vwap": 102.0, "vwap_distance_pct": -2.0, "above_vwap": False, "atr": 1.0}
    base = calculate_entry_exit("SHORT_FUTURES", 100.0, technical, None, None)
    assert base["entry"] == 102.0
    with_struct = calculate_entry_exit(
        "SHORT_FUTURES", 100.0, technical, None, None, structure=_structure([101.0]))
    assert with_struct["entry"] == 101.0


def test_no_structure_behaves_as_before():
    technical = {"vwap": 99.9, "vwap_distance_pct": 0.1, "above_vwap": True, "atr": 0.5}
    a = calculate_entry_exit("LONG_FUTURES", 100.0, technical, None, None)
    b = calculate_entry_exit("LONG_FUTURES", 100.0, technical, None, None, structure=None)
    assert a == b
