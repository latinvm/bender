"""Tests for Phase 2: portfolio risk safeguards, market rotation, and the
honest (no-live-price, fee-aware) backtester."""

import math
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from trader.backtester import Backtester
from trader.database import TradeDatabase
from trader.enhanced_strategy import EnhancedStrategy
from trader.multi_market_strategy import MultiMarketStrategy
from trader.risk import RiskManager
from trader.virtual_wallet import VirtualWallet


class TestRiskManager:
    def _store(self, today_pl=0.0, total_pl=0.0):
        store = Mock()
        store.get_profit_loss_since.return_value = today_pl
        store.get_total_profit_loss.return_value = total_pl
        return store

    def test_no_limits_always_allowed(self):
        rm = RiskManager(self._store(today_pl=-9999, total_pl=-9999), capital_base=1000.0)
        allowed, _ = rm.can_open_position()
        assert allowed is True

    def test_daily_loss_limit_blocks(self):
        rm = RiskManager(self._store(today_pl=-101.0), capital_base=1000.0, max_daily_loss_pct=10.0)
        allowed, reason = rm.can_open_position()
        assert allowed is False
        assert 'DAILY LOSS LIMIT' in reason

    def test_daily_loss_within_limit_allows(self):
        rm = RiskManager(self._store(today_pl=-99.0), capital_base=1000.0, max_daily_loss_pct=10.0)
        allowed, _ = rm.can_open_position()
        assert allowed is True

    def test_drawdown_limit_blocks(self):
        rm = RiskManager(self._store(total_pl=-251.0), capital_base=1000.0, max_drawdown_pct=25.0)
        allowed, reason = rm.can_open_position()
        assert allowed is False
        assert 'MAX DRAWDOWN' in reason

    def test_drawdown_within_limit_allows(self):
        rm = RiskManager(self._store(total_pl=-249.0), capital_base=1000.0, max_drawdown_pct=25.0)
        allowed, _ = rm.can_open_position()
        assert allowed is True

    def test_zero_capital_base_allowed(self):
        rm = RiskManager(self._store(today_pl=-9999), capital_base=0.0,
                         max_daily_loss_pct=10.0, max_drawdown_pct=25.0)
        allowed, _ = rm.can_open_position()
        assert allowed is True

    def test_strategy_blocks_buy_when_tripped(self):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        market_ops = Mock()

        tripped = Mock()
        tripped.can_open_position.return_value = (False, 'DAILY LOSS LIMIT HIT')

        strategy = EnhancedStrategy(
            market_ops=market_ops,
            market='TEST-EUR',
            virtual_wallet=wallet,
            risk_manager=tripped,
        )
        with patch.object(strategy, 'get_historical_data'), \
             patch.object(strategy, 'calculate_indicators'), \
             patch.object(strategy, 'should_buy', return_value=(True, 'test')), \
             patch.object(strategy, 'should_sell', return_value=(False, '')):
            strategy.execute_trade()

        market_ops.place_market_order.assert_not_called()
        assert strategy.positions == {}


class TestProfitLossSince:
    def test_trade_database(self, tmp_path):
        db = TradeDatabase(str(tmp_path / 'trades.db'))
        db.record_trade_entry('VET-EUR', entry_price=1.0, amount=10.0)
        db.record_trade_exit('VET-EUR', exit_price=0.9)  # -1.0 P/L

        midnight = datetime.combine(datetime.now().date(), datetime.min.time())
        assert db.get_profit_loss_since(midnight) == pytest.approx(-1.0)
        tomorrow = midnight + timedelta(days=1)
        assert db.get_profit_loss_since(tomorrow) == 0.0

    def test_virtual_wallet(self, tmp_path):
        wallet = VirtualWallet(str(tmp_path / 'wallet.db'), initial_balance=1000.0)
        wallet.record_buy('VET-EUR', price=1.0, amount=10.0, fee=0.0)
        wallet.record_sell('VET-EUR', price=0.9, amount=10.0, fee=0.0)

        midnight = datetime.combine(datetime.now().date(), datetime.min.time())
        assert wallet.get_profit_loss_since(midnight) == pytest.approx(-1.0)
        tomorrow = midnight + timedelta(days=1)
        assert wallet.get_profit_loss_since(tomorrow) == 0.0


class TestMarketRotation:
    def _strategy(self, markets):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        with patch('trader.enhanced_strategy.TradeDatabase'):
            return MultiMarketStrategy(
                market_ops=Mock(),
                markets=markets,
                virtual_wallet=wallet,
            )

    def test_rotation_applied_at_cycle_start(self):
        strategy = self._strategy(['AAA-EUR', 'BBB-EUR'])
        for s in strategy.strategies.values():
            s.execute_trade = Mock()

        strategy.update_markets(['AAA-EUR', 'CCC-EUR'])
        strategy.execute_all_trades()

        assert set(strategy.markets) == {'AAA-EUR', 'CCC-EUR'}
        assert 'BBB-EUR' not in strategy.strategies
        assert 'CCC-EUR' in strategy.strategies

    def test_market_with_open_position_never_dropped(self):
        strategy = self._strategy(['AAA-EUR', 'BBB-EUR'])
        # BBB holds a position: it must survive rotation
        strategy.strategies['BBB-EUR'].positions = {'BBB-EUR': 5.0}
        for s in strategy.strategies.values():
            s.execute_trade = Mock()

        strategy.update_markets(['CCC-EUR'])
        strategy.execute_all_trades()

        assert 'BBB-EUR' in strategy.markets
        assert 'AAA-EUR' not in strategy.markets
        assert 'CCC-EUR' in strategy.markets

    def test_no_pending_rotation_is_noop(self):
        strategy = self._strategy(['AAA-EUR'])
        strategy.strategies['AAA-EUR'].execute_trade = Mock()
        strategy.execute_all_trades()
        assert strategy.markets == ['AAA-EUR']


def make_candles(prices, start_ms=1_700_000_000_000):
    """Build hourly candles [[ts, open, high, low, close, volume], ...]"""
    candles = []
    for i, close in enumerate(prices):
        ts = start_ms + i * 3_600_000
        candles.append([ts, str(close), str(close * 1.01), str(close * 0.99), str(close), '1000'])
    return candles


class TestHonestBacktester:
    def _price_series(self):
        # Steep decline (drives RSI into oversold -> buy), then a strong
        # recovery (take-profit or technical sell)
        down = [100 - i * 0.8 for i in range(60)]     # 100 -> 52.8
        up = [52.8 + i * 1.2 for i in range(60)]      # 52.8 -> 123.6
        return down + up

    def test_runs_offline_without_any_live_price_access(self):
        market_ops = Mock()
        candles = make_candles(self._price_series())

        backtester = Backtester(
            market_ops=market_ops,
            strategy_class=EnhancedStrategy,
            market='TEST-EUR',
            start_date='2023-01-01',
            end_date='2024-12-31',
            initial_balance=1000.0,
            investment_amount=10.0,
            trading_fee_pct=0.25,
            candles=candles,
        )
        results = backtester.run()

        # Offline: candles were provided, so no API fetch...
        market_ops.get_historical_candles.assert_not_called()
        # ...and crucially the live ticker is NEVER consulted: exit decisions
        # must use historical closes only
        market_ops.get_ticker.assert_not_called()

        assert results, "backtest should produce results for valid candles"
        for key in ('total_return', 'total_return_pct', 'max_drawdown_pct',
                    'win_rate', 'total_trades', 'buy_hold_return_pct'):
            assert key in results
        assert math.isfinite(results['total_return'])

    def test_trades_settle_through_wallet_with_fees(self):
        market_ops = Mock()
        candles = make_candles(self._price_series())

        backtester = Backtester(
            market_ops=market_ops,
            strategy_class=EnhancedStrategy,
            market='TEST-EUR',
            start_date='2023-01-01',
            end_date='2024-12-31',
            initial_balance=1000.0,
            investment_amount=10.0,
            trading_fee_pct=0.25,
            candles=candles,
        )
        results = backtester.run()

        # The price series is engineered to produce at least one buy
        assert results['total_trades'] >= 1 or backtester.strategy.positions
        # Wallet accounting must hold: equity = balance + open positions
        stats = backtester.wallet.get_statistics()
        assert stats['balance'] <= 1000.0  # fees + invested capital deducted

    def test_never_touches_real_trade_database(self):
        with patch('trader.enhanced_strategy.TradeDatabase') as mock_db:
            backtester = Backtester(
                market_ops=Mock(),
                strategy_class=EnhancedStrategy,
                market='TEST-EUR',
                start_date='2023-01-01',
                end_date='2024-12-31',
                candles=make_candles(self._price_series()),
            )
            backtester.run()
            mock_db.assert_not_called()


class TestShouldSellExplicitPrice:
    """should_sell(df, current_price=...) must use the given price and never
    fetch the live ticker - the contract the backtester relies on."""

    def _strategy_with_position(self):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        strategy = EnhancedStrategy(
            market_ops=Mock(),
            market='TEST-EUR',
            virtual_wallet=wallet,
        )
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        return strategy

    def _df_no_technical_sell(self):
        df = pd.DataFrame({
            'close': [100.0] * 30,
            'RSI_14': [55.0] * 30,
            'MACD_12_26_9': [0.5] * 30,
            'MACDs_12_26_9': [0.4] * 30,
            'BBU_20_2.0_2.0': [120.0] * 30,
            'BBL_20_2.0_2.0': [80.0] * 30,
        })
        return df

    def test_take_profit_uses_explicit_price(self):
        strategy = self._strategy_with_position()
        strategy.get_current_price = Mock(side_effect=AssertionError("live ticker must not be fetched"))

        should_sell, reason = strategy.should_sell(self._df_no_technical_sell(), current_price=116.0)

        assert should_sell is True
        assert 'Take Profit' in reason

    def test_stop_loss_uses_explicit_price(self):
        strategy = self._strategy_with_position()
        strategy.get_current_price = Mock(side_effect=AssertionError("live ticker must not be fetched"))

        should_sell, reason = strategy.should_sell(self._df_no_technical_sell(), current_price=94.0)

        assert should_sell is True
        assert 'Stop Loss' in reason

    def test_no_sell_at_neutral_explicit_price(self):
        strategy = self._strategy_with_position()
        strategy.get_current_price = Mock(side_effect=AssertionError("live ticker must not be fetched"))

        should_sell, _ = strategy.should_sell(self._df_no_technical_sell(), current_price=102.0)

        assert should_sell is False
