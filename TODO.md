# Bender Trading Bot - Improvement Roadmap

> **Note**: This document consolidates and expands on the original TODO.txt items. Items marked with 🔥 ORIGINAL TODO directly address requests from the initial TODO list.

## Project Goal
Transform Bender into a robust, profitable trading bot that effectively exploits volatility in crypto markets through improved pair selection, risk management, and adaptive strategies.

---

## Recent Achievements (2025-10-20)

### ✅ Completed: Enhanced Market Selection (Phase 1.1)
1. **Bid-Ask Spread Filter**: Rejects markets with >0.5% spread to prevent execution cost drain
2. **Reweighted Scoring Formula**: Now prioritizes volatility (25%), Sharpe (25%), and Sortino (25%)
3. **Volume Consistency Check**: Detects and penalizes pump & dump patterns (>5x spike) and dying markets (<0.3x)
4. **Comprehensive Testing**: Added 3 new unit tests validating all improvements

**Impact**: Bot now selects more profitable volatile pairs while avoiding execution traps and unsustainable pumps.

---

## Phase 1: Critical Improvements (Week 1-2)

### 1.1 Enhanced Market Selection ✅ IN PROGRESS

#### Immediate Actions (Priority: CRITICAL)
- [x] **Add Bid-Ask Spread Filter**
  - Fetch order book data for candidate markets
  - Calculate spread percentage: `((ask - bid) / bid) * 100`
  - Reject pairs with spread >0.5%
  - Add spread score (10% weight) to market selection
  - **Impact**: Prevents execution costs from eating into profits
  - **File**: `src/trader/main.py::find_best_market()`

- [x] **Reweight Scoring Formula**
  - Update weights in market selection algorithm:
    - Volatility: 25% (increased from 20%)
    - Sharpe Ratio: 25% (increased from 20%)
    - Sortino Ratio: 25% (increased from 20%)
    - Volume: 15% (decreased from 20%)
    - Spread: 10% (new metric)
  - **Impact**: Prioritizes volatility and risk-adjusted returns
  - **File**: `src/trader/main.py::find_best_market()`

- [x] **Volume Consistency Check**
  - Calculate 7-day average volume from hourly candles
  - Compare current 24h volume to 7-day average
  - Apply 0.6x penalty if ratio > 5 (pump & dump detection)
  - Apply 0.7x penalty if ratio < 0.3 (dying market detection)
  - **Impact**: Avoids unsustainable volume spikes and illiquid markets
  - **File**: `src/trader/main.py::find_best_market()`

#### Quick Wins (Priority: HIGH)

- [ ] **Improve Logging - Decision Explanations** 🔥 ORIGINAL TODO
  - **Original Request**: "When decisions on buying or selling are made, log a verbose 'why' message"
  - Add verbose logging for buy/sell decisions showing exact reasoning
  - Log which conditions triggered entry/exit with actual values
  - Include metric values at decision time (RSI, MACD, MA crossover, volume, etc.)
  - Add structured logging format for analysis
  - Example log format:
    ```
    BUY SIGNAL TRIGGERED for VET-EUR:
      ✓ Short MA (1.25) > Long MA (1.20) [BULLISH CROSSOVER]
      ✓ Volume increasing: 24h (15000) > Prev (12000) [+25%]
      ✓ RSI (35) < 40 [OVERSOLD]
      ✓ Current positions: 1/3 [ROOM AVAILABLE]
      → Executing BUY order: 10.0 VET @ €1.25
    ```
  - **Impact**: Critical for debugging, optimization, and understanding bot behavior
  - **Estimated Time**: 2-3 hours
  - **Files**: `src/trader/strategies.py`, `src/trader/enhanced_strategy.py`

- [ ] **Add ATR (Average True Range) to Scoring**
  - Calculate ATR from hourly candles using pandas-ta
  - Calculate ATR as percentage of price: `(ATR / price) * 100`
  - Add ATR score (15% weight) to selection algorithm
  - Adjust other weights accordingly
  - **Impact**: Captures gaps and true intraday volatility
  - **Estimated Time**: 2-3 hours
  - **File**: `src/trader/main.py::find_best_market()`

### 1.2 Position Management Improvements

- [ ] **Multi-Position Monitoring System** 🔥 ORIGINAL TODO
  - **Original Request**: "What if different stock is picked when there are still open positions? Keep monitoring those? Possibility to add multiple positions and check those?"
  - Track positions across different markets simultaneously
  - When new "best market" is found, continue monitoring existing positions in old markets
  - Implement position status dashboard in logs showing all active positions
  - Add logic to prevent opening new positions in same market
  - Options to implement:
    1. **Portfolio Approach**: Select 3 best markets upfront, trade all simultaneously
    2. **Rotation with Memory**: Switch markets but keep monitoring old positions until closed
    3. **Hybrid**: Primary market + monitoring up to 2 legacy positions
  - **Impact**: Solves critical TODO - handles market rotation with open positions
  - **Current Behavior**: Bot switches to new market, may ignore old positions ❌
  - **Estimated Time**: 4-6 hours
  - **Files**: `src/trader/main.py`, `src/trader/market.py`

- [ ] **Dynamic Position Sizing**
  - Adjust position size based on market volatility
  - Higher volatility = smaller positions (risk parity)
  - Formula: `position_size = base_amount / (volatility_pct / target_volatility)`
  - Cap maximum position size at €15, minimum at €5
  - **Impact**: Better risk management across varying volatility regimes
  - **Estimated Time**: 3-4 hours
  - **File**: `src/trader/main.py::run_trading_bot()`

### 1.3 Testing & Validation

- [ ] **Enhanced Backtesting Framework**
  - Add support for testing on multiple pairs simultaneously
  - Include spread costs in backtest results
  - Track maximum drawdown and win rate metrics
  - Generate performance report with statistics
  - **Impact**: Better strategy validation before live trading
  - **Estimated Time**: 6-8 hours
  - **File**: `src/trader/backtester.py`

- [ ] **Unit Tests for New Features**
  - Test spread calculation and filtering
  - Test volume consistency detection
  - Test reweighted scoring algorithm
  - Mock Bitvavo API responses for testing
  - **Estimated Time**: 4-5 hours
  - **File**: `tests/test_main.py`

---

## Phase 2: Advanced Market Selection (Week 3-4)

### 2.1 Advanced Volatility Metrics

- [ ] **Realized Volatility Calculator**
  - Calculate annualized volatility from returns
  - Support multiple timeframes: 1d, 7d, 30d
  - Add volatility consistency score
  - **Estimated Time**: 3-4 hours
  - **File**: `src/trader/volatility_analysis.py` (new)

- [ ] **Volatility Regime Detection**
  - Classify markets into low/medium/high volatility regimes
  - Compare short-term vs long-term volatility
  - Identify expanding vs contracting volatility
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/volatility_analysis.py`

- [ ] **ADX (Average Directional Index) Filter**
  - Calculate ADX from hourly candles
  - Filter for ADX between 20-40 (trending but not overextended)
  - Add trend quality score to market selection
  - **Estimated Time**: 2-3 hours
  - **File**: `src/trader/main.py::find_best_market()`

### 2.2 Liquidity & Execution Quality

- [ ] **Order Book Depth Analysis**
  - Measure liquidity at top 5 levels of order book
  - Calculate total depth in EUR for buy/sell sides
  - Require minimum €1000 total depth for trading
  - **Estimated Time**: 3-4 hours
  - **File**: `src/trader/market.py` (new function)

- [ ] **Slippage Estimation**
  - Estimate potential slippage for €10 orders
  - Factor slippage into pair selection scoring
  - Track actual slippage in live trading
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/market.py`

### 2.3 Correlation & Diversification

- [ ] **BTC Correlation Analysis**
  - Calculate correlation of each pair to BTC-EUR
  - Prefer pairs with 0.3-0.7 correlation for diversification
  - Store correlation data for portfolio construction
  - **Estimated Time**: 3-4 hours
  - **File**: `src/trader/correlation_analysis.py` (new)

- [ ] **Multi-Pair Portfolio Selection**
  - Select top 3 uncorrelated pairs for trading
  - Ensure pairwise correlation < 0.7
  - Allocate capital across pairs (€10 / 3 = €3.33 each)
  - Rebalance daily based on updated scores
  - **Estimated Time**: 6-8 hours
  - **Files**: `src/trader/main.py`, `src/trader/portfolio_manager.py` (new)

---

## Phase 3: Strategy Enhancements (Week 5-6)

### 3.1 Adaptive Strategy Parameters

- [ ] **Volatility-Adjusted Stops and Targets**
  - Scale stop-loss based on ATR: `stop = entry_price - (2 * ATR)`
  - Scale take-profit based on ATR: `target = entry_price + (3 * ATR)`
  - Maintain minimum -5% stop, maximum -10% stop
  - **Impact**: More adaptive to market conditions
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/enhanced_strategy.py`

- [ ] **Multiple Time Frame Analysis**
  - Check trend alignment across 5m, 1h, 4h timeframes
  - Only enter when all timeframes align
  - Use longer timeframe for trend, shorter for entry
  - **Estimated Time**: 5-6 hours
  - **File**: `src/trader/enhanced_strategy.py`

### 3.2 Additional Strategy Types

- [ ] **Mean Reversion Strategy**
  - Implement Bollinger Band-based mean reversion
  - Buy at lower band, sell at upper band
  - Use on pairs with Hurst exponent < 0.5
  - **Estimated Time**: 6-8 hours
  - **File**: `src/trader/mean_reversion_strategy.py` (new)

- [ ] **Breakout Strategy**
  - Detect consolidation patterns
  - Enter on volatility expansion breakouts
  - Use on pairs with increasing volume
  - **Estimated Time**: 8-10 hours
  - **File**: `src/trader/breakout_strategy.py` (new)

### 3.3 Strategy Selection Logic

- [ ] **Auto-Strategy Selector**
  - Analyze market characteristics (trending vs ranging)
  - Select best strategy for current market regime
  - Use ADX for trend strength, ATR for volatility
  - **Estimated Time**: 5-6 hours
  - **File**: `src/trader/strategy_selector.py` (new)

---

## Phase 4: Risk Management & Portfolio Optimization (Week 7-8)

### 4.1 Advanced Risk Management

- [ ] **Maximum Drawdown Protection**
  - Track portfolio equity in real-time
  - Stop trading if drawdown exceeds -15% from peak
  - Require manual restart after drawdown breach
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/risk_manager.py` (new)

- [ ] **Daily Loss Limits**
  - Set maximum daily loss (e.g., -€5 or -10%)
  - Stop trading for the day if limit hit
  - Reset at midnight UTC
  - **Estimated Time**: 3-4 hours
  - **File**: `src/trader/risk_manager.py`

- [ ] **Position Correlation Monitoring**
  - Track correlation between active positions
  - Alert if total portfolio correlation > 0.8
  - Prevent opening highly correlated positions
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/portfolio_manager.py`

### 4.2 Portfolio Optimization

- [ ] **Kelly Criterion Position Sizing**
  - Calculate optimal position size using Kelly formula
  - Based on historical win rate and avg win/loss
  - Apply fractional Kelly (e.g., 0.25x) for safety
  - **Estimated Time**: 5-6 hours
  - **File**: `src/trader/position_sizing.py` (new)

- [ ] **Dynamic Capital Allocation**
  - Allocate more capital to better-performing strategies
  - Reduce allocation after losing streaks
  - Implement equity curve-based scaling
  - **Estimated Time**: 6-8 hours
  - **File**: `src/trader/portfolio_manager.py`

---

## Phase 5: Analytics & Monitoring (Week 9-10)

### 5.1 Performance Analytics

- [ ] **Performance Dashboard**
  - Web-based dashboard showing current positions
  - Real-time P&L tracking
  - Strategy performance comparison
  - Market selection history
  - **Estimated Time**: 12-15 hours
  - **Files**: `src/dashboard/` (new module), requires Flask/FastAPI

- [ ] **Trade Analytics System**
  - Calculate win rate, profit factor, Sharpe ratio
  - Track performance by strategy, market, time of day
  - Generate weekly performance reports
  - **Estimated Time**: 6-8 hours
  - **File**: `src/trader/analytics.py` (new)

### 5.2 Alerting & Notifications

- [ ] **Trade Notifications**
  - Send notifications on trade entry/exit
  - Alert on significant P&L changes
  - Support email, Telegram, or Discord
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/notifications.py` (new)

- [ ] **System Health Monitoring**
  - Alert on API errors or connectivity issues
  - Monitor database health
  - Track system uptime and performance
  - **Estimated Time**: 3-4 hours
  - **File**: `src/trader/health_monitor.py` (new)

### 5.3 Advanced Pattern Recognition

- [ ] **Time-of-Day Analysis**
  - Identify hours with highest volatility per pair
  - Adjust trading schedule based on patterns
  - Track performance by hour of day
  - **Estimated Time**: 5-6 hours
  - **File**: `src/trader/temporal_analysis.py` (new)

- [ ] **Day-of-Week Patterns**
  - Analyze weekday vs weekend performance
  - Identify optimal trading days per pair
  - Adjust strategy parameters by day
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/temporal_analysis.py`

---

## Phase 6: Machine Learning & Advanced Features (Week 11-12+)

### 6.1 ML-Based Predictions

- [ ] **Volatility Prediction Model**
  - Train model to predict next 24h realized volatility
  - Features: historical volatility, volume, momentum indicators
  - Use XGBoost or LightGBM
  - **Estimated Time**: 15-20 hours
  - **File**: `src/ml/volatility_predictor.py` (new)

- [ ] **Price Direction Classifier**
  - Predict probability of upward move in next 1-4 hours
  - Combine with traditional signals for entry
  - Regular retraining on recent data
  - **Estimated Time**: 20-25 hours
  - **File**: `src/ml/direction_classifier.py` (new)

### 6.2 Advanced Market Analysis

- [ ] **Hurst Exponent Calculator**
  - Calculate Hurst exponent for trend persistence
  - Use to classify markets as trending/mean-reverting/random
  - Select strategy based on Hurst value
  - **Estimated Time**: 6-8 hours
  - **File**: `src/trader/hurst_analysis.py` (new)

- [ ] **Market Regime Detection**
  - Use Hidden Markov Models for regime detection
  - Identify bull/bear/sideways/volatile regimes
  - Adjust strategy based on detected regime
  - **Estimated Time**: 12-15 hours
  - **File**: `src/ml/regime_detector.py` (new)

### 6.3 Alternative Data Sources

- [ ] **Social Sentiment Integration**
  - Monitor Twitter/Reddit for coin mentions
  - Calculate sentiment scores
  - Boost pair score on increasing positive sentiment
  - **Estimated Time**: 15-20 hours
  - **File**: `src/data/sentiment_analyzer.py` (new)
  - **Note**: Requires Twitter/Reddit API access

- [ ] **On-Chain Metrics**
  - Integrate blockchain data (active addresses, transaction volume)
  - Use as additional signals for pair selection
  - Focus on fundamentals for medium-term holds
  - **Estimated Time**: 20-25 hours
  - **File**: `src/data/onchain_data.py` (new)
  - **Note**: Requires blockchain data provider API

---

## Phase 7: Infrastructure & Operations (Ongoing)

### 7.1 Deployment & Reliability

- [ ] **Docker Containerization**
  - Create Dockerfile for easy deployment
  - Docker Compose for multi-service setup
  - Include database and dashboard services
  - **Estimated Time**: 4-6 hours

- [ ] **Automated Testing Pipeline**
  - Set up GitHub Actions for CI/CD
  - Run tests on every commit
  - Automated backtesting on strategy changes
  - **Estimated Time**: 6-8 hours

- [ ] **Database Migration System**
  - Implement proper migrations with Alembic
  - Version control for database schema
  - Safe upgrade path for production
  - **Estimated Time**: 5-6 hours

### 7.2 Configuration & Flexibility

- [ ] **Configuration Management System**
  - Move all parameters to config file
  - Support multiple configuration profiles
  - Hot-reload configuration without restart
  - **Estimated Time**: 4-5 hours
  - **File**: `src/trader/config.py`

- [ ] **Strategy Parameter Optimization**
  - Grid search for optimal strategy parameters
  - Walk-forward optimization
  - Store results for analysis
  - **Estimated Time**: 10-12 hours
  - **File**: `src/optimization/parameter_optimizer.py` (new)

### 7.3 Documentation

- [ ] **API Documentation**
  - Document all public functions and classes
  - Add docstrings with examples
  - Generate Sphinx documentation
  - **Estimated Time**: 8-10 hours

- [ ] **Strategy Documentation**
  - Detailed explanation of each strategy
  - Entry/exit rules with examples
  - Risk management rules
  - **Estimated Time**: 6-8 hours

- [ ] **Operations Runbook**
  - How to deploy and run the bot
  - Troubleshooting common issues
  - Emergency procedures (stop trading, etc.)
  - **Estimated Time**: 4-6 hours

---

## Success Metrics

### Performance Targets (3-Month Goals)
- **Win Rate**: >45% (currently unknown, need to track)
- **Profit Factor**: >1.5 (gross profit / gross loss)
- **Sharpe Ratio**: >1.0 (risk-adjusted returns)
- **Maximum Drawdown**: <20% from peak equity
- **Average Trade Duration**: 4-24 hours (exploit volatility)

### Operational Targets
- **Uptime**: >99% (minimize downtime)
- **API Error Rate**: <1% of calls
- **Trade Execution Time**: <5 seconds from signal to order
- **Backtest Coverage**: 100% of strategies tested on 1 year of data

### Risk Limits (Hard Stops)
- **Daily Loss Limit**: -€10 or -10% of capital
- **Maximum Drawdown**: -20% from peak (stop all trading)
- **Maximum Position Size**: €15 per position
- **Maximum Open Positions**: 3 concurrent
- **Maximum Leverage**: None (spot trading only)

---

## Priority Matrix

### Critical (Do First)
1. ✅ Bid-ask spread filter
2. ✅ Reweight scoring formula
3. ✅ Volume consistency check
4. Decision logging improvements
5. Multi-position monitoring

### High Priority (Do Next)
6. ATR-based volatility scoring
7. Enhanced backtesting framework
8. Dynamic position sizing
9. Order book depth analysis
10. BTC correlation analysis

### Medium Priority (After Core Features)
11. Multi-pair portfolio selection
12. Volatility-adjusted stops/targets
13. Multiple timeframe analysis
14. ADX trend quality filter
15. Performance analytics dashboard

### Low Priority (Nice to Have)
16. Alternative strategies (mean reversion, breakout)
17. ML-based predictions
18. Social sentiment integration
19. On-chain metrics
20. Advanced regime detection

---

## Notes & Considerations

### Known Issues to Address
1. **Market switching with open positions**: Currently no logic to handle switching markets when positions are open. Need to either continue monitoring old positions or close them before switching.

2. **Minimum order sizes**: Some pairs have high minimum order requirements that may exceed €10. Need better handling or filtering of these pairs.

3. **API rate limits**: Bitvavo has rate limits. May need to implement rate limiting and caching to avoid hitting limits during market selection.

4. **Timezone handling**: All timestamps should use UTC consistently. Need audit of timezone usage.

### Technical Debt
- Consider migrating from SQLite to PostgreSQL for production
- Add proper logging rotation (currently creates new file per day, but no cleanup)
- Implement connection pooling for database
- Add retry logic with exponential backoff for API calls

### Future Considerations
- **Multi-exchange support**: Expand beyond Bitvavo to other exchanges
- **Arbitrage opportunities**: Cross-exchange or triangular arbitrage
- **Futures trading**: Leverage-based strategies (requires different risk management)
- **Automated parameter tuning**: Continuous optimization based on recent performance
- **Paper trading mode**: Test new strategies without real money

---

## Getting Started with TODO

### For Developers
1. Start with Phase 1 (Critical Improvements)
2. Each item includes estimated time and file locations
3. Test thoroughly in backtest mode before live trading
4. Create feature branches for major changes
5. Update this document as items are completed

### Testing Workflow
1. Write unit tests for new features
2. Run backtests on historical data (1+ year)
3. Paper trade for 1-2 weeks
4. Start with small capital (€30-50) for live testing
5. Scale up gradually as confidence increases

---

**Last Updated**: 2025-10-20
**Version**: 1.0
**Status**: Phase 1 in progress
