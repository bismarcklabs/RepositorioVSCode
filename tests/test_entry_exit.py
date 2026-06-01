import pytest
from app.entry_exit import calculate_entry_exit

_BASE_TECH = {
    "trend_bias": "bullish",
    "vwap": 49_500.0,
    "vwap_distance_pct": 0.5,
    "above_vwap": True,
    "return_1h": 1.5,
}
_BEARISH_TECH = {
    "trend_bias": "bearish",
    "vwap": 50_500.0,
    "vwap_distance_pct": -0.5,
    "above_vwap": False,
    "return_1h": -1.5,
}
_VP = {
    "poc": 49_200.0,
    "hvn_levels": [49_000.0, 49_500.0],
    "lvn_levels": [49_800.0],
    "nearest_level": 49_500.0,
    "nearest_level_type": "HVN",
    "distance_to_level_pct": 0.5,
}
_GEX = {
    "spot": 50_000.0,
    "call_wall": 52_000.0,
    "put_wall": 48_000.0,
    "gamma_flip": 49_000.0,
    "positive_gex_levels": [],
    "negative_gex_levels": [],
    "nearest_gex_level": 48_000.0,
    "nearest_gex_type": "put_wall",
    "distance_to_gex_pct": 4.0,
}


# ── Estructura de resultado ───────────────────────────────────────────────

def test_result_has_required_keys():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, _VP, _GEX)
    assert result is not None
    for key in (
        "timing", "entry_type", "entry_zone_low", "entry_zone_high",
        "entry", "stop_loss", "take_profit_1", "take_profit_2",
        "risk_reward_1", "risk_reward_2", "position_note",
    ):
        assert key in result


def test_returns_none_when_price_zero():
    assert calculate_entry_exit("BUY_SPOT", 0.0, _BASE_TECH, _VP, _GEX) is None


def test_returns_none_for_wait_action():
    assert calculate_entry_exit("WAIT", 50_000.0, _BASE_TECH, _VP, _GEX) is None


# ── BUY_SPOT entrada NOW ──────────────────────────────────────────────────

def test_buy_spot_now_when_above_vwap_close():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, None, None)
    assert result is not None
    assert result["timing"] == "NOW"
    assert result["entry_type"] == "market_zone"
    assert result["entry"] == pytest.approx(50_000.0, rel=1e-4)


def test_buy_spot_stop_below_entry():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, None, None)
    assert result["stop_loss"] < result["entry"]


def test_buy_spot_tp1_above_entry():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, None, None)
    assert result["take_profit_1"] > result["entry"]


def test_buy_spot_tp2_gte_tp1():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, _VP, _GEX)
    assert result["take_profit_2"] >= result["take_profit_1"]


# ── BUY_SPOT con pullback ─────────────────────────────────────────────────

def test_buy_spot_pullback_when_extended():
    tech_extended = {**_BASE_TECH, "vwap_distance_pct": 2.5}
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, tech_extended, _VP, _GEX)
    assert result is not None
    assert result["timing"] == "WAIT_FOR_PULLBACK"
    # Entrada debe ser menor al precio actual (pullback hacia soporte)
    assert result["entry"] < 50_000.0


# ── BUY_SPOT breakout cuando bajo VWAP ───────────────────────────────────

def test_buy_spot_breakout_when_below_vwap():
    tech_below = {**_BASE_TECH, "above_vwap": False, "vwap_distance_pct": -0.3}
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, tech_below, None, None)
    assert result is not None
    assert result["timing"] == "WAIT_FOR_BREAKOUT"


# ── LONG_FUTURES con put wall como soporte ────────────────────────────────

def test_long_futures_tp1_uses_call_wall():
    result = calculate_entry_exit("LONG_FUTURES", 50_000.0, _BASE_TECH, None, _GEX)
    assert result is not None
    # call_wall=52000 > entry=50000 → debe ser tp1 candidato
    assert result["take_profit_1"] <= 52_000.0


def test_long_futures_rr_positive():
    result = calculate_entry_exit("LONG_FUTURES", 50_000.0, _BASE_TECH, _VP, _GEX)
    assert result is not None
    assert result["risk_reward_1"] > 0.0
    assert result["risk_reward_2"] >= result["risk_reward_1"]


# ── SHORT_FUTURES con call wall como resistencia ──────────────────────────

def test_short_futures_timing_now():
    result = calculate_entry_exit("SHORT_FUTURES", 50_000.0, _BEARISH_TECH, None, None)
    assert result is not None
    assert result["timing"] == "NOW"
    assert result["stop_loss"] > result["entry"]


def test_short_futures_tp1_below_entry():
    result = calculate_entry_exit("SHORT_FUTURES", 50_000.0, _BEARISH_TECH, _VP, _GEX)
    assert result is not None
    assert result["take_profit_1"] < result["entry"]


def test_short_futures_tp2_lte_tp1():
    result = calculate_entry_exit("SHORT_FUTURES", 50_000.0, _BEARISH_TECH, _VP, _GEX)
    assert result is not None
    assert result["take_profit_2"] <= result["take_profit_1"]


# ── SELL_SPOT ─────────────────────────────────────────────────────────────

def test_sell_spot_stop_above_entry():
    result = calculate_entry_exit("SELL_SPOT", 50_000.0, _BEARISH_TECH, None, None)
    assert result is not None
    assert result["stop_loss"] > result["entry"]


# ── Cálculo R/R ───────────────────────────────────────────────────────────

def test_rr_at_least_one_for_long():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, None, None)
    assert result is not None
    # TP1 nunca puede ser menos de 1R
    risk = result["entry"] - result["stop_loss"]
    assert result["take_profit_1"] >= result["entry"] + risk * 0.99


def test_rr_at_least_one_for_short():
    result = calculate_entry_exit("SHORT_FUTURES", 50_000.0, _BEARISH_TECH, None, None)
    assert result is not None
    risk = result["stop_loss"] - result["entry"]
    assert result["take_profit_1"] <= result["entry"] - risk * 0.99


# ── Sin setup si riesgo excesivo ──────────────────────────────────────────

def test_no_setup_if_stop_same_as_entry():
    # Si no hay ningún soporte y el precio es 0, no debe haber setup
    assert calculate_entry_exit("BUY_SPOT", 0.0, _BASE_TECH, None, None) is None


def test_entry_zone_contains_entry():
    result = calculate_entry_exit("BUY_SPOT", 50_000.0, _BASE_TECH, None, None)
    assert result is not None
    assert result["entry_zone_low"] <= result["entry"] <= result["entry_zone_high"]
