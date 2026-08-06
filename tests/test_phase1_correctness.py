"""Tests for Phase 1 correctness fixes: Bitvavo error-dict validation,
Sharpe/Sortino NaN handling, and configurable strategy thresholds."""

import numpy as np
import pytest
from unittest.mock import Mock, patch

from trader.bitvavo import check_bitvavo_response
from trader.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BitvavoError,
    MarketNotFoundError,
    RateLimitError,
)
from trader.main import calculate_sharpe_ratio, calculate_sortino_ratio


class TestCheckBitvavoResponse:
    def test_passes_through_valid_list(self):
        data = [{'market': 'BTC-EUR'}]
        assert check_bitvavo_response(data) is data

    def test_passes_through_valid_dict(self):
        data = {'price': '30000', 'market': 'BTC-EUR'}
        assert check_bitvavo_response(data) is data

    def test_rate_limit_error(self):
        with pytest.raises(RateLimitError):
            check_bitvavo_response({'errorCode': 105, 'error': 'Your IP is banned'})

    def test_rate_limit_by_message(self):
        with pytest.raises(RateLimitError):
            check_bitvavo_response({'errorCode': 101, 'error': 'Rate limit exceeded'})

    def test_authentication_error(self):
        with pytest.raises(AuthenticationError):
            check_bitvavo_response({'errorCode': 301, 'error': 'API key must be of length 64'})

    def test_market_not_found(self):
        with pytest.raises(MarketNotFoundError):
            check_bitvavo_response({'errorCode': 205, 'error': 'market does not exist'})

    def test_generic_error(self):
        with pytest.raises(BitvavoError):
            check_bitvavo_response({'errorCode': 216, 'error': 'Insufficient funds'})

    def test_context_in_message(self):
        with pytest.raises(BitvavoError, match='ticker BTC-EUR'):
            check_bitvavo_response({'errorCode': 216, 'error': 'nope'}, 'ticker BTC-EUR')


class TestMarketOpsSurfaceTypedErrors:
    """Error dicts from the client must surface as typed exceptions, not KeyErrors."""

    def _ops(self, bitvavo_mock):
        from trader.market import MarketOperations
        with patch('trader.market.TradeDatabase'):
            client = Mock()
            client.bitvavo = bitvavo_mock
            return MarketOperations(client)

    def test_ticker_error_dict(self):
        bitvavo = Mock()
        bitvavo.tickerPrice.return_value = {'errorCode': 205, 'error': 'market does not exist'}
        ops = self._ops(bitvavo)
        with pytest.raises(MarketNotFoundError):
            ops.get_ticker('NOPE-EUR')

    def test_ticker_missing_price(self):
        bitvavo = Mock()
        bitvavo.tickerPrice.return_value = {'market': 'BTC-EUR'}  # no price key
        ops = self._ops(bitvavo)
        with pytest.raises(APIConnectionError, match='no price'):
            ops.get_ticker('BTC-EUR')

    def test_balance_rate_limit(self):
        bitvavo = Mock()
        bitvavo.balance.return_value = {'errorCode': 105, 'error': 'banned'}
        ops = self._ops(bitvavo)
        with pytest.raises(RateLimitError):
            ops.get_balance()

    def test_candles_error_dict(self):
        bitvavo = Mock()
        bitvavo.candles.return_value = {'errorCode': 216, 'error': 'something broke'}
        ops = self._ops(bitvavo)
        with pytest.raises(BitvavoError):
            ops.get_historical_candles('BTC-EUR')


class TestRatioEdgeCases:
    def test_sharpe_empty_series(self):
        assert calculate_sharpe_ratio(np.array([])) == 0.0

    def test_sharpe_constant_series(self):
        assert calculate_sharpe_ratio(np.array([0.01] * 20)) == 0.0

    def test_sharpe_normal_series(self):
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
        result = calculate_sharpe_ratio(returns)
        assert np.isfinite(result)

    def test_sortino_empty_series(self):
        assert calculate_sortino_ratio(np.array([])) == 0.0

    def test_sortino_all_positive_returns_high_score_not_nan(self):
        # This used to return NaN (std of empty downside array) and poison
        # the market ranking
        result = calculate_sortino_ratio(np.array([0.01, 0.02, 0.03]))
        assert result == 1.0

    def test_sortino_all_zero_returns_zero(self):
        assert calculate_sortino_ratio(np.array([0.0, 0.0, 0.0])) == 0.0

    def test_sortino_normal_series_finite(self):
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
        assert np.isfinite(calculate_sortino_ratio(returns))

    def test_sortino_single_downside_value_not_nan(self):
        result = calculate_sortino_ratio(np.array([0.02, 0.03, -0.01]))
        assert np.isfinite(result)


class TestConfigurableThresholds:
    def test_config_defaults(self, monkeypatch):
        for var in ('RSI_BUY_STRONG', 'RSI_BUY_MODERATE', 'RSI_SELL'):
            monkeypatch.delenv(var, raising=False)
        from trader.config import get_config
        _, _, _, strategy_config = get_config(load_env=False)
        assert strategy_config.rsi_buy_strong == 40.0
        assert strategy_config.rsi_buy_moderate == 50.0
        assert strategy_config.rsi_sell == 60.0

    def test_config_env_override(self, monkeypatch):
        monkeypatch.setenv('RSI_BUY_STRONG', '35')
        monkeypatch.setenv('RSI_BUY_MODERATE', '45')
        monkeypatch.setenv('RSI_SELL', '65')
        from trader.config import get_config
        _, _, _, strategy_config = get_config(load_env=False)
        assert strategy_config.rsi_buy_strong == 35.0
        assert strategy_config.rsi_buy_moderate == 45.0
        assert strategy_config.rsi_sell == 65.0

    def test_strategy_uses_custom_thresholds(self):
        from trader.enhanced_strategy import EnhancedStrategy
        wallet = Mock()
        wallet.get_active_positions.return_value = []
        strategy = EnhancedStrategy(
            market_ops=Mock(),
            market='TEST-EUR',
            virtual_wallet=wallet,
            rsi_buy_strong=35.0,
            rsi_buy_moderate=45.0,
            rsi_sell=65.0,
        )
        assert strategy.rsi_buy_strong == 35.0
        assert strategy.rsi_buy_moderate == 45.0
        assert strategy.rsi_sell == 65.0
