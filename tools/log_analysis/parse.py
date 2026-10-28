"""Parse a Bender log file into a SQLite database for analysis.

Usage:
    python -m tools.log_analysis.parse logs/2026-08-13.log --db data/analysis/bender_2026-08-13.db

The log is read line by line (it can be several GB) in a single pass. Every
line is counted in `line_stats` as exactly one category: parsed into a
table, or explicitly ignored, or 'unrecognised' - so nothing is dropped
silently when the log format changes.

Things to know about the log format (verified on logs/2026-08-13.log):

- Line format: `YYYY-MM-DD HH:MM:SS,mmm - <logger> - <LEVEL> - <message>`.
  Timestamps are UTC (checked against Bitvavo candles). Lines may end in
  CRLF (Bender ran on Windows).
- Messages starting with a newline become a prefix line with an empty
  message followed by continuation lines without a prefix (`--- MKT ---`,
  `Analyzing MKT:`, `====`). A continuation line belongs to the most recent
  prefixed line: the logging module writes each record in one call.
- Two threads write interleaved: the trading thread (one `--- MKT ---` block
  per market per cycle) and the TUI price thread, which emits
  `Fetching ticker for MKT` and `Error fetching current price: ticker MKT`
  at any point. Those are attributed by the market name in the message,
  never by block position. `Error executing trade: ...` has no market name
  and belongs to the current block.
- Indicator values (RSI, MACD, Bollinger bands, candle price) are stored as
  logged. Until the candle-order fix they were computed on time-reversed
  candles; this parser does not try to correct them.
- Prices are printed with 6 decimals, so prices below €0.001 have fewer
  than 4 significant digits (PEPE at €0.000004 is +-12%). `price_precise`
  flags rows where the logged price is >= €0.001; the view
  `prices_precise` filters the price table the same way. Wallet P/L (€ and
  %) and the `Position P/L` percentages are computed at full precision, so
  trade results do not suffer from this.

Tables: checks, trades, prices, balance, cycles, rescans, market_scores,
quick_scores, selections, rotations, errors, line_stats, meta.
"""

import argparse
import re
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

PRECISE_PRICE = 0.001  # 6 printed decimals give >= 4 significant digits from here up
FLUSH_EVERY = 100_000
SEPARATOR = '=' * 80

SCHEMA = """
CREATE TABLE checks (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    market TEXT NOT NULL,
    rsi REAL, macd REAL, macd_signal REAL, candle_price REAL,
    lower_bb REAL, upper_bb REAL,
    sig1 INTEGER, sig2 INTEGER, sig3 INTEGER,
    sell_rsi_cond INTEGER, sell_macd_cond INTEGER,
    position_pl_pct REAL, entry_price REAL, ticker_price REAL,
    buy_signal_reason TEXT, sell_signal_reason TEXT,
    outcome TEXT, error_msg TEXT,
    price_precise INTEGER
);
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    market TEXT NOT NULL,
    pre_log INTEGER NOT NULL,
    entry_ts TEXT, entry_reason TEXT, entry_price REAL, amount REAL,
    entry_rsi REAL, entry_macd REAL, entry_macd_signal REAL,
    entry_candle_price REAL, entry_lower_bb REAL, entry_fee REAL,
    exit_ts TEXT, exit_reason TEXT, exit_reason_raw TEXT, exit_price REAL, exit_fee REAL,
    pl_eur REAL, pl_pct REAL, gross_pl_eur REAL, gross_pl_pct REAL, fees_eur REAL,
    hold_minutes REAL, mfe_pct REAL, mae_pct REAL, n_checks_held INTEGER,
    price_precise INTEGER
);
CREATE TABLE prices (ts TEXT NOT NULL, market TEXT NOT NULL, price REAL NOT NULL);
CREATE TABLE balance (ts TEXT NOT NULL, fee REAL, balance REAL);
CREATE TABLE cycles (ts TEXT NOT NULL, n_markets INTEGER, n_active INTEGER, active_markets TEXT);
CREATE TABLE rescans (rescan_id INTEGER PRIMARY KEY, ts TEXT NOT NULL, periodic INTEGER,
                      n_altcoins INTEGER, n_analyzed INTEGER);
CREATE TABLE market_scores (
    rescan_id INTEGER, ts TEXT NOT NULL, market TEXT NOT NULL,
    volume_24h REAL, volume_score REAL, volatility_pct REAL, volatility_score REAL,
    sharpe REAL, sharpe_score REAL, sortino REAL, sortino_score REAL,
    spread_pct REAL, spread_score REAL, volume_consistency REAL, penalty TEXT,
    final_score REAL, rejected_reason TEXT
);
CREATE TABLE quick_scores (rescan_id INTEGER, ts TEXT NOT NULL, rank INTEGER, market TEXT,
                           score REAL, volume REAL, volatility_pct REAL);
CREATE TABLE selections (rescan_id INTEGER, ts TEXT NOT NULL, rank INTEGER, market TEXT, score REAL);
CREATE TABLE rotations (ts TEXT NOT NULL, market TEXT NOT NULL, action TEXT NOT NULL);
CREATE TABLE errors (template TEXT, logger TEXT, level TEXT, count INTEGER,
                     first_ts TEXT, last_ts TEXT, example TEXT, markets TEXT);
CREATE TABLE line_stats (category TEXT PRIMARY KEY, count INTEGER);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE VIEW prices_precise AS SELECT * FROM prices WHERE price >= 0.001;
"""

INDEXES = """
CREATE INDEX idx_prices_market_ts ON prices(market, ts);
CREATE INDEX idx_checks_market_ts ON checks(market, ts);
CREATE INDEX idx_trades_market ON trades(market, entry_ts);
CREATE INDEX idx_scores_market ON market_scores(market, rescan_id);
"""

TABLES = ('checks', 'trades', 'prices', 'balance', 'cycles', 'rescans', 'market_scores',
          'quick_scores', 'selections', 'rotations', 'errors', 'line_stats', 'meta')

CHECK_COLUMNS = ('ts', 'market', 'rsi', 'macd', 'macd_signal', 'candle_price', 'lower_bb', 'upper_bb',
                 'sig1', 'sig2', 'sig3', 'sell_rsi_cond', 'sell_macd_cond', 'position_pl_pct',
                 'entry_price', 'ticker_price', 'buy_signal_reason', 'sell_signal_reason',
                 'outcome', 'error_msg', 'price_precise')
TRADE_COLUMNS = ('market', 'pre_log', 'entry_ts', 'entry_reason', 'entry_price', 'amount',
                 'entry_rsi', 'entry_macd', 'entry_macd_signal', 'entry_candle_price', 'entry_lower_bb',
                 'entry_fee', 'exit_ts', 'exit_reason', 'exit_reason_raw', 'exit_price', 'exit_fee',
                 'pl_eur', 'pl_pct', 'gross_pl_eur', 'gross_pl_pct', 'fees_eur', 'hold_minutes',
                 'mfe_pct', 'mae_pct', 'n_checks_held', 'price_precise')
SCORE_COLUMNS = ('rescan_id', 'ts', 'market', 'volume_24h', 'volume_score', 'volatility_pct',
                 'volatility_score', 'sharpe', 'sharpe_score', 'sortino', 'sortino_score',
                 'spread_pct', 'spread_score', 'volume_consistency', 'penalty', 'final_score',
                 'rejected_reason')

# Message patterns (matched against the message part only)
RE_BUY_CHECK = re.compile(r'Buy check - RSI: (\S+), MACD: (\S+), Signal: (\S+), Price: €(\S+), Lower BB: €(\S+)$')
RE_SELL_CHECK = re.compile(r'Sell check - RSI: (\S+), MACD: (\S+), Signal: (\S+), Price: €(\S+), Upper BB: €(\S+)$')
RE_POSITION_PL = re.compile(r'(\S+) Position P/L: (\S+)% \(Entry: €([^,)]+)(?:, Current: €(\S+))?\)$')
RE_SELL_CONDS = re.compile(r'RSI > \S+: (True|False), MACD < Signal: (True|False)$')
RE_BUY_SIGNAL = re.compile(r'BUY SIGNAL TRIGGERED for (\S+)! \((.*)\)$')
RE_SELL_SIGNAL = re.compile(r'SELL SIGNAL TRIGGERED for (\S+) \((.*)\)$')
RE_AMOUNT_BUY = re.compile(r'Amount: (\S+) (\S+) \(€(\S+)\)$')
RE_FILL = re.compile(r'Fill price: €(\S+) \(fee: €(\S+)\)$')
RE_ENTRY_EXIT = re.compile(r'Entry: €(\S+) -> Exit: €(\S+) \(fee: €(\S+)\)$')
RE_GROSS_PL = re.compile(r'P/L: (\S+)% \(€(\S+)\)$')
RE_LOADED = re.compile(r'Loaded active position: (\S+) (\S+) @ €(\S+)$')
RE_FEE = re.compile(r'\[VIRTUAL\] Fee: €(\S+) \| Balance: €(\S+)$')
RE_ORDER_EXECUTED = re.compile(r'\[VIRTUAL\] Order executed: (buy|sell) \S+ (\S+) @')
RE_VIRTUAL_SELL = re.compile(r'Virtual SELL: \S+ (\S+) @ €\S+ \| P/L: €(\S+) \((\S+)%\)$')
RE_CHECKING = re.compile(r'Checking (\d+) markets\.\.\.$')
RE_PORTFOLIO = re.compile(r'Portfolio Summary: (\d+)/(\d+) markets active$')
RE_QUICK_SCORE = re.compile(r'(\d+)\. (\S+): score=(\S+), volume=€(\S+), vol=(\S+)%$')
RE_SELECTION = re.compile(r'(\d+)\. (\S+) \(score: (\S+)\)$')
RE_METRIC_WITH_SCORE = re.compile(r'(Volume \(24h\)|Volatility|Sharpe Ratio|Sortino Ratio|Bid-Ask Spread): €?(\S+?)%? \| Score: (\S+)$')
RE_FOUND_ALTCOINS = re.compile(r'Found (\d+) total altcoins')
RE_ANALYZING_N = re.compile(r'Performing detailed analysis on (\d+) markets')
RE_REJECT_SPREAD = re.compile(r'Rejecting (\S+): Spread too wide \((\S+)% > \S+\)$')
RE_SYMBOL = re.compile(r'[A-Z0-9]+-EUR')
RE_NUMBER = re.compile(r'[-+]?\d+(?:[.,]\d+)?(?:e-?\d+)?')

METRIC_FIELDS = {
    'Volume (24h)': ('volume_24h', 'volume_score'),
    'Volatility': ('volatility_pct', 'volatility_score'),
    'Sharpe Ratio': ('sharpe', 'sharpe_score'),
    'Sortino Ratio': ('sortino', 'sortino_score'),
    'Bid-Ask Spread': ('spread_pct', 'spread_score'),
}

# Messages that carry nothing the analysis needs, by logger: prefix -> category
IGNORED_PREFIXES = {
    'trader.market': (
        ('Fetching detailed info for', 'market_scan'),
        ('Fetching order book for', 'market_scan'),
        ('Fetching historical candles for', 'market_scan'),
        ('Fetching market info for', 'order_flow'),
        ('Fetching altcoins under', 'market_scan'),
        ('MarketOperations initialized', 'startup'),
    ),
    'trader.enhanced_strategy': (
        ('Active positions: ', 'position_list'),
        ('Starting enhanced trading strategy', 'startup'),
        ('Strategy for ', 'shutdown'),
    ),
    'trader.virtual_market': (
        ('[VIRTUAL] Placing ', 'order_flow'),
        ('VirtualMarketOperations initialized', 'startup'),
        ('Starting balance', 'startup'),
    ),
    'trader.virtual_wallet': (
        ('Virtual BUY: ', 'order_flow'),
        ('Virtual wallet', 'startup'),
    ),
    'trader.multi_market': (
        (SEPARATOR, 'separator'),
        ('Market rotation applied', 'rotation_summary'),
        ('Market rotation: selection unchanged', 'rotation_summary'),
        ('Market re-selection queued', 'rotation_summary'),
        ('Initializing strategy for', 'startup'),
        ('Found ', 'startup'),
        ('Adding these markets', 'startup'),
        ('MultiMarketStrategy initialized', 'startup'),
        ('Markets: ', 'startup'),
        ('Total capital allocation', 'startup'),
        ('Max concurrent positions', 'startup'),
        ('Starting multi-market strategy', 'startup'),
        ('Checking ', 'startup'),  # 'Checking N markets every N seconds'
        ('Multi-market strategy stopped', 'shutdown'),
        ('=== Final Portfolio Summary', 'shutdown'),
        ('Total markets tracked', 'shutdown'),
        ('Active positions: ', 'shutdown'),
        ('Active in: ', 'shutdown'),
    ),
    'trader.main': (
        (SEPARATOR, 'separator'),
        ('Progress: ', 'market_scan'),
        ('Fetching complete altcoin list', 'market_scan'),
        ('Quick-scoring all', 'market_scan'),
        ('Top ', 'market_scan'),
        ('STEP 2:', 'market_scan'),
        ('Using pre-filtered', 'market_scan'),
        ('Fetching detailed info for', 'market_scan'),
        ('Market rescan completed', 'market_scan'),
        ('FINAL SELECTION', 'startup'),
        ('Markets: ', 'startup'),
        ('Market: ', 'startup'),
        ('Status: ', 'startup'),
        ('Base: ', 'startup'),
        ('Quote: ', 'startup'),
        ('Current Price: ', 'startup'),
        ('Price: €', 'startup'),
        ('Resuming with', 'startup'),
        ('Using multi-market strategy', 'startup'),
        ('Started periodic market rescan', 'startup'),
        ('Starting strategy with', 'startup'),
        ('Starting trader application', 'startup'),
        ('WARNING: All trades will be simulated', 'startup'),
        ('Monitor mode enabled', 'startup'),
        ('Log file: ', 'startup'),
        ('Virtual wallet initialized', 'startup'),
        ('2-STEP MARKET SELECTION', 'startup'),
        ('Waiting for strategy', 'shutdown'),
    ),
    'trader.bitvavo': (('', 'bitvavo'),),
    'trader.risk': (('', 'risk'),),
}
RE_RESUME_POSITION = re.compile(r'[A-Z0-9]+-EUR: \S+ @ €\S+$')  # main's 'Resuming with' position list


def _f(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: str) -> int:
    return 1 if value == 'True' else 0


def normalise(message: str) -> str:
    """Template of a message: market symbols -> MKT, numbers -> N."""
    return RE_NUMBER.sub('N', RE_SYMBOL.sub('MKT', message))


def _minutes_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60


def _exit_reason(raw: str) -> str:
    if raw.startswith('Technical'):
        return 'technical'
    if raw.startswith('Take Profit'):
        return 'take_profit'
    if raw.startswith('Stop Loss'):
        return 'stop_loss'
    return 'other'


@dataclass
class ParseSummary:
    lines: int = 0
    line_stats: Counter = field(default_factory=Counter)
    unrecognised: Counter = field(default_factory=Counter)
    table_counts: dict = field(default_factory=dict)


class LogParser:
    """Single-pass state machine over log lines. Feed lines, then finish()."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.summary = ParseSummary()
        self.stats = self.summary.line_stats
        self.buffers = {name: [] for name in ('checks', 'prices', 'balance', 'cycles', 'rotations',
                                              'market_scores', 'quick_scores', 'selections')}
        # trading thread
        self.block: Optional[dict] = None
        self.open_trades: dict[str, dict] = {}
        self.closed_trades: list[dict] = []
        self.last_trade: Optional[dict] = None  # receives the Reason/Amount/... lines after EXECUTED
        self.pending_fee: dict[str, float] = {}
        self.pending_wallet_pl: dict[str, tuple] = {}
        self.fee_market: Optional[str] = None
        self.cycle: Optional[list] = None
        # rescan thread
        self.rescans: list[list] = []
        self.rescan_id = 0
        self.pending_periodic = False
        self.score: Optional[dict] = None
        # errors: (logger, level, template) -> [count, first_ts, last_ts, example, Counter(market)]
        self.errors: dict[tuple, list] = {}
        self._template_cache: dict[str, tuple] = {}  # message -> (template, market symbols)
        # continuation lines belong to the last prefixed line
        self.last_logger = ''
        self.last_ts = ''

        self.handlers = {
            'trader.market': self._market,
            'trader.enhanced_strategy': self._strategy,
            'trader.multi_market': self._multi_market,
            'trader.main': self._main,
            'trader.virtual_market': self._virtual_market,
            'trader.virtual_wallet': self._virtual_wallet,
        }

    # ------------------------------------------------------------------ input

    def feed(self, raw: str) -> None:
        line = raw.rstrip('\r\n')
        self.summary.lines += 1
        if len(line) > 26 and line[19] == ',' and line[23:26] == ' - ' and line[:2] == '20':
            ts = line[:19] + '.' + line[20:23]
            parts = line[26:].split(' - ', 2)
            logger = parts[0]
            if len(parts) == 3:
                level, msg = parts[1], parts[2]
            else:
                level, msg = parts[1].rstrip(' -') if len(parts) > 1 else '', ''
            self.last_logger, self.last_ts = logger, ts
            if level in ('ERROR', 'WARNING', 'CRITICAL'):
                self._record_error(logger, level, msg, ts)
            if not msg.strip():
                category = 'ignored.multiline_head'
            else:
                handler = self.handlers.get(logger)
                category = handler(ts, level, msg) if handler else None
                if category is None:
                    category = self._ignored(logger, msg)
                if category is None and level in ('ERROR', 'WARNING', 'CRITICAL'):
                    category = 'errors'
                if category is None:
                    self.summary.unrecognised[f"{logger} - {level} - {normalise(msg)}"] += 1
                    category = 'unrecognised'
        else:
            category = self._continuation(line)
            if category is None:
                self.summary.unrecognised[f"(continuation of {self.last_logger}) {normalise(line)}"] += 1
                category = 'unrecognised'
        self.stats[category] += 1

    def _ignored(self, logger: str, msg: str) -> Optional[str]:
        for prefix, name in IGNORED_PREFIXES.get(logger, ()):
            if msg.startswith(prefix):
                return f'ignored.{name}'
        if logger == 'trader.main' and RE_RESUME_POSITION.match(msg):
            return 'ignored.startup'
        return None

    def _record_error(self, logger: str, level: str, msg: str, ts: str) -> None:
        cached = self._template_cache.get(msg)
        if cached is None:
            cached = (normalise(msg), tuple(RE_SYMBOL.findall(msg)))
            if len(self._template_cache) < 50_000:
                self._template_cache[msg] = cached
        template, markets = cached
        key = (logger, level, template)
        entry = self.errors.get(key)
        if entry is None:
            entry = self.errors[key] = [0, ts, ts, msg, Counter()]
        entry[0] += 1
        entry[2] = ts
        entry[4].update(markets)

    # ------------------------------------------------------- continuation lines

    def _continuation(self, line: str) -> Optional[str]:
        stripped = line.strip()
        if not stripped:
            return 'ignored.empty'
        if stripped == SEPARATOR:
            if self.last_logger == 'trader.multi_market':
                self._close_block()
            return 'ignored.separator'
        if self.last_logger == 'trader.multi_market' and line.startswith('--- ') and line.endswith(' ---'):
            self._open_block(self.last_ts, line[4:-4])
            return 'checks'
        if self.last_logger == 'trader.main':
            if line.startswith('Analyzing ') and line.endswith(':'):
                self._finish_score()
                self.score = {'rescan_id': self.rescan_id, 'ts': self.last_ts, 'market': line[10:-1]}
                return 'market_scores'
            m = RE_REJECT_SPREAD.match(line)
            if m:
                self._finish_score()
                self.buffers['market_scores'].append(self._score_row(
                    {'rescan_id': self.rescan_id, 'ts': self.last_ts, 'market': m.group(1),
                     'spread_pct': _f(m.group(2)), 'rejected_reason': 'spread'}))
                return 'market_scores'
            if line.startswith('Selected top ') or line.startswith('Cached top '):
                self._finish_score()
                return 'ignored.market_scan'
            if line.startswith('=== ') or line.startswith('Top '):
                return 'ignored.startup'
        return None

    # ------------------------------------------------------------ trader.market

    def _market(self, ts: str, level: str, msg: str) -> Optional[str]:
        if msg.startswith('Fetching ticker for '):
            market, _, price = msg[20:].partition(': €')
            price_f = _f(price)
            if price_f is None:
                return None
            self.buffers['prices'].append((ts, market, price_f))
            block = self.block
            if block is not None and block['market'] == market and block['ticker_price'] is None:
                block['ticker_price'] = price_f
            self._maybe_flush('prices')
            return 'prices'
        return None

    # ------------------------------------------------------ trading thread blocks

    def _open_block(self, ts: str, market: str) -> None:
        self._close_block()
        self.block = dict.fromkeys(CHECK_COLUMNS)
        self.block['ts'] = ts
        self.block['market'] = market

    def _close_block(self) -> None:
        block = self.block
        if block is None:
            return
        self.block = None
        if block['outcome'] is None:
            block['outcome'] = 'unknown'
        price = block['ticker_price'] if block['ticker_price'] is not None else block['candle_price']
        block['price_precise'] = None if price is None else int(price >= PRECISE_PRICE)
        self.buffers['checks'].append(tuple(block[c] for c in CHECK_COLUMNS))
        self._maybe_flush('checks')

    def _block_for(self, market: Optional[str] = None) -> Optional[dict]:
        block = self.block
        if block is None or (market is not None and block['market'] != market):
            return None
        return block

    def _strategy(self, ts: str, level: str, msg: str) -> Optional[str]:
        if level == 'ERROR':
            if msg.startswith('Error fetching current price'):
                return 'errors'  # TUI or trading thread; only aggregated
            if msg.startswith('Error executing trade: ') or msg.startswith('Cannot execute '):
                block = self._block_for()
                if block is not None:
                    block['outcome'] = 'error'
                    block['error_msg'] = msg.partition(': ')[2] if msg.startswith('Error') else msg
                return 'checks'
            return None

        block = self.block
        c0 = msg[0]
        if c0 == 'S':
            if msg.startswith('Signal '):
                if block is not None:
                    block['sig' + msg[7]] = 1 if msg.endswith('True') else 0
                return 'checks'
            if msg.startswith('Sell check'):
                m = RE_SELL_CHECK.match(msg)
                if m and block is not None:
                    block['upper_bb'] = _f(m.group(5))
                return 'checks' if m else None
            if msg.startswith('SELL SIGNAL TRIGGERED'):
                m = RE_SELL_SIGNAL.match(msg)
                if m:
                    b = self._block_for(m.group(1))
                    if b is not None:
                        b['sell_signal_reason'] = m.group(2)
                return 'checks' if m else None
            if msg.startswith('SELL EXECUTED for '):
                return self._sell_executed(ts, msg[18:])
        elif c0 == 'B':
            if msg.startswith('Buy check'):
                m = RE_BUY_CHECK.match(msg)
                if m and block is not None:
                    block['rsi'], block['macd'], block['macd_signal'], block['candle_price'], block['lower_bb'] = (
                        _f(g) for g in m.groups())
                return 'checks' if m else None
            if msg.startswith('BUY SIGNAL TRIGGERED'):
                m = RE_BUY_SIGNAL.match(msg)
                if m:
                    b = self._block_for(m.group(1))
                    if b is not None:
                        b['buy_signal_reason'] = m.group(2)
                return 'checks' if m else None
            if msg.startswith('BUY EXECUTED for '):
                return self._buy_executed(ts, msg[17:])
            if msg.startswith('BUY BLOCKED for '):
                b = self._block_for(msg[16:].partition(':')[0])
                if b is not None:
                    b['outcome'] = 'blocked_risk'
                return 'checks'
        elif c0 == 'H' and msg.startswith('HOLDING '):
            b = self._block_for(msg[8:].partition(' ')[0])
            if b is not None:
                b['outcome'] = 'holding'
            return 'checks'
        elif c0 == 'M' and msg.startswith('MONITORING '):
            b = self._block_for(msg[11:].partition(' ')[0])
            if b is not None:
                b['outcome'] = 'monitoring'
            return 'checks'
        elif c0 == 'R':
            if msg.startswith('RSI > '):
                m = RE_SELL_CONDS.match(msg)
                if m and block is not None:
                    block['sell_rsi_cond'], block['sell_macd_cond'] = _bool(m.group(1)), _bool(m.group(2))
                return 'checks' if m else None
            if msg.startswith('Reason: '):
                return self._trade_detail('reason', msg[8:])
        elif c0 == 'P':
            if msg.startswith('POSITION LIMIT REACHED'):
                if block is not None:
                    block['outcome'] = 'blocked_position_limit'
                return 'checks'
            if msg.startswith('P/L: '):
                return self._trade_detail('gross_pl', msg)
        elif c0 == 'A' and msg.startswith('Amount: '):
            return self._trade_detail('amount', msg)
        elif c0 == 'F' and msg.startswith('Fill price: '):
            return self._trade_detail('fill', msg)
        elif c0 == 'E' and msg.startswith('Entry: '):
            return self._trade_detail('entry_exit', msg)
        elif c0 == 'L' and msg.startswith('Loaded active position: '):
            return self._loaded_position(msg)

        if ' Position P/L: ' in msg:
            m = RE_POSITION_PL.match(msg)
            if not m:
                return None
            market, pl = m.group(1), _f(m.group(2))
            b = self._block_for(market)
            if b is not None:
                b['position_pl_pct'] = pl
                b['entry_price'] = _f(m.group(3))
            trade = self.open_trades.get(market)
            if trade is not None and pl is not None:
                trade['n_checks_held'] += 1
                trade['mfe_pct'] = pl if trade['mfe_pct'] is None else max(trade['mfe_pct'], pl)
                trade['mae_pct'] = pl if trade['mae_pct'] is None else min(trade['mae_pct'], pl)
            return 'checks'
        return None

    # ------------------------------------------------------------------ trades

    def _new_trade(self, market: str, pre_log: int) -> dict:
        trade = dict.fromkeys(TRADE_COLUMNS)
        trade.update(market=market, pre_log=pre_log, n_checks_held=0)
        return trade

    def _loaded_position(self, msg: str) -> Optional[str]:
        m = RE_LOADED.match(msg)
        if not m:
            return None
        market = m.group(2)
        if market not in self.open_trades:
            trade = self._new_trade(market, pre_log=1)
            trade.update(entry_reason='pre_log', amount=_f(m.group(1)), entry_price=_f(m.group(3)))
            self.open_trades[market] = trade
        return 'trades'

    def _buy_executed(self, ts: str, market: str) -> str:
        trade = self._new_trade(market, pre_log=0)
        trade['entry_ts'] = ts
        trade['entry_fee'] = self.pending_fee.pop(market, None)
        block = self._block_for(market)
        if block is not None:
            block['outcome'] = 'bought'
            trade.update(entry_rsi=block['rsi'], entry_macd=block['macd'],
                         entry_macd_signal=block['macd_signal'],
                         entry_candle_price=block['candle_price'], entry_lower_bb=block['lower_bb'])
        self.open_trades[market] = trade
        self.last_trade = trade
        return 'trades'

    def _sell_executed(self, ts: str, market: str) -> str:
        trade = self.open_trades.pop(market, None)
        if trade is None:  # bought before the log started without a 'Loaded' line
            trade = self._new_trade(market, pre_log=1)
            trade['entry_reason'] = 'pre_log'
        trade['exit_ts'] = ts
        trade['exit_fee'] = self.pending_fee.pop(market, None)
        wallet = self.pending_wallet_pl.pop(market, None)
        if wallet is not None:
            trade['pl_eur'], trade['pl_pct'] = wallet
        block = self._block_for(market)
        if block is not None:
            block['outcome'] = 'sold'
        self.closed_trades.append(trade)
        self.last_trade = trade
        return 'trades'

    def _trade_detail(self, kind: str, value: str) -> Optional[str]:
        trade = self.last_trade
        if trade is None:
            return None
        selling = trade['exit_ts'] is not None
        if kind == 'reason':
            if selling:
                trade['exit_reason_raw'] = value
                trade['exit_reason'] = _exit_reason(value)
            else:
                trade['entry_reason'] = value
            return 'trades'
        if kind == 'amount':
            m = RE_AMOUNT_BUY.match(value)
            if m and not selling:
                trade['amount'] = _f(m.group(1))
            return 'trades'
        if kind == 'fill':
            m = RE_FILL.match(value)
            if not m:
                return None
            trade['entry_price'] = _f(m.group(1))
            return 'trades'
        if kind == 'entry_exit':
            m = RE_ENTRY_EXIT.match(value)
            if not m:
                return None
            trade['exit_price'] = _f(m.group(2))
            return 'trades'
        if kind == 'gross_pl':
            m = RE_GROSS_PL.match(value)
            if not m:
                return None
            trade['gross_pl_pct'], trade['gross_pl_eur'] = _f(m.group(1)), _f(m.group(2))
            return 'trades'
        return None

    def _virtual_market(self, ts: str, level: str, msg: str) -> Optional[str]:
        if msg.startswith('[VIRTUAL] Fee: '):
            m = RE_FEE.match(msg)
            if not m:
                return None
            fee, balance = _f(m.group(1)), _f(m.group(2))
            self.buffers['balance'].append((ts, fee, balance))
            market = self.fee_market or (self.block['market'] if self.block else None)
            if market is not None and fee is not None:
                self.pending_fee[market] = self.pending_fee.get(market, 0.0) + fee
            self.fee_market = None
            return 'balance'
        if msg.startswith('[VIRTUAL] Order executed: '):
            m = RE_ORDER_EXECUTED.match(msg)
            if m:
                self.fee_market = m.group(2)
            return 'ignored.order_flow'
        return None

    def _virtual_wallet(self, ts: str, level: str, msg: str) -> Optional[str]:
        if msg.startswith('Virtual SELL: '):
            m = RE_VIRTUAL_SELL.match(msg)
            if not m:
                return None
            self.pending_wallet_pl[m.group(1)] = (_f(m.group(2)), _f(m.group(3)))
            return 'trades'
        return None

    # ------------------------------------------------------- portfolio / cycles

    def _multi_market(self, ts: str, level: str, msg: str) -> Optional[str]:
        if msg.startswith('Checking ') and msg.endswith('markets...'):
            m = RE_CHECKING.match(msg)
            if not m:
                return None
            self._close_block()
            self.cycle = [ts, int(m.group(1)), None, None]
            self.buffers['cycles'].append(self.cycle)
            return 'cycles'
        if msg.startswith('Portfolio Summary: '):
            m = RE_PORTFOLIO.match(msg)
            if not m:
                return None
            self._close_block()
            if self.cycle is not None:
                self.cycle[2] = int(m.group(1))
            return 'cycles'
        if msg.startswith('Active markets: '):
            if self.cycle is not None:
                self.cycle[3] = msg[16:].replace(' ', '')
            return 'cycles'
        if msg.startswith('Rotating in '):
            self.buffers['rotations'].append((ts, msg[12:].strip(), 'in'))
            return 'rotations'
        if msg.startswith('Rotating out '):
            self.buffers['rotations'].append((ts, msg[13:].partition(' ')[0], 'out'))
            return 'rotations'
        if level == 'ERROR' and msg.startswith('Error executing trade for '):
            b = self._block_for(msg[26:].partition(':')[0])
            if b is not None:
                b['outcome'] = 'error'
                b['error_msg'] = msg.partition(': ')[2]
            return 'checks'
        return None

    # ---------------------------------------------------------------- rescans

    def _score_row(self, score: dict) -> tuple:
        return tuple(score.get(c) for c in SCORE_COLUMNS)

    def _finish_score(self) -> None:
        if self.score is not None:
            self.buffers['market_scores'].append(self._score_row(self.score))
            self.score = None

    def _main(self, ts: str, level: str, msg: str) -> Optional[str]:
        score = self.score
        if score is not None:
            m = RE_METRIC_WITH_SCORE.match(msg)
            if m:
                value_field, score_field = METRIC_FIELDS[m.group(1)]
                score[value_field], score[score_field] = _f(m.group(2)), _f(m.group(3))
                return 'market_scores'
            if msg.startswith('Volume Consistency: '):
                score['volume_consistency'] = _f(msg[20:].partition('x')[0])
                return 'market_scores'
            if msg.startswith('Penalty Applied: '):
                score['penalty'] = msg[17:]
                return 'market_scores'
            if msg.startswith('Final Score: '):
                score['final_score'] = _f(msg[13:])
                self._finish_score()
                return 'market_scores'
        if msg[0].isdigit():
            m = RE_SELECTION.match(msg)
            if m:
                self._finish_score()
                self.buffers['selections'].append(
                    (self.rescan_id, ts, int(m.group(1)), m.group(2), _f(m.group(3))))
                return 'selections'
            m = RE_QUICK_SCORE.match(msg)
            if m:
                self.buffers['quick_scores'].append(
                    (self.rescan_id, ts, int(m.group(1)), m.group(2), _f(m.group(3)),
                     _f(m.group(4)), _f(m.group(5))))
                return 'quick_scores'
            return None
        if msg.startswith('PERIODIC MARKET RESCAN'):
            self.pending_periodic = True
            return 'rescans'
        if msg.startswith('STEP 1: Scanning'):
            self._finish_score()
            self.rescan_id += 1
            self.rescans.append([self.rescan_id, ts, int(self.pending_periodic), None, None])
            self.pending_periodic = False
            return 'rescans'
        if msg.startswith('Found ') and 'total altcoins' in msg:
            m = RE_FOUND_ALTCOINS.match(msg)
            if m and self.rescans:
                self.rescans[-1][3] = int(m.group(1))
            return 'rescans'
        if msg.startswith('Performing detailed analysis on '):
            m = RE_ANALYZING_N.match(msg)
            if m and self.rescans:
                self.rescans[-1][4] = int(m.group(1))
            return 'rescans'
        if level == 'WARNING' and msg.startswith('Rejecting ') and 'non-finite' in msg:
            self._finish_score()
            self.buffers['market_scores'].append(self._score_row(
                {'rescan_id': self.rescan_id, 'ts': ts, 'market': msg[10:].partition(':')[0],
                 'rejected_reason': 'non_finite_score'}))
            return 'market_scores'
        return None

    # ------------------------------------------------------------------ output

    def _maybe_flush(self, table: str) -> None:
        if len(self.buffers[table]) >= FLUSH_EVERY:
            self._flush(table)

    def _flush(self, table: str) -> None:
        rows = self.buffers[table]
        if not rows:
            return
        if table == 'checks':
            sql = f"INSERT INTO checks ({', '.join(CHECK_COLUMNS)}) VALUES ({', '.join('?' * len(CHECK_COLUMNS))})"
        else:
            sql = f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})"
        self.conn.executemany(sql, rows)
        self.buffers[table] = []

    def finish(self) -> ParseSummary:
        self._close_block()
        self._finish_score()
        for table in self.buffers:
            self._flush(table)

        trades = self.closed_trades + list(self.open_trades.values())
        trades.sort(key=lambda t: (t['entry_ts'] or '', t['exit_ts'] or '9999'))
        for t in trades:
            fees = [f for f in (t['entry_fee'], t['exit_fee']) if f is not None]
            t['fees_eur'] = sum(fees) if fees else None
            t['hold_minutes'] = _minutes_between(t['entry_ts'], t['exit_ts'])
            t['price_precise'] = None if t['entry_price'] is None else int(t['entry_price'] >= PRECISE_PRICE)
        self.conn.executemany(
            f"INSERT INTO trades ({', '.join(TRADE_COLUMNS)}) VALUES ({', '.join('?' * len(TRADE_COLUMNS))})",
            [tuple(t[c] for c in TRADE_COLUMNS) for t in trades])
        self.conn.executemany("INSERT INTO rescans VALUES (?, ?, ?, ?, ?)", self.rescans)
        self.conn.executemany(
            "INSERT INTO errors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(template, logger, level, count, first, last, example,
              ','.join(f"{m}:{n}" for m, n in markets.most_common()) or None)
             for (logger, level, template), (count, first, last, example, markets)
             in sorted(self.errors.items(), key=lambda kv: -kv[1][0])])
        self.conn.executemany("INSERT INTO line_stats VALUES (?, ?)", sorted(self.stats.items()))
        self.conn.executescript(INDEXES)
        self.conn.commit()

        self.summary.table_counts = {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        return self.summary


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("DROP VIEW IF EXISTS prices_precise")
    for table in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(SCHEMA)


def parse_lines(lines: Iterable[str], conn: sqlite3.Connection, progress_every: int = 0) -> ParseSummary:
    """Parse log lines into the (re)created schema on conn and return a summary."""
    create_schema(conn)
    parser = LogParser(conn)
    started = time.monotonic()
    for i, line in enumerate(lines, 1):
        parser.feed(line)
        if progress_every and i % progress_every == 0:
            print(f"  {i:>12,} lines  ({time.monotonic() - started:6.1f}s)", flush=True)
    return parser.finish()


def parse_file(log_path: Path, db_path: Path) -> ParseSummary:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    # The DB is a derived artifact rebuilt from scratch: durability is not needed
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    started = time.monotonic()
    with open(log_path, encoding='utf-8', errors='replace') as f:
        summary = parse_lines(f, conn, progress_every=1_000_000)
    elapsed = time.monotonic() - started
    conn.executemany("INSERT INTO meta VALUES (?, ?)", [
        ('source', str(log_path)), ('lines', str(summary.lines)),
        ('parse_seconds', f"{elapsed:.1f}"), ('parsed_at', datetime.now().isoformat(timespec='seconds'))])
    conn.commit()
    conn.close()
    summary.table_counts['meta'] = 4
    print(f"Parsed {summary.lines:,} lines in {elapsed:.1f}s -> {db_path}")
    return summary


def print_summary(summary: ParseSummary) -> None:
    print("\nTable rows:")
    for table, count in summary.table_counts.items():
        print(f"  {table:<14} {count:>12,}")
    print("\nLine categories:")
    for category, count in sorted(summary.line_stats.items(), key=lambda kv: -kv[1]):
        print(f"  {category:<28} {count:>12,}")
    unrecognised = summary.line_stats.get('unrecognised', 0)
    print(f"\nUnrecognised lines: {unrecognised:,}")
    for template, count in summary.unrecognised.most_common(20):
        print(f"  {count:>10,}  {template[:150]}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('log', type=Path, help='Bender log file')
    ap.add_argument('--db', type=Path, help='output SQLite file (default: data/analysis/bender_<log stem>.db)')
    args = ap.parse_args(argv)
    db = args.db or Path('data/analysis') / f"bender_{args.log.stem}.db"
    summary = parse_file(args.log, db)
    print_summary(summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
