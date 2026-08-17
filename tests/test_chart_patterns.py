from app.chart_patterns import detect_chart_patterns


def _candles(values, wick=0.5, volume=100.0):
    return [
        [i * 60000, v, v + wick, v - wick, v, volume]
        for i, v in enumerate(values)
    ]


# Doble techo: dos máximos ~110.5/110.9, valle en ~97.5, cierre final 95 (< neckline)
_DOUBLE_TOP = [
    100, 101, 103, 106, 110, 106, 103, 100, 98, 100,
    103, 106, 110.4, 106, 103, 100, 97, 96, 95,
]

# H-C-H: hombros ~108.5/108.7, cabeza 112.5, neckline ~99.5, cierre final 95
_HNS = [
    100, 103, 106, 108, 105, 102, 100, 103, 107, 110,
    112, 110, 107, 103, 100, 103, 106, 108.2, 105, 102,
    99, 97, 95,
]


def test_double_top_confirmed():
    patterns = detect_chart_patterns(_candles(_DOUBLE_TOP))
    tops = [p for p in patterns if p["pattern"] == "double_top"]
    assert tops, "debe detectar el doble techo"
    p = tops[0]
    assert p["direction"] == "short"
    assert p["confirmed"] is True
    assert p["target"] < p["neckline"]


def test_double_top_not_confirmed_above_neckline():
    # Misma figura pero el precio aún no rompe la neckline
    series = _DOUBLE_TOP[:-3] + [100, 99.5, 99]
    patterns = detect_chart_patterns(_candles(series))
    tops = [p for p in patterns if p["pattern"] == "double_top"]
    assert tops and tops[0]["confirmed"] is False


def test_head_and_shoulders_confirmed():
    patterns = detect_chart_patterns(_candles(_HNS))
    hns = [p for p in patterns if p["pattern"] == "head_and_shoulders"]
    assert hns, "debe detectar el hombro-cabeza-hombro"
    p = hns[0]
    assert p["direction"] == "short"
    assert p["confirmed"] is True
    assert p["neckline"] < p["extreme"]
    # Confirmado va primero en la lista
    assert patterns[0]["pattern"] == "head_and_shoulders"


def test_inverse_hns_confirmed():
    inverted = [200 - v for v in _HNS]
    patterns = detect_chart_patterns(_candles(inverted))
    ihns = [p for p in patterns if p["pattern"] == "inverse_head_and_shoulders"]
    assert ihns, "debe detectar el H-C-H invertido"
    assert ihns[0]["direction"] == "long"
    assert ihns[0]["confirmed"] is True


def test_no_patterns_in_trend():
    trend = [100 + i for i in range(20)]
    assert detect_chart_patterns(_candles(trend)) == []


def test_insufficient_candles():
    assert detect_chart_patterns(_candles([100, 101, 102])) == []


# Doble piso ("W"): dos mínimos ~90.5/90.3, neckline ~103.5, precio recién
# rebotando desde el 2do fondo (3 velas atrás, a un tercio de la neckline)
_DOUBLE_BOTTOM_FRESH_BOUNCE = [
    103, 101, 98, 94, 90.5, 94, 98, 101, 103,
    101, 98, 94, 90.3, 92, 93, 94.5,
]


def test_double_bottom_bounce_valid_fresh():
    patterns = detect_chart_patterns(_candles(_DOUBLE_BOTTOM_FRESH_BOUNCE))
    bottoms = [p for p in patterns if p["pattern"] == "double_bottom"]
    assert bottoms, "debe detectar el doble piso"
    p = bottoms[0]
    assert p["confirmed"] is False
    assert p["bounce_age_candles"] == 3
    assert p["bounce_valid"] is True
    assert 0 < p["bounce_progress_pct"] < 65


def test_double_bottom_bounce_invalid_near_neckline():
    # Mismo piso pero el precio ya recuperó casi toda la altura hacia la neckline
    series = _DOUBLE_BOTTOM_FRESH_BOUNCE[:-2] + [99, 102.5]
    patterns = detect_chart_patterns(_candles(series))
    bottoms = [p for p in patterns if p["pattern"] == "double_bottom"]
    assert bottoms
    p = bottoms[0]
    assert p["confirmed"] is False
    assert p["bounce_progress_pct"] > 65
    assert p["bounce_valid"] is False


def test_double_bottom_bounce_invalid_when_stale():
    # El 2do fondo quedó confirmado hace muchas velas — el rebote ya no es "fresco"
    series = _DOUBLE_BOTTOM_FRESH_BOUNCE + [95, 96, 97, 98, 99, 100, 101]
    patterns = detect_chart_patterns(_candles(series))
    bottoms = [p for p in patterns if p["pattern"] == "double_bottom"]
    assert bottoms
    p = bottoms[0]
    assert p["confirmed"] is False
    assert p["bounce_age_candles"] > 4
    assert p["bounce_valid"] is False


def test_confirmed_pattern_has_no_bounce():
    patterns = detect_chart_patterns(_candles(_DOUBLE_TOP))
    tops = [p for p in patterns if p["pattern"] == "double_top"]
    assert tops and tops[0]["confirmed"] is True
    assert tops[0]["bounce_valid"] is False
    assert tops[0]["bounce_age_candles"] == 0
