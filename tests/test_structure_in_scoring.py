"""Tests de _structure_score y su integración en calculate_opportunity_score."""
from app.scoring import _structure_score, calculate_opportunity_score


_BRK_UP = {"direction": "up", "confirmed": True, "touches": 3,
           "margin_pct": 0.4, "rvol": 2.0, "level": 110.0, "strength": 40.0}


def test_aligned_breakout_scores_positive():
    pts, reasons = _structure_score({"breakout": _BRK_UP, "patterns": []}, "accumulation")
    assert pts >= 10
    assert any("Ruptura" in r for r in reasons)


def test_opposed_breakout_scores_negative():
    brk_down = {**_BRK_UP, "direction": "down"}
    pts, _ = _structure_score({"breakout": brk_down, "patterns": []}, "accumulation")
    assert pts < 0


def test_confirmed_pattern_aligned_adds_points():
    structure = {"breakout": None,
                 "patterns": [{"pattern": "double_bottom", "direction": "long",
                               "confirmed": True, "neckline": 100.0}]}
    pts, reasons = _structure_score(structure, "accumulation")
    assert pts >= 6
    assert any("double_bottom" in r for r in reasons)


def test_support_proximity_bullish():
    structure = {"breakout": None, "patterns": [],
                 "nearest_support": {"price": 99.5, "touches": 4,
                                     "strength": 45.0, "distance_pct": 0.5}}
    pts, _ = _structure_score(structure, "accumulation")
    assert pts == 5


def test_no_structure_is_zero():
    assert _structure_score(None, "accumulation") == (0, [])


def test_bounce_valid_pattern_aligned_adds_smaller_bonus():
    structure = {"breakout": None,
                 "patterns": [{"pattern": "double_bottom", "direction": "long",
                               "confirmed": False, "bounce_valid": True,
                               "bounce_progress_pct": 30.0, "neckline": 100.0}]}
    pts, reasons = _structure_score(structure, "accumulation")
    assert pts == 4
    assert any("2a pata" in r for r in reasons)


def test_confirmed_pattern_takes_priority_over_bounce():
    # Un patron distinto ya confirmado no debe sumar ademas el bonus de rebote
    structure = {"breakout": None,
                 "patterns": [
                     {"pattern": "double_top", "direction": "long",
                      "confirmed": True, "bounce_valid": False, "neckline": 100.0},
                 ]}
    pts, reasons = _structure_score(structure, "accumulation")
    assert pts == 6
    assert not any("2a pata" in r for r in reasons)


def test_opportunity_score_includes_structure_component():
    score_data = calculate_opportunity_score(
        symbol="BTCUSDT",
        metrics={"delta": 500, "cvd": 1000, "cvd_15m": 300},
        signal="accumulation",
        funding=0.0001,
        open_interest=1_000_000,
        imbalance=0.1,
        spread_pct=0.01,
        technical={"relative_volume": 1.2, "return_5m": 0.1, "return_15m": 0.2},
        liquidation_summary=None,
        structure={"breakout": _BRK_UP, "patterns": []},
    )
    assert "structure_score" in score_data
    assert score_data["structure_score"] >= 10
