from app.structure_levels import analyze_structure, build_levels, find_pivots


def _candles(values, wick=0.5, volume=100.0):
    """Velas sintéticas formato Binance: open=close=value, high/low = value±wick."""
    return [
        [i * 60000, v, v + wick, v - wick, v, volume]
        for i, v in enumerate(values)
    ]


# Serie con resistencia ~110.5 tocada 3 veces y ruptura al final
_BREAKOUT_SERIES = [
    100, 102, 105, 108, 110, 108, 105, 103, 101, 103,
    106, 109, 110.2, 108, 105, 103, 102, 104, 106, 108,
    109.8, 108, 106, 105, 104, 105, 107, 109, 111.5, 112.5,
]


def test_find_pivots_detects_swing_highs_and_lows():
    pivots = find_pivots(_candles(_BREAKOUT_SERIES))
    kinds = {p["kind"] for p in pivots}
    assert "high" in kinds and "low" in kinds
    highs = [p for p in pivots if p["kind"] == "high"]
    assert len(highs) >= 3  # los tres toques de la resistencia


def test_build_levels_clusters_touches():
    levels = build_levels(_candles(_BREAKOUT_SERIES))
    assert levels, "debe existir al menos el nivel de resistencia"
    top = levels[0]
    assert top["touches"] >= 3
    assert 109.5 <= top["price"] <= 111.5


def test_breakout_up_confirmed_with_volume():
    structure = analyze_structure(
        _candles(_BREAKOUT_SERIES), atr=1.0, relative_volume=2.0
    )
    assert structure is not None
    brk = structure["breakout"]
    assert brk is not None
    assert brk["direction"] == "up"
    assert brk["confirmed"] is True
    assert brk["touches"] >= 3


def test_breakout_not_confirmed_without_volume():
    structure = analyze_structure(
        _candles(_BREAKOUT_SERIES), atr=1.0, relative_volume=1.0
    )
    brk = structure["breakout"]
    assert brk is not None and brk["confirmed"] is False


def test_nearest_support_after_breakout():
    structure = analyze_structure(
        _candles(_BREAKOUT_SERIES), atr=1.0, relative_volume=2.0
    )
    sup = structure["nearest_support"]
    assert sup is not None
    assert sup["price"] < _BREAKOUT_SERIES[-1]


def test_no_breakout_in_flat_range():
    flat = [100, 101, 100, 99, 100, 101, 100, 99, 100, 101,
            100, 99, 100, 101, 100, 99, 100, 101, 100, 99]
    structure = analyze_structure(_candles(flat), atr=0.5, relative_volume=1.0)
    assert structure is None or structure["breakout"] is None


def test_insufficient_candles_returns_none():
    assert analyze_structure(_candles([100, 101, 102])) is None
