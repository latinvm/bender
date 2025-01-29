from typing import Dict, List, Optional
import logging
from trader.bitvavo import BitvavoClient
from trader.logger import setup_logger
from trader.exceptions import MarketNotFoundError, APIConnectionError, AuthenticationError
from datetime import datetime
import time

logger = logging.getLogger('trader.market')

class MarketOperations:
    def __init__(self, client: BitvavoClient):
        self.client = client
        logger.info("MarketOperations initialized")

    def get_balance(self) -> List[Dict]:
        """Get balance for all assets"""
        logger.info("Fetching balance for all assets")
        try:
            balance = self.client.bitvavo.balance({})
            logger.debug(f"Retrieved balance: {balance}")
            return balance
        except Exception as e:
            if 'UNAUTHORIZED' in str(e):
                logger.error("Authentication failed when fetching balance")
                raise AuthenticationError("Invalid API credentials") from e
            logger.error(f"Error fetching balance: {str(e)}")
            raise APIConnectionError(f"Failed to fetch balance: {str(e)}") from e

    def get_market_info(self, market: str) -> Dict:
        """Get detailed market information"""
        logger.info(f"Fetching market info for {market}")
        try:
            all_markets = self.client.bitvavo.markets({})
            for market_info in all_markets:
                if market_info['market'] == market:
                    logger.debug(f"Market info found: {market_info}")
                    return market_info
            logger.error(f"Market {market} not found")
            raise MarketNotFoundError(f"Market {market} not found")
        except MarketNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error fetching market info: {str(e)}")
            raise APIConnectionError(f"Failed to fetch market info: {str(e)}") from e

    def get_book(self, market: str, depth: int = 10) -> Dict:
        """Get order book for a market"""
        logger.info(f"Fetching order book for {market} with depth {depth}")
        try:
            book = self.client.bitvavo.book(market, {'depth': depth})
            logger.debug(f"Retrieved order book: {book}")
            return book
        except Exception as e:
            if 'market' in str(e).lower():
                raise MarketNotFoundError(f"Market {market} not found") from e
            logger.error(f"Error fetching order book: {str(e)}")
            raise APIConnectionError(f"Failed to fetch order book: {str(e)}") from e
    
    def get_ticker(self, market: str) -> Dict:
        """Get current ticker information"""
        logger.info(f"Fetching ticker for {market}")
        try:
            ticker = self.client.bitvavo.tickerPrice({'market': market})
            logger.debug(f"Retrieved ticker: {ticker}")
            return ticker
        except Exception as e:
            logger.error(f"Error fetching ticker: {str(e)}")
            raise APIConnectionError(f"Failed to fetch ticker: {str(e)}") from e

    def monitor_price(self, market: str, interval: float = 5.0) -> None:
        """
        Monitor price for a given market
        Args:
            market: Market to monitor (e.g., 'BTC-EUR')
            interval: Update interval in seconds
        """
        logger.info(f"Starting price monitor for {market}")
        previous_price = None

        try:
            while True:
                ticker = self.get_ticker(market)
                current_price = float(ticker['price'])
                current_time = datetime.now().strftime("%H:%M:%S")

                if previous_price is not None:
                    change = ((current_price - previous_price) / previous_price) * 100
                    logger.info(f"[{current_time}] {market}: €{current_price:.2f} ({change:+.2f}%)")
                else:
                    logger.info(f"[{current_time}] {market}: €{current_price:.2f}")

                previous_price = current_price
                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Price monitoring stopped by user")