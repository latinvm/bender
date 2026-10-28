"""Analyse a Bender run: what happened, why, and what would have worked.

Inputs are the database written by tools.log_analysis.parse and the candle
cache written by tools.log_analysis.candles. Writes report.md (tables) and
results.json (the same numbers, machine-readable) to --out.

    venv/bin/python -m tools.log_analysis.analyze \\
        --log-db data/analysis/bender_2026-08-13.db \\
        --candles data/analysis/candles_5m.db --out data/analysis

Log timestamps are UTC (verified against Bitvavo candles).
"""

import argparse
from dataclasses import replace
import json
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from tools.log_analysis.candles import INTERVAL_MS, CandleStore
from tools.log_analysis.replay import (
    AUG_OCT_RULES, MODERATE, NEAR_SUPPORT, STRONG, Rules, buy_reason, full_series_snapshots, replay, window_snapshot,
    window_snapshots)
from tools.log_analysis.validation import exit_agreement

FEE_ROUND_TRIP_PCT = 0.5
FIVE_MIN = pd.Timedelta(minutes=5)

# Walk-forward periods: rules are judged on the period before the live run
# and then checked on the live run itself, split in two halves
PERIODS = {
    'before (15 May-12 Aug)': ('2026-05-15', '2026-08-13'),
    'live A (13 Aug-30 Sep)': ('2026-08-13', '2026-10-01'),
    'live B (1-28 Oct)': ('2026-10-01', '2026-10-29'),
}

VARIANTS = {
    'Aug-Oct live rules': AUG_OCT_RULES,
    'signal 1 only (RSI<40)': replace(AUG_OCT_RULES, signals=(STRONG,)),
    'signal 2 only (RSI<50 + MACD up)': replace(AUG_OCT_RULES, signals=(MODERATE,)),
    'signal 3 only (near lower BB)': replace(AUG_OCT_RULES, signals=(NEAR_SUPPORT,)),
    'current rules (strict signal 3)': Rules(),
    'no technical exit (TP 15 / SL 5)': replace(AUG_OCT_RULES, technical_exit=False),
    'TP 5 / SL 3, no technical exit': replace(AUG_OCT_RULES, technical_exit=False, take_profit_pct=5, stop_loss_pct=3),
    'TP 3 / SL 3, no technical exit': replace(AUG_OCT_RULES, technical_exit=False, take_profit_pct=3, stop_loss_pct=3),
    'TP 10 / SL 5, no technical exit': replace(AUG_OCT_RULES, technical_exit=False, take_profit_pct=10, stop_loss_pct=5),
    'trailing 3%, SL 5, no technical exit': replace(AUG_OCT_RULES, technical_exit=False, trailing_stop_pct=3),
    'trailing 5%, SL 5, no technical exit': replace(AUG_OCT_RULES, technical_exit=False, trailing_stop_pct=5),
    'live rules + max hold 24h': replace(AUG_OCT_RULES, max_hold=pd.Timedelta(hours=24)),
    'RSI<30 only, TP 5 / SL 3, no technical exit': replace(AUG_OCT_RULES, signals=(STRONG,), rsi_buy_strong=30,
                                                                  technical_exit=False, take_profit_pct=5, stop_loss_pct=3),
    'live rules, only above 1-day average': replace(AUG_OCT_RULES, require_uptrend='1d'),
    'live rules, only above 7-day average': replace(AUG_OCT_RULES, require_uptrend='7d'),
    'TP 3 / SL 3, no technical exit, only above 7-day average': replace(AUG_OCT_RULES, technical_exit=False, take_profit_pct=3,
                                                                                        stop_loss_pct=3, require_uptrend='7d'),
}


# ---------------------------------------------------------------- helpers

def bars_for(horizon: pd.Timedelta, interval: str) -> int:
    """Number of candles of `interval` that span `horizon`."""
    return int(horizon / pd.Timedelta(milliseconds=INTERVAL_MS[interval]))


def min_history(interval: str) -> int:
    """Fewest candles a market needs for the studies: 500 of 5 minutes (as always), four days of hourly ones."""
    return 500 if interval == '5m' else bars_for(pd.Timedelta(days=4), interval)


def median_spreads(conn) -> dict:
    """Per market median bid-ask half-spread as a fraction (market_scores.spread_pct is a percentage)."""
    spreads = pd.read_sql('SELECT market, spread_pct FROM market_scores WHERE spread_pct IS NOT NULL', conn)
    return (spreads.groupby('market')['spread_pct'].median() / 200).to_dict()


def md_table(df: pd.DataFrame, floatfmt: str = '{:.2f}') -> list:
    df = df.reset_index() if df.index.name or isinstance(df.index, pd.MultiIndex) else df
    head = '| ' + ' | '.join(str(c) for c in df.columns) + ' |'
    sep = '|' + '|'.join('---' for _ in df.columns) + '|'

    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return '' if pd.isna(v) else floatfmt.format(v)
        return str(v)
    rows = ['| ' + ' | '.join(fmt(v) for v in row) + ' |' for row in df.itertuples(index=False)]
    return [head, sep, *rows, '']


def trade_stats(trades: pd.DataFrame) -> dict:
    closed = trades.dropna(subset=['pl_eur'])
    if closed.empty:
        return dict(trades=0, win_pct=np.nan, avg_pl_pct=np.nan, total_eur=0.0, profit_factor=np.nan,
                    median_hold_h=np.nan)
    wins, losses = closed.pl_eur[closed.pl_eur > 0].sum(), -closed.pl_eur[closed.pl_eur <= 0].sum()
    hold = closed['hold'] if 'hold' in closed else pd.to_timedelta(closed.hold_minutes, unit='min')
    return dict(trades=len(closed), win_pct=(closed.pl_eur > 0).mean() * 100, avg_pl_pct=closed.pl_pct.mean(),
                total_eur=closed.pl_eur.sum(), profit_factor=wins / losses if losses else np.inf,
                median_hold_h=pd.to_timedelta(hold).median() / pd.Timedelta(hours=1))


_store = None


def _candles(db_path, market):
    global _store
    if _store is None:
        _store = CandleStore(db_path)
    return _store.load(market)


def schedule_from_checks(conn) -> pd.DataFrame:
    """(t, market) pairs: the 5-minute buckets each market was evaluated in, in log order."""
    checks = pd.read_sql('SELECT id, ts, market FROM checks', conn, parse_dates=['ts'])
    checks['t'] = checks.ts.dt.floor('5min')
    first = checks.groupby(['t', 'market'], sort=False).id.min().reset_index()
    return first.sort_values('id')[['t', 'market']].reset_index(drop=True)


# ---------------------------------------------------------- 1. live run

def live_run(conn) -> tuple:
    trades = pd.read_sql('SELECT * FROM trades', conn, parse_dates=['entry_ts', 'exit_ts'])
    closed = trades.dropna(subset=['exit_ts'])
    overall = trade_stats(closed)
    overall.update(gross_eur=closed.gross_pl_eur.sum(), fees_eur=closed.fees_eur.sum())

    def by(col):
        g = closed.groupby(col)
        out = pd.DataFrame({'trades': g.size(), 'win %': g.pl_eur.apply(lambda x: (x > 0).mean() * 100),
                            'avg P/L %': g.pl_pct.mean(), 'total €': g.pl_eur.sum(),
                            'median hold h': g.hold_minutes.median() / 60,
                            'median best %': g.mfe_pct.median(), 'median worst %': g.mae_pct.median()})
        out.index.name = col
        return out
    quick = closed[closed.hold_minutes < 10]
    losers = closed[closed.pl_eur < 0]
    outcomes = pd.read_sql('SELECT outcome, COUNT(*) AS checks FROM checks GROUP BY outcome ORDER BY checks DESC', conn)
    errors = pd.read_sql('SELECT template, count, first_ts, last_ts FROM errors ORDER BY count DESC LIMIT 5', conn)
    open_now = trades[trades.exit_ts.isna()][['market', 'entry_ts', 'entry_reason', 'mfe_pct', 'mae_pct']]

    result = dict(overall=overall, quick_round_trips=dict(trades=len(quick), total_eur=quick.pl_eur.sum(),
                                                          near_support=int((quick.entry_reason == NEAR_SUPPORT).sum())),
                  losers_once_up_5pct=int((losers.mfe_pct >= 5).sum()), losers=len(losers))
    md = ['## 1. What the live run did', '',
          f"{overall['trades']} closed trades, win rate {overall['win_pct']:.1f}%, average {overall['avg_pl_pct']:+.2f}% "
          f"per trade, total €{overall['total_eur']:+.2f} (gross €{overall['gross_eur']:+.2f}, fees €{overall['fees_eur']:.2f}).", '',
          '### By exit reason', '', *md_table(by('exit_reason')),
          '### By entry signal', '', *md_table(by('entry_reason')),
          f"- {len(quick)} trades were closed within 10 minutes of opening (€{quick.pl_eur.sum():+.2f}); "
          f"{result['quick_round_trips']['near_support']} of them entered on signal 3.",
          f"- {result['losers_once_up_5pct']} of {len(losers)} losing trades had been at least +5% up.", '',
          '### Check outcomes', '', *md_table(outcomes),
          '### Most frequent errors', '', *md_table(errors),
          '### Still open at the end of the log', '', *md_table(open_now)]
    return md, result


# ----------------------------------------------- 2. bug reproduction

def _reproduce(args):
    db_path, market, rows = args
    candles = _candles(db_path, market)
    out = []
    for check_id, t, rsi, price, logged_buy in rows:
        buggy, fixed = window_snapshot(candles, t, reverse=True), window_snapshot(candles, t)
        if buggy is None or fixed is None:
            continue
        out.append((check_id, market, rsi, price, buggy.rsi, buggy.close, fixed.rsi, fixed.close,
                    bool(logged_buy), buy_reason(buggy, AUG_OCT_RULES) is not None))
    return out


def bug_reproduction(conn, candles_db, n=3000, seed=7) -> tuple:
    checks = pd.read_sql("SELECT id, ts, market, rsi, candle_price, (sig1 OR sig2 OR sig3) AS logged_buy FROM checks "
                         "WHERE rsi IS NOT NULL AND price_precise = 1", conn, parse_dates=['ts'])
    sample = checks.sample(min(n, len(checks)), random_state=seed)
    sample['t'] = sample.ts.dt.floor('5min')
    jobs = [(candles_db, m, list(g[['id', 't', 'rsi', 'candle_price', 'logged_buy']].itertuples(index=False, name=None)))
            for m, g in sample.groupby('market')]
    with ProcessPoolExecutor() as pool:
        rows = [r for chunk in pool.map(_reproduce, jobs) for r in chunk]
    df = pd.DataFrame(rows, columns=['id', 'market', 'rsi', 'price', 'buggy_rsi', 'buggy_close', 'fixed_rsi', 'fixed_close',
                                     'logged_buy', 'replayed_buy'])

    def match(rsi_col, close_col):
        return ((df[rsi_col] - df.rsi).abs() < 1.0) & ((df[close_col] / df.price - 1).abs() < 0.002)
    result = dict(compared=len(df), buggy_match_pct=match('buggy_rsi', 'buggy_close').mean() * 100,
                  fixed_match_pct=match('fixed_rsi', 'fixed_close').mean() * 100,
                  median_abs_rsi_gap_fixed_vs_logged=(df.fixed_rsi - df.rsi).abs().median(),
                  buy_decision_agreement_pct=(df.logged_buy == df.replayed_buy).mean() * 100,
                  logged_buy_pct=df.logged_buy.mean() * 100)
    md = ['## 2. Reproducing what the bot saw', '',
          f"{len(df)} randomly sampled checks were recomputed from Bitvavo candles. A check matches when RSI is within "
          f"1 point and the candle price within 0.2% of the logged values.", '',
          f"- Candles in time-reversed order (the bug): **{result['buggy_match_pct']:.1f}%** match.",
          f"- Candles in correct order (the fix): **{result['fixed_match_pct']:.1f}%** match; the median RSI gap "
          f"between what was logged and the correct value is {result['median_abs_rsi_gap_fixed_vs_logged']:.1f} points.",
          f"- Buy signal or not: the reversed-candle replay agrees with the logged decision in "
          f"**{result['buy_decision_agreement_pct']:.1f}%** of checks (a buy signal was logged in "
          f"{result['logged_buy_pct']:.1f}% of them).", '']
    return md, result


# --------------------------------------- 3. replays on the live schedule

def _buggy_snapshots(args):
    db_path, market, times = args
    return market, window_snapshots(_candles(db_path, market), times, reverse=True)


def _full_snapshots(args):
    db_path, market = args
    candles = _candles(db_path, market)
    return market, (full_series_snapshots(candles) if len(candles) else None)


def live_replays(conn, candles_db) -> tuple:
    schedule = schedule_from_checks(conn)
    live = pd.read_sql('SELECT * FROM trades', conn, parse_dates=['entry_ts', 'exit_ts'])
    end = schedule.t.max() + FIVE_MIN
    # Slots the simulation cannot reproduce: positions carried over from the
    # previous session, and RVN-EUR (no candles exist for delisted markets)
    occupied = [(schedule.t.min(), e if pd.notna(e) else end)
                for e in live[live.pre_log == 1].exit_ts]
    occupied += [(r.entry_ts, end) for r in live[live.market == 'RVN-EUR'].itertuples()]

    jobs = [(candles_db, m, sorted(g.t.unique())) for m, g in schedule.groupby('market')]
    with ProcessPoolExecutor() as pool:
        buggy = {m: f for m, f in pool.map(_buggy_snapshots, jobs) if not f.empty}
        full = {m: f for m, f in pool.map(_full_snapshots, [(candles_db, m) for m in schedule.market.unique()])
                if f is not None and not f.empty}

    cache = {}

    def fill(market, t):
        if market not in cache:
            cache[market] = _candles(candles_db, market)
        return window_snapshot(cache[market], t, reverse=True)

    runs = {
        'as live (reversed candles, live rules)': replay(buggy, AUG_OCT_RULES, schedule=schedule, occupied=occupied, fill=fill),
        'fixed candles, Aug-Oct rules': replay(full, AUG_OCT_RULES, schedule=schedule),
        'fixed candles, current rules': replay(full, Rules(), schedule=schedule),
        'fixed candles, signal 1 only': replay(full, replace(AUG_OCT_RULES, signals=(STRONG,)), schedule=schedule),
    }
    live_closed = live[(live.pre_log == 0)].dropna(subset=['exit_ts'])
    table = {'live run (actual)': trade_stats(live_closed)}
    for name, trades in runs.items():
        table[name] = trade_stats(trades)
    table = pd.DataFrame(table).T
    table.index.name = 'run'

    # How many live entries the as-live replay reproduces (same market, within 15 minutes)
    sim = runs['as live (reversed candles, live rules)']
    matched = 0
    for r in live[live.pre_log == 0].itertuples():
        near = sim[(sim.market == r.market) & ((sim.entry_t - r.entry_ts.floor('5min')).abs() <= pd.Timedelta(minutes=15))]
        matched += not near.empty
    n_live = int((live.pre_log == 0).sum())
    no_candles = sorted(set(schedule.market) - set(full))
    exits = exit_agreement(live, buggy, AUG_OCT_RULES)
    result = dict(runs=table.to_dict(orient='index'), live_entries_reproduced=matched, live_entries=n_live,
                  exit_agreement=exits,
                  markets_without_candles=no_candles,
                  exit_mix={k: v.exit_reason.value_counts().to_dict() for k, v in runs.items()})
    md = ['## 3. Replaying the live period', '',
          'Same markets at the same times as the live bot, max 3 positions, €10 per trade, 0.25% fee per side.',
          'The first replay reproduces the bug, to check that the simulator behaves like the live bot; the others '
          'show what the same period would have looked like with correctly ordered candles.', '',
          *md_table(table),
          f"- The as-live portfolio replay reproduces only {matched} of {n_live} live entries (same market, within 15 "
          "minutes): with the position limit binding, one different exit sends the whole run down a different path.",
          f"- Trade by trade it does match: starting each of {exits['trades']} live trades at its real entry, the replay "
          f"exits within 15 minutes of the live exit in {exits['same_time_pct']:.0f}% of trades and for the same reason in "
          f"{exits['same_reason_pct']:.0f}%; P/L correlation {exits['pl_correlation']:.2f} (average {exits['sim_avg_pl']:+.2f}% "
          f"replayed vs {exits['live_avg_pl']:+.2f}% live).",
          f"- Markets without candle data (excluded): {', '.join(no_candles) or 'none'}.", '',
          'Exit reasons per run:', '']
    for name, mix in result['exit_mix'].items():
        md.append(f"- {name}: " + ', '.join(f"{k} {v}" for k, v in mix.items()))
    md.append('')
    return md, result


# ------------------------------------- 4. rule variants, walk-forward

def _study_market(args):
    db_path, market, interval = args
    candles = _candles(db_path, market)
    if len(candles) < min_history(interval):
        return []
    snaps = full_series_snapshots(candles)
    out = []
    for period, (start, end) in PERIODS.items():
        window = snaps.loc[start:end]
        if len(window) < bars_for(pd.Timedelta(days=1), interval):  # less than a day of data
            continue
        hold_return = (window.price.iloc[-1] / window.price.iloc[0] - 1) * 100
        for name, rules in VARIANTS.items():
            trades = replay({market: window}, rules, max_positions=None)
            trades['variant'], trades['period'], trades['hold_return'] = name, period, hold_return
            out.append(trades)
        out.append(pd.DataFrame({'market': [market], 'variant': ['__buy_and_hold__'], 'period': [period],
                                 'hold_return': [hold_return]}))
    return out


def rule_study(markets, candles_db, interval='5m') -> tuple:
    with ProcessPoolExecutor() as pool:
        frames = [f for chunk in pool.map(_study_market, [(candles_db, m, interval) for m in markets]) for f in chunk]
    df = pd.concat(frames, ignore_index=True)
    hold = df[df.variant == '__buy_and_hold__'].groupby('period').hold_return.agg(['mean', 'median', 'size'])
    trades = df[df.variant != '__buy_and_hold__']
    rows = []
    for (variant, period), g in trades.groupby(['variant', 'period'], sort=False):
        s = trade_stats(g)
        s.update(variant=variant, period=period, markets=g.market.nunique())
        rows.append(s)
    stats = pd.DataFrame(rows)
    pivot = stats.pivot(index='variant', columns='period', values='avg_pl_pct')[list(PERIODS)].reindex(list(VARIANTS))
    counts = stats.pivot(index='variant', columns='period', values='trades')[list(PERIODS)].reindex(list(VARIANTS))
    win = stats.pivot(index='variant', columns='period', values='win_pct')[list(PERIODS)].reindex(list(VARIANTS))
    pivot.index.name = counts.index.name = win.index.name = 'variant'
    result = dict(stats=stats.to_dict(orient='records'), buy_and_hold=hold.to_dict(orient='index'))
    md = ['## 4. Which rules would have worked? (walk-forward)', '',
          f"Each rule set runs independently on each of {df.market.nunique()} markets the bot monitored (one position "
          "per market, correctly ordered candles, 0.25% fee per side). Judge rules on the first period, then check "
          "that they hold up on the two live periods.", '',
          '### Average net P/L per trade (%)', '', *md_table(pivot, '{:+.2f}'),
          '### Number of trades', '', *md_table(counts, '{:.0f}'),
          '### Win rate (%)', '', *md_table(win, '{:.1f}'),
          '### Buy and hold over the same markets (% per market)', '', *md_table(hold)]
    return md, result


# --------------------------------------------- 5. signal forward returns

def _signal_edges(args):
    db_path, market, interval = args
    candles = _candles(db_path, market)
    if len(candles) < min_history(interval):
        return None
    snaps = full_series_snapshots(candles)
    grid = candles.close.resample(pd.Timedelta(milliseconds=INTERVAL_MS[interval])).last().ffill()
    horizons = {h: bars_for(pd.Timedelta(h), interval) for h in ('1h', '4h', '24h')}
    fwd = {h: (grid.shift(-k) / grid - 1).reindex(snaps.index) * 100 for h, k in horizons.items()}
    rows = []
    for name, only in (('signal 1', STRONG), ('signal 2', MODERATE), ('signal 3', NEAR_SUPPORT)):
        single = replace(AUG_OCT_RULES, signals=(only,))
        fired = pd.Series([buy_reason(s, single) is not None for s in snaps.itertuples()], index=snaps.index)
        starts = fired & ~fired.shift(1, fill_value=False)
        for period, (start, end) in PERIODS.items():
            sel = starts.loc[start:end]
            sel = sel[sel].index
            base = {h: f.loc[start:end].mean() for h, f in fwd.items()}
            for t in sel:
                rows.append(dict(market=market, signal=name, period=period,
                                 **{f'fwd_{h}': fwd[h].get(t) for h in horizons},
                                 **{f'base_{h}': base[h] for h in horizons}))
    return pd.DataFrame(rows)


def signal_edges(markets, candles_db, interval='5m') -> tuple:
    with ProcessPoolExecutor() as pool:
        frames = [f for f in pool.map(_signal_edges, [(candles_db, m, interval) for m in markets]) if f is not None]
    df = pd.concat(frames, ignore_index=True).dropna()
    g = df.groupby(['signal', 'period'], sort=False)
    table = pd.DataFrame({
        'signals': g.size(),
        '1h after %': g.fwd_1h.mean(), '4h after %': g.fwd_4h.mean(), '24h after %': g.fwd_24h.mean(),
        '4h vs random %': g.apply(lambda x: (x.fwd_4h - x.base_4h).mean()),
        '24h vs random %': g.apply(lambda x: (x.fwd_24h - x.base_24h).mean()),
        '4h up %': g.fwd_4h.apply(lambda x: (x > 0).mean() * 100),
    })
    table.index.names = ['signal', 'period']
    result = table.reset_index().to_dict(orient='records')
    md = ['## 5. Do the buy signals predict anything?', '',
          'Price change after each new signal (correctly ordered candles) compared with the average change over all '
          f'times in the same market and period ("vs random"). A round trip costs {FEE_ROUND_TRIP_PCT}% in fees, so '
          'a signal needs to beat random by more than that to pay for itself.', '',
          *md_table(table, '{:+.2f}')]
    return md, result


# ------------------------------------------------ 6. market selection

def market_selection(conn, candles_db) -> tuple:
    scores = pd.read_sql('SELECT rescan_id, ts, market, sharpe, sortino, volatility_pct, final_score FROM market_scores '
                         'WHERE rejected_reason IS NULL', conn, parse_dates=['ts'])
    selected = pd.read_sql('SELECT rescan_id, market FROM selections', conn)
    selected['selected'] = True
    scores = scores.merge(selected, on=['rescan_id', 'market'], how='left').fillna({'selected': False})
    rows = []
    for market, g in scores.groupby('market'):
        candles = _candles(candles_db, market)
        if candles.empty:
            continue
        close = candles.close

        def at(ts, close=close):
            before = close.loc[:ts]
            return before.iloc[-1] if len(before) else np.nan
        for r in g.itertuples():
            now = at(r.ts)
            rows.append(dict(market=market, rescan_id=r.rescan_id, sharpe=r.sharpe, selected=r.selected,
                             past_7d=(now / at(r.ts - pd.Timedelta(days=7)) - 1) * 100,
                             next_24h=(at(r.ts + pd.Timedelta(hours=24)) / now - 1) * 100))
    df = pd.DataFrame(rows).dropna()
    corr_past = df[['sharpe', 'past_7d']].corr(method='spearman').iloc[0, 1]
    corr_next = df[['sharpe', 'next_24h']].corr(method='spearman').iloc[0, 1]
    by_sel = df.groupby('selected')[['past_7d', 'next_24h']].mean()
    by_sel.index = by_sel.index.map({True: 'selected', False: 'not selected'})
    by_sel.index.name = 'candidates'
    result = dict(rows=len(df), spearman_sharpe_vs_past_7d=corr_past, spearman_sharpe_vs_next_24h=corr_next,
                  by_selection=by_sel.to_dict(orient='index'))
    md = ['## 6. Market selection', '',
          f"{len(df)} scored candidates across all rescans, with their price change over the 7 days before and the "
          "24 hours after each rescan.", '',
          f"- Rank correlation between the logged Sharpe ratio and the past 7-day return: **{corr_past:+.2f}**. "
          "A correct Sharpe ratio rises with past returns; a negative value means the scorer ranked falling markets highest.",
          f"- Rank correlation between the logged Sharpe ratio and the next 24 hours: {corr_next:+.2f}.", '',
          *md_table(by_sel, '{:+.2f}')]
    return md, result


# ---------------------------------------------------------------- main

HOURLY_SECTIONS = ('4', '5', '7')  # section 7 arrives with the rule-search work

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--log-db', required=True)
    parser.add_argument('--candles', required=True)
    parser.add_argument('--out', default='data/analysis')
    parser.add_argument('--sections', default='1,2,3,4,5,6', help='comma-separated section numbers to run')
    parser.add_argument('--interval', default='5m', choices=list(INTERVAL_MS), help='candle interval of --candles')
    args = parser.parse_args(argv)
    if args.interval != '5m':
        # the other sections replay or compare against 5-minute candles
        disallowed = set(args.sections.split(',')) - set(HOURLY_SECTIONS)
        if disallowed:
            parser.error(f"--interval {args.interval} supports only sections {','.join(HOURLY_SECTIONS)}, not {','.join(sorted(disallowed))}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.log_db)
    monitored = sorted(pd.read_sql('SELECT DISTINCT market FROM checks', conn).market)
    sections = {
        '1': lambda: live_run(conn),
        '2': lambda: bug_reproduction(conn, args.candles),
        '3': lambda: live_replays(conn, args.candles),
        '4': lambda: rule_study(monitored, args.candles, args.interval),
        '5': lambda: signal_edges(monitored, args.candles, args.interval),
        '6': lambda: market_selection(conn, args.candles),
    }
    md, results = ['# Bender log analysis', ''], {}
    for key in args.sections.split(','):
        print(f'section {key}...', flush=True)
        lines, result = sections[key]()
        md += lines
        results[key] = result
    (out / 'report.md').write_text('\n'.join(md))
    (out / 'results.json').write_text(json.dumps(results, indent=2, default=str))
    print(f"wrote {out / 'report.md'} and {out / 'results.json'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
