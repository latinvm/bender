import pytest
from unittest.mock import Mock, patch
from trader.main import display_market_info, find_best_market
from trader.exceptions import MarketNotFoundError, APIConnectionError

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

def test_find_best_market(mock_market_ops):
    """Test best market finding algorithm"""
    best_market = find_best_market(mock_market_ops)
    
    # Verify market operations were called
    mock_market_ops.list_alt_coins.assert_called_once()
    assert mock_market_ops.get_detailed_market_info.call_count == 2  # Called for VET-EUR and ADA-EUR
    
    # Verify a valid market was returned
    assert best_market in ['VET-EUR', 'ADA-EUR']

def test_find_best_market_no_suitable_markets(mock_market_ops):
    """Test fallback behavior when no suitable markets are found"""
    # Mock empty alt coins list
    mock_market_ops.list_alt_coins.return_value = []
    
    best_market = find_best_market(mock_market_ops)
    
    # Should return default market
    assert best_market == 'VET-EUR'

def test_find_best_market_scoring(mock_market_ops):
    """Test market scoring algorithm"""
    # Mock two markets with different characteristics
    mock_market_ops.list_alt_coins.return_value = [
        {'market': 'VET-EUR', 'status': 'trading'},
        {'market': 'ADA-EUR', 'status': 'trading'}
    ]

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

    best_market = find_best_market(mock_market_ops)

    # ADA-EUR should be selected due to higher volatility (25% weight in new scoring)
    assert best_market == 'ADA-EUR'

def test_find_best_market_spread_filter(mock_market_ops):
    """Test that markets with excessive spread are rejected"""
    mock_market_ops.list_alt_coins.return_value = [
        {'market': 'WIDE-EUR', 'status': 'trading'},
        {'market': 'TIGHT-EUR', 'status': 'trading'}
    ]

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

    best_market = find_best_market(mock_market_ops)

    # TIGHT-EUR should be selected, WIDE-EUR rejected
    assert best_market == 'TIGHT-EUR'

def test_find_best_market_volume_spike_penalty(mock_market_ops, caplog):
    """Test that volume spikes are detected and penalized"""
    import logging
    caplog.set_level(logging.INFO)

    mock_market_ops.list_alt_coins.return_value = [
        {'market': 'PUMP-EUR', 'status': 'trading'}
    ]

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

    best_market = find_best_market(mock_market_ops)

    # Check that penalty was applied (>5x volume spike)
    assert 'PUMP (volume' in caplog.text or 'Penalty Applied' in caplog.text
    # Verify volume spike was detected
    assert 'Volume Consistency:' in caplog.text
    assert best_market == 'PUMP-EUR'  # Still selected (it's the only option)

@patch('trader.main.get_config')
@patch('trader.main.TradeDatabase')
@patch('trader.main.BitvavoClient')
@patch('trader.main.MarketOperations')
@patch('trader.main.EnhancedStrategy')
@patch('trader.main.display_market_info')
@patch('trader.main.find_best_market')
def test_main_test_trade_fails(
    mock_find_best_market,
    mock_display_market_info,
    mock_strategy,
    mock_market_ops_class,
    mock_bitvavo_client,
    mock_db,
    mock_get_config,
    caplog
):
    """Test that the main function handles a failed test trade"""
    # Arrange
    mock_get_config.return_value = (Mock(), Mock())
    mock_db.return_value.get_active_positions.return_value = []
    mock_db.return_value.get_total_profit_loss.return_value = 0.0
    mock_market_ops = Mock()
    mock_market_ops.test_trade.return_value = False
    mock_market_ops_class.return_value = mock_market_ops
    mock_find_best_market.return_value = 'VET-EUR'

    # Act
    from trader.main import main
    main()

    # Assert
    assert "Test trade failed - aborting strategy" in caplog.text
    mock_strategy.assert_not_called()