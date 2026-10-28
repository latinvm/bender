"""Shared builders for the log-analysis tests."""

import numpy as np
import pandas as pd

FIVE_MIN = pd.Timedelta(minutes=5)
T0 = pd.Timestamp('2026-09-01 00:00')


def candle_frame(closes, start=T0):
    closes = np.asarray(closes, dtype=float)
    index = pd.date_range(start, periods=len(closes), freq='5min', name='timestamp')
    return pd.DataFrame({'open': closes, 'high': closes * 1.001, 'low': closes * 0.999,
                         'close': closes, 'volume': 1000.0}, index=index)


def flat_snapshots(prices, rsi):
    """Snapshot frame with constant indicators: rsi decides buy (<40) / sell (>60, MACD bearish)."""
    index = pd.date_range(T0, periods=len(prices), freq='5min')
    return pd.DataFrame({'rsi': rsi, 'macd': -1.0, 'macd_signal': 0.0, 'close': prices, 'price': prices,
                         'bb_lower': 0.0, 'bb_upper': 1e9, 'trend_1d': np.nan, 'trend_7d': np.nan}, index=index)
