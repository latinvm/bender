import pytest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from datetime import datetime
from trader.enhanced_strategy import EnhancedStrategy


@pytest.fixture
def mock_market_ops():
    """Fixture for mocked MarketOperations"""
    mock = Mock()
    mock.client = Mock()
    mock.client.bitvavo = Mock()

    # Mock candles data for technical indicators
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
    with patch('trader.enhanced_strategy.TradeDatabase') as mock_db_class:
        mock_db = Mock()
        mock_db.get_active_positions.return_value = []
        mock_db.record_trade_entry.return_value = None
        mock_db.record_trade_exit.return_value = None
        mock_db_class.return_value = mock_db
        yield mock_db


@pytest.fixture
def strategy(mock_market_ops, mock_trade_db):
    """Fixture for EnhancedStrategy instance"""
    return EnhancedStrategy(
        market_ops=mock_market_ops,
        market='TEST-EUR',
        investment_amount=10.0,
        virtual_wallet=None,
        max_positions=3,
        stop_loss_pct=5.0,
        take_profit_pct=15.0
    )


@pytest.fixture
def sample_df():
    """Create a sample dataframe with technical indicators"""
    df = pd.DataFrame({
        'open': [100.0] * 100,
        'high': [110.0] * 100,
        'low': [95.0] * 100,
        'close': [105.0] * 100,
        'volume': [1000.0] * 100
    })
    df.index = pd.date_range(start='2024-01-01', periods=100, freq='5min')
    return df


class TestEnhancedStrategyInitialization:
    """Test EnhancedStrategy initialization"""

    def test_init_default_parameters(self, mock_market_ops, mock_trade_db):
        """Test initialization with default parameters"""
        strategy = EnhancedStrategy(
            market_ops=mock_market_ops,
            market='BTC-EUR',
            investment_amount=10.0
        )

        assert strategy.market == 'BTC-EUR'
        assert strategy.investment_amount == 10.0
        assert strategy.max_positions == 3
        assert strategy.stop_loss_pct == 5.0
        assert strategy.take_profit_pct == 15.0
        assert strategy.positions == {}
        assert strategy.entry_prices == {}
        assert strategy.last_price is None
        assert strategy.last_price_timestamp is None

    def test_init_custom_parameters(self, mock_market_ops, mock_trade_db):
        """Test initialization with custom parameters"""
        strategy = EnhancedStrategy(
            market_ops=mock_market_ops,
            market='ETH-EUR',
            investment_amount=20.0,
            max_positions=5,
            stop_loss_pct=10.0,
            take_profit_pct=25.0
        )

        assert strategy.market == 'ETH-EUR'
        assert strategy.investment_amount == 20.0
        assert strategy.max_positions == 5
        assert strategy.stop_loss_pct == 10.0
        assert strategy.take_profit_pct == 25.0

    def test_init_loads_active_positions(self, mock_market_ops):
        """Test that initialization loads existing active positions"""
        with patch('trader.enhanced_strategy.TradeDatabase') as mock_db_class:
            mock_db = Mock()
            mock_db.get_active_positions.return_value = [
                {
                    'market': 'BTC-EUR',
                    'amount': 0.5,
                    'entry_price': 30000.0
                }
            ]
            mock_db_class.return_value = mock_db

            strategy = EnhancedStrategy(
                market_ops=mock_market_ops,
                market='BTC-EUR',
                investment_amount=10.0
            )

            assert 'BTC-EUR' in strategy.positions
            assert strategy.positions['BTC-EUR'] == 0.5
            assert strategy.entry_prices['BTC-EUR'] == 30000.0

    def test_init_with_virtual_wallet(self, mock_market_ops):
        """Test initialization with virtual wallet"""
        mock_wallet = Mock()
        mock_wallet.get_active_positions.return_value = []

        strategy = EnhancedStrategy(
            market_ops=mock_market_ops,
            market='ADA-EUR',
            investment_amount=10.0,
            virtual_wallet=mock_wallet
        )

        assert strategy.virtual_wallet == mock_wallet
        mock_wallet.get_active_positions.assert_called_once()


class TestBuySignals:
    """Test all three buy signals"""

    def test_buy_signal_1_strong_oversold(self, strategy, sample_df):
        """Test Signal 1: Strong Oversold (RSI < 40)"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Set RSI to trigger signal 1
        df.loc[df.index[-1], 'RSI_14'] = 35.0
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.5
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.4
        df.loc[df.index[-1], 'BBL_20_2.0_2.0'] = 90.0

        should_buy, reason = strategy.should_buy(df)

        assert should_buy is True
        assert reason == "Strong Oversold"

    def test_buy_signal_2_moderate_oversold_with_momentum(self, strategy, sample_df):
        """Test Signal 2: Moderate Oversold + Momentum (RSI < 50 AND MACD > Signal)"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Set indicators to trigger signal 2
        df.loc[df.index[-1], 'RSI_14'] = 48.0  # Below 50
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.6  # MACD > Signal
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.5
        df.loc[df.index[-1], 'BBL_20_2.0_2.0'] = 90.0

        should_buy, reason = strategy.should_buy(df)

        assert should_buy is True
        assert reason == "Moderate Oversold + Momentum"

    def test_buy_signal_3_near_support_with_momentum(self, strategy, sample_df):
        """Test Signal 3: Near Support + Momentum (Price < Lower BB * 1.01 AND MACD crossing)"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Set indicators to trigger signal 3
        df.loc[df.index[-1], 'RSI_14'] = 55.0  # Above 50
        df.loc[df.index[-1], 'close'] = 99.0  # Price near lower band
        df.loc[df.index[-1], 'BBL_20_2.0_2.0'] = 98.5  # Lower band
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.5  # MACD crossing signal
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.5

        should_buy, reason = strategy.should_buy(df)

        assert should_buy is True
        assert reason == "Near Support + Momentum"

    def test_no_buy_signal(self, strategy, sample_df):
        """Test that no buy signal is triggered when conditions aren't met"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Set indicators to NOT trigger any signal
        df.loc[df.index[-1], 'RSI_14'] = 55.0  # Above 40
        df.loc[df.index[-1], 'close'] = 105.0
        df.loc[df.index[-1], 'BBL_20_2.0_2.0'] = 95.0  # Price not near lower band
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.4  # MACD < Signal
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.5

        should_buy, reason = strategy.should_buy(df)

        assert should_buy is False
        assert reason == ""

    def test_buy_signal_priority(self, strategy, sample_df):
        """Test that Signal 1 has priority when multiple signals are active"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Trigger all signals - Signal 1 should be returned
        df.loc[df.index[-1], 'RSI_14'] = 35.0  # Triggers signal 1
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.6  # Triggers signal 2
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.5
        df.loc[df.index[-1], 'close'] = 99.0
        df.loc[df.index[-1], 'BBL_20_2.0_2.0'] = 98.5  # Triggers signal 3

        should_buy, reason = strategy.should_buy(df)

        assert should_buy is True
        assert reason == "Strong Oversold"


class TestSellSignals:
    """Test sell signal logic"""

    def test_sell_no_position(self, strategy, sample_df):
        """Test that no sell signal when no position exists"""
        df = strategy.calculate_indicators(sample_df.copy())

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is False
        assert reason == ""

    def test_sell_technical_signal(self, strategy, sample_df):
        """Test technical sell signal (RSI > 60 AND MACD < Signal)"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Create a position
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 105.0
        strategy.last_price_timestamp = datetime.now().timestamp()

        # Set indicators to trigger technical sell
        df.loc[df.index[-1], 'RSI_14'] = 65.0  # RSI > 60
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.4  # MACD < Signal
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.5
        df.loc[df.index[-1], 'BBU_20_2.0_2.0'] = 115.0

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is True
        assert "Technical" in reason

    def test_sell_take_profit(self, strategy, sample_df):
        """Test take profit sell signal (P/L >= +15%)"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Create a position with profitable entry
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 116.0  # 16% profit
        strategy.last_price_timestamp = datetime.now().timestamp()

        # Set indicators to NOT trigger technical sell
        df.loc[df.index[-1], 'RSI_14'] = 55.0
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.5
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.4

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is True
        assert "Take Profit" in reason

    def test_sell_stop_loss(self, strategy, sample_df):
        """Test stop loss sell signal (P/L <= -5%)"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Create a position with losing entry
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 94.0  # -6% loss
        strategy.last_price_timestamp = datetime.now().timestamp()

        # Set indicators to NOT trigger technical sell
        df.loc[df.index[-1], 'RSI_14'] = 55.0
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.5
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.4

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is True
        assert "Stop Loss" in reason

    def test_sell_custom_stop_loss(self, mock_market_ops, mock_trade_db):
        """Test stop loss with custom percentage"""
        strategy = EnhancedStrategy(
            market_ops=mock_market_ops,
            market='TEST-EUR',
            investment_amount=10.0,
            stop_loss_pct=10.0  # Custom 10% stop loss
        )

        df = pd.DataFrame({
            'close': [100.0] * 100,
            'RSI_14': [55.0] * 100,
            'MACD_12_26_9': [0.5] * 100,
            'MACDs_12_26_9': [0.4] * 100,
            'BBU_20_2.0_2.0': [110.0] * 100,
            'BBL_20_2.0_2.0': [90.0] * 100
        })

        # Create a losing position
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 89.0  # -11% loss
        strategy.last_price_timestamp = datetime.now().timestamp()

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is True
        assert "Stop Loss" in reason

    def test_sell_custom_take_profit(self, mock_market_ops, mock_trade_db):
        """Test take profit with custom percentage"""
        strategy = EnhancedStrategy(
            market_ops=mock_market_ops,
            market='TEST-EUR',
            investment_amount=10.0,
            take_profit_pct=25.0  # Custom 25% take profit
        )

        df = pd.DataFrame({
            'close': [100.0] * 100,
            'RSI_14': [55.0] * 100,
            'MACD_12_26_9': [0.5] * 100,
            'MACDs_12_26_9': [0.4] * 100,
            'BBU_20_2.0_2.0': [110.0] * 100,
            'BBL_20_2.0_2.0': [90.0] * 100
        })

        # Create a profitable position
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 126.0  # +26% profit
        strategy.last_price_timestamp = datetime.now().timestamp()

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is True
        assert "Take Profit" in reason

    def test_no_sell_signal(self, strategy, sample_df):
        """Test that no sell signal when conditions aren't met"""
        df = strategy.calculate_indicators(sample_df.copy())

        # Create a position with small profit
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 102.0  # +2% profit (not enough)
        strategy.last_price_timestamp = datetime.now().timestamp()

        # Set indicators to NOT trigger technical sell
        df.loc[df.index[-1], 'RSI_14'] = 55.0  # RSI not > 60
        df.loc[df.index[-1], 'MACD_12_26_9'] = 0.5
        df.loc[df.index[-1], 'MACDs_12_26_9'] = 0.4

        should_sell, reason = strategy.should_sell(df)

        assert should_sell is False
        assert reason == ""


class TestPriceCaching:
    """Test price caching functionality"""

    def test_get_current_price_fresh_fetch(self, strategy):
        """Test fetching fresh price (no cache)"""
        strategy.market_ops.get_ticker.return_value = {'price': '105.50'}

        price = strategy.get_current_price(use_cache=False)

        assert price == 105.50
        assert strategy.last_price == 105.50
        assert strategy.last_price_timestamp is not None
        strategy.market_ops.get_ticker.assert_called_once_with('TEST-EUR')

    def test_get_current_price_use_cache(self, strategy):
        """Test using cached price when fresh enough"""
        import time

        # Set cached price
        strategy.last_price = 100.0
        strategy.last_price_timestamp = time.time()

        price = strategy.get_current_price(use_cache=True, cache_max_age=30.0)

        assert price == 100.0
        # Should not call API when cache is fresh
        strategy.market_ops.get_ticker.assert_not_called()

    def test_get_current_price_expired_cache(self, strategy):
        """Test fetching new price when cache is expired"""
        import time

        # Set old cached price
        strategy.last_price = 100.0
        strategy.last_price_timestamp = time.time() - 60.0  # 60 seconds ago
        strategy.market_ops.get_ticker.return_value = {'price': '105.50'}

        price = strategy.get_current_price(use_cache=True, cache_max_age=30.0)

        assert price == 105.50
        strategy.market_ops.get_ticker.assert_called_once()

    def test_get_current_price_no_cache_set(self, strategy):
        """Test fetching price when no cache exists"""
        strategy.market_ops.get_ticker.return_value = {'price': '99.99'}

        price = strategy.get_current_price(use_cache=True)

        assert price == 99.99
        strategy.market_ops.get_ticker.assert_called_once()

    def test_get_current_price_api_error(self, strategy):
        """Test handling API error with cached fallback"""
        import time

        # Set cached price
        strategy.last_price = 100.0
        strategy.last_price_timestamp = time.time()

        # Make API call fail
        strategy.market_ops.get_ticker.side_effect = Exception("API Error")

        price = strategy.get_current_price(use_cache=False)

        # Should return cached price as fallback
        assert price == 100.0

    def test_get_current_price_api_error_no_cache(self, strategy):
        """Test handling API error with no cached fallback"""
        strategy.market_ops.get_ticker.side_effect = Exception("API Error")

        price = strategy.get_current_price(use_cache=False)

        # Should return None when no cache available
        assert price is None


class TestExecuteTrade:
    """Test trade execution logic"""

    def test_execute_buy_success(self, strategy, mock_market_ops):
        """Test successful buy execution"""
        mock_market_ops.get_ticker.return_value = {'price': '100.00'}
        mock_market_ops.place_market_order.return_value = {
            'orderId': '12345',
            'status': 'filled'
        }

        # Create mock dataframe with buy signal
        with patch.object(strategy, 'get_historical_data') as mock_get_data:
            df = pd.DataFrame({
                'close': [100.0] * 100,
                'high': [105.0] * 100,
                'low': [95.0] * 100,
                'open': [100.0] * 100,
                'volume': [1000.0] * 100
            })
            df.index = pd.date_range(start='2024-01-01', periods=100, freq='5min')
            df = strategy.calculate_indicators(df)

            # Set buy signal
            df.loc[df.index[-1], 'RSI_14'] = 35.0

            mock_get_data.return_value = df

            strategy.execute_trade()

            # Verify buy was executed
            assert 'TEST-EUR' in strategy.positions
            assert strategy.entry_prices['TEST-EUR'] == 100.0
            mock_market_ops.place_market_order.assert_called_once()

    def test_execute_sell_success(self, strategy, mock_market_ops):
        """Test successful sell execution"""
        # Set up position
        strategy.positions['TEST-EUR'] = 100.0
        strategy.entry_prices['TEST-EUR'] = 100.0
        strategy.last_price = 116.0  # Trigger take profit
        strategy.last_price_timestamp = datetime.now().timestamp()

        mock_market_ops.get_ticker.return_value = {'price': '116.00'}
        mock_market_ops.place_market_order.return_value = {
            'orderId': '12345',
            'status': 'filled'
        }

        with patch.object(strategy, 'get_historical_data') as mock_get_data:
            df = pd.DataFrame({
                'close': [116.0] * 100,
                'RSI_14': [55.0] * 100,
                'MACD_12_26_9': [0.5] * 100,
                'MACDs_12_26_9': [0.4] * 100,
                'BBU_20_2.0_2.0': [120.0] * 100
            })
            df.index = pd.date_range(start='2024-01-01', periods=100, freq='5min')
            mock_get_data.return_value = df

            strategy.execute_trade()

            # Verify sell was executed
            assert 'TEST-EUR' not in strategy.positions
            assert 'TEST-EUR' not in strategy.entry_prices
            mock_market_ops.place_market_order.assert_called_once()

    def test_execute_buy_position_limit_reached(self, strategy, mock_market_ops, mock_trade_db):
        """Test that buy is blocked when position limit is reached"""
        # Mock active positions at limit
        mock_trade_db.get_active_positions.return_value = [
            {'market': 'BTC-EUR', 'amount': 0.1, 'entry_price': 30000.0},
            {'market': 'ETH-EUR', 'amount': 1.0, 'entry_price': 2000.0},
            {'market': 'ADA-EUR', 'amount': 1000.0, 'entry_price': 1.0}
        ]

        with patch.object(strategy, 'get_historical_data') as mock_get_data:
            df = pd.DataFrame({
                'close': [100.0] * 100,
                'high': [105.0] * 100,
                'low': [95.0] * 100,
                'open': [100.0] * 100,
                'volume': [1000.0] * 100
            })
            df.index = pd.date_range(start='2024-01-01', periods=100, freq='5min')
            df = strategy.calculate_indicators(df)

            # Set buy signal
            df.loc[df.index[-1], 'RSI_14'] = 35.0

            mock_get_data.return_value = df

            strategy.execute_trade()

            # Verify buy was NOT executed
            assert 'TEST-EUR' not in strategy.positions
            mock_market_ops.place_market_order.assert_not_called()

    def test_execute_trade_api_error(self, strategy):
        """Test handling of API errors during trade execution"""
        with patch.object(strategy, 'get_historical_data') as mock_get_data:
            mock_get_data.side_effect = Exception("API Connection Error")

            # Should not raise exception
            strategy.execute_trade()

            # Position should not be created
            assert 'TEST-EUR' not in strategy.positions


class TestCalculateIndicators:
    """Test technical indicator calculation"""

    def test_calculate_indicators_adds_all_required(self, strategy, sample_df):
        """Test that all required indicators are added"""
        df = strategy.calculate_indicators(sample_df)

        # Check that all required indicators are present
        assert 'RSI_14' in df.columns
        assert 'MACD_12_26_9' in df.columns
        assert 'MACDs_12_26_9' in df.columns
        assert 'BBL_20_2.0_2.0' in df.columns
        assert 'BBM_20_2.0_2.0' in df.columns
        assert 'BBU_20_2.0_2.0' in df.columns

    def test_calculate_indicators_preserves_original_data(self, strategy, sample_df):
        """Test that original OHLCV data is preserved"""
        df = strategy.calculate_indicators(sample_df)

        assert 'open' in df.columns
        assert 'high' in df.columns
        assert 'low' in df.columns
        assert 'close' in df.columns
        assert 'volume' in df.columns


class TestGetHistoricalData:
    """Test historical data retrieval"""

    def test_get_historical_data_default_params(self, strategy):
        """Test getting historical data with default parameters"""
        df = strategy.get_historical_data()

        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert list(df.columns) == ['open', 'high', 'low', 'close', 'volume']
        strategy.market_ops.client.bitvavo.candles.assert_called_with(
            'TEST-EUR', '5m', {'limit': 100}
        )

    def test_get_historical_data_custom_params(self, strategy):
        """Test getting historical data with custom parameters"""
        df = strategy.get_historical_data(interval='1h', limit=200)

        assert isinstance(df, pd.DataFrame)
        strategy.market_ops.client.bitvavo.candles.assert_called_with(
            'TEST-EUR', '1h', {'limit': 200}
        )
