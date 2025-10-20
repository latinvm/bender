import logging
import time
import pandas as pd
import pandas_ta as ta
from trader.market import MarketOperations
from trader.database import TradeDatabase

logger = logging.getLogger('trader.enhanced_strategy')

class EnhancedStrategy:
    def __init__(self, market_ops: MarketOperations, market: str, investment_amount: float = 10.0):
        self.market_ops = market_ops
        self.market = market
        self.investment_amount = investment_amount
        self.db = TradeDatabase()
        self.positions = {}
        self.entry_prices = {}

        # Load active positions
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
        # Buy condition: RSI < 30, MACD crossover, and price is near the lower Bollinger Band
        if last['RSI_14'] < 30 and last['MACD_12_26_9'] > last['MACDs_12_26_9'] and last['close'] < last['BBL_20_2.0']:
            return True
        return False

    def should_sell(self, df: pd.DataFrame) -> bool:
        """Determine if we should sell based on the strategy."""
        last = df.iloc[-1]
        # Sell condition: RSI > 70, MACD crossunder, and price is near the upper Bollinger Band
        if last['RSI_14'] > 70 and last['MACD_12_26_9'] < last['MACDs_12_26_9'] and last['close'] > last['BBU_20_2.0']:
            return True

        # Stop-loss and take-profit
        if self.market in self.positions:
            entry_price = self.entry_prices[self.market]
            current_price = last['close']
            profit_percentage = ((current_price - entry_price) / entry_price) * 100
            if profit_percentage >= 15.0 or profit_percentage <= -5.0:
                return True

        return False

    def execute_trade(self):
        """Execute the trading strategy."""
        try:
            df = self.get_historical_data()
            df = self.calculate_indicators(df)

            if self.should_buy() and self.market not in self.positions:
                # Place buy order
                ticker = self.market_ops.get_ticker(self.market)
                current_price = float(ticker['price'])
                amount = self.investment_amount / current_price
                order = self.market_ops.place_market_order(self.market, 'buy', amount)
                self.positions[self.market] = amount
                self.entry_prices[self.market] = current_price
                self.db.record_trade_entry(self.market, current_price, amount)
                logger.info(f"Buy order placed for {amount:.8f} {self.market} at €{current_price:.6f}")

            elif self.should_sell() and self.market in self.positions:
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
