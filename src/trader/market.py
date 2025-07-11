from typing import Dict, List, Optional
import logging
from trader.bitvavo import BitvavoClient
from trader.logger import setup_logger
from trader.exceptions import MarketNotFoundError, APIConnectionError, AuthenticationError
from datetime import datetime
import time
from trader.database import TradeDatabase

logger = logging.getLogger('trader.market')

class MarketOperations:
    def __init__(self, client: BitvavoClient, operator_id: Optional[str] = None):
        self.client = client
        self.db = TradeDatabase()
        self.operator_id = operator_id
        if self.operator_id:
            logger.info(f"MarketOperations initialized with operatorId: {self.operator_id}")
        else:
            logger.info("MarketOperations initialized without operatorId (orders will not include it)")
        # logger.info("MarketOperations initialized") # Original log line, potentially redundant

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
        Monitor price for a given market and show potential profit/loss for open positions
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

                # Get active positions for this market
                active_positions = [pos for pos in self.db.get_active_positions() if pos['market'] == market]
                
                # Calculate and display price change
                if previous_price is not None:
                    change = ((current_price - previous_price) / previous_price) * 100
                    logger.info(f"[{current_time}] {market}: €{current_price:.2f} ({change:+.2f}%)")
                else:
                    logger.info(f"[{current_time}] {market}: €{current_price:.2f}")

                # Display potential profit/loss for each open position
                for position in active_positions:
                    entry_price = position['entry_price']
                    amount = position['amount']
                    pl_amount = (current_price - entry_price) * amount
                    pl_percentage = ((current_price - entry_price) / entry_price) * 100
                    logger.info(f"Position: {amount:.8f} {market} | Entry: €{entry_price:.2f} | P/L: €{pl_amount:+.2f} ({pl_percentage:+.2f}%)")

                previous_price = current_price
                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Price monitoring stopped by user")
    
    def get_available_balance(self, symbol: str) -> float:
        """Get available balance for a specific asset"""
        logger.info(f"Fetching balance for {symbol}")
        try:
            balances = self.client.bitvavo.balance({})
            for balance in balances:
                if balance['symbol'] == symbol:
                    return float(balance['available'])
            return 0.0
        except Exception as e:
            logger.error(f"Error fetching balance: {str(e)}")
            raise APIConnectionError(f"Failed to fetch balance: {str(e)}") from e
    
    def place_limit_order(self, market: str, side: str, amount: float, price: float) -> Dict:
        """
        Place a limit order
        Args:
            market: Trading pair (e.g., 'BTC-EUR')
            side: 'buy' or 'sell'
            amount: Amount in base currency (e.g., BTC)
            price: Limit price in quote currency (e.g., EUR)
        """
        logger.info(f"Placing {side} limit order: {amount} {market} @ {price}")
        try:
            order_payload = {
                'amount': str(amount),
                'price': str(price)
            }
            if self.operator_id:
                order_payload['operatorId'] = self.operator_id

            response = self.client.bitvavo.placeOrder(market, side, 'limit', order_payload)
            logger.info(f"Order placed successfully: {response['orderId']}")
            return response
        except Exception as e:
            logger.error(f"Error placing limit order: {str(e)}")
            raise APIConnectionError(f"Failed to place limit order: {str(e)}") from e

    def place_market_order(self, market: str, side: str, amount: float) -> Dict:
        """
        Place a market order
        Args:
            market: Trading pair (e.g., 'BTC-EUR')
            side: 'buy' or 'sell'
            amount: Amount in base currency (e.g., BTC)
        """
        logger.info(f"Placing {side} market order: {amount} {market}")
        try:
            # Validate market first
            market_info = self.get_market_info(market)
            if market_info['status'] != 'trading':
                raise APIConnectionError(f"Market {market} is not available for trading")
                
            # Log market requirements
            logger.info("\n=== Market Requirements ===")
            logger.info(f"Market: {market}")
            logger.info(f"Min Base Asset: {market_info.get('minOrderInBaseAsset')} {market_info['base']}")
            logger.info(f"Min Quote Asset: {market_info.get('minOrderInQuoteAsset')} EUR")
            
            # Get minimum order sizes
            min_base = float(market_info.get('minOrderInBaseAsset', '0'))
            min_quote = float(market_info.get('minOrderInQuoteAsset', '0'))
            
            # Get current price for quote calculations
            ticker = self.get_ticker(market)
            current_price = float(ticker['price'])
            
            # Calculate order value in quote currency (EUR)
            order_value = amount * current_price
            
            logger.info(f"Order amount: {amount} {market_info['base']}")
            logger.info(f"Order value: €{order_value:.2f}")
            
            # Check minimum order requirements
            if amount < min_base:
                logger.error(f"Order amount {amount} {market_info['base']} below minimum {min_base} {market_info['base']}")
                raise APIConnectionError(f"Order amount {amount} {market_info['base']} below minimum {min_base} {market_info['base']}")
                
            if order_value < min_quote:
                logger.error(f"Order value €{order_value:.2f} below minimum €{min_quote}")
                raise APIConnectionError(f"Order value €{order_value:.2f} below minimum €{min_quote}")
                
            logger.info("Order meets minimum requirements")
            
            # Round amount to market precision
            precision = len(str(min_base).split('.')[-1])
            rounded_amount = round(amount, precision)
            
            if rounded_amount != amount:
                logger.info(f"Rounded order amount from {amount} to {rounded_amount} to match market precision")

            order_payload = {
                'amount': str(rounded_amount)
            }
            if self.operator_id:
                order_payload['operatorId'] = self.operator_id

            response = self.client.bitvavo.placeOrder(market, side, 'market', order_payload)
            
            # Log full response for debugging
            logger.debug(f"API Response: {response}")
            
            # Check if response indicates an error
            if isinstance(response, dict) and 'error' in response:
                raise APIConnectionError(f"API Error: {response['error']}")
            
            # Check if response is valid
            if not isinstance(response, dict) or 'orderId' not in response:
                raise APIConnectionError(f"Invalid API response format: {response}")
                
            logger.info(f"Order placed successfully: {response['orderId']}")
            return response
            
        except MarketNotFoundError as e:
            logger.error(f"Market not found: {market}")
            raise
        except Exception as e:
            logger.error(f"Error placing market order: {str(e)}")
            raise APIConnectionError(f"Failed to place market order: {str(e)}") from e

    def cancel_order(self, market: str, order_id: str) -> Dict:
        """Cancel an existing order"""
        logger.info(f"Canceling order {order_id} for {market}")
        try:
            response = self.client.bitvavo.cancelOrder(market, order_id)
            logger.info(f"Order canceled successfully: {order_id}")
            return response
        except Exception as e:
            logger.error(f"Error canceling order: {str(e)}")
            raise APIConnectionError(f"Failed to cancel order: {str(e)}") from e

    def get_order_status(self, market: str, order_id: str) -> Dict:
        """Get the status of an order"""
        logger.info(f"Fetching status for order {order_id}")
        try:
            response = self.client.bitvavo.getOrder(market, order_id)
            logger.debug(f"Order status: {response}")
            return response
        except Exception as e:
            logger.error(f"Error fetching order status: {str(e)}")
            raise APIConnectionError(f"Failed to get order status: {str(e)}") from e

    def get_open_orders(self, market: str) -> List[Dict]:
        """Get all open orders for a market"""
        logger.info(f"Fetching open orders for {market}")
        try:
            response = self.client.bitvavo.getOrders(market, {})
            logger.debug(f"Open orders: {response}")
            return response
        except Exception as e:
            logger.error(f"Error fetching open orders: {str(e)}")
            raise APIConnectionError(f"Failed to get open orders: {str(e)}") from e
    
    def list_alt_coins(self, max_price: float = 10.0) -> List[Dict]:
        """List all available altcoins under a certain price"""
        logger.info(f"Fetching altcoins under €{max_price}")
        try:
            all_markets = self.client.bitvavo.markets({})
            alt_coins = []
            
            for market in all_markets:
                if market['quote'] == 'EUR':  # Only EUR pairs
                    try:
                        ticker = self.client.bitvavo.tickerPrice({'market': market['market']})
                        price = float(ticker['price'])
                        if price <= max_price:
                            alt_coins.append({
                                'market': market['market'],
                                'price': price,
                                'status': market['status']
                            })
                    except Exception:
                        continue
                        
            return sorted(alt_coins, key=lambda x: x['price'])
        except Exception as e:
            logger.error(f"Error fetching altcoins: {str(e)}")
            raise
    
    def test_trade(self, market: str) -> bool:
        """
        Execute a test trade cycle (buy and sell) with minimum amounts
        Returns True if successful, False otherwise
        """
        logger.info(f"Testing trade cycle for {market}")
        try:
            # Get market info for minimum order size
            market_info = self.get_market_info(market)
            if market_info['status'] != 'trading':
                logger.error(f"Market {market} is not available for trading")
                return False
                
            # Get minimum order sizes and current price
            min_base = float(market_info.get('minOrderInBaseAsset', '0'))
            min_quote = float(market_info.get('minOrderInQuoteAsset', '0'))
            ticker = self.get_ticker(market)
            current_price = float(ticker['price'])
            
            # Calculate minimum amount that satisfies both base and quote requirements
            quote_min_amount = min_quote / current_price
            test_amount = max(min_base, quote_min_amount) * 1.1  # 10% above minimum
            
            logger.info("\n=== Test Trade Parameters ===")
            logger.info(f"Market: {market}")
            logger.info(f"Min Base Amount: {min_base} {market_info['base']}")
            logger.info(f"Min Quote Amount: {min_quote} EUR")
            logger.info(f"Current Price: €{current_price:.8f}")
            logger.info(f"Calculated Test Amount: {test_amount:.8f} {market_info['base']}")
            logger.info(f"Estimated Value: €{(test_amount * current_price):.2f}")
            
            # Place test buy order
            buy_order = self.place_market_order(market, 'buy', test_amount)
            logger.info(f"Test buy successful: {buy_order['orderId']}")
            
            # Small delay to ensure order is processed
            time.sleep(2)
            
            # Get actual amount bought
            balance = self.get_available_balance(market.split('-')[0])
            if balance <= 0:
                logger.error("Test buy succeeded but no balance found")
                return False
                
            logger.info(f"Placing test sell order: {balance:.8f} {market}")
            
            # Sell everything back
            sell_order = self.place_market_order(market, 'sell', balance)
            logger.info(f"Test sell successful: {sell_order['orderId']}")
            
            logger.info("Trade cycle test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Trade cycle test failed: {str(e)}")
            return False

    def get_detailed_market_info(self, market: str) -> Dict:
        """Get detailed market information including 24h volume"""
        logger.info(f"Fetching detailed info for {market}")
        try:
            ticker_24h = self.client.bitvavo.ticker24h({'market': market})
            return {
                'market': market,
                'price': float(ticker_24h['last']),
                'volume': float(ticker_24h['volume']),
                'volume_quote': float(ticker_24h['volumeQuote']),
                'open': float(ticker_24h['open']),
                'high': float(ticker_24h['high']),
                'low': float(ticker_24h['low'])
            }
        except Exception as e:
            logger.error(f"Error fetching detailed market info: {str(e)}")
            raise