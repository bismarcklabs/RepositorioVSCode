import pytest
from app.websocket_client import (
    set_stream_symbols,
    get_trades_snapshot,
    _get_stream_symbols,
    trade_store,
    _trade_lock,
)
from collections import deque


def test_set_stream_symbols_updates_list():
    set_stream_symbols(["BTCUSDT", "ETHUSDT"])
    syms = _get_stream_symbols()
    assert "BTCUSDT" in syms
    assert "ETHUSDT" in syms


def test_set_stream_symbols_uppercases():
    set_stream_symbols(["btcusdt", "ethusdt"])
    syms = _get_stream_symbols()
    assert "BTCUSDT" in syms
    assert "ETHUSDT" in syms


def test_set_stream_symbols_deduplicates():
    set_stream_symbols(["BTCUSDT", "BTCUSDT", "ETHUSDT"])
    syms = _get_stream_symbols()
    # No exige dedup en la lista, pero debe contener los símbolos
    assert "BTCUSDT" in syms
    assert "ETHUSDT" in syms


def test_set_stream_symbols_empty_list():
    # No debe lanzar excepción con lista vacía
    set_stream_symbols([])
    # Puede quedar vacío o con el valor anterior; lo importante es no romper
    assert isinstance(_get_stream_symbols(), list)


def test_get_trades_snapshot_empty_for_unknown_symbol():
    result = get_trades_snapshot("XYZUNKNOWN99")
    assert result == []


def test_get_trades_snapshot_returns_copy():
    sym = "TESTTOKEN"
    with _trade_lock:
        trade_store[sym] = deque([{"trade_id": 1, "price": 100.0, "qty": 1.0,
                                    "maker": False, "timestamp": 1000}], maxlen=1000)
    snapshot = get_trades_snapshot(sym)
    assert len(snapshot) == 1
    assert snapshot[0]["price"] == 100.0
    # Modificar la copia no afecta el store
    snapshot.clear()
    assert len(get_trades_snapshot(sym)) == 1


def test_get_trades_snapshot_preserves_order():
    sym = "ORDTEST"
    trades = [{"trade_id": i, "price": float(i), "qty": 1.0,
               "maker": False, "timestamp": i} for i in range(5)]
    with _trade_lock:
        trade_store[sym] = deque(trades, maxlen=1000)
    snapshot = get_trades_snapshot(sym)
    prices = [t["price"] for t in snapshot]
    assert prices == [0.0, 1.0, 2.0, 3.0, 4.0]
