# Institutional Crypto Dashboard

Real-time cryptocurrency market dashboard powered by Binance API with institutional-grade indicators and signal generation.

## Features

- **Market Scanner**: Monitors top USDT trading pairs on Binance
- **Real-time Trades**: WebSocket stream for aggTrade data
- **Institutional Indicators**: Delta/CVD, Order Book Imbalance (OBI), volume analysis
- **Futures Analytics**: Open interest, funding rates, premium index
- **Order Book Analysis**: Depth analysis and volume imbalance metrics
- **Signal Generation**: Automated detection of institutional trading signals
- **Risk Alerts**: Real-time alerts for market stress and squeeze conditions
- **Streamlit UI**: Interactive dashboard with live charts and metrics

## Project Structure

```
crypto-dashboard/
├── app/
│   ├── main.py              # Streamlit dashboard
│   ├── market_scanner.py    # Top symbols scanner
│   ├── websocket_client.py  # Trade stream client
│   ├── indicators.py        # Technical indicators (Delta, CVD, OBI)
│   ├── futures.py           # Futures data endpoints
│   ├── orderbook.py         # Order book analysis
│   ├── signals.py           # Signal generation logic
│   ├── alerts.py            # Alert system
│   ├── liquidations.py      # Liquidation data (optional)
│   └── config.py            # Configuration loader
├── data/                    # Data storage directory
├── requirements.txt         # Python dependencies
├── .env.example            # Environment template
├── .gitignore              # Git ignore rules
└── setup.ps1/setup.bat     # Setup scripts
```

## Setup & Installation

### Prerequisites
- Python 3.8+
- Git

### Quick Start

1. **Clone repository**
   ```bash
   git clone https://github.com/yourusername/crypto-dashboard.git
   cd crypto-dashboard
   ```

2. **Create virtual environment**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings (optional: add Binance API credentials)
   ```

5. **Run dashboard**
   ```bash
   streamlit run app/main.py
   ```

Dashboard will be available at `http://localhost:8501`

## Configuration

Create a `.env` file based on `.env.example`:

```
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
ENABLE_LIQUIDATIONS=False
```

- `BINANCE_API_KEY` / `BINANCE_API_SECRET`: For accessing protected endpoints (optional)
- `ENABLE_LIQUIDATIONS`: Set to `True` to fetch forced liquidation data

## Usage

### Dashboard Sections

- **Market Metrics**: Real-time price, volume, and change % for top symbols
- **Institutional Signals**: Detected trading signals with confidence levels
- **Futures Data**: Open interest and funding rate trends
- **Order Book Analysis**: Bid/ask imbalance metrics
- **Alerts**: Active risk and squeeze alerts
- **Signal Distribution**: Visual chart of signal types

### Customization

Edit `app/config.py` to adjust:
- Top symbols count
- WebSocket reconnection behavior
- Indicator thresholds
- Alert sensitivity

## Versioning

- **v1.0.0**: Initial release with core features
- **v2.0+**: WebSocket integration, liquidation tracking, advanced analytics

## Development

To contribute or develop locally:

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make changes and test with `streamlit run app/main.py`
3. Commit changes with descriptive messages
4. Push and create a pull request

## Troubleshooting

**ModuleNotFoundError**: Ensure you activated the virtual environment
```powershell
.\venv\Scripts\Activate.ps1
```

**Binance 401 Unauthorized**: Add valid API credentials to `.env` or leave empty for public endpoints only

**Dashboard not updating**: Check internet connection and Binance API availability

## License

MIT License - see LICENSE file for details

## Disclaimer

This dashboard is for educational and monitoring purposes. Always verify data independently before making trading decisions. Crypto trading involves significant risk.
# crytptolab
