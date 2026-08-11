# 🤖 Bender - Automated Cryptocurrency Trading Bot for Bitvavo

An open-source crypto trading bot that automates your trading on the [Bitvavo](https://bitvavo.com/invite?a=00B4208D84) exchange. Bender uses technical analysis (RSI, MACD, Bollinger Bands) to execute trades 24/7, featuring multi-market portfolio management, risk controls, and both paper trading and live trading modes.

## 🧪 A Vibe Coding Origin Story

Bender started as my first "vibe coding" experiment. What began as copy-pasting functions and classes through Claude's chat interface—iterating piece by piece, asking "can you add this?" and "what if we did that?"—has evolved into a fully-fledged trading bot built with [Claude Code](https://github.com/anthropics/claude-code).

The journey from scattered code snippets in a chat window to a structured project with proper testing, architecture, and documentation has been a testament to how AI-assisted development is changing the way we build software. This project represents the full spectrum: from the earliest days of prompting for individual functions, to now having an AI pair programmer that understands the entire codebase.

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

**Signal 2: Moderate Oversold + Momentum (RSI < 50 AND MACD > Signal)**
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
- **Stop-Loss**: Sells at -5% by default (configurable via `STOP_LOSS_PCT`)
- **Take-Profit**: Sells at +15% by default (configurable via `TAKE_PROFIT_PCT`)

**Portfolio Safeguards**
- **Daily loss limit**: Stops opening new positions when today's realized loss exceeds `MAX_DAILY_LOSS_PCT` of your capital (default 10%; existing positions are still managed and can be sold)
- **Max drawdown halt**: Stops opening new positions when total realized loss exceeds `MAX_DRAWDOWN_PCT` of your capital (default 25%)
- Note: the stop-loss is evaluated by the bot every `STRATEGY_INTERVAL` seconds; if the bot is not running, positions are unprotected. Exchange-side stop orders are available as `MarketOperations.place_stop_loss_order()` but not yet wired into the strategy automatically.

**Automatic Market Rotation**
- Every `MARKET_CACHE_HOURS`, all markets are rescanned and the selection is refreshed. Markets without an open position rotate out in favour of better candidates; markets holding a position stay managed until the position exits.

#### 🎲 Intelligent Market Selection

- **Multi-factor scoring system** analyzing 5 key metrics
- **Bid-ask spread filtering** (rejects markets with >0.5% spread)
- **Volume consistency checks** (detects and avoids pump & dump patterns)
- **Risk-adjusted returns analysis** (Sharpe & Sortino ratios)
- **Volatility-focused selection** to maximize trading opportunities

#### 💼 Portfolio Management

- **Multi-market trading**: Runs 3 markets simultaneously by default (configurable via `MAX_POSITIONS`)
- **Smart position sizing**: €10 per position by default (configurable via `TRADE_AMOUNT`)
- **Position tracking**: Real-time P/L monitoring per position
- **Automatic minimum order handling**
- **Complete trade history** with statistics

#### 🔄 Restart-Safe Design

- **Resumes with open positions**: Safely restarts without losing track of trades
- **Position recovery**: Automatically loads existing positions on startup
- **Continuous monitoring**: Checks sell conditions on all open positions

## 🚀 Getting Started

### Prerequisites

- Python 3.12 or higher
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
git clone https://github.com/latinvm/bender.git
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

### 📊 Trading Strategy Settings

All trading parameters can be customized via the `.env` file:

```env
# Trading Strategy Configuration
TRADE_AMOUNT=10.0                # Amount in EUR to invest per position
STOP_LOSS_PCT=5.0                # Stop loss percentage (e.g., 5.0 = -5%)
TAKE_PROFIT_PCT=15.0             # Take profit percentage (e.g., 15.0 = +15%)
MAX_COIN_PRICE=10.0              # Maximum coin price in EUR to consider
STRATEGY_INTERVAL=60             # Seconds between strategy execution cycles
MARKET_CACHE_HOURS=6             # Hours to cache top 50 market selections
MAX_CANDIDATES=30                # Maximum markets to analyze in detail
RSI_BUY_STRONG=40.0              # Signal 1 threshold: buy when RSI below this
RSI_BUY_MODERATE=50.0            # Signal 2 threshold: buy when RSI below this AND MACD > signal
RSI_SELL=60.0                    # Sell threshold: sell when RSI above this AND MACD < signal
```

**What These Settings Mean:**

- **TRADE_AMOUNT**: How much EUR to invest per position (default: €10)
- **STOP_LOSS_PCT**: Maximum loss before auto-selling (default: 5% = -5% loss)
- **TAKE_PROFIT_PCT**: Target profit before auto-selling (default: 15% = +15% gain)
- **MAX_COIN_PRICE**: Only trade coins under this price (default: €10)
- **STRATEGY_INTERVAL**: How often to check for trading signals in seconds (default: 60)
- **MARKET_CACHE_HOURS**: How long to cache market rankings (default: 6 hours)
- **MAX_CANDIDATES**: Number of top markets to analyze deeply (default: 30)

**Example Custom Configuration:**
```env
# More aggressive settings
TRADE_AMOUNT=25.0
STOP_LOSS_PCT=3.0
TAKE_PROFIT_PCT=20.0
STRATEGY_INTERVAL=30
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

# Optionally verify order execution with a real minimum-size buy+sell
# cycle on startup (costs fees; disabled by default)
trader trade --test-trade
```

⚠️ **WARNING**: This uses real money! Test with virtual trading first.

**Startup safety checks (real mode):**
- A read-only connectivity check verifies your API credentials without placing any orders. Pass `--test-trade` if you explicitly want a real minimum-size buy+sell verification cycle instead.
- Recorded positions are reconciled against your actual exchange balances. If the database references assets you no longer hold, Bender refuses to trade until you clean up the database or pass `--force`.

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

## 🔧 Known Issues & Fixes

### Bitvavo Rate Limit Bug (FIXED ✅)

The upstream `python-bitvavo-api` library has a bug that causes `ValueError: sleep length must be non-negative`. This has been **fixed** in Bender with an automatic patch.

**What was the issue?**
```
Exception in thread Thread-1:
ValueError: sleep length must be non-negative
```

**Our solution:** Bender automatically patches the library on startup to handle this gracefully. No action needed from you!

For technical details, see [docs/BITVAVO_RATE_LIMIT_FIX.md](docs/BITVAVO_RATE_LIMIT_FIX.md)

## 🧪 Running Tests

Bender has a comprehensive test suite. To run the tests:

```bash
# Activate the virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -r requirements-dev.txt

# Run all tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_config.py -v

# Run with coverage report
python -m pytest tests/ --cov=src/trader --cov-report=term-missing
```

**Test Categories:**
- `test_config.py` - Configuration loading and validation
- `test_database.py` - Trade database operations
- `test_enhanced_strategy.py` - Trading strategy logic and signals
- `test_multi_market_strategy.py` - Multi-market portfolio management
- `test_market.py` - Market operations and API interactions
- `test_virtual_wallet.py` - Virtual trading wallet functionality
- `test_bitvavo_patch.py` - Bitvavo rate limit fix verification

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