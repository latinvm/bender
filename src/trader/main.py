from typing import Dict, List, Optional
import logging
import argparse
from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.market import MarketOperations
from trader.logger import setup_logger
import numpy as np
from trader.exceptions import BitvavoError, MarketNotFoundError, APIConnectionError, AuthenticationError
from trader.enhanced_strategy import EnhancedStrategy
from trader.database import TradeDatabase
from trader.backtester import Backtester
from trader.virtual_wallet import VirtualWallet
from trader.virtual_market import VirtualMarketOperations
from trader.multi_market_strategy import MultiMarketStrategy
import time
from datetime import datetime, timedelta

# Logger will be set up in main() based on --monitor flag
logger = None

# Global cache for top 50 markets
_top_50_cache: Optional[Dict] = None

def display_market_info(market_ops: MarketOperations, market: str) -> None:
    """Display comprehensive market information"""
    try:
        # Get market information
        market_info = market_ops.get_market_info(market)
        logger.info("\n=== Market Information ===")
        logger.info(f"Market: {market}")
        logger.info(f"Status: {market_info['status']}")
        logger.info(f"Base: {market_info['base']}")
        logger.info(f"Quote: {market_info['quote']}")
        
        # Get current price
        ticker = market_ops.get_ticker(market)
        logger.info(f"Current Price: €{float(ticker['price']):.2f}")
        
        # Get order book
        book = market_ops.get_book(market, 5)
        logger.info("\n=== Order Book ===")
        logger.info("Top 5 Bids:")
        for bid in book['bids']:
            logger.info(f"Price: €{float(bid[0]):.2f}, Amount: {float(bid[1]):.6f}")
        logger.info("\nTop 5 Asks:")
        for ask in book['asks']:
            logger.info(f"Price: €{float(ask[0]):.2f}, Amount: {float(ask[1]):.6f}")

    except (MarketNotFoundError, APIConnectionError) as e:
        logger.error(f"Error getting market info: {str(e)}")

def calculate_sharpe_ratio(returns, risk_free_rate=0.0):
    """Calculate the Sharpe ratio for a series of returns."""
    excess_returns = returns - risk_free_rate
    if np.std(excess_returns) == 0:
        return 0.0
    return np.mean(excess_returns) / np.std(excess_returns)

def calculate_sortino_ratio(returns, risk_free_rate=0.0):
    """Calculate the Sortino ratio for a series of returns."""
    excess_returns = returns - risk_free_rate
    downside_returns = excess_returns[excess_returns < 0]
    if np.std(downside_returns) == 0:
        return 0.0
    return np.mean(excess_returns) / np.std(downside_returns)

def scan_all_markets_for_top_50(market_ops: MarketOperations, cache_duration_hours: int = 6) -> List[str]:
    """STEP 1: Scan ALL altcoins and select top 50 by volume and basic metrics

    This is a periodic, comprehensive scan that caches results for cache_duration_hours.

    Args:
        market_ops: MarketOperations instance
        cache_duration_hours: How long to cache results (default: 6 hours)

    Returns:
        List of top 50 market symbols sorted by a basic score
    """
    global _top_50_cache

    # Check if cache is valid
    if _top_50_cache is not None:
        cache_age = datetime.now() - _top_50_cache['timestamp']
        if cache_age < timedelta(hours=cache_duration_hours):
            logger.info(f"Using cached top 50 markets (age: {cache_age.total_seconds()/3600:.1f}h, expires in {cache_duration_hours - cache_age.total_seconds()/3600:.1f}h)")
            return _top_50_cache['markets']

    logger.info("=" * 80)
    logger.info("STEP 1: Scanning ALL altcoins to find top 50 candidates")
    logger.info("=" * 80)

    # Get ALL altcoins under configured max price
    logger.info("Fetching complete altcoin list...")
    from trader.config import get_config
    _, _, _, strategy_config = get_config(load_env=False)  # Config already loaded
    alt_coins = market_ops.list_alt_coins(max_price=strategy_config.max_coin_price)
    logger.info(f"Found {len(alt_coins)} total altcoins under €{strategy_config.max_coin_price}")

    if not alt_coins:
        logger.warning("No altcoins found, using defaults")
        return ['VET-EUR', 'FLOKI-EUR', 'PEPE-EUR']

    # Quick-score all markets based on volume and basic metrics
    logger.info(f"Quick-scoring all {len(alt_coins)} markets...")
    scored_markets = []

    for i, coin in enumerate(alt_coins, 1):
        if coin['status'] != 'trading':
            continue

        market = coin['market']

        # Progress indicator every 50 markets
        if i % 50 == 0:
            logger.info(f"Progress: {i}/{len(alt_coins)} markets scanned...")

        try:
            # Get 24h ticker data (fast, single API call)
            info = market_ops.get_detailed_market_info(market)

            # Calculate basic score components
            volume = info['volume_quote']  # Volume in EUR
            volatility = ((info['high'] - info['low']) / info['low']) * 100 if info['low'] > 0 else 0

            # Quick score: 70% volume, 30% volatility
            # This is a fast pre-filter, detailed analysis happens in Step 2
            volume_score = min(volume / 10000, 1.0)  # Normalize volume
            volatility_score = min(volatility / 10, 1.0)  # Normalize volatility
            quick_score = (volume_score * 0.7) + (volatility_score * 0.3)

            scored_markets.append({
                'market': market,
                'score': quick_score,
                'volume': volume,
                'volatility': volatility
            })

        except Exception as e:
            logger.debug(f"Error scoring {market}: {str(e)}")
            continue

    # Sort by score and take top 50
    scored_markets = sorted(scored_markets, key=lambda x: x['score'], reverse=True)
    top_50 = [m['market'] for m in scored_markets[:50]]

    logger.info(f"\nSelected top 50 markets from {len(scored_markets)} candidates")
    logger.info("Top 10 markets by quick-score:")
    for i, market_data in enumerate(scored_markets[:10], 1):
        logger.info(f"{i}. {market_data['market']}: score={market_data['score']:.3f}, volume=€{market_data['volume']:.0f}, vol={market_data['volatility']:.1f}%")

    # Cache the results
    _top_50_cache = {
        'markets': top_50,
        'timestamp': datetime.now(),
        'detailed_data': scored_markets[:50]  # Store top 50 with details
    }

    logger.info(f"\nCached top 50 markets for {cache_duration_hours} hours")
    logger.info("=" * 80)

    return top_50

def find_best_markets(market_ops: MarketOperations, top_n: int = 3, max_candidates: int = 10, top_50_markets: Optional[List[str]] = None) -> List[str]:
    """STEP 2: Find the best markets from top 50 based on detailed analysis

    Args:
        market_ops: MarketOperations instance
        top_n: Number of top markets to return (default: 3)
        max_candidates: Maximum number of markets to analyze in detail (default: 10)
        top_50_markets: Pre-filtered list of top 50 markets from Step 1 (optional)

    Returns:
        List of top market symbols (e.g., ['FLOKI-EUR', 'PEPE-EUR', 'SHIB-EUR'])

    Improvements:
        - Added bid-ask spread filter (rejects >0.5% spread)
        - Added volume consistency check (penalizes pumps/dumps)
        - Reweighted scoring: Volatility 25%, Sharpe 25%, Sortino 25%, Volume 15%, Spread 10%
        - Now uses pre-filtered top 50 markets from Step 1 for efficiency
    """
    logger.info("=" * 80)
    logger.info(f"STEP 2: Detailed analysis to find top {top_n} markets from candidates")
    logger.info("=" * 80)

    # If no top_50_markets provided, use all altcoins (fallback to old behavior)
    if top_50_markets is None:
        logger.info("No pre-filtered markets provided, fetching all altcoins...")
        from trader.config import get_config
        _, _, _, strategy_config = get_config(load_env=False)  # Config already loaded
        alt_coins = market_ops.list_alt_coins(max_price=strategy_config.max_coin_price)
        logger.info(f"Found {len(alt_coins)} altcoins under €{strategy_config.max_coin_price}")

        if not alt_coins:
            logger.warning("No altcoins found, using defaults")
            return ['VET-EUR', 'FLOKI-EUR', 'PEPE-EUR'][:top_n]

        # Use the first 50 as candidates
        candidate_markets = [coin['market'] for coin in alt_coins[:50] if coin['status'] == 'trading']
    else:
        logger.info(f"Using pre-filtered top 50 markets from cache")
        candidate_markets = top_50_markets

    # Get detailed info for candidates
    logger.info(f"Fetching detailed info for {min(max_candidates, len(candidate_markets))} candidates...")
    candidates = []
    for market in candidate_markets[:max_candidates]:  # Use pre-filtered markets
        try:
            info = market_ops.get_detailed_market_info(market)
            candidates.append({
                'market': market,
                'volume_quote': info['volume_quote'],
                'info': info
            })
        except Exception as e:
            logger.debug(f"Skipping {market}: {str(e)}")
            continue

    # Sort by volume and take top candidates
    candidates = sorted(candidates, key=lambda x: x['volume_quote'], reverse=True)[:max_candidates]
    logger.info(f"Performing detailed analysis on {len(candidates)} markets...")

    # Store all scored markets
    scored_markets = []

    for candidate in candidates:
        market = candidate['market']
        info = candidate['info']

        # Calculate basic metrics
        volatility = ((info['high'] - info['low']) / info['low']) * 100 if info['low'] > 0 else 0
        volume = info['volume_quote']  # Volume in EUR
        trend = (info['price'] - info['open']) / info['open'] * 100 if info['open'] > 0 else 0

        # Get historical data for Sharpe, Sortino ratios, and volume consistency
        try:
            candles = market_ops.get_historical_candles(market, interval='1h', limit=168) # 7 days of hourly data
            if not candles or len(candles) < 10:
                logger.debug(f"Insufficient candle data for {market}")
                continue

            closes = np.array([float(c[4]) for c in candles])
            returns = (closes[1:] - closes[:-1]) / closes[:-1]

            sharpe_ratio = calculate_sharpe_ratio(returns)
            sortino_ratio = calculate_sortino_ratio(returns)

            # Calculate volume consistency (compare recent 24h volume vs 7-day average)
            # Get volume in quote currency (EUR) from candles - need to sum last 24 hourly candles
            volumes_quote = np.array([float(c[5]) * float(c[4]) for c in candles])  # volume * close price = quote volume

            # Calculate average daily volume from the 7 days of data
            avg_daily_volume = np.mean(volumes_quote) * 24  # Average hourly * 24 = daily average

            # Compare current 24h volume to average daily volume
            volume_spike_ratio = volume / avg_daily_volume if avg_daily_volume > 0 else 1.0

        except Exception as e:
            logger.debug(f"Error calculating ratios for {market}: {str(e)}")
            sharpe_ratio = 0
            sortino_ratio = 0
            volume_spike_ratio = 1.0

        # NEW: Get bid-ask spread
        spread_pct = 999.0  # Default to high value if we can't get spread
        spread_score = 0.0
        try:
            book = market_ops.get_book(market, depth=5)
            if book and 'bids' in book and 'asks' in book and len(book['bids']) > 0 and len(book['asks']) > 0:
                best_bid = float(book['bids'][0][0])
                best_ask = float(book['asks'][0][0])
                spread_pct = ((best_ask - best_bid) / best_bid) * 100

                # Spread score: 1.0 for 0% spread, 0.0 for >=0.5% spread
                spread_score = max(0, min(1.0, 1.0 - (spread_pct / 0.5)))
        except Exception as e:
            logger.debug(f"Error fetching spread for {market}: {str(e)}")

        # Score the market components
        volume_score = min(volume / 10000, 1.0)  # Normalize volume, max at €10k
        volatility_score = min(volatility / 10, 1.0)  # Normalize volatility, max at 10%
        sharpe_score = max(0, min(sharpe_ratio, 1.0))
        sortino_score = max(0, min(sortino_ratio, 1.0))

        # NEW: Reweighted scoring formula
        # Volatility 25%, Sharpe 25%, Sortino 25%, Volume 15%, Spread 10%
        total_score = (
            (volatility_score * 0.25) +
            (sharpe_score * 0.25) +
            (sortino_score * 0.25) +
            (volume_score * 0.15) +
            (spread_score * 0.10)
        )

        # NEW: Apply volume consistency penalties
        penalty_applied = None
        if volume_spike_ratio > 5.0:
            total_score *= 0.6  # 40% penalty for pump & dump pattern
            penalty_applied = f"PUMP (volume {volume_spike_ratio:.1f}x normal)"
        elif volume_spike_ratio < 0.3:
            total_score *= 0.7  # 30% penalty for dying market
            penalty_applied = f"LOW_VOLUME (volume {volume_spike_ratio:.1f}x normal)"

        # Reject markets with excessive spread
        if spread_pct > 0.5:
            logger.info(f"\nRejecting {market}: Spread too wide ({spread_pct:.2f}% > 0.5%)")
            continue

        logger.info(f"\nAnalyzing {market}:")
        logger.info(f"Volume (24h): €{volume:.2f} | Score: {volume_score:.2f}")
        logger.info(f"Volatility: {volatility:.1f}% | Score: {volatility_score:.2f}")
        logger.info(f"Sharpe Ratio: {sharpe_ratio:.2f} | Score: {sharpe_score:.2f}")
        logger.info(f"Sortino Ratio: {sortino_ratio:.2f} | Score: {sortino_score:.2f}")
        logger.info(f"Bid-Ask Spread: {spread_pct:.3f}% | Score: {spread_score:.2f}")
        logger.info(f"Volume Consistency: {volume_spike_ratio:.2f}x avg")
        if penalty_applied:
            logger.info(f"Penalty Applied: {penalty_applied}")
        logger.info(f"Final Score: {total_score:.3f}")

        # Add to scored markets list
        scored_markets.append({
            'market': market,
            'score': total_score
        })

    # Sort by score and select top N
    scored_markets = sorted(scored_markets, key=lambda x: x['score'], reverse=True)

    if not scored_markets:
        logger.warning("No suitable markets found, using defaults")
        return ['VET-EUR', 'FLOKI-EUR', 'PEPE-EUR'][:top_n]

    # Get top N markets
    top_markets = [m['market'] for m in scored_markets[:top_n]]

    logger.info(f"\nSelected top {len(top_markets)} markets:")
    for i, market_data in enumerate(scored_markets[:top_n], 1):
        logger.info(f"{i}. {market_data['market']} (score: {market_data['score']:.3f})")

    return top_markets

def main():
    parser = argparse.ArgumentParser(description="Bender Trading Bot")
    parser.add_argument('command', nargs='?', default='trade', help="Command to run: trade, virtual, or backtest")
    parser.add_argument('--market', type=str, default='VET-EUR', help="Market for backtesting (e.g., VET-EUR)")
    parser.add_argument('--start', type=str, default='2023-01-01', help="Start date for backtesting (YYYY-MM-DD)")
    parser.add_argument('--end', type=str, default='2023-12-31', help="End date for backtesting (YYYY-MM-DD)")
    parser.add_argument('--reset', action='store_true', help="Reset virtual wallet to initial balance (virtual mode only)")
    parser.add_argument('--stats', action='store_true', help="Show trading statistics and exit")
    parser.add_argument('--monitor', action='store_true', help="Show live terminal UI while trading (outputs logs to file)")
    args = parser.parse_args()

    # Setup logger - disable console output if monitor is active
    setup_logger('trader', console_output=not args.monitor)
    global logger
    logger = logging.getLogger('trader.main')

    if args.command == 'trade' or args.command == 'virtual':
        # Determine mode based on command
        virtual_mode = args.command == 'virtual'

        # Validate that --reset only works with virtual mode
        if args.reset and not virtual_mode:
            logger.error("Error: --reset can only be used with 'trader virtual' command")
            logger.error("Usage: trader virtual --reset")
            return

        if virtual_mode:
            logger.info("Starting trader application in VIRTUAL TRADING MODE")
            logger.info("WARNING: All trades will be simulated - no real money will be used")
        else:
            logger.info("Starting trader application in REAL TRADING MODE")
            logger.info("WARNING: Real trades will be executed with real money!")

        if args.monitor:
            logger.info("Monitor mode enabled - logs will be written to logs/ directory")
            logger.info(f"Log file: logs/{time.strftime('%Y-%m-%d')}.log")

        try:
            # Initialize configurations
            bitvavo_config, db_config, virtual_config, strategy_config = get_config()

            # Initialize Bitvavo client
            client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)

            # Initialize market operations (real or virtual)
            if virtual_mode:
                # Initialize virtual wallet
                virtual_wallet = VirtualWallet(
                    db_path=virtual_config.virtual_db_path,
                    initial_balance=virtual_config.initial_balance
                )

                # Handle reset if requested (before monitor starts)
                reset_performed = False
                if args.reset:
                    logger.info("Resetting virtual wallet...")
                    virtual_wallet.reset_wallet()
                    logger.info(f"Virtual wallet reset to €{virtual_wallet.get_balance():.2f}")
                    reset_performed = True

                # Show stats if requested
                if args.stats:
                    stats = virtual_wallet.get_statistics()
                    logger.info("\n" + "="*80)
                    logger.info("VIRTUAL TRADING STATISTICS")
                    logger.info("="*80)
                    logger.info(f"Current Balance:      €{stats['balance']:.2f}")
                    logger.info(f"Initial Balance:      €{stats['initial_balance']:.2f}")
                    logger.info(f"Total Return:         €{stats['total_return']:+.2f} ({stats['total_return_pct']:+.2f}%)")
                    logger.info(f"Total Trades:         {stats['total_trades']}")
                    logger.info(f"Winning Trades:       {stats['winning_trades']}")
                    logger.info(f"Losing Trades:        {stats['losing_trades']}")
                    logger.info(f"Win Rate:             {stats['win_rate']:.1f}%")
                    logger.info(f"Avg P/L per Trade:    €{stats['avg_profit_loss']:+.2f}")
                    logger.info(f"Best Trade:           €{stats['max_profit']:+.2f}")
                    logger.info(f"Worst Trade:          €{stats['max_loss']:+.2f}")
                    logger.info("="*80)

                    # Show recent trades
                    recent_trades = virtual_wallet.get_trade_history(limit=10)
                    if recent_trades:
                        logger.info("\nRecent Trades (Last 10):")
                        logger.info("-"*80)
                        for trade in recent_trades:
                            if trade['status'] == 'CLOSED':
                                logger.info(f"[CLOSED] {trade['market']}: {trade['amount']:.8f} @ €{trade['entry_price']:.6f} -> €{trade['exit_price']:.6f} | P/L: €{trade['profit_loss']:+.2f} ({trade['profit_loss_pct']:+.2f}%)")
                            else:
                                logger.info(f"[ACTIVE] {trade['market']}: {trade['amount']:.8f} @ €{trade['entry_price']:.6f}")
                    return

                # Initialize virtual market operations
                market_ops = VirtualMarketOperations(
                    client=client,
                    virtual_wallet=virtual_wallet,
                    operator_id=bitvavo_config.operator_id,
                    trading_fee_pct=virtual_config.trading_fee_pct
                )

                logger.info(f"Virtual wallet initialized with €{virtual_wallet.get_balance():.2f}")
            else:
                # Real trading mode
                db = TradeDatabase(db_config.db_path)
                logger.info(f"Initialized trade database at {db_config.db_path}")

                # Show stats if requested
                if args.stats:
                    logger.info("\n" + "="*80)
                    logger.info("REAL TRADING STATISTICS")
                    logger.info("="*80)

                    # Show active positions
                    active_positions = db.get_active_positions()
                    if active_positions:
                        logger.info(f"\nActive Positions: {len(active_positions)}")
                        for pos in active_positions:
                            logger.info(f"{pos['market']}: {pos['amount']:.2f} @ €{pos['entry_price']:.6f}")
                    else:
                        logger.info("\nActive Positions: 0")

                    # Show total P/L
                    total_pl = db.get_total_profit_loss()
                    logger.info(f"\nTotal P/L: €{total_pl:+.2f}")
                    logger.info("="*80)
                    return

                # Show any active positions from previous runs
                active_positions = db.get_active_positions()
                if active_positions:
                    logger.info("Found active positions from previous session:")
                    for pos in active_positions:
                        logger.info(f"{pos['amount']} {pos['market']} @ €{pos['entry_price']:.6f}")

                # Show total P/L
                total_pl = db.get_total_profit_loss()
                logger.info(f"Total P/L from all trades: €{total_pl:.2f}")

                market_ops = MarketOperations(client, operator_id=bitvavo_config.operator_id)

            # 2-STEP MARKET SELECTION
            # STEP 1: Scan all markets and get top 50 (cached for configured hours)
            logger.info("\n" + "=" * 80)
            logger.info("2-STEP MARKET SELECTION PROCESS")
            logger.info("=" * 80)
            top_50_markets = scan_all_markets_for_top_50(market_ops, cache_duration_hours=strategy_config.market_cache_hours)

            # STEP 2: Detailed analysis on top 50 to select best markets
            num_markets = virtual_config.max_positions
            markets = find_best_markets(market_ops, top_n=num_markets, max_candidates=strategy_config.max_candidates, top_50_markets=top_50_markets)

            logger.info("\n" + "=" * 80)
            logger.info(f"FINAL SELECTION: {len(markets)} market(s) for trading")
            logger.info(f"Markets: {', '.join(markets)}")
            logger.info("=" * 80 + "\n")

            # Display market information for first market
            display_market_info(market_ops, markets[0])

            # Run test trade cycle - skip if resuming with existing positions
            if virtual_mode:
                # Check if we have any active positions from a previous session
                active_positions = virtual_wallet.get_active_positions()
                if active_positions:
                    logger.info(f"Resuming with {len(active_positions)} existing position(s) - skipping test trade")
                    for pos in active_positions:
                        logger.info(f"{pos['market']}: {pos['amount']:.2f} @ €{pos['entry_price']:.6f}")
                else:
                    logger.info("Running test trade cycle...")
                    if not market_ops.test_trade(markets[0]):
                        logger.error("Test trade failed - aborting strategy")
                        return
                    logger.info("Test trade successful - starting main strategy")
            else:
                # Real trading mode - always run test trade
                logger.info("Running test trade cycle...")
                if not market_ops.test_trade(markets[0]):
                    logger.error("Test trade failed - aborting strategy")
                    return
                logger.info("Test trade successful - starting main strategy")

            # Determine strategy interval from configuration
            # Both virtual and real mode use the same interval for consistent behavior
            strategy_interval = strategy_config.strategy_interval

            # Create strategy based on number of markets
            # Pass virtual_wallet and strategy_config to strategies when in virtual mode
            if len(markets) > 1:
                # Multi-market strategy
                logger.info(f"Using multi-market strategy with {len(markets)} markets")
                strategy = MultiMarketStrategy(
                    market_ops=market_ops,
                    markets=markets,
                    investment_per_market=strategy_config.trade_amount,
                    virtual_wallet=virtual_wallet if virtual_mode else None,
                    max_positions=virtual_config.max_positions,
                    stop_loss_pct=strategy_config.stop_loss_pct,
                    take_profit_pct=strategy_config.take_profit_pct
                )
            else:
                # Single market strategy
                logger.info(f"Using single-market strategy")
                strategy = EnhancedStrategy(
                    market_ops=market_ops,
                    market=markets[0],
                    investment_amount=strategy_config.trade_amount,
                    virtual_wallet=virtual_wallet if virtual_mode else None,
                    max_positions=virtual_config.max_positions,
                    stop_loss_pct=strategy_config.stop_loss_pct,
                    take_profit_pct=strategy_config.take_profit_pct
                )

            # Setup periodic market rescan (every configured hours)
            import threading

            def periodic_market_rescan():
                """Periodically rescan all markets to refresh top 50 cache"""
                while True:
                    time.sleep(strategy_config.market_cache_hours * 60 * 60)
                    try:
                        logger.info("\n" + "=" * 80)
                        logger.info(f"PERIODIC MARKET RESCAN (every {strategy_config.market_cache_hours} hours)")
                        logger.info("=" * 80)
                        # Force cache refresh by calling scan function
                        # (cache will be automatically invalidated after configured hours)
                        scan_all_markets_for_top_50(market_ops, cache_duration_hours=strategy_config.market_cache_hours)
                        logger.info("Market rescan completed - top 50 cache refreshed")
                        logger.info("=" * 80 + "\n")
                    except Exception as e:
                        logger.error(f"Error during periodic market rescan: {e}")

            # Start periodic rescan thread
            rescan_thread = threading.Thread(target=periodic_market_rescan, daemon=True)
            rescan_thread.start()
            logger.info(f"Started periodic market rescan thread (rescans every {strategy_config.market_cache_hours} hours)")

            # Handle monitor mode
            if args.monitor:
                logger.info(f"Starting strategy with {strategy_interval}s interval with live TUI monitor...")

                # Log reset status if it was performed (for TUI log panel)
                if virtual_mode and reset_performed:
                    logger.info("Note: Virtual wallet was reset to initial balance before starting")

                from trader.tui import run_tui_with_data

                # Run TUI in main thread, strategy in background thread
                def run_strategy_in_background():
                    """Run strategy in background thread"""
                    try:
                        strategy.run(interval=strategy_interval)
                    except KeyboardInterrupt:
                        logger.info("Strategy stopped by user")
                    except Exception as e:
                        logger.error(f"Strategy error: {e}")

                # Start strategy in background thread
                strategy_thread = threading.Thread(target=run_strategy_in_background, daemon=True)
                strategy_thread.start()

                # Run TUI in main thread (blocks until user quits)
                # Pass live data sources to TUI
                if virtual_mode:
                    run_tui_with_data(virtual_mode=True, wallet=virtual_wallet, strategy=strategy)
                else:
                    run_tui_with_data(virtual_mode=False, db=db, strategy=strategy)

            else:
                # No monitor - run strategy normally with optional portfolio updates
                if virtual_mode:
                    logger.info(f"Starting strategy with {strategy_interval}s interval and portfolio updates every 5 minutes...")
                    import threading

                    def show_portfolio_periodically():
                        """Show portfolio summary every 5 minutes"""
                        while True:
                            time.sleep(300)  # 5 minutes
                            try:
                                market_ops.show_portfolio_summary()
                            except Exception as e:
                                logger.error(f"Error showing portfolio: {e}")

                    # Start portfolio monitoring thread
                    portfolio_thread = threading.Thread(target=show_portfolio_periodically, daemon=True)
                    portfolio_thread.start()

                    # Show initial portfolio
                    market_ops.show_portfolio_summary()
                else:
                    logger.info(f"Starting strategy with {strategy_interval}s interval...")

                # Run strategy
                strategy.run(interval=strategy_interval)

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {str(e)}")
        except BitvavoError as e:
            logger.error(f"Bitvavo API error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise

    elif args.command == 'backtest':
        logger.info("Starting backtester")
        bitvavo_config, _, _, strategy_config = get_config()
        client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)
        market_ops = MarketOperations(client)

        backtester = Backtester(
            market_ops=market_ops,
            strategy_class=EnhancedStrategy,
            market=args.market,
            start_date=args.start,
            end_date=args.end
        )
        backtester.run()

if __name__ == "__main__":
    main()