import pytest
from unittest.mock import Mock, patch
from trader.market import MarketOperations
from trader.exceptions import MarketNotFoundError, APIConnectionError, AuthenticationError

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
def market_ops(mock_client):
    """Fixture for MarketOperations instance"""
    return MarketOperations(mock_client)

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
    
    mock_bitvavo.placeOrder.assert_called_once_with(
        'BTC-EUR', 'buy', 'limit',
        {'amount': '1.0', 'price': '30000.0'}
    )
    assert order['orderId'] == '12345'
    assert order['status'] == 'filled'

def test_place_market_order(market_ops, mock_bitvavo):
    """Test market order placement"""
    order = market_ops.place_market_order('BTC-EUR', 'buy', 1.0)
    
    # Verify market validation was performed
    mock_bitvavo.markets.assert_called_once()
    mock_bitvavo.tickerPrice.assert_called_once()
    
    # Verify order placement
    assert mock_bitvavo.placeOrder.call_args[0][0] == 'BTC-EUR'
    assert mock_bitvavo.placeOrder.call_args[0][1] == 'buy'
    assert mock_bitvavo.placeOrder.call_args[0][2] == 'market'
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
    
    def mock_ticker_price(params):
        market = params['market']
        if market == 'VET-EUR':
            return {'price': '0.10'}
        elif market == 'BTC-EUR':
            return {'price': '30000.00'}
        return {'price': '0.0'}
    
    mock_bitvavo.tickerPrice.side_effect = mock_ticker_price
    
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