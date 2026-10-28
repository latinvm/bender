"""Helpers of the run analysis."""

import sqlite3

import pandas as pd
import pytest

from tests.log_analysis_helpers import hourly_random_walk, random_walk
from tools.log_analysis.analyze import PERIODS, bars_for, cost_experiments, main, median_spreads, order_rules, passes_gate, rule_study
from tools.log_analysis.candles import CandleStore
from tools.log_analysis.replay import Rules


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


GOOD = dict(trades=250, avg_pl_pct=0.6)


def test_gate_requires_every_period():
    assert passes_gate({p: GOOD for p in PERIODS}, margin_pp=0.4)
    assert not passes_gate({p: GOOD for p in list(PERIODS)[:2]}, margin_pp=0.4)


def test_gate_rejects_thin_or_marginal_periods():
    stats = {p: GOOD for p in PERIODS}
    assert not passes_gate({**stats, 'live B (1-28 Oct)': dict(trades=150, avg_pl_pct=1.0)}, margin_pp=0.4)
    assert not passes_gate({**stats, 'live B (1-28 Oct)': dict(trades=250, avg_pl_pct=0.39)}, margin_pp=0.4)


def test_gate_boundary_passes_and_nan_fails():
    assert passes_gate({p: dict(trades=200, avg_pl_pct=0.4) for p in PERIODS}, margin_pp=0.4)
    stats = {p: GOOD for p in PERIODS}
    assert not passes_gate({**stats, 'live B (1-28 Oct)': dict(trades=250, avg_pl_pct=float('nan'))}, margin_pp=0.4)


@pytest.mark.parametrize('interval, timeout', [('5m', '15min'), ('1h', '3h')])
def test_limit_orders_wait_three_bars(interval, timeout):
    rules = order_rules(Rules(), 'limit', interval)
    assert (rules.entry_order, rules.take_profit_order, rules.limit_offset_pct) == ('limit', 'limit', 0.5)
    assert rules.limit_timeout == pd.Timedelta(timeout)
    assert order_rules(Rules(), 'market', interval) == Rules()


def test_cost_experiments_grid_spread_fallback_and_terciles(tmp_path):
    c5m, c1h = str(tmp_path / 'c5m.db'), str(tmp_path / 'c1h.db')
    # three days of 5-minute candles in each period, and hourly candles throughout
    five_min = [c for seed, day in enumerate(('2026-06-01', '2026-09-01', '2026-10-10'))
                for c in random_walk(day, pd.Timestamp(day) + pd.Timedelta(days=3), '5min', seed)]
    for market in ('A-EUR', 'B-EUR', 'C-EUR'):  # identical prices, different spreads
        CandleStore(c5m).save(market, five_min)
        CandleStore(c1h).save(market, hourly_random_walk('2026-05-01', '2026-10-29'))
    spreads = {'A-EUR': 0.0005, 'C-EUR': 0.005, 'Z-EUR': 0.001}  # B-EUR has none: it gets the median, 0.001

    md, result = cost_experiments(['A-EUR', 'B-EUR', 'C-EUR'], c5m, c1h, spreads)

    assert result['spread_fallback'] == {'markets': ['B-EUR'], 'half_spread': pytest.approx(0.001), 'scored_markets': 3}
    assert result['spread_pct'] == {'markets': 3, 'median': pytest.approx(0.2), 'min': pytest.approx(0.1), 'max': pytest.approx(1.0)}
    assert len(result['configs']) == 12
    assert {(c['interval'], c['orders']) for c in result['configs']} == {('5m', 'market'), ('5m', 'limit'), ('1h', 'market'), ('1h', 'limit')}
    for config in result['configs']:
        assert set(config['periods']) == set(PERIODS)
        assert config['passes_gate'] is False  # 3 markets cannot reach 200 trades per period
    assert [t['markets'] for t in result['terciles']] == [['A-EUR'], ['B-EUR'], ['C-EUR']]
    lowest, highest = result['terciles'][0]['periods'], result['terciles'][2]['periods']
    assert all(lowest[p]['avg_pl_pct'] > highest[p]['avg_pl_pct'] for p in PERIODS)
    assert result['lowest_tercile_beats_highest'] is True
    assert any('passes gate' in line for line in md)


def test_cost_experiments_terciles_without_the_spread_charge(tmp_path):
    c5m, c1h = str(tmp_path / 'c5m.db'), str(tmp_path / 'c1h.db')
    five_min = [c for seed, day in enumerate(('2026-06-01', '2026-09-01', '2026-10-10'))
                for c in random_walk(day, pd.Timestamp(day) + pd.Timedelta(days=3), '5min', seed)]
    for market in ('A-EUR', 'B-EUR', 'C-EUR'):  # identical prices, different spreads
        CandleStore(c5m).save(market, five_min)
        CandleStore(c1h).save(market, hourly_random_walk('2026-05-01', '2026-10-29'))

    md, result = cost_experiments(['A-EUR', 'B-EUR', 'C-EUR'], c5m, c1h, {'A-EUR': 0.0005, 'B-EUR': 0.001, 'C-EUR': 0.005})

    lowest = result['terciles'][0]
    for tercile, full_spread in zip(result['terciles'], (0.1, 0.2, 1.0), strict=True):
        # the trade-weighted round-trip spread charged with market orders: the full spread
        assert tercile['round_trip_spread_pct'] == {p: pytest.approx(full_spread) for p in PERIODS}
        # identical prices: without the spread charge every tercile trades the same
        assert tercile['periods_no_spread'] == lowest['periods_no_spread']
    assert all(lowest['periods_no_spread'][p]['trades'] > 0 for p in PERIODS)
    assert result['lowest_tercile_beats_highest'] is True
    assert result['lowest_tercile_beats_highest_no_spread'] is False
    assert any('without the spread charge' in line.lower() for line in md)


@pytest.mark.parametrize('extra, message', [([], 'section 7 needs --candles-1h'),
                                            (['--interval', '1h', '--candles-1h', 'c1h.db'], 'supports only sections 4,5, not 7')])
def test_section_7_needs_hourly_candles_and_5m_candles(extra, message, capsys, tmp_path):
    with pytest.raises(SystemExit):
        main(['--log-db', str(tmp_path / 'log.db'), '--candles', 'c.db', '--out', str(tmp_path), '--sections', '7', *extra])
    assert message in capsys.readouterr().err
