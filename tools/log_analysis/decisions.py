"""Load the structured decision logs and virtual-wallet trades of a real run.

Both loaders return naive UTC times, in the same shape the replay simulator
and the parser's `trades` table use, so a virtual run can be compared with a
replay of the same period.

    decisions, skipped = load_decisions(sorted(Path('logs').glob('decisions-*.jsonl')))
    trades = attach_exit_reasons(load_wallet_trades(Path('data/virtual_wallet.db')), decisions)
"""

import json
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

DECISION_COLUMNS = ['ts', 'market', 'action', 'reason', 'price', 'entry_price',
                    'candle_ts', 'candle_close', 'rsi', 'macd', 'macd_signal', 'bb_lower', 'bb_upper']
NUMERIC_COLUMNS = ['price', 'entry_price', 'candle_close', 'rsi', 'macd', 'macd_signal', 'bb_lower', 'bb_upper']
TRADE_COLUMNS = ['market', 'entry_ts', 'entry_price', 'exit_ts', 'exit_price', 'pl_eur', 'pl_pct', 'fees_eur', 'pre_log']
EXIT_MATCH_WINDOW = pd.Timedelta(minutes=2)
REASON_PREFIXES = (('Technical', 'technical'), ('Take Profit', 'take_profit'), ('Stop Loss', 'stop_loss'))


def read_records(path: Path) -> tuple[list[dict], int]:
    records, skipped = [], 0
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                skipped += 1
    return records, skipped


def naive_utc(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, utc=True, format='ISO8601').dt.tz_localize(None)


def load_decisions(paths: Iterable[Path]) -> tuple[pd.DataFrame, int]:
    """Read decision JSONL files; return (frame sorted by ts, skipped line count)."""
    records, skipped = [], 0
    for path in paths:
        file_records, file_skipped = read_records(Path(path))
        records.extend(file_records)
        skipped += file_skipped
    df = pd.DataFrame(records).reindex(columns=DECISION_COLUMNS)
    df['ts'] = naive_utc(df['ts'])
    df['candle_ts'] = naive_utc(df['candle_ts'])
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors='coerce')
    return df.sort_values('ts', kind='stable').reset_index(drop=True), skipped


def load_wallet_trades(db_path: Path, utc_offset_hours: float = 0.0) -> pd.DataFrame:
    """Read virtual_trades. The wallet stores local time; subtract the UTC offset.

    profit_loss already includes the buy and sell fee (see VirtualWallet.record_sell)
    and `fees` holds both fees of a closed trade, so they map straight to pl_eur/fees_eur.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        raw = pd.read_sql_query(
            'SELECT market, entry_time, entry_price, exit_time, exit_price, profit_loss, profit_loss_pct, fees '
            'FROM virtual_trades ORDER BY entry_time', conn)
    finally:
        conn.close()
    offset = pd.Timedelta(hours=utc_offset_hours)
    return pd.DataFrame({
        'market': raw['market'],
        'entry_ts': pd.to_datetime(raw['entry_time']) - offset,
        'entry_price': raw['entry_price'].astype(float),
        'exit_ts': pd.to_datetime(raw['exit_time']) - offset,
        'exit_price': raw['exit_price'].astype(float),
        'pl_eur': raw['profit_loss'].astype(float),
        'pl_pct': raw['profit_loss_pct'].astype(float),
        'fees_eur': raw['fees'].astype(float),
        'pre_log': 0,
    }, columns=TRADE_COLUMNS)


def exit_reason_for(reason: str) -> str | None:
    for prefix, name in REASON_PREFIXES:
        if str(reason).startswith(prefix):
            return name
    return None


def attach_exit_reasons(trades: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Add exit_reason from the sell/delisted decision within 2 minutes of each exit."""
    out = trades.copy()
    exits = decisions[decisions['action'].isin(['sell', 'delisted'])]
    reasons = []
    for trade in out.itertuples():
        reason = None
        if pd.notna(trade.exit_ts):
            near = exits[(exits['market'] == trade.market) & ((exits['ts'] - trade.exit_ts).abs() <= EXIT_MATCH_WINDOW)]
            if len(near):
                best = near.loc[(near['ts'] - trade.exit_ts).abs().idxmin()]
                reason = 'delisted' if best['action'] == 'delisted' else exit_reason_for(best['reason'])
        reasons.append(reason)
    out['exit_reason'] = pd.Series(reasons, index=out.index, dtype=object)
    return out
