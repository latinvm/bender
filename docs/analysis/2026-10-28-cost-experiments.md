# Cost experiments: can lower costs give Bender's signals an edge?

The [log analysis](2026-10-28-log-analysis.md) found that with correctly ordered candles, Bender's buy
signals beat random entries by only 0.1–0.3% per trade. A round trip costs 0.5% in fees plus the
bid-ask spread. It also found that the replay is about 0.4 percentage points per trade optimistic. Its
section 7 proposed three ways to lower costs: limit orders, hourly candles and tight-spread markets.
This document tests them in the replay and applies a gate that was fixed in the
[strategy improvement plan](../plans/2026-10-28-strategy-improvement-plan.md) before the experiments
ran. The result decides which Phase 4 tasks of that plan go ahead.

## Summary

- **No configuration passes the gate.** None of the 12 configurations averages 0.4% per trade in all
  three periods, and none breaks even in all three. Every one loses money in the 90 days before the
  run and in October. The closest is hourly candles, market orders, RSI < 30 only: −0.72%, +0.52% and
  −0.59% per trade. Its worst period is 1.12 points below the margin.
- **Task 8 cannot change this.** Task 8 will set the margin to max(0.4, measured optimism), so the
  gate can only get stricter. No configuration is waiting on Task 8.
- **Limit orders did not help**, even with a fill model that favours them. They did worse than market
  orders in 17 of 18 comparisons (same interval, rules and period).
- **Hourly candles did not help consistently.** With market orders, they did better than 5-minute
  candles in the Aug–Sep rally for all three rule sets, worse in the period before the run for all
  three, and better in October for one.
- **Tight-spread markets lose less, but only by paying less spread.** The tercile of markets with the
  lowest spreads did better than the tercile with the highest spreads in every period, which meets
  Task 14's gate. With the spread charge removed, the high-spread markets did as well or better in
  every period, so the whole gap is the spread itself. The low-spread markets still lost 0.89% and
  0.92% per trade in two of the three periods.

What this means for the project: the cost reductions tested here do not close the gap between the
signals' edge and the costs. The plan's go/no-go for real money requires a configuration that passes
this gate, so these rules should not trade real money. The shortfall of the closest configuration
(1.12 points per trade) is larger than the whole cost of a market-order round trip at the median
spread (about 0.7 points: 0.5 in fees plus 0.21 in spread). So even trading for free would most likely
leave these rules short of the gate. Passing it would take entries with a larger edge, which this plan
does not include.

## 1. What was tested

**The gate** (fixed in the plan before this run): a configuration passes if its average net P/L per
trade is at least 0.4% in every period, with at least 200 trades in each period. The 0.4 is the
replay's optimism measured in the log analysis (section 8). The periods are the same as in the log
analysis: before (15 May – 12 Aug, the 90 days before the run), live A (13 Aug – 30 Sep) and live B
(1 – 28 Oct).

**The grid:** 2 candle intervals × 2 order types × 3 rule sets = 12 configurations.

| Dimension | Values |
|---|---|
| Candle interval | 5 minutes (as the bot runs now); 1 hour |
| Orders | Market orders; limit orders (below) |
| Rules | Current rules; TP 3 / SL 3, no technical exit; RSI < 30 only, TP 5 / SL 3, no technical exit |

- **Current rules:** the bot's rules on this branch. It buys on any of the three signals: RSI < 40;
  RSI < 50 with MACD above its signal line; or price no more than 1% above the lower Bollinger band
  with MACD above its signal line. It sells on the technical exit (RSI > 60 with MACD below its
  signal line), at +15% (take-profit) or at −5% (stop-loss).
- **TP 3 / SL 3, no technical exit:** the same entries; it sells only at +3% or −3%.
- **RSI < 30 only, TP 5 / SL 3, no technical exit:** it buys only when RSI < 30, and sells at +5% or −3%.

The second and third rule sets were the two that lost least in the "before" period in section 4 of
the log analysis. There they were built on the Aug–Oct rules; here they are built on the current
rules, which differ only in signal 3's MACD check.

**Costs:**

- **Fees:** Bitvavo's base tier on EUR markets, 0.25% for market (taker) orders and 0.15% for limit
  (maker) orders (bitvavo.com/en/fees, checked 28 Oct 2026).
- **Spread:** each market's median bid-ask spread as the market scorer logged it from the order book
  during the run. Over the 145 monitored markets the median is 0.21%, and the range is 0.04–2.47%.
  All 145 have a logged spread, so none needed the fallback (the median over all 265 scored markets,
  0.24%).
- **Market orders** buy at the candle close plus half the spread and sell at the close minus half the
  spread. Both sides pay the taker fee.
- **Limit orders:**
  - The buy is placed 0.5% below the signal price and stays valid for 3 candles (15 minutes on 5m,
    3 hours on 1h). It fills at the limit price, with the maker fee and no spread, once a candle's low
    reaches it.
  - The take-profit rests as a limit order at the target. It fills at the target, with the maker fee,
    once a candle's high reaches it.
  - All other exits (stop-loss, technical exit) are market orders and pay the taker fee and half the
    spread.

**Replay:** the same method as section 4 of the log analysis. Each configuration runs on its own on
each of the 142 monitored markets that have candle data (RVN-EUR, ICX-EUR and VANRY-EUR have none).
It holds one position per market, uses correctly ordered candles and decides on closed candles. Trades
still open at the end of a period are not counted.

## 2. Results

Average net P/L per trade, after fees and spread:

| Interval | Orders | Rules | Before (15 May – 12 Aug) | Live A (13 Aug – 30 Sep) | Live B (1 – 28 Oct) | Trades (before / A / B) | Passes |
|---|---|---|---|---|---|---|---|
| 5m | market | current rules | −0.97% | +0.15% | −1.15% | 9,100 / 5,638 / 3,173 | no |
| 5m | market | TP 3 / SL 3, no technical exit | −0.72% | −0.29% | −0.83% | 21,499 / 12,725 / 7,170 | no |
| 5m | market | RSI<30 only, TP 5 / SL 3, no technical exit | −0.60% | +0.16% | −0.92% | 7,191 / 3,793 / 2,559 | no |
| 5m | limit | current rules | −1.00% | −0.06% | −1.30% | 7,317 / 4,395 / 2,506 | no |
| 5m | limit | TP 3 / SL 3, no technical exit | −0.79% | −0.37% | −0.93% | 14,187 / 8,440 / 4,730 | no |
| 5m | limit | RSI<30 only, TP 5 / SL 3, no technical exit | −0.77% | −0.01% | −0.81% | 3,355 / 1,819 / 1,271 | no |
| 1h | market | current rules | −1.55% | +1.75% | −1.93% | 3,535 / 1,674 / 1,191 | no |
| 1h | market | TP 3 / SL 3, no technical exit | −0.85% | −0.17% | −0.85% | 10,430 / 4,876 / 3,620 | no |
| 1h | market | RSI<30 only, TP 5 / SL 3, no technical exit | −0.72% | +0.52% | −0.59% | 2,333 / 931 / 984 | no |
| 1h | limit | current rules | −1.69% | +1.40% | −2.03% | 3,501 / 1,564 / 1,173 | no |
| 1h | limit | TP 3 / SL 3, no technical exit | −0.95% | −0.23% | −1.25% | 8,545 / 4,005 / 2,856 | no |
| 1h | limit | RSI<30 only, TP 5 / SL 3, no technical exit | −0.88% | −0.28% | −0.83% | 1,512 / 578 / 655 | no |

- **Every configuration fails on P/L, not on sample size.** The smallest count is 578 trades in one
  period, well above 200.
- **Every configuration loses in the "before" period and in October.** Live A, when the coins rose
  38%, is the only period with positive results, as in the log analysis.
- **The spread costs about 0.3 points per trade.** With current rules, market orders and 5-minute
  candles, the result is −0.97%, +0.15% and −1.15%. The same replay without a spread (log analysis,
  section 4) gave −0.69%, +0.43% and −0.86%.
- **Limit orders did worse than market orders** in 17 of 18 comparisons, by up to 0.80 points. The
  exception is 5m, RSI < 30 only, in October (−0.81% against −0.92%). Limit configurations made
  47–99% as many trades as the market-order ones. A plausible reason, not tested here: a buy 0.5%
  below the signal price fills only when the price keeps falling, and misses the entries where it
  rises straight away. The fee and spread saved do not make up for that.
- **Hourly candles mostly make the swings bigger.** With current rules and market orders the hourly
  replay made +1.75% in live A (5m: +0.15%) and lost 1.55% and 1.93% in the other periods (5m: 0.97%
  and 1.15%). With TP 3 / SL 3 and market orders the interval made little difference (within 0.13
  points in every period).

## 3. Spread terciles

Current rules, market orders, 5-minute candles. The 142 markets are ranked by their median logged
spread and split into three groups of equal size. Spreads are the full bid-ask spread, as the scorer
logs it.

| Tercile | Markets | Spread range | Before | Live A | Live B | Trades (before / A / B) |
|---|---|---|---|---|---|---|
| Lowest | 47 | 0.042–0.173% | −0.89% | +0.17% | −0.92% | 3,404 / 2,222 / 1,261 |
| Middle | 47 | 0.175–0.238% | −0.99% | +0.25% | −1.15% | 3,012 / 1,820 / 1,003 |
| Highest | 48 | 0.241–2.470% | −1.06% | +0.02% | −1.48% | 2,684 / 1,596 / 909 |

- **The lowest tercile did better than the highest in every period**, by 0.18, 0.16 and 0.55 points.
  That is Task 14's gate.
- **The gap is the spread charge itself.** The replay charges each market its own spread: on average
  0.11–0.12% per round trip in the lowest tercile and 0.55–0.58% in the highest. As a check outside the
  committed report, the same tercile rows were rerun with the spread set to zero and everything else
  unchanged:

  | Tercile | Before | Live A | Live B |
  |---|---|---|---|
  | Lowest | −0.78% | +0.28% | −0.82% |
  | Highest | −0.47% | +0.65% | −0.83% |

  Without the spread charge, the high-spread markets did better in two periods and the same in
  October. The signals do not work better in tight-spread markets. Trading them only avoids paying
  their spread, and that saving holds only if the logged spreads are what real orders pay.
- **Low spreads alone do not make money.** The lowest tercile still lost 0.89% and 0.92% per trade in
  two of the three periods.
- The middle tercile is not between the other two in live A (+0.25%, the best of the three).

## 4. The gate

- **Passes at the current margin (0.4):** none.
- **Waiting on the Task 8 margin:** none. Task 8 sets the margin to max(0.4, measured optimism), so it
  can only remove passes, never add them. No configuration is even at break-even in every period, so
  this result holds whatever Task 8 measures. Task 8 is still needed before the replay is used to test
  any other idea.

## 5. Caveats

- **The 0.4 margin is provisional** until the Task 8 calibration run measures it again. It was
  measured on 5-minute candles with market orders. How optimistic the replay is on hourly candles or
  with limit orders has not been measured.
- **The limit-order fill model favours limit orders.** It assumes a fill whenever a candle's low
  touches the limit price (or its high touches the take-profit). Real orders wait in a queue behind
  others at the same price and can fill partly or not at all. Even so, limit orders did worse.
- **Spreads come from the scorer's order-book snapshots**, one median per market over the whole log
  (13 Aug – 28 Oct), including rescans where the market was rejected. That median is applied to all
  three periods, including the "before" period, when no spreads were logged. Spreads usually widen
  when prices move fast, and the buy signals fire after drops, so the spread at signal times may be
  higher than the median. This was not measured.
- **Hourly exits are coarser.** On 1-hour candles the replay checks the stop-loss, the technical exit
  and (with market orders) the take-profit only at each hourly close, while the bot checks prices every
  minute. Whether this makes the hourly rows better or worse than a live bot would do is not known.
- **One market regime:** 90 days before the run plus the 76 days of the run, the same data as the log
  analysis.
- **Per market, not the portfolio:** each market is replayed on its own with one position, not with the
  bot's three shared position slots and its market selection. This measures the average trade of a
  rule set, not what the bot would have earned.
- **The rule sets were picked on the same data.** The two alternative rule sets come from section 4 of
  the log analysis, which used the same candles and periods. Rules picked from results on the same data
  are favoured when they are tested again on it. None passed anyway.

## 6. Go / no-go for Phase 4

- **Task 13, `CANDLE_INTERVAL` setting: no-go.** No 1h row passes. The gate cannot pass with any margin
  Task 8 can set.
- **Task 14, `MAX_SPREAD_PCT` setting: go.** Its gate holds: the lowest spread tercile did better than
  the highest in every period. A stricter spread limit only lowers costs. It does not make the rules
  profitable, and the gain is the spread not paid (section 3).
- **Task 15, live limit orders: no-go.** No limit row passes, and limit orders did worse than market
  orders in 17 of 18 comparisons, even with a fill model that favours them.

Reproduce with:

```bash
venv/bin/python -m tools.log_analysis.analyze --log-db data/analysis/bender_2026-08-13.db \
    --candles data/analysis/candles_5m.db --candles-1h data/analysis/candles_1h.db \
    --out data/analysis --sections 7
```

The inputs come from the commands under "Analysing a run" in the README. The hourly candles come from
`tools.log_analysis.candles` with `--interval 1h --start 2026-05-01 --end 2026-10-29 --db
data/analysis/candles_1h.db`.
