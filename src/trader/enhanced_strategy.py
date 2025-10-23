import logging
import time
import pandas as pd
import pandas_ta as ta
from trader.market import MarketOperations
from trader.database import TradeDatabase
from typing import Dict, Optional

logger = logging.getLogger('trader.enhanced_strategy')

class EnhancedStrategy:
    def __init__(self, market_ops: MarketOperations, market: str, investment_amount: float = 10.0, virtual_wallet=None, max_positions: int = 3, stop_loss_pct: float = 5.0, take_profit_pct: float = 15.0):
        self.market_ops = market_ops
        self.market = market
        self.investment_amount = investment_amount
        self.db = TradeDatabase()
        self.virtual_wallet = virtual_wallet
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.positions = {}
        self.entry_prices = {}
        # Price cache for TUI to avoid redundant API calls
        self.last_price: Optional[float] = None
        self.last_price_timestamp: Optional[float] = None

        # Load active positions
        # In virtual mode, load from virtual wallet; otherwise load from regular database
        if virtual_wallet is not None:
            active_positions = virtual_wallet.get_active_positions()
        else:
            active_positions = self.db.get_active_positions()

        # Only load the position for THIS market (not all positions)
        for pos in active_positions:
            if pos['market'] == self.market:
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

    def should_buy(self, df: pd.DataFrame) -> tuple[bool, str]:
        """Determine if we should buy based on the strategy.

        Returns:
            Tuple of (should_buy: bool, reason: str)
        """
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

        logger.info(f"Signal 1 - Strong Oversold (RSI < 40): {strong_oversold}")
        logger.info(f"Signal 2 - Moderate + Momentum (RSI < 55 + MACD>Signal): {moderate_oversold_with_momentum}")
        logger.info(f"Signal 3 - Near Support + Momentum: {near_support_with_momentum}")

        # Trigger buy if ANY signal is met
        if strong_oversold:
            reason = "Strong Oversold"
            logger.info(f"BUY SIGNAL TRIGGERED for {self.market}! ({reason})")
            return True, reason
        elif moderate_oversold_with_momentum:
            reason = "Moderate Oversold + Momentum"
            logger.info(f"BUY SIGNAL TRIGGERED for {self.market}! ({reason})")
            return True, reason
        elif near_support_with_momentum:
            reason = "Near Support + Momentum"
            logger.info(f"BUY SIGNAL TRIGGERED for {self.market}! ({reason})")
            return True, reason

        return False, ""

    def should_sell(self, df: pd.DataFrame) -> tuple[bool, str]:
        """Determine if we should sell based on the strategy.

        Returns:
            Tuple of (should_sell: bool, reason: str)
        """
        last = df.iloc[-1]

        # Check if we have a position
        if self.market not in self.positions:
            return False, ""

        # Log current indicators
        rsi = last['RSI_14']
        macd = last['MACD_12_26_9']
        macd_signal = last['MACDs_12_26_9']
        price = last['close']
        upper_bb = last['BBU_20_2.0_2.0']

        entry_price = self.entry_prices[self.market]

        # For P/L reporting, use current ticker price (not historical close price)
        # This ensures consistency with what's shown in Active Positions pane
        current_price = self.get_current_price(use_cache=True)
        if current_price is not None:
            profit_percentage = ((current_price - entry_price) / entry_price) * 100
            logger.info(f"Sell check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Upper BB: €{upper_bb:.6f}")
            logger.info(f"{self.market} Position P/L: {profit_percentage:+.2f}% (Entry: €{entry_price:.6f}, Current: €{current_price:.6f})")
        else:
            # Fallback to historical close if current price unavailable
            profit_percentage = ((price - entry_price) / entry_price) * 100
            logger.info(f"Sell check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Upper BB: €{upper_bb:.6f}")
            logger.info(f"{self.market} Position P/L: {profit_percentage:+.2f}% (Entry: €{entry_price:.6f})")

        # RELAXED Sell condition: RSI > 60 AND MACD bearish
        # This will exit positions earlier before major reversals
        rsi_overbought = rsi > 60  # Relaxed from 70 to 60
        macd_bearish = macd < macd_signal
        # Removed the upper BB requirement for more signals

        logger.info(f"RSI > 60: {rsi_overbought}, MACD < Signal: {macd_bearish}")

        if rsi_overbought and macd_bearish:
            reason = f"Technical (RSI: {rsi:.1f}, MACD Bearish)"
            logger.info(f"SELL SIGNAL TRIGGERED for {self.market} ({reason})")
            return True, reason

        # Stop-loss and take-profit (use configured values)
        if profit_percentage >= self.take_profit_pct:
            reason = f"Take Profit ({profit_percentage:+.2f}%)"
            logger.info(f"SELL SIGNAL TRIGGERED for {self.market} ({reason})")
            return True, reason
        elif profit_percentage <= -self.stop_loss_pct:
            reason = f"Stop Loss ({profit_percentage:+.2f}%)"
            logger.info(f"SELL SIGNAL TRIGGERED for {self.market} ({reason})")
            return True, reason

        return False, ""

    def get_current_price(self, use_cache: bool = True, cache_max_age: float = 30.0) -> Optional[float]:
        """Get current price with optional caching

        Args:
            use_cache: If True, return cached price if fresh enough
            cache_max_age: Maximum age of cache in seconds (default: 30s)

        Returns:
            Current price or None if unavailable
        """
        if use_cache and self.last_price is not None and self.last_price_timestamp is not None:
            age = time.time() - self.last_price_timestamp
            if age < cache_max_age:
                return self.last_price

        try:
            ticker = self.market_ops.get_ticker(self.market)
            self.last_price = float(ticker['price'])
            self.last_price_timestamp = time.time()
            return self.last_price
        except Exception as e:
            logger.error(f"Error fetching current price: {str(e)}")
            return self.last_price  # Return stale cache if fetch fails

    def execute_trade(self):
        """Execute the trading strategy."""
        try:
            df = self.get_historical_data()
            df = self.calculate_indicators(df)

            should_buy, buy_reason = self.should_buy(df)
            should_sell, sell_reason = self.should_sell(df)

            if should_buy and self.market not in self.positions:
                # Check global position limit before buying
                if self.virtual_wallet is not None:
                    active_positions = self.virtual_wallet.get_active_positions()
                else:
                    active_positions = self.db.get_active_positions()

                current_position_count = len(active_positions)

                if current_position_count >= self.max_positions:
                    active_markets = [pos['market'] for pos in active_positions]
                    logger.info(f"POSITION LIMIT REACHED ({current_position_count}/{self.max_positions}) - Cannot buy {self.market}")
                    logger.info(f"Active positions: {', '.join(active_markets)}")
                    return

                # Place buy order
                current_price = self.get_current_price(use_cache=False)  # Always fetch fresh for trading
                if current_price is None:
                    logger.error("Cannot execute buy: price unavailable")
                    return

                amount = self.investment_amount / current_price
                order = self.market_ops.place_market_order(self.market, 'buy', amount)
                self.positions[self.market] = amount
                self.entry_prices[self.market] = current_price
                self.db.record_trade_entry(self.market, current_price, amount)

                logger.info(f"BUY EXECUTED for {self.market}")
                logger.info(f"Reason: {buy_reason}")
                logger.info(f"Amount: {amount:.8f} {self.market} (€{self.investment_amount:.2f})")
                logger.info(f"Price: €{current_price:.6f}")
                logger.info(f"Active positions: {current_position_count + 1}/{self.max_positions}")

            elif should_sell and self.market in self.positions:
                # Place sell order
                current_price = self.get_current_price(use_cache=False)  # Always fetch fresh for trading
                if current_price is None:
                    logger.error("Cannot execute sell: price unavailable")
                    return

                amount = self.positions[self.market]
                entry_price = self.entry_prices[self.market]
                profit_pct = ((current_price - entry_price) / entry_price) * 100
                profit_eur = (amount * current_price) - (amount * entry_price)

                order = self.market_ops.place_market_order(self.market, 'sell', amount)
                self.db.record_trade_exit(self.market, current_price)
                del self.positions[self.market]
                del self.entry_prices[self.market]

                logger.info(f"SELL EXECUTED for {self.market}")
                logger.info(f"Reason: {sell_reason}")
                logger.info(f"Amount: {amount:.8f} {self.market}")
                logger.info(f"Entry: €{entry_price:.6f} -> Exit: €{current_price:.6f}")
                logger.info(f"P/L: {profit_pct:+.2f}% (€{profit_eur:+.4f})")
            else:
                # Not trading but still update price cache for TUI
                self.get_current_price(use_cache=False)
                if self.market in self.positions:
                    logger.info(f"HOLDING {self.market} - No sell signal")
                else:
                    logger.info(f"MONITORING {self.market} - No buy signal")

        except Exception as e:
            logger.error(f"Error executing trade: {str(e)}")

    def run(self, interval: int = 300):
        """Run the trading strategy."""
        logger.info(f"Starting enhanced trading strategy for {self.market}")
        while True:
            self.execute_trade()
            time.sleep(interval)
