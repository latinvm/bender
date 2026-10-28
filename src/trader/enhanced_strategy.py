import json
import logging
import threading
import time
from datetime import datetime, timezone
import pandas as pd
import pandas_ta  # noqa: F401  (registers the DataFrame .ta accessor used in calculate_indicators)
from trader.market import MarketOperations, parse_order_fills
from trader.database import TradeDatabase
from trader.exceptions import MarketDelistedError, MarketNotFoundError
from typing import Optional

logger = logging.getLogger('trader.enhanced_strategy')
decision_logger = logging.getLogger('trader.decisions')

REQUIRED_INDICATORS = ['RSI_14', 'MACD_12_26_9', 'MACDs_12_26_9', 'BBL_20_2.0_2.0', 'BBU_20_2.0_2.0']

class EnhancedStrategy:
    def __init__(self, market_ops: MarketOperations, market: str, investment_amount: float = 10.0, virtual_wallet=None, max_positions: int = 3, stop_loss_pct: float = 5.0, take_profit_pct: float = 15.0,
                 rsi_buy_strong: float = 40.0, rsi_buy_moderate: float = 50.0, rsi_sell: float = 60.0,
                 risk_manager=None):
        self.market_ops = market_ops
        self.market = market
        self.investment_amount = investment_amount
        self.rsi_buy_strong = rsi_buy_strong
        self.rsi_buy_moderate = rsi_buy_moderate
        self.rsi_sell = rsi_sell
        self.risk_manager = risk_manager
        # Exactly one trade store per mode: the virtual wallet in virtual mode,
        # TradeDatabase in real mode. Writing virtual trades to the real DB
        # creates phantom positions that a later real session would try to sell.
        self.db = TradeDatabase() if virtual_wallet is None else None
        self.virtual_wallet = virtual_wallet
        self.max_positions = max_positions
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.positions = {}
        self.entry_prices = {}
        # Price cache for TUI to avoid redundant API calls
        self.last_price: Optional[float] = None
        self.last_price_timestamp: Optional[float] = None
        # Set once the exchange reports the market delisted; both the trading
        # thread and the TUI price thread can detect it
        self.delisted = False
        self._delisting_lock = threading.Lock()
        # Trading thread only: the delisting has been acted on and recorded
        self._delisting_handled = False

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
        """Get historical data for the market, oldest candle first."""
        klines = self.market_ops.get_historical_candles(self.market, interval=interval, limit=limit)
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

        logger.debug(f"Buy check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Lower BB: €{lower_bb:.6f}")

        # MULTI-SIGNAL Strategy: Multiple ways to trigger a buy
        # This generates more opportunities while maintaining quality

        # Signal 1: Strong oversold (high confidence)
        strong_oversold = rsi < self.rsi_buy_strong

        # Signal 2: Moderate oversold + bullish momentum
        moderate_oversold_with_momentum = (rsi < self.rsi_buy_moderate) and (macd > macd_signal)

        # Signal 3: Price near support with momentum
        near_support_with_momentum = (price < lower_bb * 1.01) and (macd > macd_signal - 0.000001)

        logger.debug(f"Signal 1 - Strong Oversold (RSI < {self.rsi_buy_strong:g}): {strong_oversold}")
        logger.debug(f"Signal 2 - Moderate + Momentum (RSI < {self.rsi_buy_moderate:g} + MACD>Signal): {moderate_oversold_with_momentum}")
        logger.debug(f"Signal 3 - Near Support + Momentum: {near_support_with_momentum}")

        # Trigger buy if ANY signal is met
        if strong_oversold:
            reason = "Strong Oversold"
            logger.debug(f"BUY SIGNAL TRIGGERED for {self.market}! ({reason})")
            return True, reason
        elif moderate_oversold_with_momentum:
            reason = "Moderate Oversold + Momentum"
            logger.debug(f"BUY SIGNAL TRIGGERED for {self.market}! ({reason})")
            return True, reason
        elif near_support_with_momentum:
            reason = "Near Support + Momentum"
            logger.debug(f"BUY SIGNAL TRIGGERED for {self.market}! ({reason})")
            return True, reason

        return False, ""

    def should_sell(self, df: pd.DataFrame, current_price: Optional[float] = None) -> tuple[bool, str]:
        """Determine if we should sell based on the strategy.

        Args:
            df: Historical dataframe with indicators
            current_price: Price to evaluate stop-loss/take-profit against.
                Pass explicitly during backtesting (the historical close);
                when None, the live ticker is fetched. Backtests must never
                fall through to the live ticker - that evaluates historical
                exits against today's price.

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

        # For live P/L reporting, use current ticker price (not historical
        # close price) for consistency with the Active Positions pane
        if current_price is None:
            current_price = self.get_current_price(use_cache=True, raise_if_delisted=True)
        if current_price is not None:
            profit_percentage = ((current_price - entry_price) / entry_price) * 100
            logger.debug(f"Sell check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Upper BB: €{upper_bb:.6f}")
            logger.debug(f"{self.market} Position P/L: {profit_percentage:+.2f}% (Entry: €{entry_price:.6f}, Current: €{current_price:.6f})")
        else:
            # Fallback to historical close if current price unavailable
            profit_percentage = ((price - entry_price) / entry_price) * 100
            logger.debug(f"Sell check - RSI: {rsi:.2f}, MACD: {macd:.6f}, Signal: {macd_signal:.6f}, Price: €{price:.6f}, Upper BB: €{upper_bb:.6f}")
            logger.debug(f"{self.market} Position P/L: {profit_percentage:+.2f}% (Entry: €{entry_price:.6f})")

        # Sell condition: RSI overbought AND MACD bearish
        # This exits positions before major reversals
        rsi_overbought = rsi > self.rsi_sell
        macd_bearish = macd < macd_signal

        logger.debug(f"RSI > {self.rsi_sell:g}: {rsi_overbought}, MACD < Signal: {macd_bearish}")

        if rsi_overbought and macd_bearish:
            reason = f"Technical (RSI: {rsi:.1f}, MACD Bearish)"
            logger.info(f"SELL SIGNAL TRIGGERED for {self.market} ({reason})")
            return True, reason

        return self._check_price_exit(profit_percentage)

    def _check_price_exit(self, profit_percentage: float) -> tuple[bool, str]:
        """Stop-loss and take-profit (use configured values)."""
        if profit_percentage >= self.take_profit_pct:
            reason = f"Take Profit ({profit_percentage:+.2f}%)"
            logger.info(f"SELL SIGNAL TRIGGERED for {self.market} ({reason})")
            return True, reason
        elif profit_percentage <= -self.stop_loss_pct:
            reason = f"Stop Loss ({profit_percentage:+.2f}%)"
            logger.info(f"SELL SIGNAL TRIGGERED for {self.market} ({reason})")
            return True, reason

        return False, ""

    def get_current_price(self, use_cache: bool = True, cache_max_age: float = 30.0,
                          raise_if_delisted: bool = False) -> Optional[float]:
        """Get current price with optional caching

        Args:
            use_cache: If True, return cached price if fresh enough
            cache_max_age: Maximum age of cache in seconds (default: 30s)
            raise_if_delisted: Trading paths pass True so a delisting aborts the
                decision in progress instead of continuing on a stale price.
                The TUI keeps False: it only sets the flag and gets last_price.

        Returns:
            Current price or None if unavailable
        """
        if self.delisted:
            if raise_if_delisted:
                raise MarketDelistedError(f"{self.market} is delisted")
            return self.last_price
        if use_cache and self.last_price is not None and self.last_price_timestamp is not None:
            age = time.time() - self.last_price_timestamp
            if age < cache_max_age:
                return self.last_price

        try:
            ticker = self.market_ops.get_ticker(self.market)
            self.last_price = float(ticker['price'])
            self.last_price_timestamp = time.time()
            return self.last_price
        except MarketDelistedError as e:
            self._mark_delisted(e)
            if raise_if_delisted:
                raise
            return self.last_price
        except Exception as e:
            logger.error(f"Error fetching current price: {str(e)}")
            return self.last_price  # Return stale cache if fetch fails

    def _mark_delisted(self, error: Exception) -> None:
        """Flag the market delisted and log it once. Never touches positions.

        Callable from the TUI thread. Positions are only released by
        _handle_delisting on the trading thread. A real position is never
        changed automatically: the coins still exist on the account and
        must be handled manually.
        """
        with self._delisting_lock:
            if self.delisted:
                return
            self.delisted = True

        if self.market in self.positions and self.virtual_wallet is None:
            logger.error(f"MARKET DELISTED: {self.market} ({error}). No further trading or price checks. "
                         f"The open position cannot be sold via the API: handle it manually on Bitvavo "
                         f"(it still counts toward the position limit).")
        else:
            logger.error(f"MARKET DELISTED: {self.market} ({error}). No further trading or price checks.")

    def _handle_delisting(self, df: Optional[pd.DataFrame], reason: str, entry_price: Optional[float]) -> None:
        """Trading thread, once: release a virtual position and record one 'delisted' decision."""
        if self._delisting_handled:
            return
        self._delisting_handled = True
        if self.market in self.positions and self.virtual_wallet is not None:
            self._close_virtual_position_at_last_price()
        try:
            self._record_decision(df, 'delisted', reason, entry_price)
        except Exception as e:
            logger.warning(f"Could not record decision for {self.market}: {e}")

    def _close_virtual_position_at_last_price(self) -> None:
        price = self.last_price if self.last_price is not None else self.entry_prices[self.market]
        success, message = self.virtual_wallet.record_sell(self.market, price, self.positions[self.market])
        if not success:
            logger.error(f"Could not close virtual {self.market} position: {message}")
            return
        del self.positions[self.market]
        del self.entry_prices[self.market]
        logger.info(f"Closed virtual {self.market} position at last known price €{price:.6f} "
                    f"(no fee: the market can no longer be traded)")

    @staticmethod
    def _has_indicators(df: pd.DataFrame) -> bool:
        if df.empty or any(ind not in df.columns for ind in REQUIRED_INDICATORS):
            return False
        return not df.iloc[-1][REQUIRED_INDICATORS].isna().any()

    def _price_based_exit(self) -> tuple[bool, str]:
        """Stop-loss/take-profit on the ticker alone, for when candles are unusable."""
        if self.market not in self.positions:
            return False, ""
        current_price = self.get_current_price(use_cache=True, raise_if_delisted=True)
        if current_price is None:
            return False, ""
        entry_price = self.entry_prices[self.market]
        return self._check_price_exit(((current_price - entry_price) / entry_price) * 100)

    def execute_trade(self):
        """Execute the trading strategy and record the decision."""
        entry_price = self.entry_prices.get(self.market)
        if self.delisted:
            # Flagged (possibly by the TUI poll): no orders, ever
            self._handle_delisting(None, f"{self.market} is delisted", entry_price)
            return
        df = None
        try:
            df = self.calculate_indicators(self.get_historical_data())
            action, reason = self._decide_and_act(df)
        except MarketDelistedError as e:
            self._mark_delisted(e)
            self._handle_delisting(df, str(e), entry_price)
            return
        except MarketNotFoundError as e:
            # Candles answer a delisted market with error 205; only the ticker says 219
            try:
                self.get_current_price(use_cache=False, raise_if_delisted=True)
            except MarketDelistedError as delisted:
                self._handle_delisting(df, str(delisted), entry_price)
                return
            logger.error(f"Error executing trade: {str(e)}")
            action, reason = 'error', str(e)
        except Exception as e:
            logger.error(f"Error executing trade: {str(e)}")
            action, reason = 'error', str(e)
        try:
            self._record_decision(df, action, reason, entry_price)
        except Exception as e:
            logger.warning(f"Could not record decision for {self.market}: {e}")

    def _decide_and_act(self, df: pd.DataFrame) -> tuple[str, str]:
        """Evaluate signals, place any order, and return (action, reason)."""
        if self._has_indicators(df):
            should_buy, buy_reason = self.should_buy(df)
            should_sell, sell_reason = self.should_sell(df)
        else:
            logger.warning(f"Insufficient candle data for {self.market} ({len(df)} candles): "
                           f"indicator signals skipped, only stop-loss/take-profit checked")
            should_buy, buy_reason = False, ""
            should_sell, sell_reason = self._price_based_exit()

        if should_buy and self.market not in self.positions:
            # Portfolio-level risk safeguards: when tripped, no new
            # positions are opened (sells above are unaffected)
            if self.risk_manager is not None:
                allowed, risk_reason = self.risk_manager.can_open_position()
                if not allowed:
                    logger.info(f"BUY BLOCKED for {self.market}: {risk_reason}")
                    return 'blocked_risk', risk_reason

            # Check global position limit before buying
            if self.virtual_wallet is not None:
                active_positions = self.virtual_wallet.get_active_positions()
            else:
                active_positions = self.db.get_active_positions()

            current_position_count = len(active_positions)

            if current_position_count >= self.max_positions:
                active_markets = [pos['market'] for pos in active_positions]
                logger.debug(f"POSITION LIMIT REACHED ({current_position_count}/{self.max_positions}) - Cannot buy {self.market}")
                logger.debug(f"Active positions: {', '.join(active_markets)}")
                return 'blocked_position_limit', buy_reason

            # Place buy order
            current_price = self.get_current_price(use_cache=False, raise_if_delisted=True)  # Always fetch fresh for trading
            if current_price is None:
                logger.error("Cannot execute buy: price unavailable")
                return 'no_price', buy_reason

            amount = self.investment_amount / current_price
            order = self.market_ops.place_market_order(self.market, 'buy', amount)

            # Track what actually filled, not what we asked for: market
            # orders execute at fill prices, and P/L, stop-loss and
            # take-profit must be computed against reality.
            fill_price, filled_amount, fee = parse_order_fills(
                order, fallback_price=current_price, fallback_amount=amount)
            self.positions[self.market] = filled_amount
            self.entry_prices[self.market] = fill_price
            if self.db is not None:
                self.db.record_trade_entry(self.market, fill_price, filled_amount,
                                           fee=fee, order_id=order.get('orderId'))

            logger.info(f"BUY EXECUTED for {self.market}")
            logger.info(f"Reason: {buy_reason}")
            logger.info(f"Amount: {filled_amount:.8f} {self.market} (€{self.investment_amount:.2f})")
            logger.info(f"Fill price: €{fill_price:.6f} (fee: €{fee:.4f})")
            logger.info(f"Active positions: {current_position_count + 1}/{self.max_positions}")
            return 'buy', buy_reason

        if should_sell and self.market in self.positions:
            # Place sell order
            current_price = self.get_current_price(use_cache=False, raise_if_delisted=True)  # Always fetch fresh for trading
            if current_price is None:
                logger.error("Cannot execute sell: price unavailable")
                return 'no_price', sell_reason

            amount = self.positions[self.market]
            entry_price = self.entry_prices[self.market]

            order = self.market_ops.place_market_order(self.market, 'sell', amount)
            exit_price, _, fee = parse_order_fills(
                order, fallback_price=current_price, fallback_amount=amount)
            profit_pct = ((exit_price - entry_price) / entry_price) * 100
            profit_eur = (amount * exit_price) - (amount * entry_price)
            if self.db is not None:
                self.db.record_trade_exit(self.market, exit_price,
                                          fee=fee, order_id=order.get('orderId'))
            del self.positions[self.market]
            del self.entry_prices[self.market]

            logger.info(f"SELL EXECUTED for {self.market}")
            logger.info(f"Reason: {sell_reason}")
            logger.info(f"Amount: {amount:.8f} {self.market}")
            logger.info(f"Entry: €{entry_price:.6f} -> Exit: €{exit_price:.6f} (fee: €{fee:.4f})")
            logger.info(f"P/L: {profit_pct:+.2f}% (€{profit_eur:+.4f})")
            return 'sell', sell_reason

        # Not trading but still update price cache for TUI
        self.get_current_price(use_cache=False)
        if self.market in self.positions:
            logger.debug(f"HOLDING {self.market} - No sell signal")
            return 'hold', ""
        logger.debug(f"MONITORING {self.market} - No buy signal")
        return 'monitor', ""

    def _record_decision(self, df: Optional[pd.DataFrame], action: str, reason: str,
                         entry_price: Optional[float]) -> None:
        """Write one JSON decision record per evaluation (logs/decisions-*.jsonl).

        Carries the ticker price, the candle the indicators were computed on
        and the indicator values at full precision, so runs can be analysed
        with a query instead of parsing the text log.
        """
        record = {
            'ts': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'market': self.market,
            'action': action,
            'reason': reason,
            'price': self.last_price,
            'entry_price': entry_price,
        }
        if df is not None and self._has_indicators(df):
            last = df.iloc[-1]
            record.update({
                'candle_ts': df.index[-1].isoformat(),
                'candle_close': float(last['close']),
                'rsi': float(last['RSI_14']),
                'macd': float(last['MACD_12_26_9']),
                'macd_signal': float(last['MACDs_12_26_9']),
                'bb_lower': float(last['BBL_20_2.0_2.0']),
                'bb_upper': float(last['BBU_20_2.0_2.0']),
            })
        # default=str: a record that fails to serialise must never break the trade cycle
        decision_logger.info(json.dumps(record, default=str))

    def run(self, interval: int = 300, stop_event: Optional[threading.Event] = None):
        """Run the trading strategy until stop_event is set (or forever if None)."""
        logger.info(f"Starting enhanced trading strategy for {self.market}")
        stop = stop_event if stop_event is not None else threading.Event()
        while not stop.is_set():
            self.execute_trade()
            stop.wait(interval)
        logger.info(f"Strategy for {self.market} stopped")
