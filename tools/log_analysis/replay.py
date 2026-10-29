"""Replay Bender's strategy over historical candles.

Indicator snapshots come from one of two sources:

- window_snapshot(): exactly what the live bot computes at time t, i.e. the
  last 100 candles up to t through EnhancedStrategy.calculate_indicators.
  reverse=True reproduces the candle-order bug of the 13 Aug - 28 Oct run
  (indicators over time-reversed candles, the oldest candle read as "now").
- full_series_snapshots(): indicators over a market's whole history in one
  pass. Fast; RSI is within ~0.1% of the 100-candle window, MACD can differ
  near zero. Used for the broad per-market studies.

Decisions mirror EnhancedStrategy: a buy when flat and a signal fires,
otherwise a sell when an exit fires. They are taken on closed bars of
whatever interval the candles have (5m as the bot runs, or 1h).

Fills (see replay()): by default at the bar's close with the virtual
wallet's 0.25% fee on both sides and no spread. Costs sets the taker and
maker fees and a half-spread, and `spreads` gives one per market: market
orders then buy above and sell below the close. With Rules.entry_order or
take_profit_order set to 'limit', the buy or the take-profit is a limit
order that fills at its limit price, with the maker fee and no spread, once
a bar's low (buy) or high (take-profit) reaches it.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable, Optional

import pandas as pd

from trader.enhanced_strategy import REQUIRED_INDICATORS, EnhancedStrategy

INDICATORS = dict(zip(REQUIRED_INDICATORS, ['rsi', 'macd', 'macd_signal', 'bb_lower', 'bb_upper'], strict=True))
SNAPSHOT_COLUMNS = ['rsi', 'macd', 'macd_signal', 'bb_lower', 'bb_upper', 'close', 'price', 'low', 'high', 'trend_1d', 'trend_7d']
TREND_WINDOWS = {'trend_1d': '1D', 'trend_7d': '7D'}

STRONG, MODERATE, NEAR_SUPPORT = 'Strong Oversold', 'Moderate Oversold + Momentum', 'Near Support + Momentum'


def _indicators(df: pd.DataFrame) -> pd.DataFrame:
    # calculate_indicators does not use instance state; calling it unbound
    # keeps the replay on exactly the live indicator code
    return EnhancedStrategy.calculate_indicators(None, df)


@dataclass(frozen=True)
class Rules:
    """Strategy parameters; the defaults are the live configuration."""
    rsi_buy_strong: float = 40.0
    rsi_buy_moderate: float = 50.0
    rsi_sell: float = 60.0
    take_profit_pct: float = 15.0
    stop_loss_pct: float = 5.0
    signals: tuple = (STRONG, MODERATE, NEAR_SUPPORT)
    technical_exit: bool = True
    trailing_stop_pct: Optional[float] = None
    max_hold: Optional[pd.Timedelta] = None
    # Signal 3 needs MACD above its signal line (margin 0). The Aug-Oct bot
    # accepted MACD up to 0.000001 below it: an absolute margin larger than
    # MACD itself for sub-cent coins, so it also fired when momentum was bearish
    near_support_macd_margin: float = 0.0
    # '1d' / '7d': only buy while the price is above its 1-day / 7-day average
    require_uptrend: Optional[str] = None
    # 'limit': buy with a limit order limit_offset_pct below the signal price,
    # valid for limit_timeout; it fills (maker fee, no spread) once a bar's low reaches it
    entry_order: str = 'market'
    limit_offset_pct: float = 0.5
    limit_timeout: pd.Timedelta = pd.Timedelta(minutes=15)
    # 'limit': rest the take-profit at entry * (1 + take_profit_pct / 100); fills when a bar's high reaches it
    take_profit_order: str = 'market'


@dataclass(frozen=True)
class Costs:
    """Trading costs: fees as fractions of the traded value, half_spread as a fraction of the price."""
    taker_fee: float = 0.0025
    maker_fee: float = 0.0015
    half_spread: float = 0.0


TAKER = Costs()

LIVE_RULES = Rules()
AUG_OCT_RULES = Rules(near_support_macd_margin=0.000001)


def buy_reason(s, rules: Rules) -> Optional[str]:
    """Mirror of EnhancedStrategy.should_buy (first matching signal wins)."""
    if rules.require_uptrend is not None and not getattr(s, f'trend_{rules.require_uptrend}') > 0:
        return None  # NaN (unknown trend) blocks too
    if STRONG in rules.signals and s.rsi < rules.rsi_buy_strong:
        return STRONG
    if MODERATE in rules.signals and s.rsi < rules.rsi_buy_moderate and s.macd > s.macd_signal:
        return MODERATE
    if NEAR_SUPPORT in rules.signals and s.close < s.bb_lower * 1.01 and s.macd > s.macd_signal - rules.near_support_macd_margin:
        return NEAR_SUPPORT
    return None


def sell_reason(s, price: float, entry: float, peak: float, held: pd.Timedelta, rules: Rules) -> Optional[str]:
    """Mirror of EnhancedStrategy.should_sell, plus optional trailing-stop and max-hold exits."""
    if rules.technical_exit and s.rsi > rules.rsi_sell and s.macd < s.macd_signal:
        return 'technical'
    pct = (price - entry) / entry * 100
    if pct >= rules.take_profit_pct:
        return 'take_profit'
    if pct <= -rules.stop_loss_pct:
        return 'stop_loss'
    if rules.trailing_stop_pct is not None and price <= peak * (1 - rules.trailing_stop_pct / 100):
        return 'trailing_stop'
    if rules.max_hold is not None and held >= rules.max_hold:
        return 'max_hold'
    return None


def window_snapshot(candles: pd.DataFrame, at: pd.Timestamp, window: int = 100, reverse: bool = False):
    """Indicators the live bot computes at `at` from the last `window` candles, or None."""
    recent = candles.loc[:at].iloc[-window:]
    if recent.empty:
        return None
    price = float(recent['close'].iloc[-1])
    df = _indicators((recent.iloc[::-1] if reverse else recent).copy())
    if not EnhancedStrategy._has_indicators(df):
        return None
    last = df.iloc[-1]
    # The live bot only sees 100 candles: no multi-day trend in this mode
    return SimpleNamespace(**{name: float(last[col]) for col, name in INDICATORS.items()},
                           close=float(last['close']), price=price,
                           low=float(recent['low'].iloc[-1]), high=float(recent['high'].iloc[-1]), candle_ts=df.index[-1],
                           trend_1d=float('nan'), trend_7d=float('nan'))


def window_snapshots(candles: pd.DataFrame, times, window: int = 100, reverse: bool = False) -> pd.DataFrame:
    """window_snapshot() at each time, as a frame indexed by time (missing ones dropped)."""
    rows = {}
    for t in times:
        snap = window_snapshot(candles, t, window, reverse)
        if snap is not None:
            rows[t] = [getattr(snap, c) for c in SNAPSHOT_COLUMNS]
    return pd.DataFrame.from_dict(rows, orient='index', columns=SNAPSHOT_COLUMNS).sort_index()


def full_series_snapshots(candles: pd.DataFrame) -> pd.DataFrame:
    df = _indicators(candles.copy()).rename(columns=INDICATORS)
    df['price'] = df['close']
    for column, window in TREND_WINDOWS.items():
        df[column] = df['close'] / df['close'].rolling(window).mean() - 1
    return df[SNAPSHOT_COLUMNS].dropna()


def replay(snapshots: dict, rules: Rules = LIVE_RULES, schedule: Optional[pd.DataFrame] = None,
           max_positions: Optional[int] = 3, stake: float = 10.0,
           costs: Costs = TAKER, spreads: Optional[dict] = None, occupied=(), fill: Optional[Callable] = None) -> pd.DataFrame:
    """Simulate the portfolio over time.

    Args:
        snapshots: market -> frame indexed by time with SNAPSHOT_COLUMNS
        schedule: optional frame (t, market) of when each market was being
            monitored, in evaluation order; without it every market is
            evaluated at every snapshot. Held markets are always managed.
        max_positions: concurrent position limit (None: unlimited)
        costs: fees and default half-spread; market orders buy at
            price * (1 + half_spread) and sell at price * (1 - half_spread),
            both paying the taker fee. entry_price/exit_price are those fills
        spreads: market -> half-spread fraction, overriding costs.half_spread
        Limit orders (Rules.entry_order / take_profit_order) fill at their
        limit price with the maker fee and no spread; a pending buy counts
        toward max_positions until it fills or expires.
        occupied: (start, end) intervals of slots held by positions outside
            the simulation (e.g. the stuck delisted RVN-EUR position)
        fill: optional fill(market, t) -> snapshot row for a held market
            that has no precomputed snapshot at t

    Returns one row per trade; positions still open at the end have NaN exits.
    """
    rows = {m: dict(zip(f.index, f[SNAPSHOT_COLUMNS].itertuples(index=False, name='Snap'), strict=True))
            for m, f in snapshots.items()}
    if schedule is not None:
        monitored = schedule.groupby('t', sort=False)['market'].apply(list).to_dict()
    else:
        monitored = {}
        for market in sorted(rows):
            for t in rows[market]:
                monitored.setdefault(t, []).append(market)
    times = sorted(set(monitored) | {t for r in rows.values() for t in r})

    open_positions, pending, trades = {}, {}, []
    for t in times:
        for market in [m for m, (_, deadline, _) in pending.items() if t > deadline]:
            del pending[market]
        held_elsewhere = sum(1 for start, end in occupied if start <= t < end)
        candidates = monitored.get(t, [])
        for market in candidates + [m for m in [*open_positions, *pending] if m not in candidates]:
            snap = rows.get(market, {}).get(t)
            if snap is None and fill is not None and market in open_positions:
                snap = fill(market, t)
            if snap is None:
                continue
            if market in pending:
                limit, _, reason = pending[market]
                if snap.low <= limit:
                    del pending[market]
                    open_positions[market] = dict(market=market, entry_t=t, entry_price=limit, entry_fee=costs.maker_fee,
                                                  entry_reason=reason, peak=snap.price, trough=min(snap.price, snap.low))
                continue
            position = open_positions.get(market)
            if position is None:
                reason = buy_reason(snap, rules)
                full = max_positions is not None and len(open_positions) + len(pending) + held_elsewhere >= max_positions
                if reason and not full:
                    if rules.entry_order == 'limit':
                        pending[market] = (snap.price * (1 - rules.limit_offset_pct / 100), t + rules.limit_timeout, reason)
                    else:
                        entry = snap.price * (1 + _half_spread(market, costs, spreads))
                        open_positions[market] = dict(market=market, entry_t=t, entry_price=entry, entry_fee=costs.taker_fee,
                                                      entry_reason=reason, peak=snap.price, trough=snap.price)
                continue
            position['peak'] = max(position['peak'], snap.price)
            position['trough'] = min(position['trough'], snap.price)
            target = position['entry_price'] * (1 + rules.take_profit_pct / 100)
            if rules.take_profit_order == 'limit' and snap.high >= target:
                trades.append(_close(open_positions.pop(market), t, target, 'take_profit', stake, costs.maker_fee))
                continue
            reason = sell_reason(snap, snap.price, position['entry_price'], position['peak'],
                                 t - position['entry_t'], rules)
            if reason:
                exit_fill = snap.price * (1 - _half_spread(market, costs, spreads))
                trades.append(_close(open_positions.pop(market), t, exit_fill, reason, stake, costs.taker_fee))
    trades += [_close(p, None, None, None, stake, costs.taker_fee) for p in open_positions.values()]
    return pd.DataFrame(trades, columns=['market', 'entry_t', 'entry_price', 'entry_reason', 'exit_t', 'exit_price',
                                         'exit_reason', 'pl_pct', 'pl_eur', 'hold', 'mfe_pct', 'mae_pct'])


def _half_spread(market, costs: Costs, spreads: Optional[dict]) -> float:
    return costs.half_spread if spreads is None else spreads.get(market, costs.half_spread)


def _close(position, t, price, reason, stake, exit_fee) -> dict:
    entry = position['entry_price']
    trade = dict(market=position['market'], entry_t=position['entry_t'], entry_price=entry,
                 entry_reason=position['entry_reason'], exit_t=t, exit_price=price, exit_reason=reason,
                 mfe_pct=(position['peak'] / entry - 1) * 100, mae_pct=(position['trough'] / entry - 1) * 100,
                 pl_pct=None, pl_eur=None, hold=None)
    if t is not None:
        # Same accounting as the virtual wallet: fee on the stake when buying
        # and on the proceeds when selling
        pl_eur = stake * (price / entry) * (1 - exit_fee) - stake * (1 + position['entry_fee'])
        trade.update(pl_eur=pl_eur, pl_pct=pl_eur / stake * 100, hold=t - position['entry_t'])
    return trade
