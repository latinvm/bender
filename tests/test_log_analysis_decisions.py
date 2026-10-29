"""Loader for the structured decision logs and virtual-wallet trades."""

import json

import numpy as np
import pandas as pd
import pytest

from trader.virtual_wallet import VirtualWallet
from tools.log_analysis.decisions import attach_exit_reasons, load_decisions, load_wallet_trades

INDICATORS = dict(candle_ts='2026-11-01T10:00:00', candle_close=1.0, rsi=28.5, macd=-0.01, macd_signal=-0.02, bb_lower=0.9, bb_upper=1.1)
BUY = dict(ts='2026-11-01T10:00:00.123+00:00', market='ABC-EUR', action='buy', reason='Signal 1', price=1.0, entry_price=None, **INDICATORS)
MONITOR = dict(ts='2026-11-01T10:05:00.456+00:00', market='ABC-EUR', action='monitor', reason='', price=1.01, entry_price=None, **INDICATORS)
ERROR = dict(ts='2026-11-01T10:10:00.000+00:00', market='ABC-EUR', action='error', reason='boom', price=None, entry_price=None)


def test_loads_records_and_skips_a_truncated_last_line(tmp_path):
    f = tmp_path / 'decisions-2026-11-01.jsonl'
    f.write_text(json.dumps(BUY) + '\n' + json.dumps(MONITOR) + '\n' + '{"ts": "2026-11-01T10:0')
    df, skipped = load_decisions([f])
    assert len(df) == 2 and skipped == 1
    assert df.ts.iloc[0] == pd.Timestamp('2026-11-01 10:00:00.123')   # +00:00 converted, naive UTC


def test_records_without_indicators_have_nan(tmp_path):
    f = tmp_path / 'decisions-2026-11-01.jsonl'
    f.write_text(json.dumps(ERROR) + '\n')
    df, _ = load_decisions([f])
    assert np.isnan(df.rsi.iloc[0]) and pd.isna(df.candle_ts.iloc[0])


def test_wallet_trades_from_a_real_wallet(tmp_path):
    wallet = VirtualWallet(db_path=str(tmp_path / 'w.db'), initial_balance=100.0)
    wallet.record_buy('ABC-EUR', price=1.0, amount=10.0, fee=0.025)
    wallet.record_sell('ABC-EUR', price=1.1, amount=10.0, fee=0.0275)
    [row] = load_wallet_trades(tmp_path / 'w.db').itertuples()
    assert row.entry_price == 1.0 and row.exit_price == 1.1
    assert row.pl_pct == pytest.approx((11 - 0.0275 - 10 - 0.025) / 10 * 100)
    assert row.fees_eur == pytest.approx(0.0525) and row.pre_log == 0


EXIT = pd.DataFrame([dict(market='ABC-EUR', exit_ts=pd.Timestamp('2026-11-01 12:00:00'))])


def sell_at(ts, action='sell', reason='Stop Loss (-5.10%)'):
    return pd.DataFrame([dict(market='ABC-EUR', ts=pd.Timestamp(ts), action=action, reason=reason)])


def test_exit_reason_comes_from_the_matching_sell_decision():
    assert attach_exit_reasons(EXIT, sell_at('2026-11-01 12:00:30')).exit_reason.tolist() == ['stop_loss']


def test_unmatched_exit_gets_no_reason():
    out = attach_exit_reasons(EXIT, sell_at('2026-11-01 12:05:00'))
    assert len(out) == 1 and out.exit_reason.iloc[0] is None


def test_delisted_decision_gives_delisted():
    out = attach_exit_reasons(EXIT, sell_at('2026-11-01 12:00:10', action='delisted', reason='Market delisted'))
    assert out.exit_reason.tolist() == ['delisted']


def test_technical_and_take_profit_prefixes():
    assert attach_exit_reasons(EXIT, sell_at('2026-11-01 12:00:10', reason='Technical sell: RSI')).exit_reason.tolist() == ['technical']
    assert attach_exit_reasons(EXIT, sell_at('2026-11-01 12:00:10', reason='Take Profit (+5%)')).exit_reason.tolist() == ['take_profit']


def test_open_wallet_trade_has_nan_exits_and_float_columns(tmp_path):
    wallet = VirtualWallet(db_path=str(tmp_path / 'w.db'), initial_balance=100.0)
    wallet.record_buy('ABC-EUR', price=1.0, amount=10.0, fee=0.025)
    df = load_wallet_trades(tmp_path / 'w.db')
    [row] = df.itertuples()
    assert np.isnan(row.exit_price) and np.isnan(row.pl_pct) and np.isnan(row.pl_eur) and pd.isna(row.exit_ts)
    for column in ['entry_price', 'exit_price', 'pl_eur', 'pl_pct', 'fees_eur']:
        assert df[column].dtype == float
