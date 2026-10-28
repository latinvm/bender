"""Replay simulator used to test strategy changes against historical candles."""

from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from trader.enhanced_strategy import EnhancedStrategy
from tools.log_analysis.replay import (
    Rules, buy_reason, full_series_snapshots, replay, sell_reason, window_snapshot)

FIVE_MIN = pd.Timedelta(minutes=5)
T0 = pd.Timestamp('2026-09-01 00:00')


def candle_frame(closes, start=T0):
    closes = np.asarray(closes, dtype=float)
    index = pd.date_range(start, periods=len(closes), freq='5min', name='timestamp')
    return pd.DataFrame({'open': closes, 'high': closes * 1.001, 'low': closes * 0.999,
                         'close': closes, 'volume': 1000.0}, index=index)


def random_walk(n, seed=0):
    return np.cumprod(1 + np.random.default_rng(seed).normal(0, 0.004, n))


def live_strategy(positions=None):
    wallet = Mock()
    wallet.get_active_positions.return_value = []
    strategy = EnhancedStrategy(Mock(), 'TEST-EUR', virtual_wallet=wallet)
    for market, entry in (positions or {}).items():
        strategy.positions[market] = 1.0
        strategy.entry_prices[market] = entry
    return strategy


class TestRulesMatchTheLiveStrategy:
    """With default Rules the replay must make exactly the live decisions."""

    def test_buy_reasons(self):
        df = live_strategy().calculate_indicators(candle_frame(random_walk(3000)))
        df = df.dropna()
        strategy = live_strategy()
        for i in range(0, len(df), 7):
            row = df.iloc[: i + 1]
            _, live = strategy.should_buy(row)
            assert buy_reason(window_snapshot_from(row), Rules()) == (live or None)

    def test_sell_reasons(self):
        df = live_strategy().calculate_indicators(candle_frame(random_walk(3000, seed=1))).dropna()
        for i in range(0, len(df), 7):
            row = df.iloc[: i + 1]
            entry = float(df['close'].iloc[max(0, i - 30)])
            price = float(row['close'].iloc[-1])
            _, live = live_strategy({'TEST-EUR': entry}).should_sell(row, current_price=price)
            ours = sell_reason(window_snapshot_from(row), price, entry, peak=price, held=pd.Timedelta(0), rules=Rules())
            assert ours == LIVE_EXIT_NAMES[(live or '').split(' (')[0]]


LIVE_EXIT_NAMES = {'Technical': 'technical', 'Take Profit': 'take_profit', 'Stop Loss': 'stop_loss', '': None}


def window_snapshot_from(df):
    last = df.iloc[-1]
    return SimpleNamespace(rsi=last['RSI_14'], macd=last['MACD_12_26_9'], macd_signal=last['MACDs_12_26_9'],
                           close=last['close'], bb_lower=last['BBL_20_2.0_2.0'], bb_upper=last['BBU_20_2.0_2.0'])


class TestWindowSnapshot:
    def test_matches_what_the_fixed_live_code_computes(self):
        candles = candle_frame(random_walk(300))
        at = candles.index[250]
        ops = Mock()
        window = candles.loc[:at].iloc[-100:]
        ops.get_historical_candles.return_value = [
            [int(ts.value // 10**6), *row] for ts, row in zip(window.index, window.itertuples(index=False), strict=True)]
        strategy = EnhancedStrategy(ops, 'TEST-EUR', virtual_wallet=Mock(get_active_positions=Mock(return_value=[])))
        live = strategy.calculate_indicators(strategy.get_historical_data()).iloc[-1]

        snap = window_snapshot(candles, at)

        assert snap.rsi == pytest.approx(live['RSI_14'])
        assert snap.macd == pytest.approx(live['MACD_12_26_9'])
        assert snap.bb_lower == pytest.approx(live['BBL_20_2.0_2.0'])
        assert snap.close == pytest.approx(live['close'])

    def test_reversed_window_reproduces_the_candle_order_bug(self):
        candles = candle_frame(np.linspace(2.0, 1.0, 300))  # steady decline
        at = candles.index[250]

        fixed = window_snapshot(candles, at)
        buggy = window_snapshot(candles, at, reverse=True)

        assert fixed.rsi < 30 and buggy.rsi > 70
        assert buggy.close == pytest.approx(candles['close'].loc[:at].iloc[-100])  # the oldest candle

    def test_too_little_history_gives_none(self):
        candles = candle_frame(random_walk(20))
        assert window_snapshot(candles, candles.index[-1]) is None


def test_full_series_snapshots_carry_indicators_and_price():
    candles = candle_frame(random_walk(200))

    snaps = full_series_snapshots(candles)

    assert {'rsi', 'macd', 'macd_signal', 'bb_lower', 'bb_upper', 'close', 'price'} <= set(snaps.columns)
    assert snaps['price'].equals(snaps['close'])
    assert snaps['rsi'].notna().iloc[-1]


def flat_snapshots(prices, rsi):
    """Snapshot frame with constant indicators: rsi decides buy (<40) / sell (>60, MACD bearish)."""
    index = pd.date_range(T0, periods=len(prices), freq='5min')
    return pd.DataFrame({'rsi': rsi, 'macd': -1.0, 'macd_signal': 0.0, 'close': prices, 'price': prices,
                         'bb_lower': 0.0, 'bb_upper': 1e9, 'trend_1d': np.nan, 'trend_7d': np.nan}, index=index)


class TestReplayEngine:
    def test_take_profit_trade_pays_fees_both_ways(self):
        snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.2], rsi=[30, 50, 50])}

        trades = replay(snaps, rules=Rules(take_profit_pct=15.0))

        [trade] = trades.itertuples()
        assert trade.entry_price == 1.0 and trade.exit_price == 1.2
        assert trade.exit_reason == 'take_profit'
        assert trade.pl_eur == pytest.approx(10 * 1.2 * 0.9975 - 10 - 10 * 0.0025)

    def test_position_limit_blocks_the_extra_market(self):
        snaps = {m: flat_snapshots([1.0, 1.0], rsi=[30, 50]) for m in ('A-EUR', 'B-EUR', 'C-EUR')}

        trades = replay(snaps, rules=Rules(), max_positions=2)

        assert sorted(trades['market']) == ['A-EUR', 'B-EUR']

    def test_occupied_slot_counts_toward_the_limit(self):
        snaps = {'A-EUR': flat_snapshots([1.0, 1.0], rsi=[30, 50])}

        trades = replay(snaps, rules=Rules(), max_positions=1, occupied=[(T0, T0 + FIVE_MIN * 10)])

        assert trades.empty

    def test_schedule_limits_when_markets_are_evaluated(self):
        snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.0], rsi=[30, 30, 50])}
        schedule = pd.DataFrame({'t': [T0 + FIVE_MIN], 'market': ['A-EUR']})

        trades = replay(snaps, rules=Rules(), schedule=schedule)

        assert trades['entry_t'].tolist() == [T0 + FIVE_MIN]

    def test_held_market_is_still_managed_outside_the_schedule(self):
        snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 0.9], rsi=[30, 50, 50])}
        schedule = pd.DataFrame({'t': [T0], 'market': ['A-EUR']})

        trades = replay(snaps, rules=Rules(stop_loss_pct=5.0), schedule=schedule)

        assert trades['exit_reason'].tolist() == ['stop_loss']

    def test_open_position_at_the_end_is_reported_open(self):
        snaps = {'A-EUR': flat_snapshots([1.0, 1.0], rsi=[30, 50])}

        trades = replay(snaps, rules=Rules())

        assert trades['exit_t'].isna().all()

    def test_trailing_stop_exits_after_a_pullback_from_the_peak(self):
        snaps = {'A-EUR': flat_snapshots([1.0, 1.1, 1.04], rsi=[30, 50, 50])}

        trades = replay(snaps, rules=Rules(trailing_stop_pct=5.0))

        assert trades['exit_reason'].tolist() == ['trailing_stop']
        assert trades['mfe_pct'].iloc[0] == pytest.approx(10.0)


class TestUptrendFilter:
    def _snap(self, trend):
        return SimpleNamespace(rsi=30.0, macd=0.0, macd_signal=0.0, close=1.0, bb_lower=0.5, bb_upper=2.0,
                               trend_1d=trend, trend_7d=trend)

    def test_blocks_buys_in_a_downtrend(self):
        assert buy_reason(self._snap(-0.01), Rules(require_uptrend='7d')) is None

    def test_allows_buys_in_an_uptrend(self):
        assert buy_reason(self._snap(0.01), Rules(require_uptrend='7d')) == 'Strong Oversold'

    def test_unknown_trend_blocks(self):
        assert buy_reason(self._snap(float('nan')), Rules(require_uptrend='1d')) is None

    def test_full_series_snapshots_measure_price_against_its_average(self):
        rising = candle_frame(np.linspace(1.0, 2.0, 3000))

        snaps = full_series_snapshots(rising)

        assert (snaps[['trend_1d', 'trend_7d']].iloc[-1] > 0).all()
