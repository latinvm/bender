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

- **Smart Entry Points**: Combines moving averages with volume analysis to identify optimal trading opportunities
- **Intelligent Market Selection**:
  - Multi-factor scoring system analyzing 5 key metrics
  - Bid-ask spread filtering (rejects markets with >0.5% spread)
  - Volume consistency checks (detects and avoids pump & dump patterns)
  - Risk-adjusted returns analysis (Sharpe & Sortino ratios)
  - Volatility-focused selection to maximize trading opportunities
- **Risk Management**:
  - Implements strict stop-loss at -5% to protect your capital
  - Takes profits at +15% to secure gains
  - Spreads risk across multiple positions (maximum 3)
- **Portfolio Management**:
  - Smart position sizing to optimize your investment
  - Automatic minimum order handling
  - Complete trade history tracking
- **Conservative Approach**:
  - Starts with small investment amounts (€10 per trade)
  - Only enters trades when volume is increasing (reduced slippage risk)
  - Maintains detailed logs of all operations

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
# Start virtual trading (uses real market data, virtual money)
trader virtual

# Or use the --virtual flag with trade command
trader trade --virtual

# Show virtual trading statistics
trader trade --show-stats

# Reset virtual wallet to initial balance
trader trade --reset-virtual
```

**Why Use Virtual Trading?**
- Test strategies risk-free with simulated trades
- Uses real-time Bitvavo market data
- Separate database tracks all virtual trades
- Periodic portfolio updates showing P/L per position
- Perfect for learning and strategy optimization

### Real Trading

To run the trading bot with real money:
```bash
trader trade
```

⚠️ **WARNING**: This uses real money! Test with virtual trading first.

### Backtesting

To run a backtest on historical data:
```bash
trader backtest --market VET-EUR --start 2023-01-01 --end 2023-12-31
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