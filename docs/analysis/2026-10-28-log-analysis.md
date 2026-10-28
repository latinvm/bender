# Lessons from Bender's 13 Aug – 28 Oct 2026 paper-trading run

Bender paper-traded for 76 days (13 Aug 08:20 – 28 Oct 10:22 UTC) with a virtual wallet on live Bitvavo
prices. That is the test [VIRTUAL_TRADING.md](../VIRTUAL_TRADING.md) asks for before going live, so no
real money was at risk. The run closed 237 trades for −€11.31 and wrote one 1 GB log,
`logs/2026-08-13.log`, with 10.4 million lines. This document explains the result, tests what would
have worked instead, and lists what changed in the code as a result.

## Summary

**The strategy that ran was not the strategy in the code.** Bitvavo returns candles newest-first and
the live code never sorted them. For the whole run every RSI, MACD and Bollinger value was computed on
time-reversed candles, and the oldest of the 100 candles (11–40 hours old) was read as "now". The
market scorer had the same bug, which flipped the sign of its Sharpe and Sortino ratios. Recomputing
2,941 random checks from exchange candles reproduces the logged values with reversed candles, not with
correctly ordered ones.

Three more problems added to the losses:

- **Buy-then-sell churn:** the "near lower band" buy signal can fire while the sell signal is also true.
  45 trades were closed within 10 minutes of opening, paying fees both ways.
- **A stuck position:** RVN-EUR was delisted 14 hours after it was bought. It blocked one of the three
  position slots for the last 40 days and produced 745K of the 746K error lines.
- **Fees:** before fees the run made +€0.52 on 234 trades, so fees of €11.78 were the whole loss.

**Fixing the bugs is necessary but not sufficient.**

- **Same loss with the fix:** replayed over the same markets and times with correctly ordered
  candles, the live rules would have lost about the same: −0.53% per trade against −0.46% live.
- **The signals work, but weakly:** with correct candles they pick entries slightly better than
  random, by +0.1% to +0.3% over 4–24 hours. A round trip costs 0.5% in fees.
- **No rule set made money outside the rally:** none of the 16 rule sets tested (other entries,
  exits, trend filters) made money in the 90 days before the run or in October. They all did well only
  in late August and September, when the coins themselves rose 38%.

**What worked:**

- **Paper trading first.** All of this was found with virtual money.
- **Detailed logs.** Every check logged its indicator values, so the decisions could be reconstructed
  and checked against exchange data months later. The new decision log keeps that information as one JSON
  line per check (section 6).
- **Price-based exits.** The stop-loss and take-profit used the live price, so they kept working
  despite the candle bug, except on the delisted RVN-EUR position (section 2.4).

The bugs are fixed on this branch. The strategy needs a larger edge or lower costs before real money
makes sense (section 7).

## 1. The run in numbers

| | |
|---|---|
| Trades closed | 237 (234 opened in this run, 3 carried over from the previous session) |
| Win rate | 28.7% |
| Average per trade | −0.48% (wins +5.31%, losses −2.81%) |
| Result | −€11.31: +€0.52 before fees, €11.78 fees |
| Stake | €10 per trade, at most 3 positions: at most €30 of the €967 balance in use |
| Still open at the end | RVN-EUR (delisted), BIGTIME-EUR, BABY-EUR |

| Exit | Trades | Win % | Avg P/L | Total |
|---|---|---|---|---|
| Technical (RSI > 60 and MACD below signal) | 173 | 30.1 | −0.26% | −€4.39 |
| Stop-loss (−5%) | 48 | 0 | −6.58% | −€31.62 |
| Take-profit (+15%) | 16 | 100 | +15.43% | +€24.70 |

Stop-losses averaged −6.58%, not −5%: prices moved past the threshold between checks.

| Entry signal | Trades | Win % | Avg P/L | Median hold |
|---|---|---|---|---|
| 1: Strong oversold (RSI < 40) | 85 | 31.8 | −1.02% | 8.4 h |
| 2: Moderate oversold + momentum (RSI < 50, MACD above signal) | 66 | 40.9 | +0.47% | 12.0 h |
| 3: Near support + momentum (price < lower band × 1.01) | 83 | 15.7 | −0.62% | 1 minute |

Of the 584,613 market checks, 74,118 wanted to buy but all three slots were full; 40,929 of those came
after RVN-EUR got stuck.

## 2. Why it lost

### 2.1 Indicators computed on time-reversed candles

`EnhancedStrategy.get_historical_data` built its DataFrame straight from the Bitvavo response, which
is newest-first, and `should_buy`/`should_sell` read `df.iloc[-1]` as the current candle. pandas-ta then
computed RSI, MACD and Bollinger bands backwards in time and returned the values for the oldest candle.
For a steadily falling coin the bot saw RSI 100 (maximally overbought) instead of RSI 0.

Evidence:

- 2,941 random checks were recomputed from Bitvavo's historical 5-minute candles.
  - With reversed candles, 73.8% match the logged RSI (within 1 point) and candle price (within 0.2%).
  - With correctly ordered candles, 0.2% match. The median gap from the correct RSI is 10 points.
  - The remaining mismatches come from low-volume coins, where it is unknown whether the newest
    5-minute candle existed yet at the moment of the check.
- With reversed candles the replay agrees with the logged buy/no-buy decision in 94.4% of checks.
- The backtester sorted its candles, so backtests measured a different strategy from the one that
  traded. That is why they never showed this.

The stop-loss and take-profit used the live ticker, so those worked as intended. The buy signals and
the technical sell signal, however, had no relation to the current market.

### 2.2 Market scorer ranked falling markets highest

The scorer gives 50% of a market's score to the Sharpe and Sortino ratios of its last 7 days of hourly
returns. Those returns were computed on newest-first closes, which flips their sign. So the scorer
rewarded markets that had been falling:

- Across 6,359 scored candidates in 304 rescans, the logged Sharpe ratio has a rank correlation of
  **−0.91** with the candidate's actual return over the previous 7 days.
- Selected markets had fallen **7.4%** over the previous 7 days on average; candidates that were not
  selected had risen 10.4%.
- Over the next 24 hours, selected markets moved −0.38% and the others +0.15%. However, the rank
  correlation between the Sharpe ratio and the next day's return is only +0.03. Past 7-day performance
  barely predicts the next day, so the corrected scorer should not be expected to add much.

### 2.3 Buy and sell signals that overlap

During the run, signal 3 bought when the price was within 1% of the lower Bollinger band and
`MACD > signal − 0.000001`. That margin is absolute, and for the sub-cent coins Bender trades (PEPE at
€0.000004) MACD itself is smaller than 0.000001. So the "momentum" condition was almost always true,
even when MACD was below its signal line, which is exactly the technical sell condition. Signal 3 also
ignores RSI. The bot could buy and then sell on the next cycle:

- 45 trades closed within 10 minutes of opening, 42 of them signal-3 entries, mostly by the technical
  exit. Example: GALA-EUR was bought and sold 3 times in 4 minutes.
- Signal-3 trades had a median hold of 1 minute.

### 2.4 Delisted market blocked a slot for 40 days

RVN-EUR was bought on 17 Sep 21:52 and delisted on 18 Sep 12:06. From then on:

- The position could not be sold, so it held one of the three slots until the end.
- The TUI price refresh logged a "market has been delisted" error every 5 seconds: 689,739 lines.
- Every strategy cycle crashed on the empty candle response (`single positional indexer is
  out-of-bounds`, 55,423 times), so not even the stop-loss could run.

ICX-EUR was delisted the same way on 2 Oct 12:04 while being monitored. It held no position, so the
only effect was 929 errors until the next rotation dropped it at 13:21. Bitvavo now answers candle
requests for both markets with error 205 ("market parameter is invalid") and ticker requests for RVN-EUR
with 219 ("delisted").

## 3. What the corrected strategy would have done

The replay below uses the same markets at the same times as the live bot: at most 3 positions, €10
per trade, 0.25% fee per side. The first row is the actual run. The others replay the period with
correctly ordered candles.

| Run | Trades | Win % | Avg P/L per trade | Total |
|---|---|---|---|---|
| Live run (actual) | 234 | 28.6 | −0.46% | −€10.64 |
| Fixed candles, live rules | 203 | 46.3 | −0.53% | −€10.83 |
| Fixed candles, signal 3 with a strict MACD check | 196 | 50.5 | −0.19% | −€3.74 |
| Fixed candles, signal 1 only | 204 | 50.0 | −0.51% | −€10.47 |

With correctly ordered candles the win rate rises from 29% to 46%, but the losers are bigger: 86 of
203 trades end on the −5% stop-loss. The result is the same loss as the live run. Making signal 3's
MACD check strict (MACD above its signal line, no margin) removes the buy-then-sell churn and cuts the
loss to −0.19% per trade. The replay is about 0.4 points per trade optimistic (section 8), so none of
these would have made money.

## 4. Which rules would have worked?

Each rule set ran on its own on each of the 142 monitored markets that have candle data: one position
per market, correctly ordered candles, 0.25% fee per side. The idea is to choose rules on the 90 days
*before* the run and then check them on the two halves of the run. The table shows the average net
P/L per trade.

| Rule set | Before (15 May – 12 Aug) | Live A (13 Aug – 30 Sep) | Live B (1 – 28 Oct) |
|---|---|---|---|
| Live rules | −0.69% | +0.39% | −0.86% |
| Signal 1 only (RSI < 40) | −0.65% | +0.52% | −0.87% |
| Signal 2 only | −0.90% | +0.16% | −1.03% |
| Signal 3 only | −0.75% | +0.31% | −1.04% |
| Signal 3 with strict MACD check | −0.69% | +0.43% | −0.86% |
| No technical exit, TP 15% / SL 5% | −1.11% | +1.55% | −1.45% |
| No technical exit, TP 5% / SL 3% | −0.51% | +0.23% | −0.57% |
| No technical exit, TP 3% / SL 3% | −0.39% | +0.11% | −0.44% |
| Trailing stop 3%, SL 5% | −0.68% | −0.18% | −0.78% |
| Live rules, sell after 24 h at the latest | −0.58% | +0.10% | −0.67% |
| RSI < 30 only, TP 5% / SL 3% | −0.34% | +0.39% | −0.64% |
| Live rules, buy only above the 1-day average | −0.82% | +0.30% | −1.26% |
| Live rules, buy only above the 7-day average | −0.89% | +0.30% | −1.20% |
| *Buy and hold, same markets (per market, whole period)* | *−32.7%* | *+38.5%* | *−13.3%* |

- **Nothing made money in the "before" period**, so the walk-forward has no rule set to carry forward.
- **Results follow the market.** Almost every rule set made money in live A, when the coins rose 38%,
  and lost in the other two periods, when they fell. That is what a long-only strategy without an
  edge looks like.
- **Tighter exits lose less but still lose.** TP 3% / SL 3% has the smallest losses in the down
  periods and the smallest gain in the up period.
- **Trend filters made it worse.** Buying only when the price is above its 1-day or 7-day average lowered
  the result in every period.

The full tables (16 rule sets, trade counts, win rates) are in `data/analysis/report.md` after running
the analysis.

## 5. Do the buy signals predict anything?

For every new signal (correctly ordered candles, 142 markets, 15 May – 28 Oct), the table compares the
price change over the next 4 and 24 hours with the average change over all times in the same market and
period, labelled "vs random". A round trip costs 0.5% in fees, so a signal must beat random by more
than that to pay for itself.

| Signal | Period | Signals | 4 h vs random | 24 h vs random | Up after 4 h |
|---|---|---|---|---|---|
| 1: RSI < 40 | before (15 May – 12 Aug) | 51,670 | +0.21% | +0.33% | 51% |
| | live A (13 Aug – 30 Sep) | 31,619 | +0.25% | +0.15% | 55% |
| | live B (1 – 28 Oct) | 16,453 | +0.13% | +0.26% | 50% |
| 2: RSI < 50, MACD above signal | before | 55,893 | +0.08% | +0.14% | 48% |
| | live A | 35,278 | +0.08% | +0.01% | 51% |
| | live B | 18,040 | +0.12% | +0.27% | 49% |
| 3: near lower band | before | 44,274 | +0.14% | +0.34% | 49% |
| | live A | 30,236 | +0.16% | +0.24% | 53% |
| | live B | 14,666 | +0.10% | +0.30% | 49% |

Once the candles are in the right order, all three signals do what they are meant to: in every period
they pick entries slightly better than random. The edge is consistent but small, +0.1% to +0.3%, which
is less than the fee of one round trip.

## 6. What changed in the code

| Change | Where |
|---|---|
| Candles are sorted oldest-first at the API boundary; the strategy and the market scorer both get them through `MarketOperations.get_historical_candles`, which also checks API errors | `market.py`, `enhanced_strategy.py` |
| Delisted markets (Bitvavo code 219) raise `MarketDelistedError`. In virtual mode the position is closed at the last known price; in real mode it is left for manual handling and logged once. Price polling and trading stop, and the market is dropped from rotation once it holds no position | `bitvavo.py`, `exceptions.py`, `enhanced_strategy.py`, `multi_market_strategy.py` |
| Missing or short candle history no longer crashes the cycle; open positions still get the stop-loss and take-profit check on the ticker | `enhanced_strategy.py` |
| One JSON line per evaluation in `logs/decisions-YYYY-MM-DD.jsonl`: market, action (buy, sell, hold, monitor, blocked by position limit or risk, no price, delisted, error), reason, ticker price, candle time, indicators | `enhanced_strategy.py`, `logger.py` |
| Log files roll over daily; the per-check lines (signal checks, ticker fetches, cycle banners) moved to DEBUG, and `LOG_LEVEL=DEBUG` brings them back | `logger.py`, `enhanced_strategy.py`, `market.py`, `multi_market_strategy.py` |
| Signal 3 requires MACD above its signal line (no absolute margin) | `enhanced_strategy.py` |
| Analysis tools: log parser, candle downloader, replay simulator, report | `tools/log_analysis/` |

The other strategy rules (thresholds, exits) are unchanged; section 7 says which changes the evidence
supports.

## 7. Recommendations

In order of priority:

1. **Do not switch to real money with this strategy.** No tested rule set made money outside the
   Aug–Sep rally, and real orders also pay the bid-ask spread, which virtual fills do not.
2. **Merge the fixes on this branch.** Without them no result means anything. They also remove the error
   flood and the stuck-slot problem.
3. **Make signal 3's MACD check strict** (`macd > macd_signal`, no margin). Done on this branch
   (section 6). The one-line change stops the buy-then-sell churn. On the live schedule it cut the loss
   from −0.53% to −0.19% per trade. Per market it is neutral to slightly better.
4. **Run a new virtual period with the fixes**, to check the replay against reality, not to make
   money. Expect a loss similar to section 3. With `decisions-*.jsonl` the comparison is a query. Once
   the replay is calibrated, new ideas can be tested in hours instead of months of paper trading.
5. **Close the gap between edge and costs.** The signals beat random by 0.1–0.3% per trade, while
   costs are 0.5% plus the spread. These directions have *not* been tested yet; test each in the
   replay before building it into the bot:
   - **Limit orders instead of market orders.** Bitvavo charges less for limit (maker) orders, and a
     limit order does not pay the spread.
   - **The same signals on 1-hour candles.** Typical moves are larger compared with the fixed cost
     per trade.
   - **Only trade tight-spread markets.** The scorer accepts spreads up to 0.5%, which costs as much
     as the fees.
6. **Do not expect much from market selection.** The fix makes the scorer prefer rising markets
   instead of falling ones, but a market's 7-day Sharpe ratio barely predicts its next day (rank
   correlation +0.03). A score based mainly on liquidity (volume, spread) would at least lower costs.

Trend filters (buy only above the 1-day or 7-day average), trailing stops and a maximum hold time were
tested and did not help.

## 8. Method and caveats

- **Data:** the log was parsed into SQLite with `tools.log_analysis.parse`. Every line is counted as
  parsed or as an explicitly ignored category, and none were unrecognised. Bitvavo's public 5-minute
  candles for 256 of the 265 markets the bot scored or monitored come from `tools.log_analysis.candles`
  (15 May – 29 Oct for the 145 monitored markets). RVN-EUR, ICX-EUR and VANRY-EUR have no candle data
  and are excluded from the replays.
- **Log timestamps are UTC.** This was checked by matching logged indicator values against candles.
- **Replay:** `tools.log_analysis.replay` reuses the live indicator code. Its buy and sell rules are
  tested to give the same decisions as `should_buy`/`should_sell`. It trades on closed 5-minute candles,
  fills at the candle close, and charges the 0.25% fee on both sides.
- **Validation:** a whole-portfolio replay cannot reproduce the live run trade for trade. The position
  limit was binding most of the time, so one different exit changes every trade after it. The replay
  was therefore checked one decision at a time:
  - It agrees with the logged buy/no-buy decision in 94% of checks.
  - Started at each live trade's real entry, it exits within 15 minutes of the live exit in 69% of
    trades and for the same reason in 86%.
  - It is optimistic: −0.07% per trade replayed against −0.47% live. Live fills used the ticker once a
    minute (stop-losses overshot to −6.6% on average); the replay fills at 5-minute closes. Treat any
    replay result within about 0.4 percentage points per trade of break-even as break-even.
- **Costs:** virtual fills use the last trade price. Real orders would also pay the bid-ask spread, which
  is up to 0.5% for these coins (the scorer's limit), so real results would be worse than every number
  here.
- **Period boundaries:** in sections 4 and 5 each period includes its whole end date, so neighbouring
  periods share one day: "before" also includes 13 Aug and live A also includes 1 Oct. The numbers above
  use these bounds.
- **One period:** 76 days of one market regime. The rule study tests on the 90 days before the run and on
  both halves of the run, but that is still a small sample of market conditions.

Reproduce with the three commands under "Analysing a run" in the README.
