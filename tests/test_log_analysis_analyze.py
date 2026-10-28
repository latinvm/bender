"""Helpers of the run analysis."""

import sqlite3

import pytest

from tools.log_analysis.analyze import median_spreads


def test_median_spreads_from_scores():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE market_scores (market TEXT, spread_pct REAL)')
    conn.executemany('INSERT INTO market_scores VALUES (?, ?)', [('A-EUR', 0.1), ('A-EUR', 0.3), ('A-EUR', 0.2), ('B-EUR', None)])
    assert median_spreads(conn) == {'A-EUR': pytest.approx(0.001)}
