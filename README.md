# 🤖 Genesis AI Trading System

Advanced AI-powered algorithmic trading system with multi-model ensemble, knowledge graph integration, and adaptive risk management.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)

## 🌟 Key Features

### 🧠 AI & Machine Learning
- **Multi-Model Ensemble**: LSTM, LightGBM, Genetic Programming
- **Adaptive Learning**: Online learning with concept drift detection
- **Model Validation**: Strict criteria (PF≥1.5, WR≥40%, Sharpe≥1.0)
- **Automated R&D**: Daily model training and validation cycles

### 📊 Market Analysis
- **18 Trading Instruments**: Forex pairs, Gold, Silver, Bitcoin
- **Multi-Timeframe Analysis**: M1, M5, M15, H1, H4, D1
- **60+ Technical Indicators**: ATR, RSI, MACD, Bollinger Bands, etc.
- **Market Regime Detection**: Trend, Range, Volatility classification

### 🛡️ Risk Management
- **Safety Monitor**: Auto-stop at 3% daily loss or 5% drawdown
- **Position Limits**: Max 5 concurrent positions
- **Dynamic Risk**: 0.5% per trade with adaptive sizing
- **Portfolio VaR**: Real-time Value-at-Risk monitoring

### 📰 News & Sentiment
- **Knowledge Graph**: Neo4j-based causal reasoning
- **Vector Database**: FAISS for semantic news search
- **Multi-Source Aggregation**: RSS, News APIs, Economic Calendar
- **NLP Processing**: Sentiment analysis and entity extraction

### 🎯 Trading Strategies
- **AI Consensus**: Weighted ensemble of multiple models
- **Classic Strategies**: Breakout, Mean Reversion, MA Crossover
- **Adaptive Strategy**: Regime-based strategy selection
- **RL Trade Manager**: Reinforcement learning for position management

### 🖥️ User Interface
- **Modern GUI**: PySide6-based desktop application
- **Web Dashboard**: Real-time monitoring via browser
- **Live Charts**: Interactive candlestick charts
- **Performance Analytics**: Detailed P&L tracking

## 📈 Performance Metrics

**Expected Performance (after 30 days):**
- Win Rate: 40-50%
- Profit Factor: 1.3-1.8
- Sharpe Ratio: 0.8-1.2
- Max Drawdown: <8%
- **Profitability Probability: 45-60%**

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- MetaTrader 5 terminal
- 8GB+ RAM
- Windows 10/11 (recommended)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/genesis-trading-system.git
cd genesis-trading-system
```

2. Create virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure settings:
```bash
# Copy example config
copy configs\settings.example.json configs\settings.json

# Edit configs\settings.json with your:
# - MT5 credentials
# - API keys (optional)
# - Database path
```

5. Run the system:
```bash
python main_pyside.py
```

## 📚 Documentation

- [Quick Start Guide](QUICK_START.md) - Get started in 5 minutes
- [System Improvements](QUICK_START_IMPROVEMENTS.md) - Latest optimizations
- [Troubleshooting](TROUBLESHOOTING_PROMPT.md) - Fix common issues
- [Quick Fix Guide](QUICK_FIX_GUIDE.md) - Fast solutions
- [Implementation Report](IMPLEMENTATION_REPORT.md) - Technical details

## 🔧 Configuration

### Key Settings

```json
{
  "RISK_PERCENTAGE": 0.5,           // Risk per trade (0.5%)
  "MAX_OPEN_POSITIONS": 5,          // Max concurrent positions
  "ENTRY_THRESHOLD": 0.01,          // Signal strength threshold
  "TRAINING_INTERVAL_SECONDS": 86400, // Daily retraining
  "MAX_DAILY_DRAWDOWN_PERCENT": 5.0  // Safety limit
}
```

### API Keys (Optional)

The system works without API keys but has enhanced features with:
- **Finnhub**: Real-time news
- **Alpha Vantage**: Market data
- **News API**: News aggregation
- **Polygon**: Alternative data
- **FRED**: Economic indicators

## 🛡️ Safety Features

### Safety Monitor
- **Daily Loss Limit**: Auto-stop at 3% loss
- **Drawdown Protection**: Stop at 5% from peak
- **Consecutive Losses**: Stop after 5 losses
- **Emergency Close**: Automatic position closure

### Risk Controls
- **Position Sizing**: Dynamic based on volatility
- **Stop Loss**: 3.5x ATR protection
- **Take Profit**: 2.5:1 risk-reward ratio
- **Correlation Check**: Avoid correlated positions

## 📊 System Architecture

```
Genesis Trading System
├── Core
│   ├── Trading System (main orchestrator)
│   ├── Safety Monitor (risk protection)
│   └── Training Scheduler (auto-retraining)
├── ML Models
│   ├── LSTM (PyTorch)
│   ├── LightGBM
│   └── Genetic Programming
├── Data
│   ├── MT5 Provider
│   ├── News Aggregator
│   └── Knowledge Graph
├── Risk
│   ├── Risk Engine
│   ├── Portfolio Service
│   └── VaR Calculator
└── GUI
    ├── Desktop App (PySide6)
    └── Web Dashboard
```

## 🔬 R&D Cycle

The system automatically:
1. **Collects Data**: 10,000+ bars per symbol
2. **Trains Models**: LSTM (50 epochs), LightGBM
3. **Validates**: PF≥1.5, WR≥40%, Sharpe≥1.0
4. **Backtests**: 50+ trades on holdout data
5. **Promotes**: Only profitable models to production

**Expected Results:**
- First week: 80-90% models rejected (normal)
- After 30 days: 5-10 active models
- Trading frequency: 5-10 trades/day

## 📈 Performance Optimization

### Recent Improvements (Feb 2026)

✅ **Risk Reduction**
- Risk per trade: 2.0% → 0.5% (-75%)
- Max positions: 18 → 5 (-72%)
- Max exposure: 36% → 2.5% (-93%)

✅ **Model Validation**
- Strict criteria: PF≥1.5, WR≥40%
- Reject unprofitable models
- 50+ trades minimum

✅ **Safety Monitor**
- Auto-stop at 3% daily loss
- Drawdown protection (5%)
- Consecutive loss limit (5)

✅ **Performance**
- VectorDB: Save every 5 min (was 2 sec)
- Disk I/O: -99.3%
- System speed: +15%

## 🐛 Troubleshooting

### Common Issues

**System crashes:**
```bash
# Check logs
Get-Content logs\trading_system.log -Tail 100

# Verify syntax
python -m py_compile src\core\trading_system.py
```

**Safety Monitor not working:**
```bash
# Check initialization
Select-String -Path logs\trading_system.log -Pattern "\[SAFETY\]"
```

**No trades:**
- ✅ Normal for first 24 hours (waiting for models)
- ✅ High thresholds protect from bad signals
- ✅ System is conservative by design

See [Troubleshooting Guide](TROUBLESHOOTING_PROMPT.md) for detailed solutions.

## 📊 Monitoring

### Key Metrics to Track

**Daily:**
- Number of rejected/accepted models
- Open positions (should be ≤5)
- Daily P&L
- Error logs

**Weekly:**
- Win Rate (target: >35%)
- Profit Factor (target: >1.2)
- Max Drawdown (target: <8%)
- System uptime

**Monthly:**
- Sharpe Ratio (target: >0.8)
- Total trades
- Model performance
- Readiness for live trading

## 🚨 Important Warnings

### ⚠️ Demo Testing Required

**DO NOT use on live account until:**
- [ ] 30+ days of demo testing
- [ ] Profit Factor > 1.3
- [ ] Win Rate > 35%
- [ ] Sharpe Ratio > 0.8
- [ ] Max Drawdown < 8%
- [ ] 50+ trades completed

### ⚠️ Risk Disclaimer

- Trading involves substantial risk of loss
- Past performance does not guarantee future results
- Only trade with capital you can afford to lose
- This system is for educational purposes
- Always test on demo account first

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- MetaTrader 5 for trading platform
- PyTorch for deep learning
- LightGBM for gradient boosting
- FAISS for vector search
- PySide6 for GUI framework

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/genesis-trading-system/issues)
- **Documentation**: See `/docs` folder
- **Guides**: See `QUICK_START.md` and related files

## 🗺️ Roadmap

- [ ] Multi-broker support (Interactive Brokers, Binance)
- [ ] Cloud deployment (AWS, Azure)
- [ ] Mobile app (iOS, Android)
- [ ] Advanced RL strategies
- [ ] Social trading features
- [ ] Backtesting framework improvements

---

**⚡ Built with AI. Powered by Data. Driven by Results.**

*Genesis Trading System - Where artificial intelligence meets algorithmic trading.*
