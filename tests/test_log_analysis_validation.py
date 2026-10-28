"""Replay-versus-reality checks: exit and decision agreement."""

import numpy as np
import pandas as pd
import pytest

from tests.log_analysis_helpers import FIVE_MIN, T0, candle_frame, flat_snapshots
from tools.log_analysis.replay import Rules, window_snapshot
from tools.log_analysis.validation import decision_agreement, exit_agreement


def test_exit_agreement_recovers_a_known_exit():
    snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.0, 0.94], rsi=[30, 50, 50, 50])}  # SL at t3
    trades = pd.DataFrame([dict(market='A-EUR', entry_ts=T0, entry_price=1.0, exit_ts=T0 + 3 * FIVE_MIN,
                                exit_reason='stop_loss', pl_pct=(0.94 * 0.9975 - 1.0025) * 100, pre_log=0)])
    result = exit_agreement(trades, snaps, Rules())
    assert result['same_time_pct'] == 100 and result['same_reason_pct'] == 100
    assert result['optimism_pp'] == pytest.approx(0, abs=1e-9)


def test_trades_without_snapshots_are_skipped_and_counted():
    trades = pd.DataFrame([dict(market=m, entry_ts=T0, entry_price=1.0, exit_ts=T0 + 3 * FIVE_MIN,
                                exit_reason='stop_loss', pl_pct=-6.0, pre_log=0) for m in ('A-EUR', 'B-EUR')])
    snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.0, 0.94], rsi=[30, 50, 50, 50])}
    result = exit_agreement(trades, snaps, Rules())
    assert (result['trades'], result['of']) == (1, 2)


def test_decision_agreement_matches_logged_buy():
    candles = candle_frame(np.linspace(2.0, 1.0, 300))           # falling: RSI ~0, buy signal
    t = candles.index[-1]
    snap = window_snapshot(candles, t)
    decisions = pd.DataFrame([dict(ts=t, market='A-EUR', action='buy', entry_price=np.nan, candle_ts=t,
                                   rsi=snap.rsi, candle_close=snap.close)])
    result = decision_agreement(decisions, lambda m: candles, Rules(), sample=10)
    assert result['indicator_match_pct'] == 100 and result['buy_agreement_pct'] == 100


def test_calibrate_cli_end_to_end_with_stubbed_fetch(tmp_path):
    import json

    from tools.log_analysis.calibrate import main
    from tools.log_analysis.decisions import load_wallet_trades
    from trader.virtual_wallet import VirtualWallet

    wallet = VirtualWallet(db_path=str(tmp_path / 'w.db'), initial_balance=100.0)
    wallet.record_buy('A-EUR', price=1.0, amount=10.0, fee=0.025)
    wallet.record_sell('A-EUR', price=1.1, amount=10.0, fee=0.0275)
    entry = load_wallet_trades(tmp_path / 'w.db').entry_ts.iloc[0].floor('5min')
    records = [dict(ts=(entry + i * FIVE_MIN).isoformat() + '+00:00', market='A-EUR', action='monitor', reason='', price=1.0,
                    entry_price=None, candle_ts=(entry + i * FIVE_MIN).isoformat(), candle_close=1.0, rsi=50.0, macd=0.0,
                    macd_signal=0.0, bb_lower=0.9, bb_upper=1.1) for i in range(3)]
    (tmp_path / 'decisions-x.jsonl').write_text('\n'.join(json.dumps(r) for r in records) + '\n{"ts": "trunc')
    fetched = []

    def fetch(market, start_ms, end_ms):
        fetched.append(market)
        index = pd.date_range(pd.Timestamp(start_ms, unit='ms'), pd.Timestamp(end_ms, unit='ms'), freq='5min')
        closes = 1 + 0.01 * np.sin(np.arange(len(index)) / 7)   # flat prices give no RSI
        return [[int(t.timestamp() * 1000), c, c * 1.001, c * 0.999, c, 1000.0] for t, c in zip(index, closes, strict=True)]

    out = tmp_path / 'out'
    args = ['--decisions', str(tmp_path / 'decisions-*.jsonl'), '--wallet', str(tmp_path / 'w.db'),
            '--candles', str(tmp_path / 'c.db'), '--out', str(out)]
    assert main(args, fetch=fetch) == 0
    result = json.loads((out / 'calibration.json').read_text())
    assert fetched == ['A-EUR'] and result['skipped_lines'] == 1
    assert result['trade_counts'] == dict(trades=1, closed=1) and result['decision_agreement']['compared'] == 3
    assert (out / 'calibration.md').read_text().startswith('# Replay calibration')
    assert main(args, fetch=fetch) == 0 and fetched == ['A-EUR']   # candles now cached
