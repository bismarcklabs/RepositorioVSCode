import time
from typing import Any, Dict, List

# Estado acumulado por símbolo.
# "last_trade_id" — aggTradeId del último trade procesado. Permite deduplicar
# correctamente aunque Binance entregue varios trades en el mismo milisegundo,
# ya que los aggTradeId son enteros secuenciales únicos por símbolo.
symbol_metrics: Dict[str, Dict[str, Any]] = {}

CVD_WINDOW_SECONDS: float = 3600.0   # ventana larga: 1h
CVD_SHORT_WINDOW_SECONDS: float = 900.0  # ventana corta: 15 min


def _get_or_init(symbol: str) -> Dict[str, Any]:
    if symbol not in symbol_metrics:
        now = time.time()
        symbol_metrics[symbol] = {
            "cvd": 0.0,
            "cvd_15m": 0.0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "delta": 0.0,
            "obi": 0.0,
            "cvd_window_start": now,
            "cvd_15m_window_start": now,
            "last_trade_id": 0,
            "prev_oi": 0.0,
            "oi_change_pct": 0.0,
        }
    return symbol_metrics[symbol]


def _check_cvd_window(symbol: str) -> None:
    state = _get_or_init(symbol)
    now = time.time()
    if now - state.get("cvd_window_start", now) >= CVD_WINDOW_SECONDS:
        state["cvd"] = 0.0
        state["last_trade_id"] = 0
        state["cvd_window_start"] = now
    if now - state.get("cvd_15m_window_start", now) >= CVD_SHORT_WINDOW_SECONDS:
        state["cvd_15m"] = 0.0
        state["cvd_15m_window_start"] = now


def update_open_interest(symbol: str, oi: float) -> float:
    """Registra el OI actual y retorna el cambio porcentual vs el ciclo anterior."""
    state = _get_or_init(symbol)
    prev = state["prev_oi"]
    change_pct = (oi - prev) / prev * 100.0 if prev > 0.0 else 0.0
    state["prev_oi"] = oi
    state["oi_change_pct"] = round(change_pct, 4)
    return state["oi_change_pct"]


def calculate_orderbook_imbalance(
    symbol: str,
    bids: Any,
    asks: Any,
) -> float:
    bid_volume = sum(float(level[1]) for level in bids if len(level) >= 2)
    ask_volume = sum(float(level[1]) for level in asks if len(level) >= 2)
    imbalance = (
        (bid_volume - ask_volume) / (bid_volume + ask_volume)
        if bid_volume + ask_volume > 0
        else 0.0
    )
    state = _get_or_init(symbol)
    state["obi"] = imbalance
    return round(imbalance, 8)


def calculate_metrics(symbol: str, trades: List[Dict[str, Any]]) -> Dict[str, float]:
    """Acumula CVD 1h y CVD 15m usando solo trades con trade_id nuevo.

    El campo 'trade_id' (aggTradeId de Binance) es un entero secuencial único
    por símbolo. Filtrar por trade_id > last_trade_id garantiza que trades con
    el mismo timestamp (ms) no se pierdan ni se dupliquen.

    cvd     — acumulado en la última hora (ventana larga, tendencia)
    cvd_15m — acumulado en los últimos 15 min (ventana corta, aceleración)
    """
    _check_cvd_window(symbol)
    state = _get_or_init(symbol)

    last_id: int = int(state["last_trade_id"])
    new_trades = [t for t in trades if int(t.get("trade_id", 0)) > last_id]

    if new_trades:
        state["last_trade_id"] = max(int(t.get("trade_id", 0)) for t in new_trades)

    buy_volume = 0.0
    sell_volume = 0.0
    for trade in new_trades:
        qty = float(trade.get("qty", 0.0))
        if trade.get("maker", False):
            sell_volume += qty
        else:
            buy_volume += qty

    delta = buy_volume - sell_volume
    cvd = state["cvd"] + delta
    cvd_15m = state["cvd_15m"] + delta

    state.update({
        "buy_volume": round(buy_volume, 8),
        "sell_volume": round(sell_volume, 8),
        "delta": round(delta, 8),
        "cvd": round(cvd, 8),
        "cvd_15m": round(cvd_15m, 8),
    })

    return {
        "buy_volume": state["buy_volume"],
        "sell_volume": state["sell_volume"],
        "delta": state["delta"],
        "cvd": state["cvd"],
        "cvd_15m": state["cvd_15m"],
    }
