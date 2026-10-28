"""Delisted markets and missing candle data.

In the 13 Aug - 28 Oct virtual run RVN-EUR was delisted while held. The
position could never be sold, blocked one of three position slots for 40
days, and produced ~745K error lines: the TUI polled the ticker every few
seconds and every strategy cycle crashed on empty candle data before the
stop-loss could run.
"""

import json
import logging
import time
from unittest.mock import Mock, patch

import pytest

from trader.bitvavo import check_bitvavo_response
from trader.enhanced_strategy import EnhancedStrategy
from trader.exceptions import MarketDelistedError, MarketNotFoundError
from trader.multi_market_strategy import MultiMarketStrategy
from trader.virtual_wallet import VirtualWallet

from .test_decision_log import FALLING, RISING, candles, decisions

DELISTED_RESPONSE = {'errorCode': 219, 'error': 'This market has been delisted.'}


def delisted_market_ops():
    ops = Mock()
    ops.get_historical_candles.side_effect = MarketDelistedError('candles RVN-EUR: This market has been delisted.')
    ops.get_ticker.side_effect = MarketDelistedError('ticker RVN-EUR: This market has been delisted.')
    return ops


@pytest.fixture
def wallet_holding_rvn(tmp_path):
    wallet = VirtualWallet(db_path=str(tmp_path / 'wallet.db'), initial_balance=100.0)
    wallet.record_buy('RVN-EUR', price=0.02, amount=500.0, fee=0.025)
    return wallet


def test_delisted_error_code_raises_market_delisted_error():
    with pytest.raises(MarketDelistedError):
        check_bitvavo_response(DELISTED_RESPONSE, 'ticker RVN-EUR')


class TestVirtualPositionInDelistedMarket:
    def test_position_is_closed_at_last_known_price(self, wallet_holding_rvn):
        strategy = EnhancedStrategy(delisted_market_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)
        strategy.last_price = 0.021  # last successful ticker fetch before the delisting

        strategy.execute_trade()

        assert wallet_holding_rvn.get_active_positions() == []
        closed = wallet_holding_rvn.get_trade_history()[0]
        assert closed['exit_price'] == pytest.approx(0.021)
        assert strategy.positions == {}

    def test_without_a_known_price_the_position_is_closed_at_entry(self, wallet_holding_rvn):
        strategy = EnhancedStrategy(delisted_market_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)

        strategy.execute_trade()

        assert wallet_holding_rvn.get_active_positions() == []
        assert wallet_holding_rvn.get_trade_history()[0]['exit_price'] == pytest.approx(0.02)


class TestRealPositionInDelistedMarket:
    @pytest.fixture
    def strategy(self):
        with patch('trader.enhanced_strategy.TradeDatabase') as db_class:
            db_class.return_value.get_active_positions.return_value = [
                {'market': 'RVN-EUR', 'amount': 500.0, 'entry_price': 0.02}]
            yield EnhancedStrategy(delisted_market_ops(), 'RVN-EUR')

    def test_position_is_left_for_manual_handling(self, strategy):
        strategy.execute_trade()

        strategy.market_ops.place_market_order.assert_not_called()
        strategy.db.record_trade_exit.assert_not_called()
        assert 'RVN-EUR' in strategy.positions
        assert strategy.delisted

    def test_api_is_not_called_again_after_detection(self, strategy):
        for _ in range(3):
            strategy.execute_trade()

        assert strategy.market_ops.get_historical_candles.call_count == 1

    def test_delisting_is_logged_once(self, strategy, caplog):
        with caplog.at_level(logging.INFO, logger='trader.enhanced_strategy'):
            for _ in range(3):
                strategy.execute_trade()
                strategy.get_current_price(use_cache=False)

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1
        assert 'delisted' in errors[0].getMessage().lower()


def test_price_polling_stops_after_delisting(wallet_holding_rvn):
    strategy = EnhancedStrategy(delisted_market_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)
    strategy.last_price = 0.021

    prices = [strategy.get_current_price(use_cache=False) for _ in range(3)]

    assert prices == [0.021, 0.021, 0.021]
    assert strategy.market_ops.get_ticker.call_count == 1


def test_delisted_market_is_dropped_from_rotation(wallet_holding_rvn):
    multi = MultiMarketStrategy(delisted_market_ops(), ['RVN-EUR'], virtual_wallet=wallet_holding_rvn)

    multi.execute_all_trades()

    assert 'RVN-EUR' not in multi.markets
    assert 'RVN-EUR' not in multi.strategies


class TestTooFewCandles:
    """Short or empty candle history must not crash the cycle, and an open
    position must still be protected by the price-based stop-loss."""

    def _strategy_holding(self, tmp_path, candles, ticker_price):
        wallet = VirtualWallet(db_path=str(tmp_path / 'wallet.db'), initial_balance=100.0)
        wallet.record_buy('ABC-EUR', price=1.0, amount=10.0, fee=0.025)
        ops = Mock()
        ops.get_historical_candles.return_value = candles
        ops.get_ticker.return_value = {'price': str(ticker_price)}
        ops.place_market_order.return_value = {'orderId': '1'}
        return EnhancedStrategy(ops, 'ABC-EUR', virtual_wallet=wallet, stop_loss_pct=5.0)

    def test_empty_candles_still_trigger_stop_loss(self, tmp_path):
        strategy = self._strategy_holding(tmp_path, candles=[], ticker_price=0.90)

        strategy.execute_trade()

        strategy.market_ops.place_market_order.assert_called_once_with('ABC-EUR', 'sell', 10.0)

    def test_short_history_without_exit_condition_holds(self, tmp_path, caplog):
        few = [[1_756_000_000_000 + i * 300_000, '1', '1', '1', '1', '1'] for i in range(10)]
        strategy = self._strategy_holding(tmp_path, candles=few, ticker_price=1.01)

        with caplog.at_level(logging.INFO, logger='trader.enhanced_strategy'):
            strategy.execute_trade()

        strategy.market_ops.place_market_order.assert_not_called()
        assert not [r for r in caplog.records if 'Error executing trade' in r.getMessage()]


def realistic_delisted_ops(candles_error=True):
    ops = Mock()
    if candles_error:
        ops.get_historical_candles.side_effect = MarketNotFoundError('candles RVN-EUR: market parameter is invalid.')
    else:
        ops.get_historical_candles.return_value = []
    ops.get_ticker.side_effect = MarketDelistedError('ticker RVN-EUR: This market has been delisted.')
    return ops


def test_realistic_delisting_closes_virtual_position_once(wallet_holding_rvn, caplog):
    strategy = EnhancedStrategy(realistic_delisted_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)
    strategy.last_price = 0.021
    with caplog.at_level(logging.INFO):
        strategy.execute_trade()
        strategy.execute_trade()
    assert wallet_holding_rvn.get_active_positions() == []
    assert len(wallet_holding_rvn.get_trade_history()) == 1
    actions = [json.loads(r.getMessage())['action'] for r in caplog.records if r.name == 'trader.decisions']
    assert actions == ['delisted']
    assert not [r for r in caplog.records if 'Error executing trade' in r.getMessage()]


def test_real_mode_never_orders_on_a_delisted_market():
    with patch('trader.enhanced_strategy.TradeDatabase') as db_class:
        db_class.return_value.get_active_positions.return_value = [
            {'market': 'RVN-EUR', 'amount': 500.0, 'entry_price': 0.02}]
        strategy = EnhancedStrategy(realistic_delisted_ops(candles_error=False), 'RVN-EUR')
    strategy.last_price = 0.018   # -10%: the stop-loss would fire on the stale price
    strategy.execute_trade()
    strategy.execute_trade()
    strategy.market_ops.place_market_order.assert_not_called()
    assert 'RVN-EUR' in strategy.positions


def test_delisting_seen_by_price_polling_is_handled_by_the_trading_thread(wallet_holding_rvn):
    strategy = EnhancedStrategy(realistic_delisted_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)
    strategy.last_price = 0.021
    strategy.get_current_price(use_cache=False)          # TUI thread
    assert len(wallet_holding_rvn.get_active_positions()) == 1
    strategy.execute_trade()                              # trading thread
    assert wallet_holding_rvn.get_active_positions() == []


def test_buy_signal_on_a_market_delisted_mid_cycle_places_no_order():
    ops = realistic_delisted_ops()
    ops.get_historical_candles.side_effect = None
    ops.get_historical_candles.return_value = candles(FALLING)          # RSI 0: buy signal
    strategy = EnhancedStrategy(ops, 'NEW-EUR', virtual_wallet=Mock(get_active_positions=Mock(return_value=[])))
    strategy.last_price = 1.0   # a stale price exists, so only the delisting guard can stop the order
    strategy.execute_trade()
    ops.place_market_order.assert_not_called()


def test_price_polling_survives_rotation_during_iteration():
    ops = Mock()
    ops.get_ticker.return_value = {'price': '1.0'}
    multi = MultiMarketStrategy(ops, ['A-EUR', 'B-EUR'],
                                virtual_wallet=Mock(get_active_positions=Mock(return_value=[])))

    def rotate_out_b(**kwargs):
        multi.strategies.pop('B-EUR', None)
        return 1.0
    multi.strategies['A-EUR'].get_current_price = rotate_out_b
    multi.get_current_prices()   # must not raise RuntimeError


def real_strategy_holding_rvn(ops):
    """Real mode (TradeDatabase patched) holding 500 RVN-EUR bought at 0.02."""
    with patch('trader.enhanced_strategy.TradeDatabase') as db_class:
        db_class.return_value.get_active_positions.return_value = [
            {'market': 'RVN-EUR', 'amount': 500.0, 'entry_price': 0.02}]
        return EnhancedStrategy(ops, 'RVN-EUR')


RVN_FALLING = candles([c / 100 for c in FALLING])   # full history, RSI 0: no technical sell, only the stop-loss


class TestRealPositionDelistedMidCycle:
    """The cached ticker price is fresh and 10% below entry, so the stop-loss
    would sell on it. Only the delisting guards stop that sell order."""

    def _strategy(self, ops):
        strategy = real_strategy_holding_rvn(ops)
        strategy.last_price, strategy.last_price_timestamp = 0.018, time.time()
        return strategy

    def _assert_left_for_manual_handling(self, strategy, caplog):
        strategy.market_ops.place_market_order.assert_not_called()
        strategy.db.record_trade_exit.assert_not_called()
        assert strategy.positions == {'RVN-EUR': 500.0}
        assert [d['action'] for d in decisions(caplog)] == ['delisted']

    def test_delisting_seen_by_price_polling_during_the_candle_fetch(self, caplog):
        ops = realistic_delisted_ops()
        strategy = self._strategy(ops)

        def candles_while_the_tui_polls(*args, **kwargs):
            strategy.get_current_price(use_cache=False)   # TUI thread gets the 219 mid-cycle
            return RVN_FALLING
        ops.get_historical_candles.side_effect = candles_while_the_tui_polls

        with caplog.at_level(logging.INFO):
            strategy.execute_trade()

        self._assert_left_for_manual_handling(strategy, caplog)
        # should_sell aborts on the flag; it never evaluates exits on the stale cached price
        assert not [r for r in caplog.records if 'SELL SIGNAL TRIGGERED' in r.getMessage()]

    def test_delisting_first_seen_at_the_sell_order_price_fetch(self, caplog):
        ops = realistic_delisted_ops()
        ops.get_historical_candles.side_effect = None
        ops.get_historical_candles.return_value = RVN_FALLING
        strategy = self._strategy(ops)

        with caplog.at_level(logging.INFO):
            strategy.execute_trade()

        ops.get_ticker.assert_called_once()   # the sell check used the cache; the 219 came at the order's fetch
        self._assert_left_for_manual_handling(strategy, caplog)


def test_delisting_first_seen_at_the_price_refresh_is_handled_in_the_same_cycle(caplog):
    ops = realistic_delisted_ops()
    ops.get_historical_candles.side_effect = None
    ops.get_historical_candles.return_value = candles(RISING)   # no position, no buy signal: only the refresh fetches
    strategy = EnhancedStrategy(ops, 'NEW-EUR', virtual_wallet=Mock(get_active_positions=Mock(return_value=[])))

    with caplog.at_level(logging.INFO):
        strategy.execute_trade()

    assert [d['action'] for d in decisions(caplog)] == ['delisted']
