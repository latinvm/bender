"""Structured decision log and quieter, rotating text logs.

The 13 Aug - 28 Oct run wrote a single 1 GB text file: ~10 lines per market
per minute that had to be reverse-parsed to learn anything. Each evaluation
now emits one JSON decision record (logger 'trader.decisions'), the per-check
chatter moves to DEBUG, and log files roll over daily.
"""

import json
import logging
import time
from unittest.mock import Mock

import pandas as pd
import pytest

from trader.enhanced_strategy import EnhancedStrategy
from trader.logger import DailyFileHandler, log_level_from_env

FIVE_MINUTES_MS = 5 * 60 * 1000
START_MS = 1_756_000_000_000


def candles(closes):
    """Oldest-first candles, as MarketOperations.get_historical_candles returns them."""
    return [[START_MS + i * FIVE_MINUTES_MS, str(c), str(c * 1.001), str(c * 0.999), str(c), '1000']
            for i, c in enumerate(closes)]


RISING = [1.0 + i * 0.01 for i in range(100)]   # RSI 100: no buy signal
FALLING = [2.0 - i * 0.01 for i in range(100)]  # RSI 0: strong oversold


def make_strategy(closes, active_positions=(), ticker='1.5'):
    ops = Mock()
    ops.get_historical_candles.return_value = candles(closes)
    ops.get_ticker.return_value = {'price': ticker}
    ops.place_market_order.return_value = {'orderId': '1'}
    wallet = Mock()
    wallet.get_active_positions.return_value = list(active_positions)
    return EnhancedStrategy(ops, 'TEST-EUR', virtual_wallet=wallet)


def decisions(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == 'trader.decisions']


@pytest.fixture
def capture(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


class TestDecisionRecords:
    def test_each_evaluation_records_one_decision(self, capture):
        make_strategy(RISING, ticker='1.995').execute_trade()

        [decision] = decisions(capture)
        assert decision['market'] == 'TEST-EUR'
        assert decision['action'] == 'monitor'
        assert decision['price'] == pytest.approx(1.995)
        assert decision['candle_close'] == pytest.approx(RISING[-1])
        assert decision['candle_ts'] == pd.Timestamp(START_MS + 99 * FIVE_MINUTES_MS, unit='ms').isoformat()
        assert decision['rsi'] == pytest.approx(100.0)
        for field in ('macd', 'macd_signal', 'bb_lower', 'bb_upper', 'ts', 'entry_price', 'reason'):
            assert field in decision

    def test_buy_is_recorded_with_its_reason(self, capture):
        make_strategy(FALLING).execute_trade()

        [decision] = decisions(capture)
        assert decision['action'] == 'buy'
        assert decision['reason'] == 'Strong Oversold'

    def test_buy_blocked_by_position_limit_is_recorded(self, capture):
        held = [{'market': m, 'amount': 1.0, 'entry_price': 1.0} for m in ('A-EUR', 'B-EUR', 'C-EUR')]

        make_strategy(FALLING, active_positions=held).execute_trade()

        [decision] = decisions(capture)
        assert decision['action'] == 'blocked_position_limit'
        assert decision['reason'] == 'Strong Oversold'

    def test_failed_evaluation_is_recorded(self, capture):
        strategy = make_strategy(RISING)
        strategy.market_ops.get_historical_candles.side_effect = RuntimeError('boom')

        strategy.execute_trade()

        [decision] = decisions(capture)
        assert decision['action'] == 'error'
        assert 'boom' in decision['reason']


def test_quiet_cycle_logs_nothing_at_info(capture):
    make_strategy(RISING).execute_trade()

    chatter = [r for r in capture.records
               if r.name in ('trader.enhanced_strategy', 'trader.market') and r.levelno >= logging.INFO]
    assert chatter == []


class TestDailyFileHandler:
    def _record(self, when, message):
        record = logging.LogRecord('trader', logging.INFO, __file__, 1, message, None, None)
        record.created = when
        return record

    def test_switches_file_when_the_day_changes(self, tmp_path):
        day1 = time.mktime((2026, 8, 13, 23, 59, 0, 0, 0, -1))
        handler = DailyFileHandler(tmp_path, suffix='.log', clock=lambda: day1)

        handler.handle(self._record(day1, 'first'))
        handler.handle(self._record(day1 + 120, 'second'))
        handler.close()

        assert (tmp_path / '2026-08-13.log').read_text().strip() == 'first'
        assert (tmp_path / '2026-08-14.log').read_text().strip() == 'second'

    def test_prefix_and_suffix_name_the_file(self, tmp_path):
        day1 = time.mktime((2026, 8, 13, 12, 0, 0, 0, 0, -1))
        handler = DailyFileHandler(tmp_path, prefix='decisions-', suffix='.jsonl', clock=lambda: day1)

        handler.handle(self._record(day1, '{}'))
        handler.close()

        assert (tmp_path / 'decisions-2026-08-13.jsonl').exists()


@pytest.mark.parametrize('value, expected', [
    (None, logging.INFO), ('debug', logging.DEBUG), ('WARNING', logging.WARNING), ('nonsense', logging.INFO)])
def test_log_level_from_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv('LOG_LEVEL', raising=False)
    else:
        monkeypatch.setenv('LOG_LEVEL', value)

    assert log_level_from_env() == expected
