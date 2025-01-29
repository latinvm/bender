from trader.bitvavo import BitvavoClient
from trader.config import get_config
from trader.market import MarketOperations
from trader.logger import setup_logger
from trader.exceptions import BitvavoError, MarketNotFoundError, APIConnectionError, AuthenticationError
import logging

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

def main():
    logger.info("Starting trader application")
    
    try:
        # Initialize
        config = get_config()
        client = BitvavoClient(api_key=config.api_key, api_secret=config.api_secret)
        market_ops = MarketOperations(client)
        
        # Market to monitor
        market = 'BTC-EUR'
        
        # Display market information
        display_market_info(market_ops, market)
        
        # Start price monitoring
        logger.info("\n=== Starting Price Monitor ===")
        market_ops.monitor_price(market, interval=5.0)
            
    except AuthenticationError as e:
        logger.error(f"Authentication failed: {str(e)}")
    except BitvavoError as e:
        logger.error(f"Bitvavo API error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise

if __name__ == "__main__":
    main()