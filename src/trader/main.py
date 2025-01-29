from typing import Dict, List
import logging
from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.market import MarketOperations
from trader.logger import setup_logger
from trader.exceptions import BitvavoError, MarketNotFoundError, APIConnectionError, AuthenticationError
from trader.strategies import SimpleMAStrategy

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

def find_best_market(market_ops: MarketOperations) -> str:
    """Find the best market based on volume, volatility, and trend"""
    logger.info("Finding best market to trade...")
    
    # Get all altcoins under €10
    alt_coins = market_ops.list_alt_coins(max_price=10.0)
    best_market = None
    best_score = 0
    
    for coin in alt_coins:
        if coin['status'] != 'trading':
            continue
            
        market = coin['market']
        info = market_ops.get_detailed_market_info(market)
        
        # Calculate metrics
        volatility = ((info['high'] - info['low']) / info['low']) * 100
        volume = info['volume_quote']  # Volume in EUR
        trend = (info['price'] - info['open']) / info['open'] * 100
        
        # Score the market
        volume_score = min(volume / 10000, 1.0)  # Normalize volume, max at €10k
        volatility_score = min(volatility / 10, 1.0)  # Normalize volatility, max at 10%
        trend_score = 0.5 + (trend / 10)  # Normalize trend, 0-1 range
        
        total_score = volume_score * 0.4 + volatility_score * 0.4 + trend_score * 0.2
        
        logger.info(f"\nAnalyzing {market}:")
        logger.info(f"Volume: €{volume:.2f}")
        logger.info(f"24h Volatility: {volatility:.1f}%")
        logger.info(f"Price Trend: {trend:+.1f}%")
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
    logger.info("Starting trader application")
    
    try:
        # Initialize
        config = get_config()
        client = BitvavoClient(api_key=config.api_key, api_secret=config.api_secret)
        market_ops = MarketOperations(client)
        
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
        
        # Create strategy with aggressive settings
        strategy = SimpleMAStrategy(
            market_ops=market_ops,
            market=market,
            investment_amount=10.0,  # Full €10 investment
            short_window=1,          # 1-minute short MA
            long_window=3           # 3-minute long MA
        )
        
        # Run strategy with shorter interval for faster trades
        strategy.run(interval=30)
            
    except AuthenticationError as e:
        logger.error(f"Authentication failed: {str(e)}")
    except BitvavoError as e:
        logger.error(f"Bitvavo API error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise

if __name__ == "__main__":
    main()