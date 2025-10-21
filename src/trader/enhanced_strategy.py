import logging
import time
import pandas as pd
import pandas_ta as ta
from trader.market import MarketOperations
from trader.database import TradeDatabase

logger = logging.getLogger('trader.enhanced_strategy')

class EnhancedStrategy:
    def __init__(self, market_ops: MarketOperations, market: str, investment_amount: float = 10.0, virtual_wallet=None):
        self.market_ops = market_ops
        self.market = market
        self.investment_amount = investment_amount
        self.db = TradeDatabase()
        self.virtual_wallet = virtual_wallet
        self.positions = {}
        self.entry_prices = {}

        # Load active positions
        # In virtual mode, load from virtual wallet; otherwise load from regular database
        if virtual_wallet is not None:
            active_positions = virtual_wallet.get_active_positions()
        else:
            active_positions = self.db.get_active_positions()

        for pos in active_positions:
            self.positions[pos['market']] = pos['amount']
            self.entry_prices[pos['market']] = pos['entry_price']
            logger.info(f"Loaded active position: {pos['amount']} {pos['market']} @ €{pos['entry_price']:.6f}")

    def get_historical_data(self, interval: str = '5m', limit: int = 100) -> pd.DataFrame:
        """Get historical data for the market."""
        klines = self.market_ops.client.bitvavo.candles(self.market, interval, {'limit': limit})
        df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)
        return df

    def calculate_indicators(self, df: pd.DataFrame):
        """Calculate technical indicators."""
        df.ta.rsi(length=14, append=True)
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.bbands(length=20, std=2, append=True)
        return df

    def should_buy(self, df: pd.DataFrame) -> bool:
        """Determine if we should buy based on the strategy."""
        last = df.iloc[-1]

        # Log current indicators
        rsi = last['RSI_14']
        macd = last['MACD_12_26_9']
        macd_signal = last['MACDs_12_26_9']
        price = last['close']
        lower_bb = last['BBL_20_2.0_2.0']

        logger.info(f"Buy check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Lower BB: €{lower_bb:.6f}")

        # MULTI-SIGNAL Strategy: Multiple ways to trigger a buy
        # This generates more opportunities while maintaining quality

        # Signal 1: Strong oversold (high confidence)
        strong_oversold = rsi < 40

        # Signal 2: Moderate oversold + bullish momentum
        moderate_oversold_with_momentum = (rsi < 55) and (macd > macd_signal)

        # Signal 3: Price near support with momentum
        near_support_with_momentum = (price < lower_bb * 1.01) and (macd > macd_signal - 0.000001)

        logger.info(f"  Signal 1 - Strong Oversold (RSI < 40): {strong_oversold}")
        logger.info(f"  Signal 2 - Moderate + Momentum (RSI < 55 + MACD>Signal): {moderate_oversold_with_momentum}")
        logger.info(f"  Signal 3 - Near Support + Momentum: {near_support_with_momentum}")

        # Trigger buy if ANY signal is met
        if strong_oversold:
            logger.info("  ✓ BUY SIGNAL TRIGGERED! (Strong Oversold)")
            return True
        elif moderate_oversold_with_momentum:
            logger.info("  ✓ BUY SIGNAL TRIGGERED! (Moderate Oversold + Momentum)")
            return True
        elif near_support_with_momentum:
            logger.info("  ✓ BUY SIGNAL TRIGGERED! (Near Support + Momentum)")
            return True

        return False

    def should_sell(self, df: pd.DataFrame) -> bool:
        """Determine if we should sell based on the strategy."""
        last = df.iloc[-1]

        # Check if we have a position
        if self.market not in self.positions:
            return False

        # Log current indicators
        rsi = last['RSI_14']
        macd = last['MACD_12_26_9']
        macd_signal = last['MACDs_12_26_9']
        price = last['close']
        upper_bb = last['BBU_20_2.0_2.0']

        entry_price = self.entry_prices[self.market]
        profit_percentage = ((price - entry_price) / entry_price) * 100

        logger.info(f"Sell check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Upper BB: €{upper_bb:.6f}")
        logger.info(f"  Position P/L: {profit_percentage:+.2f}% (Entry: €{entry_price:.6f})")

        # RELAXED Sell condition: RSI > 60 AND MACD bearish
        # This will exit positions earlier before major reversals
        rsi_overbought = rsi > 60  # Relaxed from 70 to 60
        macd_bearish = macd < macd_signal
        # Removed the upper BB requirement for more signals

        logger.info(f"  RSI > 60: {rsi_overbought}, MACD < Signal: {macd_bearish}")

        if rsi_overbought and macd_bearish:
            logger.info("  ✓ SELL SIGNAL TRIGGERED (Technical)")
            return True

        # Stop-loss and take-profit
        if profit_percentage >= 15.0:
            logger.info(f"  ✓ SELL SIGNAL TRIGGERED (Take Profit: {profit_percentage:+.2f}%)")
            return True
        elif profit_percentage <= -5.0:
            logger.info(f"  ✓ SELL SIGNAL TRIGGERED (Stop Loss: {profit_percentage:+.2f}%)")
            return True

        return False

    def execute_trade(self):
        """Execute the trading strategy."""
        try:
            df = self.get_historical_data()
            df = self.calculate_indicators(df)

            if self.should_buy(df) and self.market not in self.positions:
                # Place buy order
                ticker = self.market_ops.get_ticker(self.market)
                current_price = float(ticker['price'])
                amount = self.investment_amount / current_price
                order = self.market_ops.place_market_order(self.market, 'buy', amount)
                self.positions[self.market] = amount
                self.entry_prices[self.market] = current_price
                self.db.record_trade_entry(self.market, current_price, amount)
                logger.info(f"Buy order placed for {amount:.8f} {self.market} at €{current_price:.6f}")

            elif self.should_sell(df) and self.market in self.positions:
                # Place sell order
                ticker = self.market_ops.get_ticker(self.market)
                current_price = float(ticker['price'])
                amount = self.positions[self.market]
                order = self.market_ops.place_market_order(self.market, 'sell', amount)
                self.db.record_trade_exit(self.market, current_price)
                del self.positions[self.market]
                del self.entry_prices[self.market]
                logger.info(f"Sell order placed for {amount:.8f} {self.market} at €{current_price:.6f}")

        except Exception as e:
            logger.error(f"Error executing trade: {str(e)}")

    def run(self, interval: int = 300):
        """Run the trading strategy."""
        logger.info(f"Starting enhanced trading strategy for {self.market}")
        while True:
            self.execute_trade()
            time.sleep(interval)
