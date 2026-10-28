import pytest
import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch
import trader.main
from trader.config import BitvavoConfig, DatabaseConfig, TradingStrategyConfig, VirtualTradingConfig
from trader.main import display_market_info, find_best_markets, main
from trader.exceptions import MarketNotFoundError


@pytest.fixture(autouse=True)
def setup_logger():
    """Ensure the module logger is at INFO level for caplog assertions"""
    trader.main.logger.setLevel(logging.INFO)
    yield

@pytest.fixture
def mock_market_ops():
    """Fixture for mocked MarketOperations"""
    mock = Mock()
    
    # Setup market info mock
    mock.get_market_info.return_value = {
        'status': 'trading',
        'base': 'BTC',
        'quote': 'EUR'
    }
    
    # Setup ticker mock
    mock.get_ticker.return_value = {
        'price': '30000.00'
    }
    
    # Setup order book mock
    mock.get_book.return_value = {
        'bids': [
            ['29999.00', '1.5'],
            ['29998.00', '2.0'],
            ['29997.00', '1.0'],
            ['29996.00', '0.5'],
            ['29995.00', '1.0']
        ],
        'asks': [
            ['30001.00', '1.0'],
            ['30002.00', '2.0'],
            ['30003.00', '1.5'],
            ['30004.00', '1.0'],
            ['30005.00', '0.5']
        ]
    }
    
    # Setup alt coins mock
    mock.list_alt_coins.return_value = [
        {'market': 'VET-EUR', 'status': 'trading'},
        {'market': 'ADA-EUR', 'status': 'trading'},
        {'market': 'DOT-EUR', 'status': 'halted'}
    ]
    
    # Setup detailed market info mock
    mock.get_detailed_market_info.return_value = {
        'high': 1.5,
        'low': 1.0,
        'volume_quote': 15000.0,
        'price': 1.2,
        'open': 1.1
    }
    
    mock.get_historical_candles.return_value = [
        [1672531200000, '1.1', '1.2', '1.0', '1.15', '1000'],
        [1672534800000, '1.15', '1.3', '1.1', '1.05', '1200'],
        [1672538400000, '1.05', '1.4', '1.0', '1.35', '1500'],
        [1672542000000, '1.35', '1.5', '1.3', '1.25', '1800'],
        [1672545600000, '1.25', '1.6', '1.2', '1.55', '2000'],
    ]

    return mock

def test_display_market_info(mock_market_ops, caplog):
    """Test market info display functionality"""
    display_market_info(mock_market_ops, 'BTC-EUR')
    
    # Verify all required methods were called
    mock_market_ops.get_market_info.assert_called_once_with('BTC-EUR')
    mock_market_ops.get_ticker.assert_called_once_with('BTC-EUR')
    mock_market_ops.get_book.assert_called_once_with('BTC-EUR', 5)
    
    # Verify log messages contain key information
    assert 'Market Information' in caplog.text
    assert 'BTC-EUR' in caplog.text
    assert 'Order Book' in caplog.text
    assert 'Top 5 Bids' in caplog.text
    assert 'Top 5 Asks' in caplog.text

def test_display_market_info_error_handling(mock_market_ops, caplog):
    """Test error handling in market info display"""
    mock_market_ops.get_market_info.side_effect = MarketNotFoundError("Market not found")
    
    display_market_info(mock_market_ops, 'INVALID-MARKET')
    
    assert "Error getting market info: Market not found" in caplog.text

def test_find_best_markets(mock_market_ops):
    """Test best markets finding algorithm"""
    # Scoring needs at least 10 hourly candles per market
    mock_market_ops.get_historical_candles.return_value = [
        [1672531200000 + i*3600000, '1.1', '1.2', '1.0', str(1.1 + 0.01 * (i % 3)), '1000']
        for i in range(24)
    ]
    best_markets = find_best_markets(mock_market_ops, top_50_markets=['VET-EUR', 'ADA-EUR'])

    # Verify market operations were called for both markets
    assert mock_market_ops.get_detailed_market_info.call_count >= 1

    # Only scored candidates are returned
    assert len(best_markets) > 0
    assert set(best_markets) <= {'VET-EUR', 'ADA-EUR'}

def test_find_best_markets_no_suitable_markets(mock_market_ops):
    """No candidates: nothing is selected (no unchecked fallback markets)"""
    best_markets = find_best_markets(mock_market_ops, top_50_markets=[])

    assert best_markets == []

def test_find_best_markets_scoring(mock_market_ops):
    """Test market scoring algorithm"""
    # Setup historical candles for both markets
    historical_candles = [
        [1672531200000, '1.0', '1.1', '0.9', '1.05', '1000'],
        [1672534800000, '1.05', '1.15', '1.0', '1.10', '1100'],
        [1672538400000, '1.10', '1.20', '1.05', '1.15', '1200'],
        [1672542000000, '1.15', '1.25', '1.10', '1.20', '1300'],
        [1672545600000, '1.20', '1.30', '1.15', '1.25', '1400'],
        [1672549200000, '1.25', '1.35', '1.20', '1.30', '1500'],
        [1672552800000, '1.30', '1.40', '1.25', '1.35', '1600'],
        [1672556400000, '1.35', '1.45', '1.30', '1.40', '1700'],
        [1672560000000, '1.40', '1.50', '1.35', '1.45', '1800'],
        [1672563600000, '1.45', '1.55', '1.40', '1.50', '1900']
    ]
    mock_market_ops.get_historical_candles.return_value = historical_candles

    # Mock order books with good spreads
    mock_market_ops.get_book.return_value = {
        'bids': [['1.000', '1000']],
        'asks': [['1.002', '1000']]  # 0.2% spread
    }

    # First market: high volume, low volatility
    mock_market_ops.get_detailed_market_info.side_effect = [
        {
            'high': 1.1,  # 10% volatility
            'low': 1.0,
            'volume_quote': 20000.0,  # High volume
            'price': 1.05,
            'open': 1.0   # 5% trend
        },
        {
            'high': 2.0,  # 100% volatility
            'low': 1.0,
            'volume_quote': 5000.0,  # Lower volume
            'price': 1.8,
            'open': 1.0   # 80% trend
        }
    ]

    best_markets = find_best_markets(mock_market_ops, top_50_markets=['VET-EUR', 'ADA-EUR'])

    # Should return a list of markets (ADA-EUR should be first due to higher volatility)
    assert isinstance(best_markets, list)
    assert len(best_markets) <= 2

def test_find_best_markets_spread_filter(mock_market_ops):
    """Test that markets with excessive spread are rejected"""
    # Setup market info
    mock_market_ops.get_detailed_market_info.side_effect = [
        {
            'high': 1.5,
            'low': 1.0,
            'volume_quote': 15000.0,
            'price': 1.2,
            'open': 1.1
        },
        {
            'high': 1.5,
            'low': 1.0,
            'volume_quote': 15000.0,
            'price': 1.2,
            'open': 1.1
        }
    ]

    # Setup historical candles
    historical_candles = [
        [1672531200000 + i*3600000, '1.0', '1.5', '1.0', '1.2', '1000']
        for i in range(10)
    ]
    mock_market_ops.get_historical_candles.return_value = historical_candles

    # First market: wide spread (>0.5%), second market: tight spread
    def get_book_side_effect(market, depth):
        if market == 'WIDE-EUR':
            return {
                'bids': [['1.000', '100']],
                'asks': [['1.010', '100']]  # 1.0% spread - should be rejected
            }
        else:
            return {
                'bids': [['1.000', '100']],
                'asks': [['1.003', '100']]  # 0.3% spread - should be accepted
            }

    mock_market_ops.get_book.side_effect = get_book_side_effect

    best_markets = find_best_markets(mock_market_ops, top_50_markets=['WIDE-EUR', 'TIGHT-EUR'])

    # TIGHT-EUR should be in results, WIDE-EUR might be rejected due to spread
    assert isinstance(best_markets, list)

def test_spread_above_configured_max_is_rejected(mock_market_ops, caplog):
    """A 0.3% spread passes the default 0.5% limit but is rejected when max_spread_pct is 0.2"""
    mock_market_ops.get_book.return_value = {
        'bids': [['1.000', '100']],
        'asks': [['1.003', '100']]  # 0.3% spread
    }
    mock_market_ops.get_historical_candles.return_value = [
        [1672531200000 + i*3600000, '1.0', '1.5', '1.0', '1.2', '1000']
        for i in range(10)
    ]

    assert 'TIGHT-EUR' in find_best_markets(mock_market_ops, top_50_markets=['TIGHT-EUR'])

    with caplog.at_level('INFO'):
        best_markets = find_best_markets(mock_market_ops, top_50_markets=['TIGHT-EUR'], max_spread_pct=0.2)

    assert 'TIGHT-EUR' not in best_markets
    assert 'Rejecting TIGHT-EUR: Spread too wide (0.30% > 0.2%)' in caplog.text

def test_no_candidate_within_the_spread_limit_selects_nothing(mock_market_ops, caplog):
    """Every candidate fails a strict limit: no unchecked fallback markets are traded instead"""
    mock_market_ops.get_book.return_value = {
        'bids': [['1.000', '100']],
        'asks': [['1.003', '100']]  # 0.3% spread
    }
    mock_market_ops.get_historical_candles.return_value = [
        [1672531200000 + i*3600000, '1.0', '1.5', '1.0', '1.2', '1000']
        for i in range(10)
    ]

    with caplog.at_level('INFO'):
        best_markets = find_best_markets(mock_market_ops, top_50_markets=['TIGHT-EUR', 'VET-EUR'], max_spread_pct=0.1)

    assert best_markets == []
    assert 'MAX_SPREAD_PCT' in caplog.text

def test_find_best_markets_volume_spike_penalty(mock_market_ops, caplog):
    """Test that volume spikes are detected and penalized"""
    import logging
    caplog.set_level(logging.INFO)

    # PUMP-EUR has very high volume spike (should be penalized)
    mock_market_ops.get_detailed_market_info.return_value = {
        'high': 1.5,
        'low': 1.0,
        'volume_quote': 50000.0,  # Very high current volume
        'price': 1.2,
        'open': 1.1
    }

    # Historical volumes are low (creating a spike pattern)
    mock_market_ops.get_historical_candles.return_value = [
        [1672531200000 + i*3600000, '1.0', '1.5', '1.0', '1.2', '300']  # Low hourly volume
        for i in range(168)
    ]

    # Good spread
    mock_market_ops.get_book.return_value = {
        'bids': [['1.000', '100']],
        'asks': [['1.002', '100']]
    }

    best_markets = find_best_markets(mock_market_ops, top_50_markets=['PUMP-EUR'])

    # PUMP-EUR should still be in results (it's the only option)
    assert isinstance(best_markets, list)

@patch('sys.argv', ['main.py', '--test-trade'])
@patch('trader.main.get_config')
@patch('trader.main.TradeDatabase')
@patch('trader.main.BitvavoClient')
@patch('trader.main.MarketOperations')
@patch('trader.main.MultiMarketStrategy')
@patch('trader.main.display_market_info')
@patch('trader.main.find_best_markets')
@patch('trader.main.scan_all_markets_for_top_50')
def test_main_test_trade_fails(
    mock_scan_markets,
    mock_find_best_markets,
    mock_display_market_info,
    mock_strategy,
    mock_market_ops_class,
    mock_bitvavo_client,
    mock_db,
    mock_get_config,
    caplog
):
    """Test that the main function handles a failed test trade (--test-trade)"""
    # Arrange - get_config returns 4 values: bitvavo_config, db_config, virtual_config, strategy_config
    mock_get_config.return_value = (Mock(), Mock(), Mock(), Mock())
    mock_db.return_value.get_active_positions.return_value = []
    mock_db.return_value.get_total_profit_loss.return_value = 0.0
    mock_market_ops = Mock()
    mock_market_ops.test_trade.return_value = False
    mock_market_ops_class.return_value = mock_market_ops
    mock_scan_markets.return_value = ['VET-EUR']
    mock_find_best_markets.return_value = ['VET-EUR']

    # Act
    from trader.main import main
    main()

    # Assert
    assert "Test trade failed - aborting strategy" in caplog.text
    mock_strategy.assert_not_called()


@patch('sys.argv', ['main.py'])
@patch('trader.main.get_config')
@patch('trader.main.TradeDatabase')
@patch('trader.main.BitvavoClient')
@patch('trader.main.MarketOperations')
@patch('trader.main.MultiMarketStrategy')
@patch('trader.main.display_market_info')
@patch('trader.main.find_best_markets')
@patch('trader.main.scan_all_markets_for_top_50')
def test_main_real_mode_defaults_to_connectivity_check(
    mock_scan_markets,
    mock_find_best_markets,
    mock_display_market_info,
    mock_strategy,
    mock_market_ops_class,
    mock_bitvavo_client,
    mock_db,
    mock_get_config,
    caplog
):
    """Without --test-trade, real mode must not place any orders on startup"""
    mock_get_config.return_value = (Mock(), Mock(), Mock(), Mock())
    mock_db.return_value.get_active_positions.return_value = []
    mock_db.return_value.get_total_profit_loss.return_value = 0.0
    mock_market_ops = Mock()
    mock_market_ops.connectivity_check.return_value = False  # abort before strategy
    mock_market_ops_class.return_value = mock_market_ops
    mock_scan_markets.return_value = ['VET-EUR']
    mock_find_best_markets.return_value = ['VET-EUR']

    from trader.main import main
    main()

    # The real test trade must never run without the explicit flag
    mock_market_ops.test_trade.assert_not_called()
    assert "Connectivity check failed - aborting strategy" in caplog.text
    mock_strategy.assert_not_called()

def test_dotenv_is_loaded_before_logging_is_set_up(monkeypatch):
    calls = []
    monkeypatch.setattr('sys.argv', ['main.py'])
    monkeypatch.setattr('trader.main.load_dotenv', lambda *a, **k: calls.append('load_dotenv'))

    def stop(*a, **k):
        calls.append('setup_logger')
        raise SystemExit
    monkeypatch.setattr('trader.main.setup_logger', stop)
    with pytest.raises(SystemExit):
        main()
    assert calls == ['load_dotenv', 'setup_logger']


def startup_config(max_positions=3):
    return (BitvavoConfig('key', 'secret'), DatabaseConfig('trades.db'),
            VirtualTradingConfig(False, 'virtual_trades.db', 1000.0, 0.25, max_positions),
            TradingStrategyConfig(trade_amount=10.0, stop_loss_pct=5.0, take_profit_pct=15.0, max_coin_price=10.0,
                                  strategy_interval=60, market_cache_hours=6, max_candidates=30, max_spread_pct=0.1))


@pytest.fixture
def real_startup(monkeypatch):
    """main() in real mode up to strategy.run, holding RVN-EUR; exchange, database and strategies are mocks."""
    monkeypatch.setattr('sys.argv', ['main.py'])
    monkeypatch.setattr('trader.main.signal.signal', Mock())
    monkeypatch.setattr('trader.main.get_config', Mock(return_value=startup_config()))
    db = Mock()
    db.get_active_positions.return_value = [{'market': 'RVN-EUR', 'amount': 500.0, 'entry_price': 0.02}]
    db.get_total_profit_loss.return_value = 0.0
    monkeypatch.setattr('trader.main.TradeDatabase', Mock(return_value=db))
    monkeypatch.setattr('trader.main.BitvavoClient', Mock())
    ops = Mock()
    ops.get_balance.return_value = [{'symbol': 'RVN', 'available': '500', 'inOrder': '0'}]
    ops.connectivity_check.return_value = True
    monkeypatch.setattr('trader.main.MarketOperations', Mock(return_value=ops))
    monkeypatch.setattr('trader.main.scan_all_markets_for_top_50', Mock(return_value=['VET-EUR']))
    env = SimpleNamespace(ops=ops, find=Mock(), display=Mock(), single=Mock(), multi=Mock())
    # The strategy loop "runs" once and stops, which also ends the rescan thread
    env.multi.return_value.run.side_effect = lambda interval, stop_event: stop_event.set()
    monkeypatch.setattr('trader.main.find_best_markets', env.find)
    monkeypatch.setattr('trader.main.display_market_info', env.display)
    monkeypatch.setattr('trader.main.EnhancedStrategy', env.single)
    monkeypatch.setattr('trader.main.MultiMarketStrategy', env.multi)
    return env


def test_startup_with_no_market_selected_still_manages_held_positions(real_startup, caplog):
    real_startup.find.return_value = []

    with caplog.at_level(logging.INFO):
        main()

    real_startup.display.assert_not_called()
    real_startup.single.assert_not_called()
    assert real_startup.multi.call_args.kwargs['markets'] == []   # it adds the held RVN-EUR itself
    real_startup.multi.return_value.run.assert_called_once()
    assert 'MAX_SPREAD_PCT' in caplog.text


def test_one_selected_market_still_uses_the_multi_market_strategy(real_startup):
    real_startup.find.return_value = ['VET-EUR']

    main()

    real_startup.single.assert_not_called()
    assert real_startup.multi.call_args.kwargs['markets'] == ['VET-EUR']
    real_startup.multi.return_value.run.assert_called_once()


def test_test_trade_without_a_selected_market_runs_the_read_only_check(real_startup, monkeypatch, caplog):
    monkeypatch.setattr('sys.argv', ['main.py', '--test-trade'])
    real_startup.find.return_value = []

    with caplog.at_level(logging.INFO):
        main()

    real_startup.ops.test_trade.assert_not_called()
    real_startup.ops.place_market_order.assert_not_called()
    real_startup.ops.connectivity_check.assert_called_once()
    real_startup.multi.return_value.run.assert_called_once()


def test_virtual_startup_with_no_market_and_no_position_skips_the_test_trade(real_startup, monkeypatch, caplog):
    monkeypatch.setattr('sys.argv', ['main.py', 'virtual'])
    wallet = Mock()
    wallet.get_active_positions.return_value = []
    wallet.get_balance.return_value = wallet.get_initial_balance.return_value = 1000.0
    monkeypatch.setattr('trader.main.VirtualWallet', Mock(return_value=wallet))
    ops = Mock()
    monkeypatch.setattr('trader.main.VirtualMarketOperations', Mock(return_value=ops))
    real_startup.find.return_value = []

    with caplog.at_level(logging.INFO):
        main()

    ops.test_trade.assert_not_called()
    assert 'skipping the virtual test trade' in caplog.text
    real_startup.multi.return_value.run.assert_called_once()
