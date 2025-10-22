from typing import Dict, List, Optional
import logging
from trader.market import MarketOperations
from trader.virtual_wallet import VirtualWallet
from trader.bitvavo import BitvavoClient
import uuid

logger = logging.getLogger('trader.virtual_market')

class VirtualMarketOperations:
    """Wrapper around MarketOperations that simulates trades using virtual wallet

    Uses real Bitvavo market data but executes trades in a virtual wallet instead
    of placing real orders.
    """

    def __init__(self, client: BitvavoClient, virtual_wallet: VirtualWallet,
                 operator_id: Optional[int] = None, trading_fee_pct: float = 0.25):
        """Initialize virtual market operations

        Args:
            client: BitvavoClient for fetching real market data
            virtual_wallet: VirtualWallet instance for tracking virtual trades
            operator_id: Optional operator ID (not used in virtual trading)
            trading_fee_pct: Trading fee percentage (default: 0.25% per trade)
        """
        # Create real market operations for data fetching only
        self.market_ops = MarketOperations(client, operator_id)
        self.client = client
        self.virtual_wallet = virtual_wallet
        self.trading_fee_pct = trading_fee_pct / 100  # Convert to decimal
        self.operator_id = operator_id

        logger.info(f"VirtualMarketOperations initialized with {trading_fee_pct}% trading fee")
        logger.info(f"Starting balance: €{virtual_wallet.get_balance():.2f}")

    # Pass-through methods for market data (read-only operations)
    def get_balance(self) -> List[Dict]:
        """Get virtual wallet balance (formatted like Bitvavo response)"""
        balance = self.virtual_wallet.get_balance()
        positions = self.virtual_wallet.get_active_positions()

        # Format as Bitvavo balance response
        result = [{'symbol': 'EUR', 'available': str(balance), 'inOrder': '0'}]

        for pos in positions:
            market = pos['market']
            base_symbol = market.split('-')[0]
            result.append({
                'symbol': base_symbol,
                'available': str(pos['amount']),
                'inOrder': '0'
            })

        return result

    def get_market_info(self, market: str) -> Dict:
        """Get market info from real Bitvavo data"""
        return self.market_ops.get_market_info(market)

    def get_book(self, market: str, depth: int = 10) -> Dict:
        """Get order book from real Bitvavo data"""
        return self.market_ops.get_book(market, depth)

    def get_ticker(self, market: str) -> Dict:
        """Get ticker from real Bitvavo data"""
        return self.market_ops.get_ticker(market)

    def get_available_balance(self, symbol: str) -> float:
        """Get available balance for a symbol"""
        if symbol == 'EUR':
            return self.virtual_wallet.get_balance()

        # Check if we have a position in this asset
        positions = self.virtual_wallet.get_active_positions()
        for pos in positions:
            market = pos['market']
            if market.startswith(f"{symbol}-"):
                return pos['amount']

        return 0.0

    def list_alt_coins(self, max_price: float = 10.0) -> List[Dict]:
        """List altcoins from real Bitvavo data"""
        return self.market_ops.list_alt_coins(max_price)

    def get_detailed_market_info(self, market: str) -> Dict:
        """Get detailed market info from real Bitvavo data"""
        return self.market_ops.get_detailed_market_info(market)

    def get_historical_candles(self, market: str, interval: str = '1h', limit: int = 1000) -> List:
        """Get historical candles from real Bitvavo data"""
        return self.market_ops.get_historical_candles(market, interval, limit)

    # Virtual trading methods
    def place_market_order(self, market: str, side: str, amount: float) -> Dict:
        """Simulate a market order using current market price

        Args:
            market: Trading pair (e.g., 'BTC-EUR')
            side: 'buy' or 'sell'
            amount: Amount in base currency

        Returns:
            Simulated order response matching Bitvavo format
        """
        logger.info(f"[VIRTUAL] Placing {side} market order: {amount:.8f} {market}")

        try:
            # Validate market
            market_info = self.get_market_info(market)
            if market_info['status'] != 'trading':
                raise Exception(f"Market {market} is not available for trading")

            # Get current price
            ticker = self.get_ticker(market)
            current_price = float(ticker['price'])

            # Calculate fees
            order_value = amount * current_price
            fee = order_value * self.trading_fee_pct

            # Execute virtual trade
            if side.lower() == 'buy':
                success, message = self.virtual_wallet.record_buy(market, current_price, amount, fee)
            elif side.lower() == 'sell':
                success, message = self.virtual_wallet.record_sell(market, current_price, amount, fee)
            else:
                raise ValueError(f"Invalid side: {side}")

            if not success:
                raise Exception(message)

            # Create simulated order response
            order_id = str(uuid.uuid4())
            response = {
                'orderId': order_id,
                'market': market,
                'side': side,
                'orderType': 'market',
                'amount': str(amount),
                'price': str(current_price),
                'filled': str(amount),
                'status': 'filled',
                'filledAmount': str(amount),
                'filledAmountQuote': str(order_value),
                'feePaid': str(fee),
                'feeCurrency': 'EUR',
                'fills': [{
                    'price': str(current_price),
                    'amount': str(amount),
                    'fee': str(fee)
                }]
            }

            logger.info(f"[VIRTUAL] Order executed: {side} {amount:.8f} {market} @ €{current_price:.6f}")
            logger.info(f"[VIRTUAL] Fee: €{fee:.4f} | Balance: €{self.virtual_wallet.get_balance():.2f}")

            return response

        except Exception as e:
            logger.error(f"[VIRTUAL] Error placing market order: {str(e)}")
            raise

    def place_limit_order(self, market: str, side: str, amount: float, price: float) -> Dict:
        """Virtual limit orders not supported - converts to market order at current price"""
        logger.warning("[VIRTUAL] Limit orders not supported in virtual trading - executing as market order")
        return self.place_market_order(market, side, amount)

    def test_trade(self, market: str) -> bool:
        """Test trade cycle with virtual wallet

        Simulates a buy and sell to verify the virtual trading system works
        """
        logger.info(f"[VIRTUAL] Testing trade cycle for {market}")

        try:
            # Get market info
            market_info = self.get_market_info(market)
            if market_info['status'] != 'trading':
                logger.error(f"Market {market} is not available for trading")
                return False

            # Get current price and minimums
            ticker = self.get_ticker(market)
            current_price = float(ticker['price'])
            min_base = float(market_info.get('minOrderInBaseAsset', '0'))
            min_quote = float(market_info.get('minOrderInQuoteAsset', '0'))

            # Calculate test amount
            quote_min_amount = min_quote / current_price
            test_amount = max(min_base, quote_min_amount) * 1.1

            logger.info(f"[VIRTUAL] Test amount: {test_amount:.8f} {market_info['base']} @ €{current_price:.6f}")

            # Place virtual buy
            buy_order = self.place_market_order(market, 'buy', test_amount)
            logger.info(f"[VIRTUAL] Test buy successful: {buy_order['orderId']}")

            # Place virtual sell
            sell_order = self.place_market_order(market, 'sell', test_amount)
            logger.info(f"[VIRTUAL] Test sell successful: {sell_order['orderId']}")

            logger.info("[VIRTUAL] Trade cycle test completed successfully")
            return True

        except Exception as e:
            logger.error(f"[VIRTUAL] Trade cycle test failed: {str(e)}")
            return False

    def show_portfolio_summary(self) -> None:
        """Display current portfolio status with P/L"""
        # Get current prices for all positions
        positions = self.virtual_wallet.get_active_positions()

        if not positions:
            logger.info("\n" + "="*80)
            logger.info("PORTFOLIO SUMMARY - No Active Positions")
            logger.info("="*80)
        else:
            current_prices = {}
            for pos in positions:
                market = pos['market']
                try:
                    ticker = self.get_ticker(market)
                    current_prices[market] = float(ticker['price'])
                except Exception as e:
                    logger.warning(f"Could not get price for {market}: {e}")
                    current_prices[market] = pos['entry_price']

            summary = self.virtual_wallet.get_position_summary(current_prices)

            logger.info("\n" + "="*80)
            logger.info("PORTFOLIO SUMMARY")
            logger.info("="*80)

            for pos in summary['positions']:
                logger.info(f"\n{pos['market']}:")
                logger.info(f"Amount: {pos['amount']:.8f}")
                logger.info(f"Entry Price: €{pos['entry_price']:.6f}")
                logger.info(f"Current Price: €{pos['current_price']:.6f}")
                logger.info(f"Entry Value: €{pos['entry_value']:.2f}")
                logger.info(f"Current Value: €{pos['current_value']:.2f}")
                logger.info(f"Unrealized P/L: €{pos['unrealized_pl']:+.2f} ({pos['unrealized_pl_pct']:+.2f}%)")
                logger.info(f"Entry Time: {pos['entry_time']}")

            logger.info("\n" + "-"*80)
            logger.info(f"Total Positions:      {summary['position_count']}")
            logger.info(f"Total Entry Value:    €{summary['total_entry_value']:.2f}")
            logger.info(f"Total Current Value:  €{summary['total_current_value']:.2f}")
            logger.info(f"Total Unrealized P/L: €{summary['total_unrealized_pl']:+.2f}")

        # Get wallet statistics
        stats = self.virtual_wallet.get_statistics()
        balance = stats['balance']
        total_realized_pl = stats['total_realized_pl']

        logger.info("\n" + "-"*80)
        logger.info(f"Cash Balance:         €{balance:.2f}")
        logger.info(f"Total Realized P/L:   €{total_realized_pl:+.2f}")
        logger.info(f"Initial Balance:      €{stats['initial_balance']:.2f}")
        logger.info(f"Total Return:         €{stats['total_return']:+.2f} ({stats['total_return_pct']:+.2f}%)")

        if stats['total_trades'] > 0:
            logger.info("\n" + "-"*80)
            logger.info("TRADING STATISTICS")
            logger.info("-"*80)
            logger.info(f"Total Trades:     {stats['total_trades']}")
            logger.info(f"Winning Trades:   {stats['winning_trades']}")
            logger.info(f"Losing Trades:    {stats['losing_trades']}")
            logger.info(f"Win Rate:         {stats['win_rate']:.1f}%")
            logger.info(f"Avg P/L per Trade: €{stats['avg_profit_loss']:+.2f}")
            logger.info(f"Best Trade:       €{stats['max_profit']:+.2f}")
            logger.info(f"Worst Trade:      €{stats['max_loss']:+.2f}")

        logger.info("="*80 + "\n")
