"""Download Bitvavo candles for offline analysis and cache them in SQLite.

Uses the public candles endpoint only (no API key, nothing account-related).
Bitvavo returns at most `limit` candles per request, newest first, and omits
intervals without trades; fetch_candles pages backwards through the range
and returns the candles oldest-first.

    venv/bin/python -m tools.log_analysis.candles --markets-file markets.txt \\
        --start 2026-05-15 --end 2026-10-29 --db data/analysis/candles_5m.db
"""

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

API_URL = 'https://api.bitvavo.com/v2'
COLUMNS = ['open', 'high', 'low', 'close', 'volume']


def bitvavo_get(market: str, params: dict):
    response = requests.get(f'{API_URL}/{market}/candles', params=params, timeout=30)
    if response.status_code == 429:
        return {'errorCode': 105, 'error': 'rate limited'}
    return response.json()


INTERVAL_MS = {'1m': 60_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000, '1h': 3_600_000}


def fetch_candles(market: str, start_ms: int, end_ms: int, interval: str = '5m', limit: int = 1440,
                  get: Callable[[str, dict], object] = None, pause: float = 0.1) -> list:
    """All candles for market in [start_ms, end_ms], oldest first.

    Bitvavo's start is inclusive and end exclusive, and `limit` bounds the
    slots looked back from end (untraded slots included). So pages are
    aligned windows of 90% of `limit` slots, walked backwards: a short page
    only means the window had untraded slots, never that the data ended.
    Returns [] when the exchange reports an error for the market (e.g. delisted).
    """
    get = get or bitvavo_get
    step = INTERVAL_MS[interval]
    window = max(1, limit * 9 // 10) * step
    candles = {}
    end = end_ms + step  # exclusive bound that still includes the candle at end_ms
    while end > start_ms:
        start = max(start_ms, end - window)
        page = get(market, {'interval': interval, 'limit': limit, 'start': start, 'end': end})
        if isinstance(page, dict) and page.get('errorCode') in (105, 110):
            time.sleep(60)  # rate limited: wait for the window to reset, then retry
            continue
        if not isinstance(page, list):
            return []
        candles.update((candle[0], candle) for candle in page)
        end = start
        if pause:
            time.sleep(pause)
    return [candles[ts] for ts in sorted(candles)]


class CandleStore:
    """SQLite cache: one row per (market, ts); `fetched` remembers markets
    that were requested, including ones the exchange had no data for."""

    def __init__(self, db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS candles (
                market TEXT, ts INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (market, ts));
            CREATE TABLE IF NOT EXISTS fetched (market TEXT PRIMARY KEY, n INTEGER);
        ''')

    def save(self, market: str, candles: list) -> None:
        with self.conn:
            self.conn.executemany(
                'INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?)',
                [(market, int(c[0]), *map(float, c[1:6])) for c in candles])
            self.conn.execute('INSERT OR REPLACE INTO fetched VALUES (?, ?)', (market, len(candles)))

    def fetched_markets(self) -> set:
        return {row[0] for row in self.conn.execute('SELECT market FROM fetched')}

    def load(self, market: str) -> pd.DataFrame:
        df = pd.read_sql_query('SELECT ts, open, high, low, close, volume FROM candles WHERE market = ? ORDER BY ts',
                               self.conn, params=(market,))
        df.index = pd.to_datetime(df.pop('ts'), unit='ms')
        df.index.name = 'timestamp'
        return df[COLUMNS]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--markets-file', required=True, help='one market symbol per line')
    parser.add_argument('--start', required=True, help='YYYY-MM-DD (UTC)')
    parser.add_argument('--end', required=True, help='YYYY-MM-DD (UTC), inclusive of that midnight')
    parser.add_argument('--db', default='data/analysis/candles_5m.db')
    parser.add_argument('--interval', default='5m')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args(argv)

    markets = [m.strip() for m in Path(args.markets_file).read_text().split() if m.strip()]
    start_ms = int(pd.Timestamp(args.start, tz='UTC').timestamp() * 1000)
    end_ms = int(pd.Timestamp(args.end, tz='UTC').timestamp() * 1000)
    store = CandleStore(args.db)
    todo = [m for m in markets if m not in store.fetched_markets()]
    print(f'{len(markets)} markets, {len(todo)} still to fetch', flush=True)
    # A few workers stay well under Bitvavo's 1000 requests/minute; SQLite
    # writes happen on this thread only
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_candles, m, start_ms, end_ms, args.interval): m for m in todo}
        for i, future in enumerate(as_completed(futures), 1):
            market = futures[future]
            candles = future.result()
            store.save(market, candles)
            print(f'[{i}/{len(todo)}] {market}: {len(candles)} candles', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
