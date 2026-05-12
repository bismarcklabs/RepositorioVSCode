import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import time
from typing import Any, Dict, List

from app.market_scanner import get_top_symbols
from app.indicators import calculate_metrics
from app.futures import get_open_interest, get_funding
from app.orderbook import get_orderbook_imbalance
from app.signals import detect_institutional_signal
from app.liquidations import get_liquidations

# Configurar página
st.set_page_config(
    page_title="Institutional Crypto Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Tema oscuro institucional
st.markdown(
    """
    <style>
    .main {
        background-color: #0e1117;
        color: #ffffff;
    }
    .stMetric {
        background-color: #1f2937;
        border-radius: 10px;
        padding: 10px;
        color: #ffffff;
    }
    .stSubheader {
        color: #fbbf24;
        font-weight: bold;
    }
    .stProgress > div > div > div > div {
        background-color: #10b981;
    }
    .token-card {
        background-color: #111827;
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 12px;
        margin-bottom: 16px;
    }
    .token-card h4 {
        margin-bottom: 6px;
        font-size: 16px;
        color: #f9fafb;
    }
    .token-card .token-metric {
        font-size: 13px;
        margin: 3px 0;
        color: #d1d5db;
    }
    .token-card .token-label {
        color: #9ca3af;
    }
    .stMetric {
        background-color: #1f2937;
        border-radius: 10px;
        padding: 10px;
        color: #ffffff;
    }
    .stSubheader {
        color: #fbbf24;
        font-weight: bold;
    }
    .signal-long {
        color: #10b981;
        font-weight: bold;
    }
    .signal-short {
        color: #ef4444;
        font-weight: bold;
    }
    .signal-neutral {
        color: #6b7280;
        font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏛️ Institutional Crypto Dashboard")

def get_spot_price(symbol: str) -> float:
    """Obtener el precio spot actual de Binance para un símbolo."""
    url = "https://api.binance.com/api/v3/ticker/price"
    try:
        response = requests.get(
            url,
            params={"symbol": symbol.upper()},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return float(data.get("price", 0.0))
    except requests.RequestException:
        return 0.0


def get_agg_trades(symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Obtener trades agregados recientes de Binance para un símbolo."""
    url = "https://api.binance.com/api/v3/aggTrades"
    try:
        response = requests.get(
            url,
            params={"symbol": symbol.upper(), "limit": limit},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        trades = []
        for item in data:
            trades.append(
                {
                    "qty": float(item.get("q", 0.0)),
                    "maker": item.get("m", False),
                    "price": float(item.get("p", 0.0)),
                    "timestamp": float(item.get("T", 0.0)) / 1000.0,
                }
            )
        return trades
    except requests.RequestException:
        return []


def get_realtime_data(symbol: str) -> Dict[str, Any]:
    """Obtener datos en tiempo real para un símbolo."""
    try:
        funding = get_funding(symbol)
        oi = get_open_interest(symbol)
        orderbook_data = get_orderbook_imbalance(symbol)
        price = get_spot_price(symbol)
        trades = get_agg_trades(symbol, limit=100)
        liquidations = get_liquidations(symbol, limit=20)

        metrics = calculate_metrics(symbol, trades)

        signal_data = detect_institutional_signal(
            symbol=symbol,
            delta=metrics["delta"],
            cvd=metrics["cvd"],
            funding=funding,
            open_interest=oi,
            imbalance=orderbook_data["imbalance"],
            liquidations=liquidations,
        )

        return {
            "metrics": metrics,
            "funding": funding,
            "open_interest": oi,
            "orderbook": orderbook_data,
            "signal": signal_data,
            "liquidations": liquidations,
            "price": price,
        }
    except Exception as e:
        st.error(f"Error obteniendo datos para {symbol}: {e}")
        return None

# Auto-refresh cada 5 segundos
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 5:
    st.session_state.last_refresh = time.time()
    st.rerun()

# Obtener top 20 símbolos
symbols = get_top_symbols(limit=20)

# Obtener y almacenar datos de todos los símbolos
rows: List[Dict[str, Any]] = []
for symbol in symbols:
    data = get_realtime_data(symbol)
    if data is None:
        continue

    rows.append(
        {
            "symbol": symbol.upper(),
            "price": data["price"],
            "cvd": data["metrics"]["cvd"],
            "delta": data["metrics"]["delta"],
            "funding": data["funding"],
            "open_interest": data["open_interest"],
            "imbalance": data["orderbook"]["imbalance"],
            "signal": data["signal"]["signal"],
            "confidence": int(data["signal"]["confidence"].rstrip("%")),
            "signal_description": data["signal"]["institutional_interpretation"],
            "trend_estimate": data["signal"]["trend_estimate"],
        }
    )

# Mostrar métricas agregadas con Plotly
if rows:
    df = pd.DataFrame(rows)

    st.markdown("### 📈 Resumen Top 20")
    st.write("Las métricas se actualizan cada 5 segundos y muestran el estado de los 20 símbolos con mayor volumen.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(
            """
            **Open Interest**
            
            Muestra el valor total de posiciones abiertas en futuros para cada par. Un Open Interest alto suele indicar mayor interés institucional y liquidez.
            """
        )
        fig_oi = px.bar(
            df.sort_values("open_interest", ascending=False),
            x="symbol",
            y="open_interest",
            title="Open Interest",
            color="open_interest",
        )
        st.plotly_chart(fig_oi, use_container_width=True)

    with col_b:
        st.markdown(
            """
            **Funding Rate**
            
            Representa la tasa de financiación que se paga entre compradores y vendedores en los contratos de futuros. Valores positivos indican presión long, valores negativos presión short.
            """
        )
        fig_funding = px.bar(
            df.sort_values("funding", ascending=False),
            x="symbol",
            y="funding",
            title="Funding Rate",
            color="funding",
        )
        st.plotly_chart(fig_funding, use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown(
            """
            **CVD (Cumulative Volume Delta)**
            
            Indica la acumulación neta de volumen agresivo de compra vs venta. Una CVD creciente sugiere acumulación, mientras que una caída puede indicar distribución.
            """
        )
        fig_cvd = px.bar(
            df.sort_values("cvd", ascending=False),
            x="symbol",
            y="cvd",
            title="CVD",
            color="cvd",
        )
        st.plotly_chart(fig_cvd, use_container_width=True)

    with col_d:
        st.markdown(
            """
            **Delta**
            
            Muestra el volumen neto de trades agresivos de compra menos ventas. Delta alto indica demanda agresiva reciente.
            """
        )
        fig_delta = px.bar(
            df.sort_values("delta", ascending=False),
            x="symbol",
            y="delta",
            title="Delta",
            color="delta",
        )
        st.plotly_chart(fig_delta, use_container_width=True)

    st.markdown(
        """
        **Precio Spot**
        
        Precio actual del token en el mercado spot de Binance. Este valor es útil para comparar con las métricas de futuros y flujo de órdenes.
        """
    )
    fig_price = px.bar(
        df.sort_values("price", ascending=False),
        x="symbol",
        y="price",
        title="Precio Spot",
        color="price",
    )
    st.plotly_chart(fig_price, use_container_width=True)

    st.markdown(
        """
        **Imbalance**
        
        Mide la diferencia de volumen entre bids y asks en el libro de órdenes. Un imbalance positivo muestra mayor volumen comprador, negativo mayor volumen vendedor.
        """
    )
    fig_imbalance = px.bar(
        df.sort_values("imbalance", ascending=False),
        x="symbol",
        y="imbalance",
        title="Imbalance",
        color="imbalance",
    )
    st.plotly_chart(fig_imbalance, use_container_width=True)

    st.markdown(
        """
        **Confianza de señal**
        
        Una métrica de qué tan fuerte es la señal institucional detectada. Cuanto mayor, mayor seguridad de la señal generada.
        """
    )
    fig_conf = px.bar(
        df.sort_values("confidence", ascending=False),
        x="symbol",
        y="confidence",
        title="Confianza en la señal",
        color="confidence",
    )
    st.plotly_chart(fig_conf, use_container_width=True)

    # Grafico de distribución de señales
    signal_counts = df["signal"].value_counts().reset_index()
    signal_counts.columns = ["signal", "count"]
    fig_signal = px.bar(
        signal_counts,
        x="signal",
        y="count",
        title="Distribución de señales institucionales",
        color="signal",
        color_discrete_map={
            "LONG": "#10b981",
            "SHORT": "#ef4444",
            "neutral": "#6b7280",
            "accumulation": "#10b981",
            "bullish_continuation": "#10b981",
            "distribution": "#ef4444",
            "long_squeeze": "#ef4444",
            "short_squeeze": "#10b981",
        },
    )
    fig_signal.update_layout(xaxis_title="Señal", yaxis_title="Cantidad de símbolos")
    st.plotly_chart(fig_signal, use_container_width=True)

# Mostrar dashboard en cuadrícula compacta
st.markdown("### 🧩 Resumen compacto de Tokens")
st.write("Se presentan los 20 principales tokens en un formato de cuadrícula con 3 tokens por fila para facilitar la comparación rápida.")

if rows:
    for i in range(0, len(rows), 3):
        cols = st.columns(3)
        for idx, row in enumerate(rows[i : i + 3]):
            with cols[idx]:
                st.markdown(
                    f"""
                    <div class='token-card'>
                        <h4>{row['symbol']}</h4>
                        <div class='token-metric'><span class='token-label'>Precio Spot:</span> ${row['price']:.2f}</div>
                        <div class='token-metric'><span class='token-label'>CVD:</span> {row['cvd']:.2f}</div>
                        <div class='token-metric'><span class='token-label'>Delta:</span> {row['delta']:.2f}</div>
                        <div class='token-metric'><span class='token-label'>Funding:</span> {row['funding']:.6f}</div>
                        <div class='token-metric'><span class='token-label'>Open Interest:</span> {row['open_interest']:.0f}</div>
                        <div class='token-metric'><span class='token-label'>Imbalance:</span> {row['imbalance']:.4f}</div>
                        <div class='token-metric'><span class='token-label'>Señal:</span> {row['signal']}</div>
                        <div class='token-metric'><span class='token-label'>Confianza:</span> {row['confidence']}%</div>
                        <div class='token-metric'><span class='token-label'>Significado:</span> {row['signal_description']}</div>
                        <div class='token-metric'><span class='token-label'>Tendencia estimada:</span> {row['trend_estimate']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

st.markdown("---")

# Footer
st.markdown("---")
st.caption("Dashboard actualizado cada 5 segundos. Datos de Binance API.")
