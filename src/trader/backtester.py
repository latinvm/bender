import logging
import os
import tempfile

import numpy as np
import pandas as pd

from trader.market import MarketOperations
from trader.virtual_wallet import VirtualWallet

logger = logging.getLogger('trader.backtester')

REQUIRED_INDICATORS = ['RSI_14', 'MACD_12_26_9', 'MACDs_12_26_9', 'BBL_20_2.0_2.0', 'BBU_20_2.0_2.0']
MIN_PERIODS = 26  # MACD needs 26 periods before indicators are meaningful


class Backtester:
    """Backtests a strategy over historical candles.

    Honest by construction:
    - Exit decisions use the historical candle close, never the live ticker
    - Trades settle through a VirtualWallet with the configured fee, so
      results include costs
    - Position sizing matches live trading (investment_amount per position)
    """

    def __init__(self, market_ops: MarketOperations, strategy_class, market: str,
                 start_date: str, end_date: str,
                 initial_balance: float = 1000.0,
                 investment_amount: float = 10.0,
                 trading_fee_pct: float = 0.25,
                 candles: list = None):
        """
        Args:
            market_ops: MarketOperations for fetching candles (not used for trading)
            strategy_class: Strategy class to test (e.g. EnhancedStrategy)
            market: Market symbol (e.g. 'VET-EUR')
            start_date/end_date: Date range (YYYY-MM-DD)
            initial_balance: Simulated starting balance in EUR
            investment_amount: EUR per position, matching live configuration
            trading_fee_pct: Fee percentage per trade (Bitvavo ~0.25)
            candles: Optional pre-loaded candle list [[ts, o, h, l, c, v], ...];
                when provided, no API call is made (offline backtesting)
        """
        self.market_ops = market_ops
        self.market = market
        self.start_date = start_date
        self.end_date = end_date
        self.initial_balance = initial_balance
        self.investment_amount = investment_amount
        self.fee_rate = trading_fee_pct / 100
        self.candles = candles

        # A throwaway wallet keeps the simulation honest (fees, balance
        # checks) without touching any real database
        self._wallet_dir = tempfile.mkdtemp(prefix='bender-backtest-')
        self.wallet = VirtualWallet(
            db_path=os.path.join(self._wallet_dir, 'backtest.db'),
            initial_balance=initial_balance
        )

        # The strategy is given the backtest wallet so it never creates the
        # real TradeDatabase
        self.strategy = strategy_class(
            market_ops=market_ops,
            market=market,
            investment_amount=investment_amount,
            virtual_wallet=self.wallet
        )

    def _load_dataframe(self):
        candles = self.candles
        if candles is None:
            candles = self.market_ops.get_historical_candles(self.market, interval='1h', limit=1440)
        if not candles:
            return None, candles

        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df.astype(float)
        df = df.sort_index()

        start_dt = pd.to_datetime(self.start_date)
        end_dt = pd.to_datetime(self.end_date)
        return df[(df.index >= start_dt) & (df.index <= end_dt)], candles

    def run(self) -> dict:
        """Run the backtest.

        Returns:
            Dict with performance metrics (empty dict if no data)
        """
        logger.info(f"Starting backtest for {self.market} from {self.start_date} to {self.end_date}")
        logger.info(f"Balance: €{self.initial_balance:.2f} | Per position: €{self.investment_amount:.2f} | Fee: {self.fee_rate * 100:.2f}%")

        df, candles = self._load_dataframe()
        if df is None or df.empty:
            logger.error(f"No data found for {self.market} between {self.start_date} and {self.end_date}")
            if candles:
                first_date = pd.to_datetime(candles[0][0], unit='ms')
                last_date = pd.to_datetime(candles[-1][0], unit='ms')
                logger.info(f"Available data range: {first_date} to {last_date}")
                logger.info("Note: API limit is 1440 hourly candles (~60 days); pass candles= for longer offline runs")
            return {}

        logger.info(f"Backtesting with {len(df)} candles from {df.index[0]} to {df.index[-1]}")

        equity_curve = []

        for i in range(MIN_PERIODS, len(df)):
            historical_df = df.iloc[:i + 1].copy()
            historical_df = self.strategy.calculate_indicators(historical_df)

            missing = [ind for ind in REQUIRED_INDICATORS if ind not in historical_df.columns]
            if missing or historical_df.iloc[-1][REQUIRED_INDICATORS].isna().any():
                continue

            close = float(historical_df['close'].iloc[-1])
            timestamp = historical_df.index[-1]

            should_buy, buy_reason = self.strategy.should_buy(historical_df)
            # Exit decisions use the HISTORICAL close - passing the price
            # explicitly prevents should_sell from fetching the live ticker
            should_sell, sell_reason = self.strategy.should_sell(historical_df, current_price=close)

            if should_buy and self.market not in self.strategy.positions:
                amount = self.investment_amount / close
                fee = amount * close * self.fee_rate
                success, message = self.wallet.record_buy(self.market, close, amount, fee)
                if success:
                    self.strategy.positions[self.market] = amount
                    self.strategy.entry_prices[self.market] = close
                    logger.info(f"[{timestamp}] BUY {amount:.8f} @ €{close:.6f} ({buy_reason})")
                else:
                    logger.debug(f"[{timestamp}] Buy skipped: {message}")

            elif should_sell and self.market in self.strategy.positions:
                amount = self.strategy.positions[self.market]
                fee = amount * close * self.fee_rate
                success, message = self.wallet.record_sell(self.market, close, amount, fee)
                if success:
                    del self.strategy.positions[self.market]
                    del self.strategy.entry_prices[self.market]
                    logger.info(f"[{timestamp}] SELL {amount:.8f} @ €{close:.6f} ({sell_reason})")

            # Track total equity (cash + open position value) for drawdown
            position_value = sum(pos_amount * close for m, pos_amount in self.strategy.positions.items())
            equity_curve.append(self.wallet.get_balance() + position_value)

        return self._report(df, equity_curve)

    def _report(self, df: pd.DataFrame, equity_curve: list) -> dict:
        stats = self.wallet.get_statistics()

        final_close = float(df['close'].iloc[-1])
        open_value = sum(amount * final_close for amount in self.strategy.positions.values())
        final_equity = self.wallet.get_balance() + open_value
        total_return = final_equity - self.initial_balance
        total_return_pct = (total_return / self.initial_balance) * 100

        max_drawdown_pct = 0.0
        if equity_curve:
            equity = np.array(equity_curve)
            running_peak = np.maximum.accumulate(equity)
            drawdowns = (running_peak - equity) / running_peak
            max_drawdown_pct = float(np.max(drawdowns)) * 100

        # Buy & hold benchmark over the same window
        first_close = float(df['close'].iloc[0])
        buy_hold_pct = ((final_close - first_close) / first_close) * 100

        results = {
            'market': self.market,
            'candles': len(df),
            'final_equity': final_equity,
            'total_return': total_return,
            'total_return_pct': total_return_pct,
            'buy_hold_return_pct': buy_hold_pct,
            'max_drawdown_pct': max_drawdown_pct,
            'total_trades': stats['total_trades'],
            'winning_trades': stats['winning_trades'],
            'losing_trades': stats['losing_trades'],
            'win_rate': stats['win_rate'],
            'total_fees_open': self.wallet.get_total_costs(),
            'open_positions': dict(self.strategy.positions),
        }

        logger.info("=" * 80)
        logger.info(f"BACKTEST RESULTS: {self.market}")
        logger.info("=" * 80)
        logger.info(f"Final Equity:     €{final_equity:.2f} (started €{self.initial_balance:.2f})")
        logger.info(f"Total Return:     €{total_return:+.2f} ({total_return_pct:+.2f}%)")
        logger.info(f"Buy & Hold:       {buy_hold_pct:+.2f}% over the same period")
        logger.info(f"Max Drawdown:     {max_drawdown_pct:.2f}%")
        logger.info(f"Trades:           {stats['total_trades']} (win rate {stats['win_rate']:.1f}%)")
        if self.strategy.positions:
            logger.info(f"Still open:       {self.strategy.positions}")
        logger.info("=" * 80)

        return results
