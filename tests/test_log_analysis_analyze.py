"""Helpers of the run analysis."""

import sqlite3

import pandas as pd
import pytest

from tests.log_analysis_helpers import hourly_random_walk
from tools.log_analysis.analyze import PERIODS, bars_for, median_spreads, rule_study
from tools.log_analysis.candles import CandleStore


def test_median_spreads_from_scores():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE market_scores (market TEXT, spread_pct REAL)')
    conn.executemany('INSERT INTO market_scores VALUES (?, ?)', [('A-EUR', 0.1), ('A-EUR', 0.3), ('A-EUR', 0.2), ('B-EUR', None)])
    assert median_spreads(conn) == {'A-EUR': pytest.approx(0.001)}


@pytest.mark.parametrize('horizon, interval, bars', [('4h', '5m', 48), ('24h', '1h', 24), ('1h', '1h', 1)])
def test_bars_for(horizon, interval, bars):
    assert bars_for(pd.Timedelta(horizon), interval) == bars


def test_rule_study_runs_on_hourly_candles_and_skips_markets_without_data(tmp_path):
    store = CandleStore(tmp_path / 'c1h.db')
    store.save('A-EUR', hourly_random_walk('2026-05-01', '2026-10-29'))
    store.save('EMPTY-EUR', [])
    md, result = rule_study(['A-EUR', 'EMPTY-EUR'], str(tmp_path / 'c1h.db'), interval='1h')
    assert {r['period'] for r in result['stats']} == set(PERIODS)
    assert {r['markets'] for r in result['stats']} == {1}
