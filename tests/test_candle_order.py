"""Candle ordering: Bitvavo returns candles newest-first.

Everything downstream assumes oldest-first: indicators are computed forward
in time, df.iloc[-1] is read as the current candle, and the market scorer
builds return series from consecutive closes. Before this fix live trading
computed every indicator on time-reversed candles and read the oldest of the
100 candles (8-40 hours old) as "now", and the scorer's Sharpe/Sortino had
their sign flipped.
"""

from unittest.mock import Mock, patch

import numpy as np

from trader.enhanced_strategy import EnhancedStrategy

FIVE_MINUTES_MS = 5 * 60 * 1000


def newest_first_candles(closes_oldest_first, start_ms=1_756_000_000_000):
    """Build candles the way the Bitvavo API returns them (newest first)."""
    rows = [
        [start_ms + i * FIVE_MINUTES_MS, str(c), str(c * 1.001), str(c * 0.999), str(c), '1000']
        for i, c in enumerate(closes_oldest_first)
    ]
    return list(reversed(rows))


def market_ops_returning(candles):
    from trader.market import MarketOperations
    bitvavo = Mock()
    bitvavo.candles.return_value = candles
    with patch('trader.market.TradeDatabase'):
        client = Mock()
        client.bitvavo = bitvavo
        return MarketOperations(client)


def strategy_over(closes_oldest_first):
    wallet = Mock()
    wallet.get_active_positions.return_value = []
    return EnhancedStrategy(
        market_ops=market_ops_returning(newest_first_candles(closes_oldest_first)),
        market='TEST-EUR',
        virtual_wallet=wallet,
    )


class TestGetHistoricalCandles:
    def test_returns_oldest_first_when_api_returns_newest_first(self):
        ops = market_ops_returning(newest_first_candles([1.0, 2.0, 3.0]))

        candles = ops.get_historical_candles('TEST-EUR', interval='5m', limit=3)

        assert [float(c[4]) for c in candles] == [1.0, 2.0, 3.0]


class TestStrategySeesTheCurrentMarket:
    def test_last_row_is_the_newest_candle(self):
        closes = list(np.linspace(1.0, 2.0, 100))

        df = strategy_over(closes).get_historical_data()

        assert df.index.is_monotonic_increasing
        assert df['close'].iloc[-1] == closes[-1]

    def test_steady_decline_reads_as_oversold(self):
        strategy = strategy_over(list(np.linspace(2.0, 1.0, 100)))

        df = strategy.calculate_indicators(strategy.get_historical_data())

        assert df['RSI_14'].iloc[-1] < 30
