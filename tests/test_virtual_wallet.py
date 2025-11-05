import pytest
import sqlite3
import tempfile
import os
from datetime import datetime
from pathlib import Path
from trader.virtual_wallet import VirtualWallet


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def wallet(temp_db):
    """Create a VirtualWallet instance with temporary database"""
    return VirtualWallet(db_path=temp_db, initial_balance=1000.0)


@pytest.fixture
def wallet_with_position(temp_db):
    """Create a wallet with an active position"""
    wallet = VirtualWallet(db_path=temp_db, initial_balance=1000.0)
    wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.25)
    return wallet


class TestVirtualWalletInitialization:
    """Test wallet initialization"""

    def test_init_creates_database(self, temp_db):
        """Test that initialization creates database file"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=1000.0)

        assert os.path.exists(temp_db)
        assert wallet.initial_balance == 1000.0

    def test_init_creates_tables(self, temp_db):
        """Test that all required tables are created"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=500.0)

        conn = wallet._get_connection()
        cursor = conn.cursor()

        # Check wallet table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wallet'")
        assert cursor.fetchone() is not None

        # Check virtual_trades table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='virtual_trades'")
        assert cursor.fetchone() is not None

        # Check virtual_positions table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='virtual_positions'")
        assert cursor.fetchone() is not None

        # Check transactions table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
        assert cursor.fetchone() is not None

        conn.close()

    def test_init_sets_initial_balance(self, temp_db):
        """Test that initial balance is set correctly"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=2500.0)

        balance = wallet.get_balance()
        initial_balance = wallet.get_initial_balance()

        assert balance == 2500.0
        assert initial_balance == 2500.0

    def test_init_logs_initial_transaction(self, temp_db):
        """Test that initial deposit is logged in transactions"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=1000.0)

        conn = wallet._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE transaction_type = 'DEPOSIT'")
        transaction = cursor.fetchone()
        conn.close()

        assert transaction is not None
        assert transaction[2] == 1000.0  # amount

    def test_init_existing_database(self, temp_db):
        """Test initializing with existing database doesn't reset balance"""
        # Create first wallet
        wallet1 = VirtualWallet(db_path=temp_db, initial_balance=1000.0)
        wallet1.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.25)

        # Create second wallet instance with same db
        wallet2 = VirtualWallet(db_path=temp_db, initial_balance=2000.0)

        # Balance should be from first wallet, not reset
        balance = wallet2.get_balance()
        assert balance == 899.75  # 1000 - 100 - 0.25


class TestBalanceManagement:
    """Test balance operations"""

    def test_get_balance(self, wallet):
        """Test getting current balance"""
        balance = wallet.get_balance()
        assert balance == 1000.0

    def test_get_initial_balance(self, wallet):
        """Test getting initial balance"""
        initial_balance = wallet.get_initial_balance()
        assert initial_balance == 1000.0

    def test_balance_after_buy(self, wallet):
        """Test balance decreases after buy"""
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.25)

        balance = wallet.get_balance()
        # 1000 - (50 * 2) - 0.25 = 899.75
        assert balance == 899.75

    def test_balance_after_sell(self, wallet_with_position):
        """Test balance increases after sell"""
        wallet_with_position.record_sell(market='BTC-EUR', price=120.0, amount=1.0, fee=0.30)

        balance = wallet_with_position.get_balance()
        # Started at 899.75, gained (120 * 1) - 0.30 = 119.70
        # 899.75 + 119.70 = 1019.45
        assert balance == pytest.approx(1019.45, rel=1e-2)

    def test_balance_consistency(self, wallet):
        """Test balance consistency across multiple operations"""
        initial = wallet.get_balance()

        # Buy
        wallet.record_buy(market='ADA-EUR', price=1.0, amount=100.0, fee=0.25)
        balance_after_buy = wallet.get_balance()
        assert balance_after_buy == initial - 100.0 - 0.25

        # Sell
        wallet.record_sell(market='ADA-EUR', price=1.2, amount=100.0, fee=0.30)
        balance_after_sell = wallet.get_balance()
        # Should have profit of (1.2 - 1.0) * 100 - total fees (0.25 + 0.30) = 19.45
        assert balance_after_sell == pytest.approx(initial + 19.45, rel=1e-2)


class TestBuyOrders:
    """Test buy order execution"""

    def test_record_buy_success(self, wallet):
        """Test successful buy order"""
        success, message = wallet.record_buy(
            market='BTC-EUR',
            price=100.0,
            amount=1.0,
            fee=0.25
        )

        assert success is True
        assert "successful" in message.lower()

        # Verify balance was deducted
        balance = wallet.get_balance()
        assert balance == 899.75

        # Verify position was created
        positions = wallet.get_active_positions()
        assert len(positions) == 1
        assert positions[0]['market'] == 'BTC-EUR'
        assert positions[0]['amount'] == 1.0
        assert positions[0]['entry_price'] == 100.0

    def test_record_buy_with_fee(self, wallet):
        """Test buy order with trading fee"""
        fee = 0.25  # 0.25% of 100
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=fee)

        balance = wallet.get_balance()
        # 1000 - (50 * 2) - 0.25 = 899.75
        assert balance == 899.75

    def test_record_buy_insufficient_balance(self, wallet):
        """Test buy fails with insufficient balance"""
        success, message = wallet.record_buy(
            market='BTC-EUR',
            price=1000.0,
            amount=2.0,  # Would cost 2000
            fee=0.0
        )

        assert success is False
        assert "insufficient balance" in message.lower()

        # Verify no position was created
        positions = wallet.get_active_positions()
        assert len(positions) == 0

    def test_record_buy_duplicate_position(self, wallet_with_position):
        """Test buy fails when position already exists"""
        success, message = wallet_with_position.record_buy(
            market='BTC-EUR',
            price=110.0,
            amount=1.0,
            fee=0.25
        )

        assert success is False
        assert "already have an active position" in message.lower()

    def test_record_buy_zero_fee(self, wallet):
        """Test buy with zero fee"""
        success, message = wallet.record_buy(
            market='XRP-EUR',
            price=0.5,
            amount=100.0,
            fee=0.0
        )

        assert success is True
        balance = wallet.get_balance()
        assert balance == 950.0  # 1000 - 50

    def test_record_buy_creates_trade_record(self, wallet):
        """Test that buy creates a trade record"""
        wallet.record_buy(market='DOT-EUR', price=10.0, amount=5.0, fee=0.125)

        trades = wallet.get_trade_history(limit=1)
        assert len(trades) == 1
        assert trades[0]['market'] == 'DOT-EUR'
        assert trades[0]['side'] == 'BUY'
        assert trades[0]['status'] == 'ACTIVE'
        assert trades[0]['entry_price'] == 10.0
        assert trades[0]['amount'] == 5.0
        assert trades[0]['fees'] == 0.125

    def test_record_buy_logs_transaction(self, wallet):
        """Test that buy is logged in transactions"""
        wallet.record_buy(market='MATIC-EUR', price=0.8, amount=50.0, fee=0.10)

        conn = wallet._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE transaction_type = 'BUY' ORDER BY id DESC LIMIT 1")
        transaction = cursor.fetchone()
        conn.close()

        assert transaction is not None
        assert transaction[1] == 'BUY'
        assert transaction[2] == pytest.approx(-(0.8 * 50.0 + 0.10), rel=1e-2)


class TestSellOrders:
    """Test sell order execution"""

    def test_record_sell_success(self, wallet_with_position):
        """Test successful sell order"""
        success, message = wallet_with_position.record_sell(
            market='BTC-EUR',
            price=110.0,
            amount=1.0,
            fee=0.275
        )

        assert success is True
        assert "successful" in message.lower()

        # Verify position was closed
        positions = wallet_with_position.get_active_positions()
        assert len(positions) == 0

    def test_record_sell_no_position(self, wallet):
        """Test sell fails when no position exists"""
        success, message = wallet.record_sell(
            market='BTC-EUR',
            price=110.0,
            amount=1.0,
            fee=0.0
        )

        assert success is False
        assert "no active position" in message.lower()

    def test_record_sell_insufficient_amount(self, wallet_with_position):
        """Test sell fails when trying to sell more than owned"""
        success, message = wallet_with_position.record_sell(
            market='BTC-EUR',
            price=110.0,
            amount=2.0,  # Only own 1.0
            fee=0.0
        )

        assert success is False
        assert "trying to sell" in message.lower()

    def test_record_sell_full_position(self, wallet_with_position):
        """Test selling entire position"""
        wallet_with_position.record_sell(
            market='BTC-EUR',
            price=120.0,
            amount=None,  # Sell all
            fee=0.30
        )

        # Position should be completely closed
        positions = wallet_with_position.get_active_positions()
        assert len(positions) == 0

    def test_record_sell_partial_position(self, temp_db):
        """Test selling partial position"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=1000.0)
        wallet.record_buy(market='ETH-EUR', price=100.0, amount=2.0, fee=0.50)

        # Sell half
        wallet.record_sell(market='ETH-EUR', price=110.0, amount=1.0, fee=0.275)

        # Position should still exist with remaining amount
        positions = wallet.get_active_positions()
        assert len(positions) == 1
        assert positions[0]['amount'] == 1.0

    def test_record_sell_with_profit(self, wallet_with_position):
        """Test sell with profit calculates P/L correctly"""
        success, message = wallet_with_position.record_sell(
            market='BTC-EUR',
            price=120.0,
            amount=1.0,
            fee=0.30
        )

        assert success is True

        # Check trade record
        trades = wallet_with_position.get_trade_history(limit=1)
        trade = trades[0]

        # Profit = (120 - 100) * 1.0 - (0.25 + 0.30) = 19.45
        assert trade['profit_loss'] == pytest.approx(19.45, rel=1e-2)
        assert trade['profit_loss_pct'] == pytest.approx(19.45, rel=1e-1)

    def test_record_sell_with_loss(self, wallet_with_position):
        """Test sell with loss calculates P/L correctly"""
        wallet_with_position.record_sell(
            market='BTC-EUR',
            price=90.0,
            amount=1.0,
            fee=0.225
        )

        # Check trade record
        trades = wallet_with_position.get_trade_history(limit=1)
        trade = trades[0]

        # Loss = (90 - 100) * 1.0 - (0.25 + 0.225) = -10.475
        assert trade['profit_loss'] == pytest.approx(-10.475, rel=1e-2)
        assert trade['profit_loss_pct'] < 0

    def test_record_sell_updates_trade_status(self, wallet_with_position):
        """Test that sell updates trade status to CLOSED"""
        wallet_with_position.record_sell(
            market='BTC-EUR',
            price=105.0,
            amount=1.0,
            fee=0.2625
        )

        trades = wallet_with_position.get_trade_history(limit=1)
        assert trades[0]['status'] == 'CLOSED'
        assert trades[0]['exit_price'] == 105.0

    def test_record_sell_logs_transaction(self, wallet_with_position):
        """Test that sell is logged in transactions"""
        wallet_with_position.record_sell(
            market='BTC-EUR',
            price=110.0,
            amount=1.0,
            fee=0.275
        )

        conn = wallet_with_position._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE transaction_type = 'SELL' ORDER BY id DESC LIMIT 1")
        transaction = cursor.fetchone()
        conn.close()

        assert transaction is not None
        assert transaction[1] == 'SELL'


class TestPositionTracking:
    """Test position tracking functionality"""

    def test_get_active_positions_empty(self, wallet):
        """Test getting active positions when none exist"""
        positions = wallet.get_active_positions()
        assert positions == []

    def test_get_active_positions_single(self, wallet_with_position):
        """Test getting single active position"""
        positions = wallet_with_position.get_active_positions()

        assert len(positions) == 1
        assert positions[0]['market'] == 'BTC-EUR'
        assert positions[0]['amount'] == 1.0
        assert positions[0]['entry_price'] == 100.0
        assert positions[0]['entry_value'] == 100.0

    def test_get_active_positions_multiple(self, wallet):
        """Test getting multiple active positions"""
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.25)
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.25)
        wallet.record_buy(market='ADA-EUR', price=1.0, amount=100.0, fee=0.25)

        positions = wallet.get_active_positions()
        assert len(positions) == 3

        markets = [pos['market'] for pos in positions]
        assert 'BTC-EUR' in markets
        assert 'ETH-EUR' in markets
        assert 'ADA-EUR' in markets

    def test_get_active_positions_excludes_closed(self, wallet_with_position):
        """Test that closed positions are not included"""
        # Close the position
        wallet_with_position.record_sell(market='BTC-EUR', price=110.0, fee=0.0)

        positions = wallet_with_position.get_active_positions()
        assert len(positions) == 0

    def test_get_position_summary(self, temp_db):
        """Test getting position summary with P/L"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=1000.0)
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.0)

        current_prices = {
            'BTC-EUR': 120.0,  # +20% profit
            'ETH-EUR': 45.0    # -10% loss
        }

        summary = wallet.get_position_summary(current_prices)

        assert summary['position_count'] == 2
        assert summary['total_entry_value'] == 200.0  # 100 + 100
        assert summary['total_current_value'] == 210.0  # 120 + 90
        assert summary['total_unrealized_pl'] == 10.0

        # Check individual positions
        btc_pos = next(p for p in summary['positions'] if p['market'] == 'BTC-EUR')
        assert btc_pos['unrealized_pl'] == 20.0
        assert btc_pos['unrealized_pl_pct'] == pytest.approx(20.0, rel=1e-1)

        eth_pos = next(p for p in summary['positions'] if p['market'] == 'ETH-EUR')
        assert eth_pos['unrealized_pl'] == -10.0
        assert eth_pos['unrealized_pl_pct'] == pytest.approx(-10.0, rel=1e-1)

    def test_get_position_summary_empty(self, wallet):
        """Test position summary with no positions"""
        summary = wallet.get_position_summary({})

        assert summary['position_count'] == 0
        assert summary['total_entry_value'] == 0.0
        assert summary['total_current_value'] == 0.0
        assert summary['total_unrealized_pl'] == 0.0


class TestProfitLossCalculations:
    """Test profit/loss calculation accuracy"""

    def test_get_total_profit_loss_no_trades(self, wallet):
        """Test total P/L with no closed trades"""
        total_pl = wallet.get_total_profit_loss()
        assert total_pl == 0.0

    def test_get_total_profit_loss_with_profit(self, wallet):
        """Test total P/L with profitable trade"""
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.25)
        wallet.record_sell(market='BTC-EUR', price=120.0, amount=1.0, fee=0.30)

        total_pl = wallet.get_total_profit_loss()
        # Profit = (120 - 100) * 1.0 - 0.25 - 0.30 = 19.45
        assert total_pl == pytest.approx(19.45, rel=1e-2)

    def test_get_total_profit_loss_with_loss(self, wallet):
        """Test total P/L with losing trade"""
        wallet.record_buy(market='ETH-EUR', price=100.0, amount=1.0, fee=0.25)
        wallet.record_sell(market='ETH-EUR', price=90.0, amount=1.0, fee=0.225)

        total_pl = wallet.get_total_profit_loss()
        # Loss = (90 - 100) * 1.0 - 0.25 - 0.225 = -10.475
        assert total_pl == pytest.approx(-10.475, rel=1e-2)

    def test_get_total_profit_loss_multiple_trades(self, wallet):
        """Test total P/L with multiple trades"""
        # Trade 1: Profit
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.25)
        wallet.record_sell(market='BTC-EUR', price=120.0, amount=1.0, fee=0.30)

        # Trade 2: Loss
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.25)
        wallet.record_sell(market='ETH-EUR', price=45.0, amount=2.0, fee=0.225)

        total_pl = wallet.get_total_profit_loss()
        # Trade 1: +19.45, Trade 2: -10.475
        assert total_pl == pytest.approx(8.975, rel=1e-2)

    def test_get_total_profit_loss_excludes_active(self, wallet_with_position):
        """Test that active positions are excluded from total P/L"""
        total_pl = wallet_with_position.get_total_profit_loss()
        assert total_pl == 0.0  # Position is active, not closed

    def test_profit_loss_percentage_calculation(self, wallet):
        """Test P/L percentage calculation"""
        wallet.record_buy(market='ADA-EUR', price=1.0, amount=100.0, fee=0.0)
        wallet.record_sell(market='ADA-EUR', price=1.5, amount=100.0, fee=0.0)

        trades = wallet.get_trade_history(limit=1)
        trade = trades[0]

        # 50% profit
        assert trade['profit_loss'] == 50.0
        assert trade['profit_loss_pct'] == pytest.approx(50.0, rel=1e-1)


class TestFeeCalculations:
    """Test trading fee calculations"""

    def test_get_total_costs_active_positions(self, wallet_with_position):
        """Test getting total costs from active positions"""
        total_costs = wallet_with_position.get_total_costs()
        assert total_costs == 0.25  # Buy fee from active position

    def test_get_total_costs_no_active(self, wallet):
        """Test total costs with no active positions"""
        total_costs = wallet.get_total_costs()
        assert total_costs == 0.0

    def test_get_total_costs_excludes_closed(self, wallet):
        """Test that closed trade fees are excluded"""
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.25)
        wallet.record_sell(market='BTC-EUR', price=110.0, amount=1.0, fee=0.275)

        # Fees from closed trades should not be counted
        # (they're already included in realized P/L)
        total_costs = wallet.get_total_costs()
        assert total_costs == 0.0

    def test_fee_included_in_profit_calculation(self, wallet):
        """Test that fees are properly included in profit calculation"""
        wallet.record_buy(market='XRP-EUR', price=1.0, amount=100.0, fee=0.25)
        wallet.record_sell(market='XRP-EUR', price=1.1, amount=100.0, fee=0.275)

        trades = wallet.get_trade_history(limit=1)
        trade = trades[0]

        # Profit = (1.1 - 1.0) * 100 - (0.25 + 0.275) = 9.475
        assert trade['profit_loss'] == pytest.approx(9.475, rel=1e-2)


class TestTradeHistory:
    """Test trade history functionality"""

    def test_get_trade_history_empty(self, wallet):
        """Test getting history when no trades exist"""
        history = wallet.get_trade_history()
        assert history == []

    def test_get_trade_history_single_trade(self, wallet_with_position):
        """Test getting history with single trade"""
        history = wallet_with_position.get_trade_history()

        assert len(history) == 1
        assert history[0]['market'] == 'BTC-EUR'
        assert history[0]['status'] == 'ACTIVE'

    def test_get_trade_history_with_limit(self, wallet):
        """Test getting history with limit"""
        # Create 5 trades
        for i in range(5):
            market = f'TEST{i}-EUR'
            wallet.record_buy(market=market, price=10.0, amount=1.0, fee=0.0)
            wallet.record_sell(market=market, price=11.0, amount=1.0, fee=0.0)

        history = wallet.get_trade_history(limit=3)
        assert len(history) == 3

    def test_get_trade_history_ordered_by_time(self, wallet):
        """Test that history is ordered by entry time (newest first)"""
        wallet.record_buy(market='FIRST-EUR', price=10.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='FIRST-EUR', price=11.0, fee=0.0)

        wallet.record_buy(market='SECOND-EUR', price=20.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='SECOND-EUR', price=22.0, fee=0.0)

        history = wallet.get_trade_history()
        assert history[0]['market'] == 'SECOND-EUR'
        assert history[1]['market'] == 'FIRST-EUR'

    def test_get_trade_history_includes_all_fields(self, wallet):
        """Test that history includes all required fields"""
        wallet.record_buy(market='DOT-EUR', price=10.0, amount=5.0, fee=0.125)
        wallet.record_sell(market='DOT-EUR', price=12.0, amount=5.0, fee=0.15)

        history = wallet.get_trade_history()
        trade = history[0]

        required_fields = [
            'market', 'side', 'entry_price', 'exit_price', 'amount',
            'entry_time', 'exit_time', 'status', 'profit_loss',
            'profit_loss_pct', 'entry_value', 'exit_value', 'fees'
        ]

        for field in required_fields:
            assert field in trade


class TestStatistics:
    """Test trading statistics"""

    def test_get_statistics_initial_state(self, wallet):
        """Test statistics with no trades"""
        stats = wallet.get_statistics()

        assert stats['balance'] == 1000.0
        assert stats['initial_balance'] == 1000.0
        assert stats['total_return'] == 0.0
        assert stats['total_return_pct'] == 0.0
        assert stats['total_trades'] == 0
        assert stats['winning_trades'] == 0
        assert stats['losing_trades'] == 0
        assert stats['win_rate'] == 0.0

    def test_get_statistics_with_trades(self, wallet):
        """Test statistics with multiple trades"""
        # Winning trade
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='BTC-EUR', price=120.0, amount=1.0, fee=0.0)

        # Losing trade
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.0)
        wallet.record_sell(market='ETH-EUR', price=45.0, amount=2.0, fee=0.0)

        stats = wallet.get_statistics()

        assert stats['total_trades'] == 2
        assert stats['winning_trades'] == 1
        assert stats['losing_trades'] == 1
        assert stats['win_rate'] == 50.0

    def test_get_statistics_win_rate_calculation(self, wallet):
        """Test win rate calculation"""
        # 3 wins
        for _ in range(3):
            wallet.record_buy(market='WIN-EUR', price=10.0, amount=1.0, fee=0.0)
            wallet.record_sell(market='WIN-EUR', price=12.0, amount=1.0, fee=0.0)

        # 1 loss
        wallet.record_buy(market='LOSS-EUR', price=10.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='LOSS-EUR', price=8.0, amount=1.0, fee=0.0)

        stats = wallet.get_statistics()
        assert stats['win_rate'] == 75.0

    def test_get_statistics_return_calculation(self, wallet):
        """Test return calculation in statistics"""
        # Make some profitable trades
        wallet.record_buy(market='PROFIT-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='PROFIT-EUR', price=150.0, amount=1.0, fee=0.0)

        stats = wallet.get_statistics()

        # Started with 1000, gained 50
        assert stats['total_return'] == 50.0
        assert stats['total_return_pct'] == 5.0

    def test_get_statistics_max_profit_loss(self, wallet):
        """Test max profit and loss tracking"""
        # Best trade: +30
        wallet.record_buy(market='BEST-EUR', price=10.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='BEST-EUR', price=40.0, amount=1.0, fee=0.0)

        # Worst trade: -5
        wallet.record_buy(market='WORST-EUR', price=10.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='WORST-EUR', price=5.0, amount=1.0, fee=0.0)

        stats = wallet.get_statistics()
        assert stats['max_profit'] == 30.0
        assert stats['max_loss'] == -5.0


class TestWalletReset:
    """Test wallet reset functionality"""

    def test_reset_wallet_clears_trades(self, wallet):
        """Test that reset clears all trades"""
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='BTC-EUR', price=110.0, amount=1.0, fee=0.0)

        wallet.reset_wallet()

        trades = wallet.get_trade_history()
        assert len(trades) == 0

    def test_reset_wallet_clears_positions(self, wallet_with_position):
        """Test that reset clears all positions"""
        wallet_with_position.reset_wallet()

        positions = wallet_with_position.get_active_positions()
        assert len(positions) == 0

    def test_reset_wallet_resets_balance(self, wallet):
        """Test that reset resets balance"""
        # Make some trades to change balance
        wallet.record_buy(market='TEST-EUR', price=100.0, amount=1.0, fee=0.0)

        wallet.reset_wallet()

        balance = wallet.get_balance()
        initial_balance = wallet.get_initial_balance()

        assert balance == initial_balance

    def test_reset_wallet_with_new_balance(self, wallet):
        """Test reset with new starting balance"""
        wallet.reset_wallet(new_balance=2000.0)

        balance = wallet.get_balance()
        initial_balance = wallet.get_initial_balance()

        assert balance == 2000.0
        assert initial_balance == 2000.0

    def test_reset_wallet_logs_transaction(self, wallet):
        """Test that reset is logged in transactions"""
        wallet.reset_wallet()

        conn = wallet._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE transaction_type = 'RESET' ORDER BY id DESC LIMIT 1")
        transaction = cursor.fetchone()
        conn.close()

        assert transaction is not None


class TestConcurrentPositions:
    """Test handling of multiple concurrent positions"""

    def test_multiple_positions_different_markets(self, wallet):
        """Test holding positions in multiple markets simultaneously"""
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.0)
        wallet.record_buy(market='ADA-EUR', price=1.0, amount=100.0, fee=0.0)

        positions = wallet.get_active_positions()
        assert len(positions) == 3

    def test_close_one_position_keeps_others(self, wallet):
        """Test that closing one position doesn't affect others"""
        wallet.record_buy(market='BTC-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_buy(market='ETH-EUR', price=50.0, amount=2.0, fee=0.0)

        # Close first position
        wallet.record_sell(market='BTC-EUR', price=110.0, fee=0.0)

        positions = wallet.get_active_positions()
        assert len(positions) == 1
        assert positions[0]['market'] == 'ETH-EUR'

    def test_independent_profit_loss_tracking(self, wallet):
        """Test that P/L is tracked independently per position"""
        wallet.record_buy(market='WIN-EUR', price=10.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='WIN-EUR', price=15.0, amount=1.0, fee=0.0)

        wallet.record_buy(market='LOSS-EUR', price=10.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='LOSS-EUR', price=8.0, amount=1.0, fee=0.0)

        history = wallet.get_trade_history()
        win_trade = next(t for t in history if t['market'] == 'WIN-EUR')
        loss_trade = next(t for t in history if t['market'] == 'LOSS-EUR')

        assert win_trade['profit_loss'] == 5.0
        assert loss_trade['profit_loss'] == -2.0


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_very_small_amounts(self, wallet):
        """Test handling of very small trade amounts"""
        success, _ = wallet.record_buy(
            market='BTC-EUR',
            price=50000.0,
            amount=0.00001,  # Very small amount
            fee=0.0
        )

        assert success is True
        balance = wallet.get_balance()
        assert balance == pytest.approx(999.5, rel=1e-2)

    def test_very_large_amounts(self, temp_db):
        """Test handling of very large trade amounts"""
        wallet = VirtualWallet(db_path=temp_db, initial_balance=1000000.0)

        success, _ = wallet.record_buy(
            market='MICRO-EUR',
            price=0.00001,
            amount=10000000.0,  # Very large amount
            fee=0.0
        )

        assert success is True

    def test_exact_balance_purchase(self, wallet):
        """Test purchasing with exact balance"""
        balance = wallet.get_balance()

        success, _ = wallet.record_buy(
            market='ALL-IN-EUR',
            price=10.0,
            amount=100.0,  # Exactly 1000
            fee=0.0
        )

        assert success is True
        assert wallet.get_balance() == 0.0

    def test_zero_price(self, wallet):
        """Test handling of zero price (should work but unusual)"""
        success, _ = wallet.record_buy(
            market='FREE-EUR',
            price=0.0,
            amount=1000.0,
            fee=0.0
        )

        assert success is True
        assert wallet.get_balance() == 1000.0

    def test_negative_profit_loss(self, wallet):
        """Test that negative P/L is correctly tracked"""
        wallet.record_buy(market='LOSS-EUR', price=100.0, amount=1.0, fee=0.0)
        wallet.record_sell(market='LOSS-EUR', price=50.0, amount=1.0, fee=0.0)

        trades = wallet.get_trade_history(limit=1)
        assert trades[0]['profit_loss'] < 0
        assert trades[0]['profit_loss_pct'] < 0
