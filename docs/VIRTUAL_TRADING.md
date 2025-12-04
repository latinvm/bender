# Virtual Trading Guide

Virtual trading (paper trading) allows you to test Bender's trading strategies using real Bitvavo market data without risking any real money. This is the **recommended way** to test and optimize your trading strategies before committing real funds.

## What is Virtual Trading?

Virtual trading simulates all trading operations in a separate database while fetching real-time market data from Bitvavo. You start with a virtual balance (default: €1000) and all trades are executed at actual market prices with realistic trading fees.

### Key Features

- **Real Market Data**: Uses live Bitvavo prices, order books, and market information
- **Realistic Simulation**: Includes trading fees (default 0.25%) just like real trading
- **Separate Database**: All virtual trades stored in `data/virtual_trades.db`
- **Full Position Tracking**: Monitor all active positions with real-time P/L
- **Trading Statistics**: Win rate, average P/L, best/worst trades, and more
- **Risk-Free Testing**: Perfect for learning and strategy optimization

## Getting Started

### 1. Configuration

Virtual trading is configured via environment variables in your `.env` file:

```bash
# Virtual Trading Configuration
VIRTUAL_TRADING=false              # Set to 'true' to enable by default
VIRTUAL_DB_PATH=data/virtual_trades.db
VIRTUAL_INITIAL_BALANCE=1000.0     # Starting balance in EUR
VIRTUAL_TRADING_FEE=0.25           # Trading fee percentage
```

### 2. Running Virtual Trading

Start virtual trading mode:

```bash
# Start virtual trading
trader virtual

# Or explicitly with the trade command
trader trade --virtual
```

You'll see a message confirming virtual mode:
```
Starting trader application in VIRTUAL TRADING MODE
⚠️  All trades will be simulated - no real money will be used
Virtual wallet initialized with €1000.00
```

## Command Reference

### Start Virtual Trading

```bash
trader virtual
```

This will:
1. Initialize the virtual wallet
2. Connect to Bitvavo for real market data
3. Select the best market based on your strategy
4. Execute trades using virtual money
5. Show portfolio updates every 5 minutes

### View Statistics

```bash
trader trade --show-stats
```

Example output:
```
================================================================================
VIRTUAL TRADING STATISTICS
================================================================================
Current Balance:      €1050.25
Initial Balance:      €1000.00
Total Return:         €+50.25 (+5.02%)
Total Trades:         10
Winning Trades:       7
Losing Trades:        3
Win Rate:             70.0%
Avg P/L per Trade:    €+5.03
Best Trade:           €+25.50
Worst Trade:          €-12.30
================================================================================

Recent Trades (Last 10):
--------------------------------------------------------------------------------
✓ VET-EUR: 150.00000000 @ €0.025000 → €0.028500 | P/L: €+0.53 (+14.00%)
✓ ADA-EUR: 25.50000000 @ €0.450000 → €0.427500 | P/L: €-0.57 (-5.00%)
○ XRP-EUR: 18.75000000 @ €0.532000 [ACTIVE]
```

### Reset Virtual Wallet

```bash
trader trade --reset-virtual
```

This clears all trades and positions, resetting your balance to the initial amount.

## Portfolio Monitoring

When running in virtual mode, Bender automatically displays a comprehensive portfolio summary every 5 minutes:

```
================================================================================
PORTFOLIO SUMMARY
================================================================================

VET-EUR:
  Amount:       150.00000000
  Entry Price:  €0.025000
  Current Price: €0.026500
  Entry Value:  €3.75
  Current Value: €3.98
  Unrealized P/L: €+0.23 (+6.13%)
  Entry Time:   2025-01-15 14:30:22

--------------------------------------------------------------------------------
Total Positions:      1
Total Entry Value:    €3.75
Total Current Value:  €3.98
Total Unrealized P/L: €+0.23

--------------------------------------------------------------------------------
Cash Balance:         €986.25
Total Realized P/L:   €+10.50
Initial Balance:      €1000.00
Total Return:         €+10.50 (+1.05%)

--------------------------------------------------------------------------------
TRADING STATISTICS
--------------------------------------------------------------------------------
Total Trades:     5
Winning Trades:   4
Losing Trades:    1
Win Rate:         80.0%
Avg P/L per Trade: €+2.10
Best Trade:       €+5.25
Worst Trade:      €-1.50
================================================================================
```

## How Virtual Trading Works

### Market Data (Real)
- ✅ Live prices from Bitvavo
- ✅ Real order books
- ✅ Actual 24h volume and volatility
- ✅ Current bid-ask spreads
- ✅ Market selection algorithm uses real data

### Trade Execution (Virtual)
- 💰 Simulated orders at current market price
- 💰 Virtual wallet balance management
- 💰 Trading fees applied (configurable)
- 💰 Position tracking in separate database
- 💰 P/L calculation based on actual price movements

### What's Different from Real Trading?

1. **No Slippage**: Virtual orders execute at exactly the current market price
2. **Instant Fills**: No waiting for order matching
3. **No Market Impact**: Your virtual orders don't affect the real market
4. **Separate Database**: Virtual trades stored in `virtual_trades.db`

## Virtual Trading Database Schema

The virtual wallet maintains several tables:

### `wallet`
- Current balance
- Initial balance
- Creation and update timestamps

### `virtual_trades`
- Complete trade history
- Entry and exit prices
- Profit/loss per trade
- Trading fees

### `virtual_positions`
- Active positions
- Entry prices and amounts
- Position values

### `transactions`
- Detailed transaction log
- Balance changes
- Timestamps

## Example Workflow

### 1. Initial Setup

```bash
# Set your initial virtual balance in .env
echo "VIRTUAL_INITIAL_BALANCE=5000.0" >> .env

# Start virtual trading
trader virtual
```

### 2. Monitor Performance

Let the bot run for a few hours or days, then check statistics:

```bash
trader trade --show-stats
```

### 3. Optimize Strategy

If your strategy isn't performing well:

```bash
# Reset and try different parameters
trader trade --reset-virtual

# Modify strategy settings in your code
# Run again with new settings
trader virtual
```

### 4. Go Live (When Ready)

Once you're confident in your strategy's performance:

```bash
# Switch to real trading (be careful!)
trader trade
```

## Tips for Virtual Trading

1. **Run for Extended Periods**: Test for at least a few days to see how your strategy handles different market conditions

2. **Monitor Key Metrics**:
   - Win rate (aim for >60%)
   - Average P/L per trade
   - Maximum drawdown
   - Total return percentage

3. **Test Market Conditions**:
   - Bull markets (rising prices)
   - Bear markets (falling prices)
   - Sideways markets (ranging)

4. **Realistic Expectations**: Virtual trading shows what's possible, but real trading may have:
   - Slippage (worse fill prices)
   - Network delays
   - Emotional factors

5. **Keep Trading Fees Realistic**: Default 0.25% is close to Bitvavo's actual fees

## Troubleshooting

### Virtual wallet not initializing

Check that the data directory exists:
```bash
mkdir -p data
```

### Database errors

Reset the virtual database:
```bash
rm -f data/virtual_trades.db
trader trade --reset-virtual
```

### Balance issues

Verify your configuration:
```bash
trader trade --show-stats
```

## Advanced Features

### Custom Initial Balance

Set different starting amounts for testing:

```bash
# In .env
VIRTUAL_INITIAL_BALANCE=10000.0  # Start with €10,000
```

### Custom Trading Fees

Test with different fee structures:

```bash
# In .env
VIRTUAL_TRADING_FEE=0.10  # 0.10% instead of default 0.25%
```

### Database Location

Store virtual trades database elsewhere:

```bash
# In .env
VIRTUAL_DB_PATH=/custom/path/virtual_trades.db
```

## Comparing Virtual vs Real Trading

| Feature | Virtual Trading | Real Trading |
|---------|----------------|--------------|
| Market Data | Real-time from Bitvavo | Real-time from Bitvavo |
| Order Execution | Simulated | Real orders on exchange |
| Money at Risk | None (virtual) | Real money |
| Trading Fees | Simulated (0.25%) | Real fees (~0.15-0.25%) |
| Slippage | None | Possible |
| Database | `virtual_trades.db` | `trades.db` |
| Perfect for | Testing & learning | Actual trading |

## Best Practices

1. ✅ **Always test with virtual trading first**
2. ✅ **Run for at least 100 trades before evaluating performance**
3. ✅ **Monitor win rate, not just total P/L**
4. ✅ **Test during different times of day and market conditions**
5. ✅ **Keep realistic expectations about real trading results**
6. ⚠️ **Don't go live until you're consistently profitable in virtual mode**

## Support

If you encounter issues with virtual trading:

1. Check the logs for error messages
2. Verify your `.env` configuration
3. Try resetting the virtual wallet: `trader trade --reset-virtual`
4. Report issues at: https://github.com/yourusername/bender/issues

---

**Remember**: Virtual trading is a powerful tool for learning and optimization, but real trading involves additional factors like emotions, slippage, and actual money at risk. Use virtual trading to build confidence and refine your strategy!
