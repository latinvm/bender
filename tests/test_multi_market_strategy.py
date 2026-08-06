import pytest
import threading
from unittest.mock import Mock, patch, MagicMock, call
import pandas as pd
from datetime import datetime
from trader.multi_market_strategy import MultiMarketStrategy
from trader.enhanced_strategy import EnhancedStrategy


@pytest.fixture
def mock_market_ops():
    """Fixture for mocked MarketOperations"""
    mock = Mock()
    mock.client = Mock()
    mock.client.bitvavo = Mock()

    # Mock candles data
    mock.client.bitvavo.candles.return_value = [
        [1640000000000, '100.0', '110.0', '95.0', '105.0', '1000.0']
        for _ in range(100)
    ]

    # Mock ticker price
    mock.get_ticker.return_value = {'price': '100.00'}

    # Mock place order
    mock.place_market_order.return_value = {'orderId': '12345', 'status': 'filled'}

    return mock


@pytest.fixture
def mock_trade_db():
    """Fixture for mocked TradeDatabase"""
    mock = Mock()
    mock.get_active_positions.return_value = []
    return mock


@pytest.fixture
def mock_virtual_wallet():
    """Fixture for mocked VirtualWallet"""
    mock = Mock()
    mock.get_active_positions.return_value = []
    mock.record_buy.return_value = (True, "Success")
    mock.record_sell.return_value = (True, "Success")
    return mock


@pytest.fixture
def sample_markets():
    """Sample list of markets"""
    return ['BTC-EUR', 'ETH-EUR', 'ADA-EUR']


class TestMultiMarketStrategyInitialization:
    """Test MultiMarketStrategy initialization"""

    @patch('trader.database.TradeDatabase')
    def test_init_basic(self, mock_db_class, mock_market_ops, sample_markets):
        """Test basic initialization with default parameters"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        assert strategy.markets == sample_markets
        assert strategy.investment_per_market == 10.0
        assert strategy.max_positions == 3
        assert strategy.stop_loss_pct == 5.0
        assert strategy.take_profit_pct == 15.0
        assert len(strategy.strategies) == 3

    @patch('trader.database.TradeDatabase')
    def test_init_custom_parameters(self, mock_db_class, mock_market_ops, sample_markets):
        """Test initialization with custom parameters"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=20.0,
            max_positions=5,
            stop_loss_pct=10.0,
            take_profit_pct=25.0
        )

        assert strategy.investment_per_market == 20.0
        assert strategy.max_positions == 5
        assert strategy.stop_loss_pct == 10.0
        assert strategy.take_profit_pct == 25.0

    @patch('trader.database.TradeDatabase')
    def test_init_creates_strategy_instances(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that strategy instances are created for each market"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Check that strategies are created for all markets
        assert len(strategy.strategies) == len(sample_markets)
        for market in sample_markets:
            assert market in strategy.strategies
            assert isinstance(strategy.strategies[market], EnhancedStrategy)

    @patch('trader.database.TradeDatabase')
    def test_init_with_virtual_wallet(self, mock_db_class, mock_market_ops, mock_virtual_wallet, sample_markets):
        """Test initialization with virtual wallet"""
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0,
            virtual_wallet=mock_virtual_wallet
        )

        assert strategy.virtual_wallet == mock_virtual_wallet
        # Should call virtual wallet, not database
        mock_virtual_wallet.get_active_positions.assert_called()

    @patch('trader.database.TradeDatabase')
    def test_init_empty_markets_list(self, mock_db_class, mock_market_ops):
        """Test initialization with empty markets list"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=[],
            investment_per_market=10.0
        )

        assert strategy.markets == []
        assert len(strategy.strategies) == 0


class TestOrphanedPositionDetection:
    """Test detection and handling of orphaned positions"""

    @patch('trader.database.TradeDatabase')
    def test_orphaned_position_detection_adds_market(self, mock_db_class, mock_market_ops):
        """Test that orphaned positions are detected and their markets added"""
        mock_db = Mock()
        # Simulate orphaned position in market not in the markets list
        mock_db.get_active_positions.return_value = [
            {
                'market': 'ORPHAN-EUR',
                'amount': 100.0,
                'entry_price': 1.0
            }
        ]
        mock_db_class.return_value = mock_db

        markets = ['BTC-EUR', 'ETH-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0
        )

        # Orphaned market should be added
        assert 'ORPHAN-EUR' in strategy.markets
        assert 'ORPHAN-EUR' in strategy.strategies
        assert len(strategy.markets) == 3  # Original 2 + 1 orphaned

    @patch('trader.database.TradeDatabase')
    def test_orphaned_position_detection_multiple(self, mock_db_class, mock_market_ops):
        """Test detection of multiple orphaned positions"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = [
            {'market': 'ORPHAN1-EUR', 'amount': 100.0, 'entry_price': 1.0},
            {'market': 'ORPHAN2-EUR', 'amount': 50.0, 'entry_price': 2.0},
            {'market': 'BTC-EUR', 'amount': 0.1, 'entry_price': 30000.0}  # Not orphaned
        ]
        mock_db_class.return_value = mock_db

        markets = ['BTC-EUR', 'ETH-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0
        )

        # Two orphaned markets should be added
        assert 'ORPHAN1-EUR' in strategy.markets
        assert 'ORPHAN2-EUR' in strategy.markets
        assert len(strategy.markets) == 4  # Original 2 + 2 orphaned

    @patch('trader.database.TradeDatabase')
    def test_no_orphaned_positions(self, mock_db_class, mock_market_ops):
        """Test when there are no orphaned positions"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = [
            {'market': 'BTC-EUR', 'amount': 0.1, 'entry_price': 30000.0}
        ]
        mock_db_class.return_value = mock_db

        markets = ['BTC-EUR', 'ETH-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0
        )

        # No orphaned markets, list should be unchanged
        assert len(strategy.markets) == 2
        assert strategy.markets == ['BTC-EUR', 'ETH-EUR']

    def test_orphaned_position_detection_with_virtual_wallet(self, mock_market_ops, mock_virtual_wallet):
        """Test orphaned position detection with virtual wallet"""
        mock_virtual_wallet.get_active_positions.return_value = [
            {'market': 'ORPHAN-EUR', 'amount': 100.0, 'entry_price': 1.0}
        ]

        markets = ['BTC-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0,
            virtual_wallet=mock_virtual_wallet
        )

        # Orphaned market should be added
        assert 'ORPHAN-EUR' in strategy.markets
        assert len(strategy.markets) == 2


class TestPositionLimitEnforcement:
    """Test portfolio-wide position limit enforcement"""

    @patch('trader.database.TradeDatabase')
    def test_position_limit_passed_to_strategies(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that position limit is passed to all strategies"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0,
            max_positions=5
        )

        # All strategies should have the same max_positions
        for market_strategy in strategy.strategies.values():
            assert market_strategy.max_positions == 5

    @patch('trader.database.TradeDatabase')
    def test_default_position_limit(self, mock_db_class, mock_market_ops, sample_markets):
        """Test default position limit of 3"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        assert strategy.max_positions == 3
        for market_strategy in strategy.strategies.values():
            assert market_strategy.max_positions == 3


class TestStrategyInstanceCreation:
    """Test strategy instance creation for each market"""

    @patch('trader.database.TradeDatabase')
    def test_strategy_instances_have_correct_markets(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that each strategy instance is assigned the correct market"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        for market in sample_markets:
            assert strategy.strategies[market].market == market

    @patch('trader.database.TradeDatabase')
    def test_strategy_instances_share_market_ops(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that all strategy instances share the same market_ops"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        for market_strategy in strategy.strategies.values():
            assert market_strategy.market_ops is mock_market_ops

    @patch('trader.database.TradeDatabase')
    def test_strategy_instances_have_same_investment_amount(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that all strategies have the same investment amount"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=15.0
        )

        for market_strategy in strategy.strategies.values():
            assert market_strategy.investment_amount == 15.0

    @patch('trader.database.TradeDatabase')
    def test_strategy_instances_have_custom_stop_loss_take_profit(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that custom stop-loss and take-profit are passed to strategies"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0,
            stop_loss_pct=8.0,
            take_profit_pct=20.0
        )

        for market_strategy in strategy.strategies.values():
            assert market_strategy.stop_loss_pct == 8.0
            assert market_strategy.take_profit_pct == 20.0


class TestExecuteAllTrades:
    """Test executing trades across all markets"""

    @patch('trader.database.TradeDatabase')
    def test_execute_all_trades_calls_all_strategies(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that execute_all_trades calls execute_trade for all strategies"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Mock execute_trade for all strategies
        for market in sample_markets:
            strategy.strategies[market].execute_trade = Mock()

        strategy.execute_all_trades()

        # Verify execute_trade was called for each market
        for market in sample_markets:
            strategy.strategies[market].execute_trade.assert_called_once()

    @patch('trader.database.TradeDatabase')
    def test_execute_all_trades_handles_exceptions(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that exceptions in one market don't stop others"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Make one strategy fail
        strategy.strategies['BTC-EUR'].execute_trade = Mock(side_effect=Exception("API Error"))
        strategy.strategies['ETH-EUR'].execute_trade = Mock()
        strategy.strategies['ADA-EUR'].execute_trade = Mock()

        # Should not raise exception
        strategy.execute_all_trades()

        # Other strategies should still be called
        strategy.strategies['ETH-EUR'].execute_trade.assert_called_once()
        strategy.strategies['ADA-EUR'].execute_trade.assert_called_once()

    @patch('trader.database.TradeDatabase')
    def test_execute_all_trades_empty_markets(self, mock_db_class, mock_market_ops):
        """Test execute_all_trades with no markets"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=[],
            investment_per_market=10.0
        )

        # Should not raise exception
        strategy.execute_all_trades()


class TestPriceCaching:
    """Test price caching across multiple markets"""

    @patch('trader.database.TradeDatabase')
    def test_get_current_prices_all_markets(self, mock_db_class, mock_market_ops, sample_markets):
        """Test getting current prices for all markets"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Mock get_current_price for all strategies
        strategy.strategies['BTC-EUR'].get_current_price = Mock(return_value=100.0)
        strategy.strategies['ETH-EUR'].get_current_price = Mock(return_value=50.0)
        strategy.strategies['ADA-EUR'].get_current_price = Mock(return_value=1.0)

        prices = strategy.get_current_prices()

        assert prices == {
            'BTC-EUR': 100.0,
            'ETH-EUR': 50.0,
            'ADA-EUR': 1.0
        }

    @patch('trader.database.TradeDatabase')
    def test_get_current_prices_with_cache(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that cache parameter is passed to strategies"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Mock get_current_price
        for market in sample_markets:
            strategy.strategies[market].get_current_price = Mock(return_value=100.0)

        strategy.get_current_prices(use_cache=True, cache_max_age=60.0)

        # Verify cache parameters were passed
        for market in sample_markets:
            strategy.strategies[market].get_current_price.assert_called_with(
                use_cache=True,
                cache_max_age=60.0
            )

    @patch('trader.database.TradeDatabase')
    def test_get_current_prices_excludes_none_values(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that None prices are excluded from results"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Make one return None (API error)
        strategy.strategies['BTC-EUR'].get_current_price = Mock(return_value=100.0)
        strategy.strategies['ETH-EUR'].get_current_price = Mock(return_value=None)
        strategy.strategies['ADA-EUR'].get_current_price = Mock(return_value=1.0)

        prices = strategy.get_current_prices()

        # ETH should be excluded
        assert 'ETH-EUR' not in prices
        assert prices == {
            'BTC-EUR': 100.0,
            'ADA-EUR': 1.0
        }


class TestPortfolioSummary:
    """Test portfolio summary functionality"""

    @patch('trader.enhanced_strategy.TradeDatabase')
    @patch('trader.database.TradeDatabase')
    def test_get_portfolio_summary_no_positions(self, mock_db_class, mock_es_db_class, mock_market_ops, sample_markets):
        """Test portfolio summary with no active positions"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db
        mock_es_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        summary = strategy.get_portfolio_summary()

        assert summary['total_markets'] == 3
        assert summary['active_positions'] == 0
        assert summary['active_markets'] == []
        assert summary['max_capital'] == 30.0  # 10 * 3

    @patch('trader.enhanced_strategy.TradeDatabase')
    @patch('trader.database.TradeDatabase')
    def test_get_portfolio_summary_with_positions(self, mock_db_class, mock_es_db_class, mock_market_ops, sample_markets):
        """Test portfolio summary with active positions"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db
        mock_es_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Simulate positions
        strategy.strategies['BTC-EUR'].positions = {'BTC-EUR': 0.1}
        strategy.strategies['ETH-EUR'].positions = {'ETH-EUR': 1.0}
        strategy.strategies['ADA-EUR'].positions = {}

        summary = strategy.get_portfolio_summary()

        assert summary['total_markets'] == 3
        assert summary['active_positions'] == 2
        assert 'BTC-EUR' in summary['active_markets']
        assert 'ETH-EUR' in summary['active_markets']
        assert 'ADA-EUR' not in summary['active_markets']

    @patch('trader.enhanced_strategy.TradeDatabase')
    @patch('trader.database.TradeDatabase')
    def test_get_portfolio_summary_max_capital_calculation(self, mock_db_class, mock_es_db_class, mock_market_ops):
        """Test max capital calculation in portfolio summary"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db
        mock_es_db_class.return_value = mock_db

        markets = ['BTC-EUR', 'ETH-EUR', 'ADA-EUR', 'DOT-EUR', 'XRP-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=15.0
        )

        summary = strategy.get_portfolio_summary()

        # 5 markets * 15 EUR = 75 EUR
        assert summary['max_capital'] == 75.0


class TestRunLoop:
    """Test the main run loop"""

    @patch('trader.database.TradeDatabase')
    def test_run_executes_trades_periodically(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that run loop executes trades and stops via stop_event"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Stop the loop after the first trade cycle
        stop = threading.Event()
        strategy.execute_all_trades = Mock(side_effect=lambda: stop.set())

        strategy.run(interval=60, stop_event=stop)

        # Should have called execute_all_trades exactly once before stopping
        strategy.execute_all_trades.assert_called_once()

    @patch('trader.database.TradeDatabase')
    def test_run_uses_custom_interval(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that custom interval is passed to the stop event wait"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        strategy.execute_all_trades = Mock()

        stop = threading.Event()
        wait_calls = []

        def fake_wait(timeout=None):
            wait_calls.append(timeout)
            stop.set()
            return True

        stop.wait = fake_wait
        strategy.run(interval=120, stop_event=stop)

        # The loop should have waited with the custom interval
        assert wait_calls == [120]

    @patch('trader.database.TradeDatabase')
    def test_run_handles_keyboard_interrupt(self, mock_db_class, mock_market_ops, sample_markets):
        """Test that run handles KeyboardInterrupt gracefully"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10.0
        )

        # Make execute_all_trades raise KeyboardInterrupt
        strategy.execute_all_trades = Mock(side_effect=KeyboardInterrupt())

        # Should not raise exception
        strategy.run()


class TestIntegration:
    """Integration tests for multi-market strategy"""

    @patch('trader.database.TradeDatabase')
    def test_full_workflow_no_virtual_wallet(self, mock_db_class, mock_market_ops):
        """Test complete workflow without virtual wallet"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        markets = ['BTC-EUR', 'ETH-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0,
            max_positions=3
        )

        # Execute trades
        strategy.execute_all_trades()

        # Get prices
        prices = strategy.get_current_prices()
        assert len(prices) <= len(markets)

        # Get summary
        summary = strategy.get_portfolio_summary()
        assert summary['total_markets'] == 2

    def test_full_workflow_with_virtual_wallet(self, mock_market_ops, mock_virtual_wallet):
        """Test complete workflow with virtual wallet"""
        mock_virtual_wallet.get_active_positions.return_value = []

        markets = ['BTC-EUR', 'ETH-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0,
            virtual_wallet=mock_virtual_wallet
        )

        # Execute trades
        strategy.execute_all_trades()

        # Get prices
        prices = strategy.get_current_prices()
        assert len(prices) <= len(markets)

        # Get summary
        summary = strategy.get_portfolio_summary()
        assert summary['total_markets'] == 2

    @patch('trader.database.TradeDatabase')
    def test_workflow_with_orphaned_positions(self, mock_db_class, mock_market_ops):
        """Test workflow when orphaned positions exist"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = [
            {'market': 'OLD-EUR', 'amount': 100.0, 'entry_price': 1.0}
        ]
        mock_db_class.return_value = mock_db

        markets = ['BTC-EUR', 'ETH-EUR']
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0
        )

        # Orphaned market should be included
        assert 'OLD-EUR' in strategy.markets
        assert 'OLD-EUR' in strategy.strategies

        # Execute trades should handle all markets
        strategy.execute_all_trades()

        summary = strategy.get_portfolio_summary()
        assert summary['total_markets'] == 3


class TestEdgeCases:
    """Test edge cases and error handling"""

    @patch('trader.database.TradeDatabase')
    def test_single_market(self, mock_db_class, mock_market_ops):
        """Test with only a single market"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=['BTC-EUR'],
            investment_per_market=10.0
        )

        assert len(strategy.markets) == 1
        assert len(strategy.strategies) == 1

    @patch('trader.database.TradeDatabase')
    def test_many_markets(self, mock_db_class, mock_market_ops):
        """Test with many markets"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        markets = [f'COIN{i}-EUR' for i in range(10)]
        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0
        )

        assert len(strategy.markets) == 10
        assert len(strategy.strategies) == 10

    @patch('trader.database.TradeDatabase')
    def test_duplicate_markets_in_list(self, mock_db_class, mock_market_ops):
        """Test handling of duplicate markets in input list"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        # Input has duplicates
        markets = ['BTC-EUR', 'ETH-EUR', 'BTC-EUR']

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=markets,
            investment_per_market=10.0
        )

        # Should create strategies for all provided markets (including duplicates)
        # Note: This might be a bug in the actual implementation
        assert 'BTC-EUR' in strategy.strategies
        assert 'ETH-EUR' in strategy.strategies

    @patch('trader.database.TradeDatabase')
    def test_very_small_investment(self, mock_db_class, mock_market_ops, sample_markets):
        """Test with very small investment amount"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=0.01  # Very small
        )

        for market_strategy in strategy.strategies.values():
            assert market_strategy.investment_amount == 0.01

    @patch('trader.database.TradeDatabase')
    def test_very_large_investment(self, mock_db_class, mock_market_ops, sample_markets):
        """Test with very large investment amount"""
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db_class.return_value = mock_db

        strategy = MultiMarketStrategy(
            market_ops=mock_market_ops,
            markets=sample_markets,
            investment_per_market=10000.0  # Very large
        )

        for market_strategy in strategy.strategies.values():
            assert market_strategy.investment_amount == 10000.0
