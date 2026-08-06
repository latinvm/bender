from typing import Dict, List, Optional, Tuple
import logging
from decimal import Decimal, ROUND_DOWN
from trader.bitvavo import BitvavoClient
from trader.logger import setup_logger
from trader.exceptions import MarketNotFoundError, APIConnectionError, AuthenticationError
from datetime import datetime
import time
from trader.database import TradeDatabase

logger = logging.getLogger('trader.market')


def floor_to_increment(amount: float, increment: str) -> Tuple[Decimal, str]:
    """Floor an order amount to the market's orderSizeIncrement.

    Uses Decimal and always rounds DOWN: rounding up could exceed the
    available balance on sells or the intended spend on buys.

    Returns:
        Tuple of (floored Decimal amount, formatted string without trailing zeros)
    """
    step = Decimal(increment)
    floored = (Decimal(str(amount)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    text = format(floored, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return floored, text


def parse_order_fills(response: Dict, fallback_price: float = None,
                      fallback_amount: float = None) -> Tuple[float, float, float]:
    """Extract actual execution details from an order response.

    Prefers the 'fills' list (weighted average price), then the
    filledAmount/filledAmountQuote summary fields, then the provided
    fallbacks (pre-trade ticker price / requested amount).

    Returns:
        Tuple of (fill_price, filled_amount, fee_paid)
    """
    fee = 0.0
    if isinstance(response, dict):
        try:
            fee = float(response.get('feePaid', 0) or 0)
        except (TypeError, ValueError):
            fee = 0.0

        fills = response.get('fills') or []
        total_amount = 0.0
        total_quote = 0.0
        fills_fee = 0.0
        for fill in fills:
            try:
                fill_amount = float(fill['amount'])
                fill_price = float(fill['price'])
            except (KeyError, TypeError, ValueError):
                continue
            total_amount += fill_amount
            total_quote += fill_amount * fill_price
            try:
                fills_fee += float(fill.get('fee', 0) or 0)
            except (TypeError, ValueError):
                pass
        if total_amount > 0:
            return total_quote / total_amount, total_amount, fee or fills_fee

        try:
            filled_amount = float(response.get('filledAmount', 0) or 0)
            filled_quote = float(response.get('filledAmountQuote', 0) or 0)
            if filled_amount > 0 and filled_quote > 0:
                return filled_quote / filled_amount, filled_amount, fee
            if filled_amount > 0 and fallback_price is not None:
                return fallback_price, filled_amount, fee
        except (TypeError, ValueError):
            pass

    logger.warning("Order response missing fill data, falling back to requested amount/ticker price")
    return fallback_price, fallback_amount, fee

class MarketOperations:
    def __init__(self, client: BitvavoClient, operator_id: Optional[int] = None):
        self.client = client
        self.db = TradeDatabase()
        self.operator_id = operator_id
        if self.operator_id:
            logger.info(f"MarketOperations initialized with operatorId: {self.operator_id}")
        else:
            logger.info("MarketOperations initialized without operatorId (orders will not include it)")

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
        try:
            ticker = self.client.bitvavo.tickerPrice({'market': market})
            if ticker and 'price' in ticker:
                logger.info(f"Fetching ticker for {market}: €{float(ticker['price']):.6f}")
            else:
                logger.info(f"Fetching ticker for {market} (no price data)")
            logger.debug(f"Retrieved ticker: {ticker}")
            return ticker
        except Exception as e:
            logger.error(f"Error fetching ticker for {market}: {str(e)}")
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

            # Check balance for BUY orders (verify EUR balance)
            if side.lower() == 'buy':
                # Calculate required EUR amount (including estimated fee of 0.25%)
                estimated_fee_pct = 0.0025  # 0.25%
                order_value = amount * current_price
                estimated_fee = order_value * estimated_fee_pct
                total_required = order_value + estimated_fee

                # Get available EUR balance
                available_eur = self.get_available_balance('EUR')

                logger.info(f"Balance Check: Need €{total_required:.2f} (€{order_value:.2f} + €{estimated_fee:.4f} fee), Available: €{available_eur:.2f}")

                if available_eur < total_required:
                    error_msg = f"Insufficient EUR balance. Need €{total_required:.2f}, have €{available_eur:.2f}"
                    logger.error(error_msg)
                    raise APIConnectionError(error_msg)

            # Check balance for SELL orders (verify base asset balance)
            elif side.lower() == 'sell':
                base_asset = market_info['base']
                available_base = self.get_available_balance(base_asset)

                logger.info(f"Balance Check: Need {amount:.8f} {base_asset}, Available: {available_base:.8f} {base_asset}")

                if available_base < amount:
                    error_msg = f"Insufficient {base_asset} balance. Need {amount:.8f}, have {available_base:.8f}"
                    logger.error(error_msg)
                    raise APIConnectionError(error_msg)

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

            # Floor amount to the market's orderSizeIncrement. Never round up:
            # that could exceed the available balance on sells or the intended
            # spend on buys.
            order_size_increment = market_info.get('orderSizeIncrement', '0.00000001')
            floored_amount, formatted_amount = floor_to_increment(amount, order_size_increment)

            if float(floored_amount) != amount:
                logger.info(f"Floored order amount from {amount:.12f} to {formatted_amount} (increment: {order_size_increment})")

            order_payload = {
                'amount': formatted_amount
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
            # Get all markets and their 24h tickers in one efficient call
            all_markets = self.client.bitvavo.markets({})
            all_tickers = self.client.bitvavo.ticker24h({})

            # Create a map of market -> ticker for fast lookup
            ticker_map = {ticker['market']: ticker for ticker in all_tickers}

            alt_coins = []
            for market in all_markets:
                if market['quote'] == 'EUR':  # Only EUR pairs
                    try:
                        # Use pre-fetched ticker data instead of individual API calls
                        ticker = ticker_map.get(market['market'])
                        if ticker:
                            price = float(ticker['last'])
                            if price <= max_price:
                                alt_coins.append({
                                    'market': market['market'],
                                    'price': price,
                                    'status': market['status']
                                })
                    except Exception as e:
                        logger.debug(f"Error processing {market['market']}: {str(e)}")
                        continue

            return sorted(alt_coins, key=lambda x: x['price'])
        except Exception as e:
            logger.error(f"Error fetching altcoins: {str(e)}")
            raise
    
    def connectivity_check(self) -> bool:
        """Read-only startup check: verifies API reachability and credentials
        without placing any orders or moving any funds.
        """
        try:
            server_time = self.client.bitvavo.time()
            if not isinstance(server_time, dict) or 'time' not in server_time:
                logger.error(f"Connectivity check failed: unexpected time response: {server_time}")
                return False
            logger.info("Connectivity check: API reachable")

            balance = self.get_balance()
            if isinstance(balance, dict) and 'error' in balance:
                logger.error(f"Connectivity check failed: {balance['error']}")
                return False
            eur = next((float(b['available']) for b in balance if b.get('symbol') == 'EUR'), 0.0)
            logger.info(f"Connectivity check: credentials valid, EUR available: €{eur:.2f}")
            return True
        except Exception as e:
            logger.error(f"Connectivity check failed: {str(e)}")
            return False

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

            # Determine how much the test buy actually filled. NEVER sell more
            # than the test buy acquired: the account may already hold this
            # asset from before, and that balance must not be touched.
            _, filled_amount, _ = parse_order_fills(buy_order)
            if not filled_amount or filled_amount <= 0:
                order_status = self.get_order_status(market, buy_order['orderId'])
                _, filled_amount, _ = parse_order_fills(order_status)

            if not filled_amount or filled_amount <= 0:
                logger.error("Test buy succeeded but filled amount unknown - NOT selling (manual check needed)")
                return False

            # Cap at the available balance in case fees were taken in the base asset
            available = self.get_available_balance(market.split('-')[0])
            sell_amount = min(filled_amount, available)
            if sell_amount <= 0:
                logger.error("Test buy succeeded but no balance available to sell back")
                return False

            logger.info(f"Placing test sell order: {sell_amount:.8f} {market} (test buy filled: {filled_amount:.8f})")

            # Sell back only what the test buy acquired
            sell_order = self.place_market_order(market, 'sell', sell_amount)
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

    def get_historical_candles(self, market: str, interval: str = '1h', limit: int = 1000) -> List:
        """Get historical candles for a market."""
        logger.info(f"Fetching historical candles for {market}")
        try:
            candles = self.client.bitvavo.candles(market, interval, {'limit': limit})
            return candles
        except Exception as e:
            logger.error(f"Error fetching historical candles: {str(e)}")
            raise APIConnectionError(f"Failed to fetch historical candles: {str(e)}") from e