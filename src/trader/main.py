from typing import Dict, List
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
import time

# Setup logging once at the application start
setup_logger('trader')
logger = logging.getLogger('trader.main')

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

def find_best_market(market_ops: MarketOperations, max_candidates: int = 10) -> str:
    """Find the best market based on volume, volatility, spread, and risk-adjusted returns

    Args:
        market_ops: MarketOperations instance
        max_candidates: Maximum number of markets to analyze in detail (default: 10)

    Improvements:
        - Added bid-ask spread filter (rejects >0.5% spread)
        - Added volume consistency check (penalizes pumps/dumps)
        - Reweighted scoring: Volatility 25%, Sharpe 25%, Sortino 25%, Volume 15%, Spread 10%
    """
    logger.info("Finding best market to trade...")

    # Get all altcoins under €10
    logger.info("Fetching altcoin list...")
    alt_coins = market_ops.list_alt_coins(max_price=10.0)
    logger.info(f"Found {len(alt_coins)} altcoins under €10")

    if not alt_coins:
        logger.warning("No altcoins found, using default")
        return 'VET-EUR'

    # Pre-filter by getting 24h ticker data (fast) and select top candidates by volume
    logger.info(f"Pre-filtering to top {max_candidates} candidates by volume...")
    candidates = []
    for coin in alt_coins[:30]:  # Only check first 30 to avoid too many API calls
        if coin['status'] != 'trading':
            continue

        market = coin['market']
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
    logger.info(f"Analyzing top {len(candidates)} markets in detail...")

    best_market = None
    best_score = 0

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

            # Calculate volume consistency (7-day average vs current 24h)
            volumes = np.array([float(c[5]) for c in candles])  # Volume is the 6th element
            avg_7d_volume = np.mean(volumes)
            volume_spike_ratio = volume / avg_7d_volume if avg_7d_volume > 0 else 1.0

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
        logger.info(f"  Volume (24h): €{volume:.2f} | Score: {volume_score:.2f}")
        logger.info(f"  Volatility: {volatility:.1f}% | Score: {volatility_score:.2f}")
        logger.info(f"  Sharpe Ratio: {sharpe_ratio:.2f} | Score: {sharpe_score:.2f}")
        logger.info(f"  Sortino Ratio: {sortino_ratio:.2f} | Score: {sortino_score:.2f}")
        logger.info(f"  Bid-Ask Spread: {spread_pct:.3f}% | Score: {spread_score:.2f}")
        logger.info(f"  Volume Consistency: {volume_spike_ratio:.2f}x avg")
        if penalty_applied:
            logger.info(f"  ⚠️  Penalty Applied: {penalty_applied}")
        logger.info(f"  Final Score: {total_score:.3f}")

        if total_score > best_score:
            best_score = total_score
            best_market = market

    if not best_market:
        logger.warning("No suitable market found, using default")
        return 'VET-EUR'

    logger.info(f"\n🎯 Selected {best_market} with score {best_score:.3f}")
    return best_market

def main():
    parser = argparse.ArgumentParser(description="Bender Trading Bot")
    parser.add_argument('command', nargs='?', default='trade', help="Command to run (trade, backtest, or virtual)")
    parser.add_argument('--market', type=str, default='VET-EUR', help="Market to trade or backtest")
    parser.add_argument('--start', type=str, default='2023-01-01', help="Start date for backtesting (YYYY-MM-DD)")
    parser.add_argument('--end', type=str, default='2023-12-31', help="End date for backtesting (YYYY-MM-DD)")
    parser.add_argument('--virtual', action='store_true', help="Enable virtual trading mode (paper trading)")
    parser.add_argument('--reset-virtual', action='store_true', help="Reset virtual wallet to initial balance")
    parser.add_argument('--show-stats', action='store_true', help="Show virtual trading statistics and exit")
    args = parser.parse_args()

    if args.command == 'trade' or args.command == 'virtual':
        # Enable virtual mode if command is 'virtual' or --virtual flag is set
        virtual_mode = args.command == 'virtual' or args.virtual

        if virtual_mode:
            logger.info("Starting trader application in VIRTUAL TRADING MODE")
            logger.info("⚠️  All trades will be simulated - no real money will be used")
        else:
            logger.info("Starting trader application in REAL TRADING MODE")
            logger.info("⚠️  WARNING: Real trades will be executed with real money!")

        try:
            # Initialize configurations
            bitvavo_config, db_config, virtual_config = get_config()

            # Initialize Bitvavo client
            client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)

            # Initialize market operations (real or virtual)
            if virtual_mode:
                # Initialize virtual wallet
                virtual_wallet = VirtualWallet(
                    db_path=virtual_config.virtual_db_path,
                    initial_balance=virtual_config.initial_balance
                )

                # Handle reset if requested
                if args.reset_virtual:
                    logger.info("Resetting virtual wallet...")
                    virtual_wallet.reset_wallet()
                    logger.info(f"Virtual wallet reset to €{virtual_wallet.get_balance():.2f}")

                # Show stats if requested
                if args.show_stats:
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
                            status_symbol = "✓" if trade['status'] == 'CLOSED' else "○"
                            if trade['status'] == 'CLOSED':
                                logger.info(f"{status_symbol} {trade['market']}: {trade['amount']:.8f} @ €{trade['entry_price']:.6f} → €{trade['exit_price']:.6f} | P/L: €{trade['profit_loss']:+.2f} ({trade['profit_loss_pct']:+.2f}%)")
                            else:
                                logger.info(f"{status_symbol} {trade['market']}: {trade['amount']:.8f} @ €{trade['entry_price']:.6f} [ACTIVE]")
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

                # Show any active positions from previous runs
                active_positions = db.get_active_positions()
                if active_positions:
                    logger.info("Found active positions from previous session:")
                    for pos in active_positions:
                        logger.info(f"  {pos['amount']} {pos['market']} @ €{pos['entry_price']:.6f}")

                # Show total P/L
                total_pl = db.get_total_profit_loss()
                logger.info(f"Total P/L from all trades: €{total_pl:.2f}")

                market_ops = MarketOperations(client, operator_id=bitvavo_config.operator_id)

            # Find best market to trade
            market = find_best_market(market_ops)
            logger.info(f"Selected market for trading: {market}")

            # Display market information
            display_market_info(market_ops, market)

            # Run test trade cycle
            logger.info("Running test trade cycle...")
            if not market_ops.test_trade(market):
                logger.error("Test trade failed - aborting strategy")
                return

            logger.info("Test trade successful - starting main strategy")

            # Create the enhanced strategy
            strategy = EnhancedStrategy(
                market_ops=market_ops,
                market=market,
                investment_amount=10.0,  # Full €10 investment
            )

            # If virtual mode, wrap the strategy execution with periodic portfolio updates
            if virtual_mode:
                logger.info("Starting strategy with periodic portfolio updates every 5 minutes...")
                # Run strategy in a modified loop with portfolio updates
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

            # Run strategy
            strategy.run(interval=300)

        except AuthenticationError as e:
            logger.error(f"Authentication failed: {str(e)}")
        except BitvavoError as e:
            logger.error(f"Bitvavo API error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise

    elif args.command == 'backtest':
        logger.info("Starting backtester")
        bitvavo_config, _, _ = get_config()
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