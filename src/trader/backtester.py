import logging
import pandas as pd
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

        # Calculate required number of candles based on date range
        # For 1 year of hourly data, we need ~8760 candles, but API max is typically 1440
        # So we'll use the maximum available
        candles = self.market_ops.get_historical_candles(self.market, interval='1h', limit=1440)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)

        # Sort the index to ensure it's monotonic
        df = df.sort_index()

        # Filter data for the specified date range using boolean indexing
        # This is more robust than slice-based indexing
        start_dt = pd.to_datetime(self.start_date)
        end_dt = pd.to_datetime(self.end_date)
        df = df[(df.index >= start_dt) & (df.index <= end_dt)]

        if df.empty:
            logger.error(f"No data found for {self.market} between {self.start_date} and {self.end_date}")
            if candles:
                first_date = pd.to_datetime(candles[0][0], unit='ms')
                last_date = pd.to_datetime(candles[-1][0], unit='ms')
                logger.info(f"Available data range: {first_date} to {last_date}")
                logger.info("Note: API limit is 1440 hourly candles (~60 days of data)")
            return

        logger.info(f"Backtesting with {len(df)} candles from {df.index[0]} to {df.index[-1]}")

        # Simulate the strategy
        # Need minimum 26 periods for indicators (MACD requires 26)
        min_periods = 26

        for i in range(min_periods, len(df)):
            # Get historical data up to current point
            historical_df = df.iloc[:i+1].copy()

            # Calculate indicators - need to use copy to avoid modifying original
            historical_df = self.strategy.calculate_indicators(historical_df)

            # Skip if indicators couldn't be calculated (NaN values or missing columns)
            required_indicators = ['RSI_14', 'MACD_12_26_9', 'MACDs_12_26_9', 'BBL_20_2.0_2.0', 'BBU_20_2.0_2.0']
            missing_indicators = [ind for ind in required_indicators if ind not in historical_df.columns]

            if missing_indicators or historical_df.iloc[-1][required_indicators].isna().any():
                continue

            if self.strategy.should_buy(historical_df) and self.market not in self.strategy.positions:
                # Simulate buy
                entry_price = historical_df['close'].iloc[-1]
                self.strategy.positions[self.market] = 1 # Simulate 1 unit
                self.strategy.entry_prices[self.market] = entry_price
                logger.info(f"Simulated BUY at {entry_price} on {historical_df.index[-1]}")

            elif self.strategy.should_sell(historical_df) and self.market in self.strategy.positions:
                # Simulate sell
                exit_price = historical_df['close'].iloc[-1]
                entry_price = self.strategy.entry_prices[self.market]
                profit = (exit_price - entry_price) / entry_price * 100
                logger.info(f"Simulated SELL at {exit_price} on {historical_df.index[-1]} for a profit of {profit:.2f}%")
                del self.strategy.positions[self.market]
                del self.strategy.entry_prices[self.market]

        logger.info(f"Backtest complete. Final positions: {self.strategy.positions}")
