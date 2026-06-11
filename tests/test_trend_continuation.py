import pytest
from app.trend_continuation import (
    is_long_momentum_continuation,
    is_short_momentum_continuation,
    calculate_trend_priority_score,
)


# ── Snapshots de referencia ────────────────────────────────────────────────

_LONG_SNAP = {
    "technical": {
        "trend_bias":       "bullish",
        "htf_trend_bias":   "bullish",
        "above_vwap":       True,
        "return_1h":        3.0,
        "return_15m":       1.0,
        "return_5m":        0.4,
        "relative_volume":  1.8,
        "vwap_distance_pct": 3.0,
    },
    "metrics": {"cvd_15m": 800, "cvd": 3000},
    "funding": 0.0002,
}

_SHORT_SNAP = {
    "technical": {
        "trend_bias":       "bearish",
        "htf_trend_bias":   "bearish",
        "above_vwap":       False,
        "return_1h":        -3.0,
        "return_15m":       -1.0,
        "return_5m":        -0.4,
        "relative_volume":  1.8,
        "vwap_distance_pct": -3.0,
    },
    "metrics": {"cvd_15m": -800, "cvd": -3000},
    "funding": 0.0002,
}


# ── is_long_momentum_continuation ─────────────────────────────────────────

def test_long_valid():
    assert is_long_momentum_continuation(_LONG_SNAP) is True


def test_long_negative_cvd_fails():
    snap = {**_LONG_SNAP, "metrics": {"cvd_15m": -100, "cvd": -500}}
    assert is_long_momentum_continuation(snap) is False


def test_long_below_vwap_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "above_vwap": False},
    }
    assert is_long_momentum_continuation(snap) is False


def test_long_bearish_trend_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "trend_bias": "bearish"},
    }
    assert is_long_momentum_continuation(snap) is False


def test_long_bearish_htf_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "htf_trend_bias": "bearish"},
    }
    assert is_long_momentum_continuation(snap) is False


def test_long_extreme_funding_fails():
    snap = {**_LONG_SNAP, "funding": 0.005}
    assert is_long_momentum_continuation(snap) is False


def test_long_vwap_overextended_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "vwap_distance_pct": 10.0},
    }
    assert is_long_momentum_continuation(snap) is False


def test_long_weak_return_1h_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "return_1h": 1.5},
    }
    assert is_long_momentum_continuation(snap) is False


def test_long_weak_return_15m_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "return_15m": 0.3},
    }
    assert is_long_momentum_continuation(snap) is False


def test_long_weak_return_5m_fails():
    snap = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "return_5m": 0.0},
    }
    assert is_long_momentum_continuation(snap) is False


# ── is_short_momentum_continuation ────────────────────────────────────────

def test_short_valid():
    assert is_short_momentum_continuation(_SHORT_SNAP) is True


def test_short_above_vwap_fails():
    snap = {
        **_SHORT_SNAP,
        "technical": {**_SHORT_SNAP["technical"], "above_vwap": True},
    }
    assert is_short_momentum_continuation(snap) is False


def test_short_positive_cvd_fails():
    snap = {**_SHORT_SNAP, "metrics": {"cvd_15m": 100, "cvd": 500}}
    assert is_short_momentum_continuation(snap) is False


def test_short_bullish_trend_fails():
    snap = {
        **_SHORT_SNAP,
        "technical": {**_SHORT_SNAP["technical"], "trend_bias": "bullish"},
    }
    assert is_short_momentum_continuation(snap) is False


def test_short_extreme_funding_fails():
    snap = {**_SHORT_SNAP, "funding": -0.005}
    assert is_short_momentum_continuation(snap) is False


def test_short_vwap_overextended_fails():
    snap = {
        **_SHORT_SNAP,
        "technical": {**_SHORT_SNAP["technical"], "vwap_distance_pct": -10.0},
    }
    assert is_short_momentum_continuation(snap) is False


# ── calculate_trend_priority_score ────────────────────────────────────────

def test_score_range():
    for direction in ("long", "short"):
        snap = _LONG_SNAP if direction == "long" else _SHORT_SNAP
        r = calculate_trend_priority_score(snap, direction)
        assert 0 <= r["trend_priority_score"] <= 100

def test_long_full_alignment_high_score():
    r = calculate_trend_priority_score(_LONG_SNAP, "long")
    assert r["trend_priority_score"] >= 75

def test_short_full_alignment_high_score():
    r = calculate_trend_priority_score(_SHORT_SNAP, "short")
    assert r["trend_priority_score"] >= 75

def test_extreme_funding_lowers_score():
    snap_normal  = _LONG_SNAP
    snap_extreme = {**_LONG_SNAP, "funding": 0.005}
    normal  = calculate_trend_priority_score(snap_normal,  "long")["trend_priority_score"]
    extreme = calculate_trend_priority_score(snap_extreme, "long")["trend_priority_score"]
    assert extreme < normal

def test_overextended_vwap_lowers_score():
    snap_normal = _LONG_SNAP
    snap_far = {
        **_LONG_SNAP,
        "technical": {**_LONG_SNAP["technical"], "vwap_distance_pct": 10.0},
    }
    normal = calculate_trend_priority_score(snap_normal, "long")["trend_priority_score"]
    far    = calculate_trend_priority_score(snap_far,    "long")["trend_priority_score"]
    assert far < normal

def test_reasons_and_warnings_populated():
    r = calculate_trend_priority_score(_LONG_SNAP, "long")
    assert isinstance(r["trend_reasons"],  list)
    assert isinstance(r["trend_warnings"], list)
    assert len(r["trend_reasons"]) > 0

def test_mismatched_direction_short_snap_long_score_low():
    # SHORT snap evaluado como LONG: tendencia no coincide → score bajo
    r = calculate_trend_priority_score(_SHORT_SNAP, "long")
    assert r["trend_priority_score"] < 50
