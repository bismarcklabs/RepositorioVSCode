from app import position_monitor


def test_paper_stop_closes_at_configured_stop(monkeypatch):
    pos = {
        "id": 1, "symbol": "BTCUSDT", "action": "LONG_FUTURES", "mode": "paper",
        "open_time": "2026-06-07T00:00:00", "entry_price": 100.0, "size_usdt": 10.0,
        "leverage": 5, "tp1": 102.0, "tp2": 104.0, "sl": 98.0, "sl_current": 98.0,
        "tp1_hit": 0, "tp1_pnl_usdt": 0.0,
    }
    closed = {}
    monkeypatch.setattr(position_monitor, "AUTO_TRADING_ENABLED", True)
    monkeypatch.setattr(position_monitor, "AUTO_TRADING_MODE", "paper")
    monkeypatch.setattr(position_monitor.database, "get_open_auto_positions", lambda: [pos])
    monkeypatch.setattr(position_monitor, "_fetch_prices", lambda positions, scanned_prices=None: {"BTCUSDT": 70.0})
    monkeypatch.setattr(position_monitor.database, "close_auto_position", lambda *args: closed.setdefault("args", args))
    monkeypatch.setattr(position_monitor, "_notify_close", lambda *args: None)

    position_monitor.check_positions()

    assert closed["args"][1] == 98.0
    # -10% de precio con 5x sobre $10 = -$1.00, menos fees taker 0.05%/lado
    # sobre notional $50 (entrada $0.025 + salida $0.025) = -$1.05 → -10.5%
    assert closed["args"][4] == -1.05
    assert closed["args"][5] == -10.5