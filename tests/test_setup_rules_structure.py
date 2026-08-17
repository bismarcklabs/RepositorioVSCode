"""Tests de la integración de estructura (S/R, breakouts, patrones) en setup_rules."""
from app.setup_rules import evaluate_trade_setup


def _eval(action="LONG_FUTURES", structure=None, trigger=None):
    return evaluate_trade_setup(
        action=action,
        technical={"above_vwap": action in ("LONG_FUTURES", "BUY_SPOT"),
                   "trend_bias": "neutral", "htf_trend_bias": "neutral"},
        metrics={"delta": 100 if "LONG" in action or "BUY" in action else -100,
                 "cvd": 100 if "LONG" in action or "BUY" in action else -100},
        footprint=None,
        volume_profile=None,
        gex_data=None,
        setup={"risk_reward_1": 1.6, "risk_pct": 2.0},
        trigger=trigger,
        structure=structure,
    )


def test_level_breakout_route_long():
    structure = {
        "breakout": {"direction": "up", "confirmed": True, "touches": 3,
                     "margin_pct": 0.4, "rvol": 2.1, "level": 110.0, "strength": 40.0},
        "patterns": [],
    }
    ev = _eval("LONG_FUTURES", structure)
    assert ev.setup_route == "level_breakout"
    assert ev.trigger_type == "level_breakout_up"
    assert ev.checklist["trigger_ok"] is True


def test_unconfirmed_breakout_does_not_trigger():
    structure = {
        "breakout": {"direction": "up", "confirmed": False, "touches": 2,
                     "margin_pct": 0.1, "rvol": 1.0, "level": 110.0, "strength": 20.0},
        "patterns": [],
    }
    ev = _eval("LONG_FUTURES", structure)
    assert ev.setup_route != "level_breakout"
    assert ev.checklist["trigger_ok"] is False


def test_pattern_break_route_short():
    structure = {
        "breakout": None,
        "patterns": [{"pattern": "head_and_shoulders", "direction": "short",
                      "confirmed": True, "neckline": 99.5, "target": 86.5,
                      "extreme": 112.5}],
    }
    ev = _eval("SHORT_FUTURES", structure)
    assert ev.setup_route == "pattern_break"
    assert ev.trigger_type == "head_and_shoulders_break"


def test_opposing_confirmed_pattern_penalizes():
    structure = {
        "breakout": None,
        "patterns": [{"pattern": "double_top", "direction": "short",
                      "confirmed": True, "neckline": 97.5, "target": 84.0,
                      "extreme": 110.5}],
    }
    base = _eval("LONG_FUTURES", None)
    penalized = _eval("LONG_FUTURES", structure)
    assert penalized.score < base.score
    assert any("contrario" in w for w in penalized.warnings)


def test_structural_level_gives_level_ok():
    structure = {
        "breakout": None,
        "patterns": [],
        "nearest_support": {"price": 99.0, "touches": 3, "strength": 35.0,
                            "distance_pct": 0.8},
    }
    ev = _eval("LONG_FUTURES", structure)
    assert ev.checklist["level_ok"] is True


def test_no_structure_keeps_previous_behavior():
    ev = _eval("LONG_FUTURES", None,
               trigger={"type": "bullish_engulfing", "direction": "long", "strength": 80})
    assert ev.setup_route == "classic_trigger"
    assert ev.checklist["trigger_ok"] is True


def test_pattern_bounce_route_long():
    structure = {
        "breakout": None,
        "patterns": [{"pattern": "double_bottom", "direction": "long",
                      "confirmed": False, "bounce_valid": True,
                      "bounce_progress_pct": 30.0, "bounce_age_candles": 2,
                      "neckline": 103.0, "target": 117.0, "extreme": 90.0}],
    }
    ev = _eval("LONG_FUTURES", structure)
    assert ev.setup_route == "pattern_bounce"
    assert ev.trigger_type == "double_bottom_bounce"
    assert ev.checklist["trigger_ok"] is True


def test_pattern_bounce_yields_to_classic_trigger():
    # Si ya hay un gatillo clásico de price action, ese tiene prioridad sobre el rebote
    structure = {
        "breakout": None,
        "patterns": [{"pattern": "double_bottom", "direction": "long",
                      "confirmed": False, "bounce_valid": True,
                      "bounce_progress_pct": 30.0, "bounce_age_candles": 2,
                      "neckline": 103.0, "target": 117.0, "extreme": 90.0}],
    }
    ev = _eval("LONG_FUTURES", structure,
               trigger={"type": "bullish_engulfing", "direction": "long", "strength": 80})
    assert ev.setup_route == "classic_trigger"


def test_pattern_bounce_yields_to_confirmed_pattern_break():
    # Si el mismo patrón ya rompió neckline, pattern_break gana sobre el rebote pre-ruptura
    structure = {
        "breakout": None,
        "patterns": [
            {"pattern": "double_bottom", "direction": "long", "confirmed": True,
             "bounce_valid": False, "neckline": 103.0, "target": 117.0, "extreme": 90.0},
        ],
    }
    ev = _eval("LONG_FUTURES", structure)
    assert ev.setup_route == "pattern_break"


def test_opposing_bounce_pattern_penalizes():
    structure = {
        "breakout": None,
        "patterns": [{"pattern": "double_top", "direction": "short",
                      "confirmed": False, "bounce_valid": True,
                      "bounce_progress_pct": 25.0, "bounce_age_candles": 2,
                      "neckline": 97.5, "target": 84.0, "extreme": 110.5}],
    }
    base = _eval("LONG_FUTURES", None)
    penalized = _eval("LONG_FUTURES", structure)
    assert penalized.score < base.score
    assert any("contrario" in w and "rebote" in w for w in penalized.warnings)
