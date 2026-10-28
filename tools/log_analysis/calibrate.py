"""Calibrate the replay against a real (virtual) run of the fixed bot.

Reads the structured decision logs and the virtual wallet, fetches 5-minute
candles for any market missing from the candle store, and measures how far the
replay is from what the bot did: do recomputed indicators and buy decisions
match the log, and does the replay exit the real trades the same way. Writes
calibration.json and calibration.md to --out.

    venv/bin/python -m tools.log_analysis.calibrate \\
        --decisions 'logs/decisions-*.jsonl' --wallet data/virtual_trades.db \\
        --candles data/analysis/candles_5m.db --out data/analysis/calibration
"""

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

from tools.log_analysis.candles import CandleStore, fetch_candles
from tools.log_analysis.decisions import attach_exit_reasons, load_decisions, load_wallet_trades
from tools.log_analysis.replay import LIVE_RULES, window_snapshots
from tools.log_analysis.validation import decision_agreement, exit_agreement

BEFORE_FIRST = pd.Timedelta(days=2)
AFTER_LAST = pd.Timedelta(days=1)


def ensure_candles(store: CandleStore, markets, start: pd.Timestamp, end: pd.Timestamp, fetch: Callable = fetch_candles) -> list:
    """Fetch and store candles for markets not in the store yet; return the markets fetched."""
    todo = sorted(set(markets) - store.fetched_markets())
    start_ms, end_ms = (int(t.tz_localize('UTC').timestamp() * 1000) for t in (start, end))
    for i, market in enumerate(todo, 1):
        candles = fetch(market, start_ms, end_ms)
        store.save(market, candles)
        print(f'[{i}/{len(todo)}] {market}: {len(candles)} candles', flush=True)
    return todo


def exit_snapshots(decisions: pd.DataFrame, markets, candles_for: Callable[[str], pd.DataFrame]) -> dict:
    """Snapshots at each market's decision times (floored to 5 minutes), as the fixed bot computes them."""
    snapshots = {}
    for market in markets:
        times = sorted(decisions.loc[decisions.market == market, 'ts'].dt.floor('5min').unique())
        snaps = window_snapshots(candles_for(market), times)
        if not snaps.empty:
            snapshots[market] = snaps
    return snapshots


def clean(value):
    """JSON-safe copy: NaN becomes None."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, float) and value != value:
        return None
    return value


def fmt(value, spec: str = '.1f') -> str:
    return 'n/a' if value is None else format(value, spec)


def report(decisions_result: dict, exits: dict, skipped: int, counts: dict) -> list:
    d, e = decisions_result, exits
    return ['# Replay calibration', '',
            f"{counts['trades']} wallet trades ({counts['closed']} closed); {skipped} unreadable decision-log lines skipped.", '',
            '## Decisions', '',
            f"{d['compared']} logged decisions with a flat position were recomputed from candles.", '',
            f"- Indicators match (RSI within 1 point, close within 0.2%): **{fmt(d['indicator_match_pct'])}%**.",
            f"- Buy or no buy agrees with the log: **{fmt(d['buy_agreement_pct'])}%**.", '',
            '## Exits', '',
            f"Starting each of {e['trades']} closed trades (of {e['of']}) at its real entry, the replay:", '',
            f"- exits within 15 minutes of the real exit in **{fmt(e['same_time_pct'], '.0f')}%** of trades, "
            f"for the same reason in **{fmt(e['same_reason_pct'], '.0f')}%**;",
            f"- has a P/L correlation of {fmt(e['pl_correlation'], '.2f')} with the real trades;",
            f"- averages {fmt(e['sim_avg_pl'], '+.2f')}% per trade against {fmt(e['live_avg_pl'], '+.2f')}% real: "
            f"optimism {fmt(e['optimism_pp'], '+.2f')} percentage points.", '']


def main(argv=None, fetch: Callable = fetch_candles) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--decisions', required=True, help="glob for decision JSONL files, e.g. 'logs/decisions-*.jsonl'")
    parser.add_argument('--wallet', required=True, help='virtual_trades.db')
    parser.add_argument('--candles', required=True)
    parser.add_argument('--out', default='data/analysis/calibration')
    parser.add_argument('--utc-offset', type=float, default=0.0, help='hours the wallet clock is ahead of UTC')
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.decisions))
    decisions, skipped = load_decisions(paths)
    if decisions.empty:
        print(f'no decisions found for {args.decisions}', file=sys.stderr)
        return 1
    trades = attach_exit_reasons(load_wallet_trades(Path(args.wallet), args.utc_offset), decisions)

    store = CandleStore(args.candles)
    markets = set(decisions.market.dropna()) | set(trades.market)
    ensure_candles(store, markets, decisions.ts.min() - BEFORE_FIRST, decisions.ts.max() + AFTER_LAST, fetch)

    decisions_result = decision_agreement(decisions, store.load, LIVE_RULES)
    snapshots = exit_snapshots(decisions, sorted(set(trades.market)), store.load)
    exits = exit_agreement(trades, snapshots, LIVE_RULES)
    counts = dict(trades=len(trades), closed=int(trades.exit_ts.notna().sum()))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'calibration.json').write_text(json.dumps(
        clean(dict(decision_agreement=decisions_result, exit_agreement=exits, skipped_lines=skipped, trade_counts=counts)), indent=2))
    (out / 'calibration.md').write_text('\n'.join(report(clean(decisions_result), clean(exits), skipped, counts)))
    print(f"wrote {out / 'calibration.md'} and {out / 'calibration.json'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
