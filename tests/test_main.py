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
    
    # ADA-EUR should be selected due to higher volatility and trend
    assert best_market == 'ADA-EUR'