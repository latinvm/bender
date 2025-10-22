# 🤖 Bender Trading Bot

Welcome to Bender - Your Friendly Cryptocurrency Trading Assistant! 

## 🌟 Why Bender?

Ever wished you had a reliable companion to handle your crypto trading while you focus on what matters most to you? That's exactly why I created Bender! As someone passionate about both cryptocurrency and automation, I wanted to share a tool that makes trading more accessible and less time-consuming for everyone.

### 🎯 What Makes Bender Special

- **Peace of Mind**: Set your strategy and let Bender handle the rest
- **24/7 Operation**: Markets never sleep, and neither does Bender
- **Smart Strategies**: Implements proven trading strategies while managing risks
- **Transparent**: Always know what's happening with your trades
- **User-Friendly**: Built with simplicity in mind - no complex setups needed

### 📈 Trading Strategy

Bender uses a carefully crafted trading strategy designed for both safety and performance:

#### 🎯 Multi-Signal Buy Strategy

Bender uses 3 independent buy signals - if **ANY** signal triggers, it buys. This gives more opportunities while maintaining quality:

**Signal 1: Strong Oversold (RSI < 40)**
- **What it means**: The price has dropped significantly and is likely to bounce back
- **Think of it as**: A rubber band stretched down - it wants to snap back up
- **Example**: `BOME-EUR: RSI 24.79 → Strong Oversold! ✓ BUY`

**Signal 2: Moderate Oversold + Momentum (RSI < 55 AND MACD > Signal)**
- **What it means**: The price dropped somewhat AND momentum is turning positive
- **Think of it as**: A ball rolling downhill that's starting to slow and reverse
- **Example**: `DOGS-EUR: RSI 38.28, MACD crossing up → Moderate + Momentum! ✓ BUY`

**Signal 3: Near Support + Momentum (Price < Lower BB × 1.01 AND MACD ≈ Signal)**
- **What it means**: Price hit a support level (floor) and momentum is about to turn
- **Think of it as**: A basketball hitting the floor - about to bounce
- **Example**: `FLOKI-EUR: At support, MACD crossing → Near Support! ✓ BUY`

#### 🛡️ Sell Strategy

**Technical Sell Signal (RSI > 60 AND MACD < Signal)**
- Price is overbought AND momentum is turning negative
- Exits before major reversals

**Automatic Risk Controls**
- **Stop-Loss**: Sells at -5% to protect your capital
- **Take-Profit**: Sells at +15% to secure gains

#### 🎲 Intelligent Market Selection

- **Multi-factor scoring system** analyzing 5 key metrics
- **Bid-ask spread filtering** (rejects markets with >0.5% spread)
- **Volume consistency checks** (detects and avoids pump & dump patterns)
- **Risk-adjusted returns analysis** (Sharpe & Sortino ratios)
- **Volatility-focused selection** to maximize trading opportunities

#### 💼 Portfolio Management

- **Multi-market trading**: Runs 3 markets simultaneously in virtual mode
- **Smart position sizing**: €10 per position for controlled risk
- **Position tracking**: Real-time P/L monitoring per position
- **Automatic minimum order handling**
- **Complete trade history** with statistics

#### 🔄 Restart-Safe Design

- **Resumes with open positions**: Safely restarts without losing track of trades
- **Position recovery**: Automatically loads existing positions on startup
- **Continuous monitoring**: Checks sell conditions on all open positions

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- A Bitvavo account ([Sign up here](https://bitvavo.com/invite?a=00B4208D84) to support the project!)

### Why Bitvavo?

I chose Bitvavo as our trading platform for several reasons:
- 🛡️ Strong security measures
- 💰 Low trading fees
- 🌍 Excellent European coverage
- 👥 Outstanding customer support
- ⚡ Fast and reliable API

Using my referral link above helps support Bender's development while giving you access to one of Europe's most trusted cryptocurrency platforms!

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/bender.git
cd bender

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`

# Install dependencies and the trader command
pip install -r requirements.txt
pip install -e .

# Set up your configuration
cp .env.example .env
# Edit .env with your Bitvavo API credentials
```

## 🔧 Configuration

1. Create an API key in your Bitvavo account
2. Add your credentials to the `.env` file:
```env
BITVAVO_API_KEY=your_api_key
BITVAVO_API_SECRET=your_api_secret
BITVAVO_OPERATOR_ID=1 (64 bit integer)
```

## 🎮 Usage

### Virtual Trading (Paper Trading - Recommended for Testing!)

Test your strategies with virtual money using real Bitvavo market data:

```bash
# Start virtual trading (logs to console)
trader virtual

# Start virtual trading with live monitor (logs to file)
trader virtual --monitor

# Start fresh with reset wallet and live monitor
trader virtual --monitor --reset

# Show virtual trading statistics
trader virtual --stats

# Reset virtual wallet to initial balance
trader virtual --reset
```

**Why Use Virtual Trading?**
- Test strategies risk-free with simulated trades
- Uses real-time Bitvavo market data
- Separate database tracks all virtual trades
- Live terminal UI with `--monitor` flag
- Perfect for learning and strategy optimization

### Real Trading

To run the trading bot with real money:
```bash
# Start real trading (logs to console)
trader trade

# Start real trading with live monitor (logs to file)
trader trade --monitor

# Show real trading statistics
trader trade --stats
```

⚠️ **WARNING**: This uses real money! Test with virtual trading first.

### Monitor Mode

When you use the `--monitor` flag, Bender runs a beautiful live terminal UI:
- **Real-time updates** - See trades happen instantly as the bot runs
- **Live positions** - Watch your positions and P/L update every 5 seconds
- **Trading statistics** - View win rate, total trades, and performance metrics
- **Logs to file** - All output goes to `logs/YYYY-MM-DD.log` instead of console
- **Interactive** - Press `r` to refresh, `q` to quit

```bash
# Virtual trading with live monitor
trader virtual --monitor

# Real trading with live monitor
trader trade --monitor
```

### Backtesting

Test strategies on historical data:
```bash
trader backtest --market VET-EUR --start 2024-01-01 --end 2024-12-31
```

## 💡 Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest new features
- Submit pull requests

## ❤️ Support the Project

If you find Bender helpful, the best way to support its development is by:
1. Using my [Bitvavo referral link](https://bitvavo.com/invite?a=00B4208D84) when creating your account
2. Starring the project on GitHub
3. Sharing your success stories!

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

*Happy Trading with Bender! 🤖✨*

*Remember: Trading cryptocurrency involves risk. Always trade responsibly and never invest more than you can afford to lose.*