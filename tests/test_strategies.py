import pytest
from unittest.mock import Mock, patch
from trader.strategies import SimpleMAStrategy
from trader.exceptions import APIConnectionError

@pytest.fixture
def mock_market_ops():
    """Fixture for mocked MarketOperations"""
    mock = Mock()
    
    # Setup market info mock
    mock.get_market_info.return_value = {
        'minOrderInBaseAsset': '0.0001',
        'minOrderInQuoteAsset': '10.0'
    }
    
    # Setup ticker mock
    mock.get_ticker.return_value = {
        'price': '100.0'
    }
    
    # Setup detailed market info mock
    mock.get_detailed_market_info.return_value = {
        'volume': '50000.0'
    }
    
    return mock

@pytest.fixture
def mock_db():
    """Fixture for mocked TradeDatabase"""
    mock = Mock()
    mock.get_active_positions.return_value = []
    mock.get_total_profit_loss.return_value = 0.0
    return mock

@pytest.fixture
def strategy(mock_market_ops, mock_db):
    """Fixture for SimpleMAStrategy with mocked dependencies"""
    with patch('trader.strategies.TradeDatabase', return_value=mock_db):
        strategy = SimpleMAStrategy(
            market_ops=mock_market_ops,
            market='BTC-EUR',
            investment_amount=100.0,
            short_window=2,
            long_window=4
        )
        return strategy

def test_init_strategy(strategy, mock_db):
    """Test strategy initialization"""
    assert strategy.market == 'BTC-EUR'
    assert strategy.investment_amount == 100.0
    assert strategy.short_window == 2
    assert strategy.long_window == 4
    assert len(strategy.positions) == 0
    mock_db.get_active_positions.assert_called_once()

def test_init_strategy_with_active_positions(mock_market_ops):
    """Test strategy initialization with existing positions"""
    mock_db = Mock()
    mock_db.get_active_positions.return_value = [
        {'market': 'BTC-EUR', 'amount': 1.0, 'entry_price': 100.0}
    ]
    
    with patch('trader.strategies.TradeDatabase', return_value=mock_db):
        strategy = SimpleMAStrategy(mock_market_ops, 'BTC-EUR')
        
        assert 'BTC-EUR' in strategy.positions
        assert strategy.positions['BTC-EUR'] == 1.0
        assert strategy.entry_prices['BTC-EUR'] == 100.0

def test_calculate_moving_average(strategy):
    """Test moving average calculation"""
    # Not enough prices
    assert strategy.calculate_moving_average(2) == 0.0
    
    # Add prices and test
    strategy.prices = [100.0, 110.0, 120.0, 130.0]
    assert strategy.calculate_moving_average(2) == 125.0  # (120 + 130) / 2
    assert strategy.calculate_moving_average(4) == 115.0  # (100 + 110 + 120 + 130) / 4

def test_should_buy_insufficient_data(strategy):
    """Test buy signal with insufficient price history"""
    assert not strategy.should_buy()
    
    # Add some prices but still less than long_window
    strategy.prices = [100.0, 110.0]
    assert not strategy.should_buy()

def test_should_buy_with_crossover(strategy):
    """Test buy signal on moving average crossover"""
    # Test various crossover scenarios
    
    # Case 1: Clear crossover (short MA significantly higher)
    strategy.prices = [90.0, 95.0, 99.0, 100.0]  # Short MA: 99.5, Long MA: 96
    assert strategy.should_buy()
    
    # Case 2: Barely crossing (edge case)
    strategy.prices = [95.0, 95.0, 95.1, 95.2]  # Short MA: 95.15, Long MA: 95.075
    assert strategy.should_buy()
    
    # Case 3: No crossover (short MA below long MA)
    strategy.prices = [100.0, 99.0, 97.0, 95.0]  # Short MA: 96, Long MA: 97.75
    assert not strategy.should_buy()
    
    # Case 4: Equal MAs (should not buy)
    strategy.prices = [95.0, 95.0, 95.0, 95.0]  # Both MAs: 95
    assert not strategy.should_buy()
    
    # Test when already holding position
    strategy.positions['BTC-EUR'] = 1.0
    strategy.prices = [90.0, 95.0, 99.0, 100.0]  # Clear buy signal
    assert not strategy.should_buy()  # Should not buy when position exists

def test_should_sell_profit_target(strategy):
    """Test sell signal when profit target is reached"""
    strategy.prices = [100.0, 110.0, 120.0, 130.0]
    strategy.positions['BTC-EUR'] = 1.0
    strategy.entry_prices['BTC-EUR'] = 100.0
    
    # Price increased by 30% (above 15% target)
    assert strategy.should_sell()

def test_should_sell_stop_loss(strategy):
    """Test sell signal when stop loss is hit"""
    strategy.prices = [100.0, 95.0, 90.0, 85.0]
    strategy.positions['BTC-EUR'] = 1.0
    strategy.entry_prices['BTC-EUR'] = 100.0
    
    # Price decreased by 15% (below -5% stop loss)
    assert strategy.should_sell()

def test_execute_trade_buy_signal(strategy, mock_market_ops, mock_db):
    """Test trade execution on buy signal"""
    # Setup mock responses for building price history
    mock_market_ops.get_ticker.side_effect = [
        {'price': '90.0'},  # First price
        {'price': '95.0'},  # Second price
        {'price': '99.0'},  # Third price
        {'price': '100.0'}  # Fourth price - should trigger buy
    ]
    
    # Setup volume data
    mock_market_ops.get_detailed_market_info.side_effect = [
        {'volume': '40000.0'},  # Initial volume
        {'volume': '50000.0'},  # Higher volume to trigger buy
        {'volume': '60000.0'},
        {'volume': '70000.0'}
    ]
    
    # Setup market info for order placement
    mock_market_ops.get_market_info.return_value = {
        'minOrderInBaseAsset': '0.001',
        'minOrderInQuoteAsset': '10.0'
    }
    
    # Execute trades to build history
    for _ in range(4):  # Need 4 prices for long_window
        strategy.execute_trade()
        
        # Verify price history is maintained correctly
        assert len(strategy.prices) <= strategy.long_window
        if len(strategy.volumes) > 1:
            assert strategy.volumes[-1] > strategy.volumes[-2]  # Volume increasing
    
    # Verify order placement
    mock_market_ops.place_market_order.assert_called_once()
    args = mock_market_ops.place_market_order.call_args[0]
    assert args[0] == 'BTC-EUR'  # Market
    assert args[1] == 'buy'      # Side
    
    # Verify position tracking
    assert 'BTC-EUR' in strategy.positions
    mock_db.record_trade_entry.assert_called_once()

def test_execute_trade_sell_signal(strategy, mock_market_ops, mock_db):
    """Test trade execution on sell signal"""
    # Setup mock responses
    mock_market_ops.get_ticker.return_value = {'price': '120.0'}
    mock_market_ops.get_detailed_market_info.return_value = {'volume': '50000.0'}
    
    # Setup conditions for sell (20% profit)
    strategy.prices = [100.0, 110.0, 115.0, 120.0]
    strategy.positions['BTC-EUR'] = 1.0
    strategy.entry_prices['BTC-EUR'] = 100.0  # Current price is 20% higher
    
    strategy.execute_trade()
    
    # Verify order placement
    mock_market_ops.place_market_order.assert_called_once_with('BTC-EUR', 'sell', 1.0)
    
    # Verify position tracking
    assert 'BTC-EUR' not in strategy.positions
    mock_db.record_trade_exit.assert_called_once()

def test_execute_trade_minimum_requirements(strategy, mock_market_ops):
    """Test trade execution respects minimum order requirements"""
    # Set small investment amount
    strategy.investment_amount = 1.0  # Small investment
    
    # Setup mock responses for building price history
    mock_market_ops.get_ticker.side_effect = [
        {'price': '90.0'},  # First price
        {'price': '95.0'},  # Second price
        {'price': '99.0'},  # Third price
        {'price': '100.0'}  # Fourth price - should trigger buy
    ]
    
    # Setup volume data
    mock_market_ops.get_detailed_market_info.side_effect = [
        {'volume': '40000.0'},  # Initial volume
        {'volume': '50000.0'},  # Higher volume to trigger buy
        {'volume': '60000.0'},
        {'volume': '70000.0'}
    ]
    
    # Setup market info with high minimum requirements
    mock_market_ops.get_market_info.return_value = {
        'minOrderInBaseAsset': '0.1',  # High minimum to force adjustment
        'minOrderInQuoteAsset': '10.0'
    }
    
    # Execute trades to build history
    for _ in range(4):  # Need 4 prices for long_window
        strategy.execute_trade()
    
    # Verify order placement and minimum requirements
    mock_market_ops.place_market_order.assert_called_once()
    args = mock_market_ops.place_market_order.call_args[0]
    amount = float(args[2])
    assert amount >= 0.1  # Should meet minimum base asset requirement
    assert amount * 100.0 >= 10.0  # Should meet minimum quote asset requirement

def test_execute_trade_error_handling(strategy, mock_market_ops):
    """Test error handling during trade execution"""
    mock_market_ops.get_ticker.side_effect = APIConnectionError("API Error")
    
    # Should not raise exception
    strategy.execute_trade()
    
    # No positions should be opened
    assert len(strategy.positions) == 0

def test_position_limit(strategy, mock_market_ops):
    """Test maximum position limit"""
    # Setup three existing positions
    strategy.positions = {
        'BTC-EUR': 1.0,
        'ETH-EUR': 1.0,
        'ADA-EUR': 1.0
    }
    strategy.entry_prices = {
        'BTC-EUR': 100.0,
        'ETH-EUR': 100.0,
        'ADA-EUR': 100.0
    }
    
    # Setup buy conditions
    strategy.prices = [100.0, 110.0, 120.0, 140.0]
    strategy.volumes = [40000.0, 50000.0]
    
    strategy.execute_trade()
    
    # Verify no new position was opened (max limit is 3)
    assert len(strategy.positions) == 3
    mock_market_ops.place_market_order.assert_not_called()