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
    """Find the best market based on volume, volatility, and trend

    Args:
        market_ops: MarketOperations instance
        max_candidates: Maximum number of markets to analyze in detail (default: 10)
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

        # Get historical data for Sharpe and Sortino ratios
        try:
            candles = market_ops.get_historical_candles(market, interval='1h', limit=168) # 7 days of hourly data
            if not candles or len(candles) < 10:
                logger.debug(f"Insufficient candle data for {market}")
                continue

            closes = np.array([float(c[4]) for c in candles])
            returns = (closes[1:] - closes[:-1]) / closes[:-1]

            sharpe_ratio = calculate_sharpe_ratio(returns)
            sortino_ratio = calculate_sortino_ratio(returns)
        except Exception as e:
            logger.debug(f"Error calculating ratios for {market}: {str(e)}")
            sharpe_ratio = 0
            sortino_ratio = 0

        # Score the market
        volume_score = min(volume / 10000, 1.0)  # Normalize volume, max at €10k
        volatility_score = min(volatility / 10, 1.0)  # Normalize volatility, max at 10%
        trend_score = max(0, min(1.0, 0.5 + (trend / 10)))  # Normalize trend, 0-1 range
        sharpe_score = max(0, min(sharpe_ratio, 1.0))
        sortino_score = max(0, min(sortino_ratio, 1.0))

        total_score = (volume_score * 0.2) + (volatility_score * 0.2) + (trend_score * 0.2) + (sharpe_score * 0.2) + (sortino_score * 0.2)

        logger.info(f"\nAnalyzing {market}:")
        logger.info(f"Volume: €{volume:.2f}")
        logger.info(f"24h Volatility: {volatility:.1f}%")
        logger.info(f"Price Trend: {trend:+.1f}%")
        logger.info(f"Sharpe Ratio: {sharpe_ratio:.2f}")
        logger.info(f"Sortino Ratio: {sortino_ratio:.2f}")
        logger.info(f"Total Score: {total_score:.2f}")

        if total_score > best_score:
            best_score = total_score
            best_market = market

    if not best_market:
        logger.warning("No suitable market found, using default")
        return 'VET-EUR'

    logger.info(f"\nSelected {best_market} with score {best_score:.2f}")
    return best_market

def main():
    parser = argparse.ArgumentParser(description="Bender Trading Bot")
    parser.add_argument('command', nargs='?', default='trade', help="Command to run (trade or backtest)")
    parser.add_argument('--market', type=str, default='VET-EUR', help="Market to trade or backtest")
    parser.add_argument('--start', type=str, default='2023-01-01', help="Start date for backtesting (YYYY-MM-DD)")
    parser.add_argument('--end', type=str, default='2023-12-31', help="End date for backtesting (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.command == 'trade':
        logger.info("Starting trader application")
        
        try:
            # Initialize configurations
            bitvavo_config, db_config = get_config()

            # Initialize database
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

            # Initialize Bitvavo client
            client = BitvavoClient(api_key=bitvavo_config.api_key, api_secret=bitvavo_config.api_secret)

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
        bitvavo_config, _ = get_config()
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