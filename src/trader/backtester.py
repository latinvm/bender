import logging
import pandas as pd
from trader.enhanced_strategy import EnhancedStrategy
from trader.market import MarketOperations

logger = logging.getLogger('trader.backtester')

class Backtester:
    def __init__(self, market_ops: MarketOperations, strategy_class, market: str, start_date: str, end_date: str):
        self.market_ops = market_ops
        self.strategy = strategy_class(market_ops, market)
        self.market = market
        self.start_date = start_date
        self.end_date = end_date

    def run(self):
        """Run the backtest."""
        logger.info(f"Starting backtest for {self.market} from {self.start_date} to {self.end_date}")

        # Get historical data
        candles = self.market_ops.get_historical_candles(self.market, interval='1h', limit=1000) # Adjust as needed
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)

        # Filter data for the specified date range
        df = df.loc[self.start_date:self.end_date]

        # Simulate the strategy
        for i in range(len(df)):
            historical_df = df.iloc[:i+1]
            self.strategy.prices = historical_df['close'].tolist()

            if self.strategy.should_buy():
                # Simulate buy
                entry_price = historical_df['close'].iloc[-1]
                self.strategy.positions[self.market] = 1 # Simulate 1 unit
                self.strategy.entry_prices[self.market] = entry_price
                logger.info(f"Simulated BUY at {entry_price} on {historical_df.index[-1]}")

            elif self.strategy.should_sell():
                # Simulate sell
                exit_price = historical_df['close'].iloc[-1]
                entry_price = self.strategy.entry_prices[self.market]
                profit = (exit_price - entry_price) / entry_price * 100
                logger.info(f"Simulated SELL at {exit_price} on {historical_df.index[-1]} for a profit of {profit:.2f}%")
                del self.strategy.positions[self.market]
                del self.strategy.entry_prices[self.market]

        logger.info("Backtest complete.")
