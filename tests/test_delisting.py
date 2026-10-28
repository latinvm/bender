"""Delisted markets and missing candle data.

In the 13 Aug - 28 Oct virtual run RVN-EUR was delisted while held. The
position could never be sold, blocked one of three position slots for 40
days, and produced ~745K error lines: the TUI polled the ticker every few
seconds and every strategy cycle crashed on empty candle data before the
stop-loss could run.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from trader.bitvavo import check_bitvavo_response
from trader.enhanced_strategy import EnhancedStrategy
from trader.exceptions import MarketDelistedError
from trader.multi_market_strategy import MultiMarketStrategy
from trader.virtual_wallet import VirtualWallet

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
