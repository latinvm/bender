import pytest
from unittest.mock import Mock, patch
from trader.market import MarketOperations
from trader.exceptions import MarketNotFoundError, APIConnectionError, AuthenticationError

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
        {'symbol': 'EUR', 'available': '50000.0', 'inOrder': '0.0'}
    ]
    
    mock.markets.return_value = [
        {
            'market': 'BTC-EUR',
            'status': 'trading',
            'base': 'BTC',
            'quote': 'EUR',
            'minOrderInBaseAsset': '0.0001',
            'minOrderInQuoteAsset': '10.0',
            'orderSizeIncrement': '0.00000001'
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
        'status': 'filled',
        'filledAmount': '0.001',
        'filledAmountQuote': '30.0',
        'feePaid': '0.075',
        'fills': [
            {'price': '30000.00', 'amount': '0.001', 'fee': '0.075'}
        ]
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

@patch('trader.market.logger')
def test_monitor_price_with_positions(mock_logger, market_ops, mock_bitvavo):
    """Test price monitoring with active positions"""
    # Setup mock for current price
    mock_bitvavo.tickerPrice.return_value = {'price': '30000.00'}
    
    # Mock time.sleep to avoid waiting
    with patch('time.sleep', side_effect=KeyboardInterrupt):
        market_ops.monitor_price('BTC-EUR')
    
    # Verify position and P/L information was logged
    # Get all calls to the logger
    log_calls = [call[0][0] for call in mock_logger.info.call_args_list]

    assert any('BTC-EUR: €30000.00' in msg for msg in log_calls)
    assert any('Position: 0.10000000 BTC-EUR | Entry: €28000.00 | P/L: €+200.00 (+7.14%)' in msg for msg in log_calls)

@patch('trader.market.logger')
def test_monitor_price_no_positions(mock_logger, market_ops, mock_bitvavo):
    """Test price monitoring with no active positions"""
    # Setup empty positions
    market_ops.db.get_active_positions.return_value = []
    
    # Setup mock for current price
    mock_bitvavo.tickerPrice.return_value = {'price': '30000.00'}
    
    # Mock time.sleep to avoid waiting
    with patch('time.sleep', side_effect=KeyboardInterrupt):
        market_ops.monitor_price('BTC-EUR')
    
    # Verify only price was logged, no position info
    log_calls = [call[0][0] for call in mock_logger.info.call_args_list]

    assert any('BTC-EUR: €30000.00' in msg for msg in log_calls)
    assert not any('Position:' in msg for msg in log_calls)
    assert not any('P/L:' in msg for msg in log_calls)

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
    # Balance check also calls balance
    mock_bitvavo.balance.assert_called()

    # Construct expected payload
    # Note: amount is '1' after stripping trailing zeros (1.00 -> 1)
    expected_payload = {'amount': '1'}
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
    mock_bitvavo.balance.reset_mock()

    order = ops.place_market_order('BTC-EUR', 'sell', 0.1)

    mock_bitvavo.markets.assert_called_once()
    mock_bitvavo.tickerPrice.assert_called_once()
    # Balance check for sell order
    mock_bitvavo.balance.assert_called()

    expected_payload = {'amount': '0.1'} # Trailing zeros stripped (0.10 -> 0.1)
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
    # Mock balance to have sufficient EUR for the buy, and BTC for the sell
    def mock_get_balance(symbol):
        if symbol == 'EUR':
            return 1000.0  # Sufficient EUR for buy
        elif symbol == 'BTC':
            return 0.001  # BTC balance after buy
        return 0.0

    market_ops.get_available_balance = Mock(side_effect=mock_get_balance)

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


def test_test_trade_never_sells_preexisting_balance(market_ops, mock_bitvavo):
    """The test sell must only cover what the test buy filled, even when the
    account already holds a large balance of the asset."""
    # Account holds 5 BTC from before; test buy fills only 0.001 BTC
    def mock_get_balance(symbol):
        if symbol == 'EUR':
            return 1000.0
        elif symbol == 'BTC':
            return 5.0  # Pre-existing holding - must NOT be sold
        return 0.0

    market_ops.get_available_balance = Mock(side_effect=mock_get_balance)

    result = market_ops.test_trade('BTC-EUR')

    assert result is True
    sell_call = mock_bitvavo.placeOrder.call_args_list[1]
    assert sell_call[0][1] == 'sell'
    sold_amount = float(sell_call[0][3]['amount'])
    # Sold exactly the test buy's filled amount (0.001 from the mock response)
    assert sold_amount == pytest.approx(0.001)


def test_test_trade_aborts_when_fill_unknown(market_ops, mock_bitvavo):
    """If the filled amount cannot be determined, do not sell anything."""
    mock_bitvavo.placeOrder.return_value = {
        'orderId': '12345',
        'market': 'BTC-EUR',
        'status': 'filled'
        # No filledAmount / fills
    }
    # Order status lookup also yields no fill info
    mock_bitvavo.getOrder.return_value = {'orderId': '12345', 'status': 'new'}

    def mock_get_balance(symbol):
        return 1000.0 if symbol == 'EUR' else 5.0

    market_ops.get_available_balance = Mock(side_effect=mock_get_balance)

    result = market_ops.test_trade('BTC-EUR')

    assert result is False
    # Only the buy order was placed - never a sell
    assert mock_bitvavo.placeOrder.call_count == 1

def test_test_trade_failure(market_ops, mock_bitvavo):
    """Test the test trade failure handling"""
    mock_bitvavo.placeOrder.side_effect = Exception('API Error')
    
    result = market_ops.test_trade('BTC-EUR')
    assert result is False

def test_place_market_order_rounding(market_ops, mock_bitvavo):
    """Test that place_market_order correctly rounds the amount based on orderSizeIncrement."""
    # Mock the market info to include orderSizeIncrement (code uses this, not amountPrecision)
    mock_bitvavo.markets.return_value = [
        {
            'market': 'BONK-EUR',
            'status': 'trading',
            'base': 'BONK',
            'quote': 'EUR',
            'minOrderInBaseAsset': '1000',
            'minOrderInQuoteAsset': '5.0',
            'orderSizeIncrement': '0.01'  # 2 decimal places
        }
    ]
    # Mock ticker price for BONK-EUR
    mock_bitvavo.tickerPrice.return_value = {'market': 'BONK-EUR', 'price': '0.00001281'}
    # Mock sufficient EUR balance
    mock_bitvavo.balance.return_value = [
        {'symbol': 'EUR', 'available': '100.0', 'inOrder': '0.0'}
    ]

    # Amount with more decimal places than allowed
    test_amount = 429285.0452700593

    # Call the method
    market_ops.place_market_order('BONK-EUR', 'buy', test_amount)

    # Verify the amount is floored (never rounded up) to the increment
    expected_rounded_amount = '429285.04'

    # Get the actual payload from the mock
    actual_call_args = mock_bitvavo.placeOrder.call_args
    actual_payload = actual_call_args[0][3]  # The payload is the 4th argument in placeOrder call

    assert actual_payload['amount'] == expected_rounded_amount

@pytest.mark.parametrize("orderSizeIncrement, amount, expected_format", [
    ('0.01', 123.456, "123.45"),        # floored, never rounded up
    ('0.00001', 123.456789, "123.45678"),
    ('1', 123.456, "123"),
    ('0.01', 123.0, "123")  # Trailing zeros are stripped (123.00 -> 123)
])
def test_place_market_order_amount_formatting(market_ops, mock_bitvavo, orderSizeIncrement, amount, expected_format):
    """Test that place_market_order correctly formats the amount string based on orderSizeIncrement."""
    # Mock market info to provide the specified orderSizeIncrement (not amountPrecision)
    mock_bitvavo.markets.return_value = [
        {
            'market': 'TEST-EUR',
            'status': 'trading',
            'base': 'TEST',
            'quote': 'EUR',
            'minOrderInBaseAsset': '1',
            'minOrderInQuoteAsset': '1',
            'orderSizeIncrement': orderSizeIncrement
        }
    ]
    mock_bitvavo.tickerPrice.return_value = {'market': 'TEST-EUR', 'price': '1.0'}
    # Mock sufficient EUR balance
    mock_bitvavo.balance.return_value = [
        {'symbol': 'EUR', 'available': '1000.0', 'inOrder': '0.0'}
    ]

    # Place the order
    market_ops.place_market_order('TEST-EUR', 'buy', amount)

    # Get the payload from the mocked placeOrder call
    actual_payload = mock_bitvavo.placeOrder.call_args[0][3]

    # Verify that the 'amount' in the payload is formatted correctly
    assert actual_payload['amount'] == expected_format

def test_place_market_order_insufficient_eur_balance(market_ops, mock_bitvavo):
    """Test that buy order fails gracefully when EUR balance is insufficient"""
    # Mock insufficient EUR balance
    mock_bitvavo.balance.return_value = [
        {'symbol': 'EUR', 'available': '5.0', 'inOrder': '0.0'}  # Only €5
    ]

    # Try to buy 1 BTC (requires ~€30,075 including fees)
    with pytest.raises(APIConnectionError) as exc_info:
        market_ops.place_market_order('BTC-EUR', 'buy', 1.0)

    # Verify the error message mentions insufficient balance
    assert 'Insufficient EUR balance' in str(exc_info.value)
    # Verify placeOrder was never called (failed before reaching API)
    mock_bitvavo.placeOrder.assert_not_called()

def test_place_market_order_insufficient_base_asset_balance(market_ops, mock_bitvavo):
    """Test that sell order fails gracefully when base asset balance is insufficient"""
    # Mock insufficient BTC balance
    mock_bitvavo.balance.return_value = [
        {'symbol': 'BTC', 'available': '0.01', 'inOrder': '0.0'},  # Only 0.01 BTC
        {'symbol': 'EUR', 'available': '10000.0', 'inOrder': '0.0'}
    ]

    # Try to sell 1 BTC (only have 0.01)
    with pytest.raises(APIConnectionError) as exc_info:
        market_ops.place_market_order('BTC-EUR', 'sell', 1.0)

    # Verify the error message mentions insufficient balance
    assert 'Insufficient BTC balance' in str(exc_info.value)
    # Verify placeOrder was never called (failed before reaching API)
    mock_bitvavo.placeOrder.assert_not_called()