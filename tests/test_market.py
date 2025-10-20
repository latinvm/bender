import pytest
from unittest.mock import Mock, patch, MagicMock
from trader.market import MarketOperations
from trader.exceptions import MarketNotFoundError, APIConnectionError, AuthenticationError
from datetime import datetime

@pytest.fixture
def mock_trade_db():
    """Fixture for mocked TradeDatabase"""
    mock = Mock()
    mock.get_active_positions.return_value = [
        {
            'market': 'BTC-EUR',
            'amount': 0.1,
            'entry_price': 28000.0
        }
    ]
    return mock

@pytest.fixture
def mock_bitvavo():
    """Fixture for mocked Bitvavo client"""
    mock = Mock()
    
    # Setup basic successful responses
    mock.balance.return_value = [
        {'symbol': 'BTC', 'available': '1.0', 'inOrder': '0.0'},
        {'symbol': 'EUR', 'available': '10000.0', 'inOrder': '0.0'}
    ]
    
    mock.markets.return_value = [
        {
            'market': 'BTC-EUR',
            'status': 'trading',
            'base': 'BTC',
            'quote': 'EUR',
            'minOrderInBaseAsset': '0.0001',
            'minOrderInQuoteAsset': '10.0'
        }
    ]
    
    mock.book.return_value = {
        'market': 'BTC-EUR',
        'bids': [['30000.00', '1.0']],
        'asks': [['30100.00', '1.0']]
    }
    
    mock.tickerPrice.return_value = {
        'market': 'BTC-EUR',
        'price': '30000.00'
    }
    
    mock.ticker24h.return_value = {
        'market': 'BTC-EUR',
        'last': '30000.00',
        'volume': '100.0',
        'volumeQuote': '3000000.0',
        'open': '29000.00',
        'high': '31000.00',
        'low': '28000.00'
    }
    
    mock.placeOrder.return_value = {
        'orderId': '12345',
        'market': 'BTC-EUR',
        'status': 'filled'
    }
    
    return mock

@pytest.fixture
def mock_client(mock_bitvavo):
    """Fixture for mocked BitvavoClient"""
    mock = Mock()
    mock.bitvavo = mock_bitvavo
    return mock

@pytest.fixture
def market_ops(mock_client, mock_trade_db):
    """Fixture for MarketOperations instance"""
    with patch('trader.market.TradeDatabase') as mock_db_class:
        mock_db_class.return_value = mock_trade_db
        # Provide a default operator_id for most tests
        ops = MarketOperations(mock_client, operator_id=123456789)
        return ops

def test_market_ops_init_with_db(mock_client):
    """Test MarketOperations initialization with database"""
    with patch('trader.market.TradeDatabase') as mock_db_class:
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        
        ops = MarketOperations(mock_client, operator_id=98765)
        
        assert hasattr(ops, 'db')
        assert ops.operator_id == 98765
        mock_db_class.assert_called_once()

def test_market_ops_init_no_operator_id(mock_client):
    """Test MarketOperations initialization without operator_id"""
    with patch('trader.market.TradeDatabase') as mock_db_class:
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        ops = MarketOperations(mock_client, operator_id=None)
        assert ops.operator_id is None

def test_monitor_price_with_positions(market_ops, mock_bitvavo, caplog):
    """Test price monitoring with active positions"""
    # Setup mock for current price
    mock_bitvavo.tickerPrice.return_value = {'price': '30000.00'}
    
    # Mock time.sleep to avoid waiting
    with patch('time.sleep', side_effect=KeyboardInterrupt):
        market_ops.monitor_price('BTC-EUR')
    
    # Verify position and P/L information was logged
    log_messages = [record.message for record in caplog.records]
    assert any('BTC-EUR: €30000.00' in msg for msg in log_messages)
    assert any('Position: 0.10000000 BTC-EUR | Entry: €28000.00 | P/L: €+200.00 (+7.14%)' in msg for msg in log_messages)

def test_monitor_price_no_positions(market_ops, mock_bitvavo, caplog):
    """Test price monitoring with no active positions"""
    # Setup empty positions
    market_ops.db.get_active_positions.return_value = []
    
    # Setup mock for current price
    mock_bitvavo.tickerPrice.return_value = {'price': '30000.00'}
    
    # Mock time.sleep to avoid waiting
    with patch('time.sleep', side_effect=KeyboardInterrupt):
        market_ops.monitor_price('BTC-EUR')
    
    # Verify only price was logged, no position info
    log_messages = [record.message for record in caplog.records]
    assert any('BTC-EUR: €30000.00' in msg for msg in log_messages)
    assert not any('Position:' in msg for msg in log_messages)
    assert not any('P/L:' in msg for msg in log_messages)

def test_get_balance(market_ops, mock_bitvavo):
    """Test balance retrieval"""
    balance = market_ops.get_balance()
    
    mock_bitvavo.balance.assert_called_once_with({})
    assert len(balance) == 2
    assert balance[0]['symbol'] == 'BTC'
    assert float(balance[0]['available']) == 1.0

def test_get_balance_auth_error(market_ops, mock_bitvavo):
    """Test balance retrieval with authentication error"""
    mock_bitvavo.balance.side_effect = Exception('UNAUTHORIZED')
    
    with pytest.raises(AuthenticationError):
        market_ops.get_balance()

def test_get_market_info(market_ops, mock_bitvavo):
    """Test market info retrieval"""
    info = market_ops.get_market_info('BTC-EUR')
    
    mock_bitvavo.markets.assert_called_once_with({})
    assert info['market'] == 'BTC-EUR'
    assert info['status'] == 'trading'
    assert info['base'] == 'BTC'
    assert info['quote'] == 'EUR'

def test_get_market_info_not_found(market_ops, mock_bitvavo):
    """Test market info retrieval for non-existent market"""
    with pytest.raises(MarketNotFoundError):
        market_ops.get_market_info('INVALID-MARKET')

def test_get_book(market_ops, mock_bitvavo):
    """Test order book retrieval"""
    book = market_ops.get_book('BTC-EUR', 1)
    
    mock_bitvavo.book.assert_called_once_with('BTC-EUR', {'depth': 1})
    assert len(book['bids']) == 1
    assert len(book['asks']) == 1
    assert float(book['bids'][0][0]) == 30000.00

def test_get_ticker(market_ops, mock_bitvavo):
    """Test ticker retrieval"""
    ticker = market_ops.get_ticker('BTC-EUR')
    
    mock_bitvavo.tickerPrice.assert_called_once_with({'market': 'BTC-EUR'})
    assert float(ticker['price']) == 30000.00

def test_get_available_balance(market_ops, mock_bitvavo):
    """Test available balance retrieval"""
    balance = market_ops.get_available_balance('BTC')
    
    mock_bitvavo.balance.assert_called_once_with({})
    assert balance == 1.0

def test_place_limit_order(market_ops, mock_bitvavo):
    """Test limit order placement"""
    order = market_ops.place_limit_order('BTC-EUR', 'buy', 1.0, 30000.0)
    
    expected_payload = {'amount': '1.0', 'price': '30000.0'}
    if market_ops.operator_id:
        expected_payload['operatorId'] = market_ops.operator_id

    mock_bitvavo.placeOrder.assert_called_once_with(
        'BTC-EUR', 'buy', 'limit', expected_payload
    )
    assert order['orderId'] == '12345'
    assert order['status'] == 'filled'

def test_place_limit_order_no_operator_id(mock_client, mock_trade_db, mock_bitvavo):
    """Test limit order placement when MarketOperations has no operator_id"""
    with patch('trader.market.TradeDatabase') as mock_db_class:
        mock_db_class.return_value = mock_trade_db
        ops = MarketOperations(mock_client, operator_id=None) # Initialize without operator_id

    order = ops.place_limit_order('BTC-EUR', 'buy', 0.5, 29000.0)

    expected_payload = {'amount': '0.5', 'price': '29000.0'}
    # operatorId should not be in the payload
    mock_bitvavo.placeOrder.assert_called_once_with(
        'BTC-EUR', 'buy', 'limit', expected_payload
    )
    assert order['orderId'] == '12345' # Assuming mock returns this

def test_place_market_order(market_ops, mock_bitvavo):
    """Test market order placement"""
    order = market_ops.place_market_order('BTC-EUR', 'buy', 1.0)
    
    # Verify market validation was performed
    mock_bitvavo.markets.assert_called_once() # This is called by get_market_info
    mock_bitvavo.tickerPrice.assert_called_once() # This is called by get_ticker for price check

    # Construct expected payload
    # Note: amount might be rounded, but for this test input 1.0, assume it's '1.0'
    # The actual rounding logic is complex and tested implicitly if min_base allows 1.0
    expected_payload = {'amount': '1.0'}
    if market_ops.operator_id:
        expected_payload['operatorId'] = market_ops.operator_id

    # Verify order placement call
    mock_bitvavo.placeOrder.assert_called_once_with(
        'BTC-EUR', 'buy', 'market', expected_payload
    )
    assert order['orderId'] == '12345'

def test_place_market_order_no_operator_id(mock_client, mock_trade_db, mock_bitvavo):
    """Test market order placement when MarketOperations has no operator_id"""
    with patch('trader.market.TradeDatabase') as mock_db_class:
        mock_db_class.return_value = mock_trade_db
        ops = MarketOperations(mock_client, operator_id=None)

    # Reset mocks for markets and tickerPrice as they are called in place_market_order
    mock_bitvavo.markets.reset_mock()
    mock_bitvavo.tickerPrice.reset_mock()

    order = ops.place_market_order('BTC-EUR', 'sell', 0.1)

    mock_bitvavo.markets.assert_called_once()
    mock_bitvavo.tickerPrice.assert_called_once()

    expected_payload = {'amount': '0.1'} # Assuming 0.1 is valid and doesn't need rounding here
    # operatorId should not be in the payload
    mock_bitvavo.placeOrder.assert_called_once_with(
        'BTC-EUR', 'sell', 'market', expected_payload
    )
    assert order['orderId'] == '12345'


def test_place_market_order_minimum_requirements(market_ops, mock_bitvavo):
    """Test market order with minimum requirements"""
    # Try to place order below minimum
    with pytest.raises(APIConnectionError):
        market_ops.place_market_order('BTC-EUR', 'buy', 0.00001)

def test_cancel_order(market_ops, mock_bitvavo):
    """Test order cancellation"""
    market_ops.cancel_order('BTC-EUR', '12345')
    mock_bitvavo.cancelOrder.assert_called_once_with('BTC-EUR', '12345')

def test_get_detailed_market_info(market_ops, mock_bitvavo):
    """Test detailed market info retrieval"""
    info = market_ops.get_detailed_market_info('BTC-EUR')
    
    mock_bitvavo.ticker24h.assert_called_once_with({'market': 'BTC-EUR'})
    assert info['market'] == 'BTC-EUR'
    assert info['price'] == 30000.00
    assert info['volume'] == 100.0
    assert info['volume_quote'] == 3000000.0
    assert info['high'] == 31000.00
    assert info['low'] == 28000.00

def test_list_alt_coins(market_ops, mock_bitvavo):
    """Test altcoin listing"""
    # Setup mock responses for altcoin listing
    mock_bitvavo.markets.return_value = [
        {'market': 'VET-EUR', 'quote': 'EUR', 'status': 'trading'},
        {'market': 'BTC-EUR', 'quote': 'EUR', 'status': 'trading'},
        {'market': 'VET-BTC', 'quote': 'BTC', 'status': 'trading'}
    ]

    # list_alt_coins uses ticker24h, so we mock that.
    mock_bitvavo.ticker24h.return_value = [
        {'market': 'VET-EUR', 'last': '0.10'},
        {'market': 'BTC-EUR', 'last': '30000.00'},
    ]

    coins = market_ops.list_alt_coins(max_price=1.0)

    assert len(coins) == 1
    assert coins[0]['market'] == 'VET-EUR'
    assert coins[0]['price'] == 0.10

def test_test_trade(market_ops, mock_bitvavo):
    """Test the test trade functionality"""
    # Setup mock for get_available_balance after buy
    market_ops.get_available_balance = Mock(return_value=0.001)
    
    result = market_ops.test_trade('BTC-EUR')
    
    assert result is True
    # Verify buy and sell orders were placed
    assert mock_bitvavo.placeOrder.call_count == 2
    
    # First call should be buy
    buy_call = mock_bitvavo.placeOrder.call_args_list[0]
    assert buy_call[0][1] == 'buy'
    
    # Second call should be sell
    sell_call = mock_bitvavo.placeOrder.call_args_list[1]
    assert sell_call[0][1] == 'sell'

def test_test_trade_failure(market_ops, mock_bitvavo):
    """Test the test trade failure handling"""
    mock_bitvavo.placeOrder.side_effect = Exception('API Error')
    
    result = market_ops.test_trade('BTC-EUR')
    assert result is False

def test_place_market_order_rounding(market_ops, mock_bitvavo):
    """Test that place_market_order correctly rounds the amount based on amountPrecision."""
    # Mock the market info to include amountPrecision
    mock_bitvavo.markets.return_value = [
        {
            'market': 'BONK-EUR',
            'status': 'trading',
            'base': 'BONK',
            'quote': 'EUR',
            'minOrderInBaseAsset': '1000',
            'minOrderInQuoteAsset': '5.0',
            'amountPrecision': 2  # Specify precision for rounding
        }
    ]
    # Mock ticker price for BONK-EUR
    mock_bitvavo.tickerPrice.return_value = {'market': 'BONK-EUR', 'price': '0.00001281'}

    # Amount with more decimal places than allowed
    test_amount = 429285.0452700593

    # Call the method
    market_ops.place_market_order('BONK-EUR', 'buy', test_amount)

    # Verify that the amount in the payload sent to placeOrder is correctly rounded
    expected_rounded_amount = '429285.05'

    # Get the actual payload from the mock
    actual_call_args = mock_bitvavo.placeOrder.call_args
    actual_payload = actual_call_args[0][3]  # The payload is the 4th argument in placeOrder call

    assert actual_payload['amount'] == expected_rounded_amount