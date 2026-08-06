"""Tests for the Phase 0 safety fixes: fill parsing, floor rounding,
virtual/real store isolation, graceful shutdown and position reconciliation."""

import sqlite3
import threading
import time
from unittest.mock import Mock, patch

import pytest

from trader.database import TradeDatabase
from trader.enhanced_strategy import EnhancedStrategy
from trader.market import floor_to_increment, parse_order_fills


class TestParseOrderFills:
    def test_weighted_average_from_fills(self):
        response = {
            'orderId': 'abc',
            'feePaid': '0.30',
            'fills': [
                {'price': '100.0', 'amount': '1.0', 'fee': '0.10'},
                {'price': '110.0', 'amount': '3.0', 'fee': '0.20'},
            ],
        }
        price, amount, fee = parse_order_fills(response)
        assert amount == pytest.approx(4.0)
        assert price == pytest.approx((100.0 * 1 + 110.0 * 3) / 4)
        assert fee == pytest.approx(0.30)

    def test_summary_fields_when_no_fills(self):
        response = {'filledAmount': '2.0', 'filledAmountQuote': '50.0', 'feePaid': '0.05'}
        price, amount, fee = parse_order_fills(response)
        assert amount == pytest.approx(2.0)
        assert price == pytest.approx(25.0)
        assert fee == pytest.approx(0.05)

    def test_fallbacks_when_response_empty(self):
        price, amount, fee = parse_order_fills({}, fallback_price=42.0, fallback_amount=3.0)
        assert price == 42.0
        assert amount == 3.0
        assert fee == 0.0

    def test_fee_summed_from_fills_when_feepaid_missing(self):
        response = {
            'fills': [
                {'price': '10.0', 'amount': '1.0', 'fee': '0.01'},
                {'price': '10.0', 'amount': '1.0', 'fee': '0.02'},
            ]
        }
        _, _, fee = parse_order_fills(response)
        assert fee == pytest.approx(0.03)


class TestFloorToIncrement:
    @pytest.mark.parametrize("amount, increment, expected", [
        (123.456, '0.01', '123.45'),
        (123.459999, '0.01', '123.45'),
        (0.99999999, '1', '0'),
        (123.0, '0.01', '123'),
        (429285.0452700593, '0.01', '429285.04'),
        (0.000123456, '0.00000001', '0.00012345'),
    ])
    def test_always_floors(self, amount, increment, expected):
        _, text = floor_to_increment(amount, increment)
        assert text == expected

    def test_never_exceeds_input(self):
        floored, _ = floor_to_increment(0.1 + 0.2, '0.01')  # 0.30000000000000004
        assert float(floored) <= 0.1 + 0.2


class TestStoreIsolation:
    """Virtual-mode strategies must never touch the real trades database."""

    def test_virtual_mode_does_not_create_trade_database(self):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        with patch('trader.enhanced_strategy.TradeDatabase') as mock_db_class:
            strategy = EnhancedStrategy(
                market_ops=Mock(),
                market='TEST-EUR',
                virtual_wallet=wallet,
            )
            mock_db_class.assert_not_called()
            assert strategy.db is None

    def test_real_mode_creates_trade_database(self):
        with patch('trader.enhanced_strategy.TradeDatabase') as mock_db_class:
            mock_db = Mock()
            mock_db.get_active_positions.return_value = []
            mock_db_class.return_value = mock_db
            strategy = EnhancedStrategy(
                market_ops=Mock(),
                market='TEST-EUR',
                virtual_wallet=None,
            )
            mock_db_class.assert_called_once()
            assert strategy.db is mock_db


class TestGracefulStop:
    def test_run_returns_when_stop_event_set(self):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        strategy = EnhancedStrategy(
            market_ops=Mock(),
            market='TEST-EUR',
            virtual_wallet=wallet,
        )
        strategy.execute_trade = Mock()

        stop = threading.Event()
        thread = threading.Thread(target=strategy.run, kwargs={'interval': 60, 'stop_event': stop})
        thread.start()
        time.sleep(0.2)  # let it enter the first execute + wait
        stop.set()
        thread.join(timeout=5)

        assert not thread.is_alive(), "run() must return promptly after stop_event is set"
        assert strategy.execute_trade.call_count >= 1

    def test_run_skips_execution_when_already_stopped(self):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        strategy = EnhancedStrategy(
            market_ops=Mock(),
            market='TEST-EUR',
            virtual_wallet=wallet,
        )
        strategy.execute_trade = Mock()

        stop = threading.Event()
        stop.set()
        strategy.run(interval=60, stop_event=stop)
        strategy.execute_trade.assert_not_called()


class TestReconcilePositions:
    def _make_db(self, positions):
        db = Mock()
        db.get_active_positions.return_value = positions
        return db

    def _make_ops(self, balances):
        ops = Mock()
        ops.get_balance.return_value = balances
        return ops

    def test_matching_positions_pass(self):
        from trader.main import reconcile_positions
        db = self._make_db([{'market': 'VET-EUR', 'amount': 100.0, 'entry_price': 0.02}])
        ops = self._make_ops([{'symbol': 'VET', 'available': '100.0', 'inOrder': '0'}])
        assert reconcile_positions(db, ops) is True

    def test_phantom_position_blocks_trading(self):
        from trader.main import reconcile_positions
        db = self._make_db([{'market': 'VET-EUR', 'amount': 100.0, 'entry_price': 0.02}])
        ops = self._make_ops([{'symbol': 'EUR', 'available': '500.0', 'inOrder': '0'}])
        assert reconcile_positions(db, ops) is False

    def test_force_overrides_mismatch(self):
        from trader.main import reconcile_positions
        db = self._make_db([{'market': 'VET-EUR', 'amount': 100.0, 'entry_price': 0.02}])
        ops = self._make_ops([{'symbol': 'EUR', 'available': '500.0', 'inOrder': '0'}])
        assert reconcile_positions(db, ops, force=True) is True

    def test_small_shortfall_within_tolerance_passes(self):
        from trader.main import reconcile_positions
        db = self._make_db([{'market': 'VET-EUR', 'amount': 100.0, 'entry_price': 0.02}])
        ops = self._make_ops([{'symbol': 'VET', 'available': '99.5', 'inOrder': '0'}])
        assert reconcile_positions(db, ops) is True

    def test_no_positions_passes_without_api_call(self):
        from trader.main import reconcile_positions
        db = self._make_db([])
        ops = Mock()
        assert reconcile_positions(db, ops) is True
        ops.get_balance.assert_not_called()


class TestDatabaseFeesAndMigration:
    def test_migrates_old_schema(self, tmp_path):
        db_path = str(tmp_path / 'old.db')
        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                amount REAL NOT NULL,
                entry_time TIMESTAMP NOT NULL,
                exit_time TIMESTAMP,
                status TEXT NOT NULL,
                profit_loss REAL
            )
        ''')
        conn.commit()
        conn.close()

        db = TradeDatabase(db_path)
        conn = sqlite3.connect(db_path)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(trades)').fetchall()}
        conn.close()
        assert {'fee', 'entry_order_id', 'exit_order_id'} <= columns

    def test_profit_loss_is_net_of_fees(self, tmp_path):
        db = TradeDatabase(str(tmp_path / 'trades.db'))
        db.record_trade_entry('VET-EUR', entry_price=1.0, amount=10.0, fee=0.05, order_id='buy-1')
        db.record_trade_exit('VET-EUR', exit_price=1.2, fee=0.06, order_id='sell-1')

        trades = db.get_trade_history()
        assert len(trades) == 1
        # Gross P/L = (1.2 - 1.0) * 10 = 2.0; net of €0.11 fees = 1.89
        assert trades[0]['profit_loss'] == pytest.approx(1.89)

    def test_total_costs_covers_active_trades_only(self, tmp_path):
        db = TradeDatabase(str(tmp_path / 'trades.db'))
        db.record_trade_entry('VET-EUR', entry_price=1.0, amount=10.0, fee=0.05)
        db.record_trade_entry('PEPE-EUR', entry_price=2.0, amount=5.0, fee=0.03)
        db.record_trade_exit('VET-EUR', exit_price=1.1, fee=0.06)

        # Only PEPE is still active; its entry fee is the outstanding cost
        assert db.get_total_costs() == pytest.approx(0.03)


class TestFillRecording:
    """Buys/sells must record what actually filled, not the pre-trade ticker."""

    def _strategy_with_wallet(self, market_ops):
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        return EnhancedStrategy(
            market_ops=market_ops,
            market='TEST-EUR',
            investment_amount=10.0,
            virtual_wallet=wallet,
        ), wallet

    def test_buy_uses_fill_price_and_amount(self):
        market_ops = Mock()
        market_ops.get_ticker.return_value = {'price': '100.00'}
        market_ops.place_market_order.return_value = {
            'orderId': 'ord-1',
            'fills': [{'price': '101.00', 'amount': '0.0995', 'fee': '0.025'}],
            'feePaid': '0.025',
        }
        strategy, _ = self._strategy_with_wallet(market_ops)

        with patch.object(strategy, 'get_historical_data'), \
             patch.object(strategy, 'calculate_indicators'), \
             patch.object(strategy, 'should_buy', return_value=(True, 'test')), \
             patch.object(strategy, 'should_sell', return_value=(False, '')):
            strategy.execute_trade()

        # Position reflects the actual fill, not ticker price / requested amount
        assert strategy.positions['TEST-EUR'] == pytest.approx(0.0995)
        assert strategy.entry_prices['TEST-EUR'] == pytest.approx(101.00)
