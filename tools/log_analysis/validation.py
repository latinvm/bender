"""How far the replay is from what the bot actually did.

exit_agreement() restarts every real trade at its real entry and lets the
replay choose the exit; decision_agreement() recomputes logged decisions from
candles. Both are used by analyze (section 3) and calibrate.
"""

from typing import Callable

import pandas as pd

from tools.log_analysis.replay import Rules, buy_reason, sell_reason, window_snapshot

BUY_ACTIONS = {'buy', 'blocked_position_limit', 'blocked_risk', 'no_price'}
EXIT_TIME_TOLERANCE = pd.Timedelta(minutes=15)


def exit_agreement(trades: pd.DataFrame, snapshots: dict, rules: Rules, fee_rate: float = 0.0025) -> dict:
    """Start each real trade at its real entry and let the replay pick the exit.

    The portfolio replay diverges from the live run as soon as one exit
    differs (the position limit was binding most of the time), so the
    simulator is validated trade by trade instead. Trades whose market has no
    snapshots, or whose replayed run never exits, are left out of `trades`
    (but counted in `of`).
    """
    rows = []
    closed = trades[(trades.pre_log == 0) & trades.exit_ts.notna()]
    for r in closed.itertuples():
        snaps = snapshots.get(r.market)
        if snaps is None:
            continue
        entry_t = r.entry_ts.floor('5min')
        peak, exit_t, reason, price = r.entry_price, None, None, None
        for t, snap in zip(snaps.index, snaps.itertuples(index=False), strict=True):
            if t <= entry_t:
                continue
            peak = max(peak, snap.price)
            reason = sell_reason(snap, snap.price, r.entry_price, peak, t - entry_t, rules)
            if reason:
                exit_t, price = t, snap.price
                break
        if exit_t is None:
            continue
        sim_pl = ((price / r.entry_price) * (1 - fee_rate) - 1 - fee_rate) * 100
        rows.append(dict(same_time=abs(exit_t - r.exit_ts.floor('5min')) <= EXIT_TIME_TOLERANCE,
                         same_reason=reason == r.exit_reason, live_pl=r.pl_pct, sim_pl=sim_pl))
    df = pd.DataFrame(rows, columns=['same_time', 'same_reason', 'live_pl', 'sim_pl'])
    live_avg, sim_avg = df.live_pl.mean(), df.sim_pl.mean()
    return dict(trades=len(df), of=len(closed), same_time_pct=df.same_time.astype(float).mean() * 100,
                same_reason_pct=df.same_reason.astype(float).mean() * 100,
                pl_correlation=df[['live_pl', 'sim_pl']].corr().iloc[0, 1],
                live_avg_pl=live_avg, sim_avg_pl=sim_avg, optimism_pp=sim_avg - live_avg)


def decision_agreement(decisions: pd.DataFrame, candles_for: Callable[[str], pd.DataFrame], rules: Rules,
                       sample: int = 3000, seed: int = 7) -> dict:
    """Recompute logged flat-position decisions from candles and compare.

    Indicators match when RSI is within 1 point and the candle close within
    0.2% of the logged values; the buy check compares the logged action with
    whether `rules` would signal a buy on the recomputed snapshot.
    """
    flat = decisions[decisions.rsi.notna() & decisions.entry_price.isna()]
    picked = flat.sample(n=min(sample, len(flat)), random_state=seed)
    cache, rows = {}, []
    for r in picked.itertuples():
        if r.market not in cache:
            cache[r.market] = candles_for(r.market)
        snap = window_snapshot(cache[r.market], r.candle_ts)
        if snap is None:
            continue
        rows.append(dict(match=abs(snap.rsi - r.rsi) <= 1 and abs(snap.close / r.candle_close - 1) <= 0.002,
                         agree=(r.action in BUY_ACTIONS) == (buy_reason(snap, rules) is not None)))
    df = pd.DataFrame(rows, columns=['match', 'agree'])
    return dict(compared=len(df), indicator_match_pct=df.match.astype(float).mean() * 100,
                buy_agreement_pct=df.agree.astype(float).mean() * 100)
