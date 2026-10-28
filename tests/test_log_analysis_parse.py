"""Tests for the log parser (tools/log_analysis/parse.py).

Every fixture line below is copied verbatim from logs/2026-08-13.log, so the
tests pin the parser to the format Bender actually writes.
"""

import sqlite3

import pytest

from tools.log_analysis.parse import parse_lines


def lines(text: str) -> list[str]:
    return text.strip('\n').split('\n')


def run(text: str):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    summary = parse_lines(lines(text), conn)
    return conn, summary


def one(conn, sql, *params):
    rows = conn.execute(sql, params).fetchall()
    assert len(rows) == 1, f"expected 1 row for {sql!r}, got {len(rows)}"
    return rows[0]


MONITORING_BLOCK = """
2026-08-13 09:10:02,661 - trader.multi_market - INFO -
--- MOVE-EUR ---
2026-08-13 09:10:02,926 - trader.enhanced_strategy - INFO - Buy check - RSI: 54.65, MACD: 0.000015, Signal: 0.000017, Price: €0.005486, Lower BB: €0.005361
2026-08-13 09:10:02,928 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-13 09:10:02,928 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): False
2026-08-13 09:10:02,935 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-13 09:10:03,098 - trader.market - INFO - Fetching ticker for MOVE-EUR: €0.005406
2026-08-13 09:10:03,100 - trader.enhanced_strategy - INFO - MONITORING MOVE-EUR - No buy signal
"""

VANRY_BUY_BLOCK = """
2026-08-17 18:36:17,301 - trader.multi_market - INFO -
--- VANRY-EUR ---
2026-08-17 18:36:17,555 - trader.enhanced_strategy - INFO - Buy check - RSI: 47.72, MACD: -0.000005, Signal: -0.000006, Price: €0.000699, Lower BB: €0.000671
2026-08-17 18:36:17,562 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-17 18:36:17,569 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): True
2026-08-17 18:36:17,575 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-17 18:36:17,577 - trader.enhanced_strategy - INFO - BUY SIGNAL TRIGGERED for VANRY-EUR! (Moderate Oversold + Momentum)
2026-08-17 18:36:17,732 - trader.market - INFO - Fetching ticker for VANRY-EUR: €0.000737
2026-08-17 18:36:17,734 - trader.virtual_market - INFO - [VIRTUAL] Placing buy market order: 13575.88922074 VANRY-EUR
2026-08-17 18:36:17,735 - trader.market - INFO - Fetching market info for VANRY-EUR
2026-08-17 18:36:18,137 - trader.market - INFO - Fetching ticker for VANRY-EUR: €0.000737
2026-08-17 18:36:18,187 - trader.virtual_wallet - INFO - Virtual BUY: 13575.88922074 VANRY-EUR @ €0.000737 (Total: €10.03)
2026-08-17 18:36:18,204 - trader.virtual_market - INFO - [VIRTUAL] Order executed: buy 13575.88922074 VANRY-EUR @ €0.000737
2026-08-17 18:36:18,245 - trader.virtual_market - INFO - [VIRTUAL] Fee: €0.0250 | Balance: €967.26
2026-08-17 18:36:18,258 - trader.enhanced_strategy - INFO - BUY EXECUTED for VANRY-EUR
2026-08-17 18:36:18,269 - trader.enhanced_strategy - INFO - Reason: Moderate Oversold + Momentum
2026-08-17 18:36:18,281 - trader.enhanced_strategy - INFO - Amount: 13575.88922074 VANRY-EUR (€10.00)
2026-08-17 18:36:18,288 - trader.enhanced_strategy - INFO - Fill price: €0.000737 (fee: €0.0250)
2026-08-17 18:36:18,294 - trader.enhanced_strategy - INFO - Active positions: 3/3
2026-08-17 18:36:18,301 - trader.multi_market - INFO -
================================================================================

2026-08-17 18:36:18,302 - trader.multi_market - INFO - Portfolio Summary: 3/6 markets active
"""

VANRY_HOLDING_BLOCKS = """
2026-08-17 18:37:20,805 - trader.multi_market - INFO - 
--- VANRY-EUR ---
2026-08-17 18:37:21,042 - trader.enhanced_strategy - INFO - Buy check - RSI: 47.72, MACD: -0.000005, Signal: -0.000006, Price: €0.000699, Lower BB: €0.000671
2026-08-17 18:37:21,043 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-17 18:37:21,050 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): True
2026-08-17 18:37:21,058 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-17 18:37:21,063 - trader.enhanced_strategy - INFO - BUY SIGNAL TRIGGERED for VANRY-EUR! (Moderate Oversold + Momentum)
2026-08-17 18:37:21,068 - trader.enhanced_strategy - INFO - Sell check - RSI: 47.72, MACD: -0.000005, Signal: -0.000006, Price: €0.000699, Upper BB: €0.000728
2026-08-17 18:37:21,069 - trader.enhanced_strategy - INFO - VANRY-EUR Position P/L: +0.00% (Entry: €0.000737, Current: €0.000737)
2026-08-17 18:37:21,070 - trader.enhanced_strategy - INFO - RSI > 60: False, MACD < Signal: False
2026-08-17 18:37:21,227 - trader.market - INFO - Fetching ticker for VANRY-EUR: €0.000737
2026-08-17 18:37:21,229 - trader.enhanced_strategy - INFO - HOLDING VANRY-EUR - No sell signal
2026-08-17 18:48:50,900 - trader.multi_market - INFO - 
--- VANRY-EUR ---
2026-08-17 18:48:51,135 - trader.enhanced_strategy - INFO - Buy check - RSI: 44.48, MACD: -0.000005, Signal: -0.000006, Price: €0.000694, Lower BB: €0.000669
2026-08-17 18:48:51,136 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-17 18:48:51,137 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): True
2026-08-17 18:48:51,137 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-17 18:48:51,138 - trader.enhanced_strategy - INFO - BUY SIGNAL TRIGGERED for VANRY-EUR! (Moderate Oversold + Momentum)
2026-08-17 18:48:51,146 - trader.enhanced_strategy - INFO - Sell check - RSI: 44.48, MACD: -0.000005, Signal: -0.000006, Price: €0.000694, Upper BB: €0.000737
2026-08-17 18:48:51,147 - trader.enhanced_strategy - INFO - VANRY-EUR Position P/L: +2.08% (Entry: €0.000737, Current: €0.000752)
2026-08-17 18:48:51,148 - trader.enhanced_strategy - INFO - RSI > 60: False, MACD < Signal: False
2026-08-17 18:48:51,294 - trader.market - INFO - Fetching ticker for VANRY-EUR: €0.000752
2026-08-17 18:48:51,296 - trader.enhanced_strategy - INFO - HOLDING VANRY-EUR - No sell signal
"""

VANRY_SELL_BLOCK = """
2026-08-17 18:58:16,120 - trader.multi_market - INFO -
--- VANRY-EUR ---
2026-08-17 18:58:16,379 - trader.enhanced_strategy - INFO - Buy check - RSI: 51.78, MACD: -0.000006, Signal: -0.000007, Price: €0.000707, Lower BB: €0.000669
2026-08-17 18:58:16,380 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-17 18:58:16,387 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): False
2026-08-17 18:58:16,393 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-17 18:58:16,401 - trader.enhanced_strategy - INFO - Sell check - RSI: 51.78, MACD: -0.000006, Signal: -0.000007, Price: €0.000707, Upper BB: €0.000744
2026-08-17 18:58:16,402 - trader.enhanced_strategy - INFO - VANRY-EUR Position P/L: -5.65% (Entry: €0.000737, Current: €0.000695)
2026-08-17 18:58:16,403 - trader.enhanced_strategy - INFO - RSI > 60: False, MACD < Signal: False
2026-08-17 18:58:16,404 - trader.enhanced_strategy - INFO - SELL SIGNAL TRIGGERED for VANRY-EUR (Stop Loss (-5.65%))
2026-08-17 18:58:16,543 - trader.market - INFO - Fetching ticker for VANRY-EUR: €0.000695
2026-08-17 18:58:16,545 - trader.virtual_market - INFO - [VIRTUAL] Placing sell market order: 13575.88922074 VANRY-EUR
2026-08-17 18:58:16,552 - trader.market - INFO - Fetching market info for VANRY-EUR
2026-08-17 18:58:16,878 - trader.market - INFO - Fetching ticker for VANRY-EUR: €0.000695
2026-08-17 18:58:16,929 - trader.virtual_wallet - INFO - Virtual SELL: 13575.88922074 VANRY-EUR @ €0.000695 | P/L: €-0.61 (-6.13%)
2026-08-17 18:58:16,941 - trader.virtual_market - INFO - [VIRTUAL] Order executed: sell 13575.88922074 VANRY-EUR @ €0.000695
2026-08-17 18:58:16,971 - trader.virtual_market - INFO - [VIRTUAL] Fee: €0.0236 | Balance: €976.67
2026-08-17 18:58:16,979 - trader.enhanced_strategy - INFO - SELL EXECUTED for VANRY-EUR
2026-08-17 18:58:16,985 - trader.enhanced_strategy - INFO - Reason: Stop Loss (-5.65%)
2026-08-17 18:58:16,992 - trader.enhanced_strategy - INFO - Amount: 13575.88922074 VANRY-EUR
2026-08-17 18:58:16,998 - trader.enhanced_strategy - INFO - Entry: €0.000737 -> Exit: €0.000695 (fee: €0.0236)
2026-08-17 18:58:17,004 - trader.enhanced_strategy - INFO - P/L: -5.65% (€-0.5648)
2026-08-17 18:58:17,005 - trader.multi_market - INFO -
================================================================================

2026-08-17 18:58:17,006 - trader.multi_market - INFO - Portfolio Summary: 2/6 markets active
"""

PRELOADED_ICX = """
2026-08-13 08:22:17,695 - trader.enhanced_strategy - INFO - Loaded active position: 591.4709883480216 ICX-EUR @ €0.016907
2026-08-13 09:10:01,707 - trader.multi_market - INFO -
--- ICX-EUR ---
2026-08-13 09:10:02,049 - trader.enhanced_strategy - INFO - Buy check - RSI: 75.90, MACD: 0.000227, Signal: 0.000259, Price: €0.019232, Lower BB: €0.018722
2026-08-13 09:10:02,056 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-13 09:10:02,063 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): False
2026-08-13 09:10:02,069 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-13 09:10:02,073 - trader.enhanced_strategy - INFO - Sell check - RSI: 75.90, MACD: 0.000227, Signal: 0.000259, Price: €0.019232, Upper BB: €0.019431
2026-08-13 09:10:02,074 - trader.enhanced_strategy - INFO - ICX-EUR Position P/L: -1.90% (Entry: €0.016907, Current: €0.016585)
2026-08-13 09:10:02,075 - trader.enhanced_strategy - INFO - RSI > 60: True, MACD < Signal: True
2026-08-13 09:10:02,078 - trader.enhanced_strategy - INFO - SELL SIGNAL TRIGGERED for ICX-EUR (Technical (RSI: 75.9, MACD Bearish))
2026-08-13 09:10:02,226 - trader.market - INFO - Fetching ticker for ICX-EUR: €0.016585
2026-08-13 09:10:02,228 - trader.virtual_market - INFO - [VIRTUAL] Placing sell market order: 591.47098835 ICX-EUR
2026-08-13 09:10:02,229 - trader.market - INFO - Fetching market info for ICX-EUR
2026-08-13 09:10:02,566 - trader.market - INFO - Fetching ticker for ICX-EUR: €0.016585
2026-08-13 09:10:02,609 - trader.virtual_wallet - INFO - Virtual SELL: 591.47098835 ICX-EUR @ €0.016585 | P/L: €-0.24 (-2.40%)
2026-08-13 09:10:02,613 - trader.virtual_market - INFO - [VIRTUAL] Order executed: sell 591.47098835 ICX-EUR @ €0.016585
2026-08-13 09:10:02,638 - trader.virtual_market - INFO - [VIRTUAL] Fee: €0.0245 | Balance: €977.57
2026-08-13 09:10:02,644 - trader.enhanced_strategy - INFO - SELL EXECUTED for ICX-EUR
2026-08-13 09:10:02,650 - trader.enhanced_strategy - INFO - Reason: Technical (RSI: 75.9, MACD Bearish)
2026-08-13 09:10:02,651 - trader.enhanced_strategy - INFO - Amount: 591.47098835 ICX-EUR
2026-08-13 09:10:02,652 - trader.enhanced_strategy - INFO - Entry: €0.016907 -> Exit: €0.016585 (fee: €0.0245)
2026-08-13 09:10:02,652 - trader.enhanced_strategy - INFO - P/L: -1.90% (€-0.1905)
"""

# The VET block has lines from the TUI price thread interleaved: a delisted
# error for RVN and a ticker fetch for ZIG. Neither belongs to VET.
INTERLEAVED_VET_THEN_RVN = """
2026-09-18 12:08:43,704 - trader.multi_market - INFO -
--- VET-EUR ---
2026-09-18 12:08:43,907 - trader.enhanced_strategy - ERROR - Error fetching current price: ticker RVN-EUR: API error (code 219): This market has been delisted.
2026-09-18 12:08:43,996 - trader.enhanced_strategy - INFO - Buy check - RSI: 41.36, MACD: 0.000002, Signal: 0.000007, Price: €0.006523, Lower BB: €0.006507
2026-09-18 12:08:44,006 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-09-18 12:08:44,013 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): False
2026-09-18 12:08:44,013 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-09-18 12:08:44,015 - trader.enhanced_strategy - INFO - Sell check - RSI: 41.36, MACD: 0.000002, Signal: 0.000007, Price: €0.006523, Upper BB: €0.006605
2026-09-18 12:08:44,021 - trader.enhanced_strategy - INFO - VET-EUR Position P/L: +6.54% (Entry: €0.006138, Current: €0.006540)
2026-09-18 12:08:44,030 - trader.enhanced_strategy - INFO - RSI > 60: False, MACD < Signal: True
2026-09-18 12:08:44,100 - trader.market - INFO - Fetching ticker for ZIG-EUR: €0.039440
2026-09-18 12:08:44,172 - trader.market - INFO - Fetching ticker for VET-EUR: €0.006540
2026-09-18 12:08:44,174 - trader.enhanced_strategy - INFO - HOLDING VET-EUR - No sell signal
2026-09-18 12:08:44,175 - trader.multi_market - INFO -
--- RVN-EUR ---
2026-09-18 12:08:44,348 - trader.enhanced_strategy - ERROR - Error executing trade: single positional indexer is out-of-bounds
2026-09-18 12:08:48,907 - trader.enhanced_strategy - ERROR - Error fetching current price: ticker RVN-EUR: API error (code 219): This market has been delisted.
"""

POSITION_LIMIT_BLOCK = """
2026-08-13 10:55:48,291 - trader.multi_market - INFO -
--- MOVE-EUR ---
2026-08-13 10:55:48,553 - trader.enhanced_strategy - INFO - Buy check - RSI: 43.19, MACD: -0.000004, Signal: -0.000009, Price: €0.005364, Lower BB: €0.005298
2026-08-13 10:55:48,554 - trader.enhanced_strategy - INFO - Signal 1 - Strong Oversold (RSI < 40): False
2026-08-13 10:55:48,554 - trader.enhanced_strategy - INFO - Signal 2 - Moderate + Momentum (RSI < 50 + MACD>Signal): True
2026-08-13 10:55:48,555 - trader.enhanced_strategy - INFO - Signal 3 - Near Support + Momentum: False
2026-08-13 10:55:48,555 - trader.enhanced_strategy - INFO - BUY SIGNAL TRIGGERED for MOVE-EUR! (Moderate Oversold + Momentum)
2026-08-13 10:55:48,594 - trader.enhanced_strategy - INFO - POSITION LIMIT REACHED (3/3) - Cannot buy MOVE-EUR
2026-08-13 10:55:48,595 - trader.enhanced_strategy - INFO - Active positions: USELESS-EUR, XAN-EUR, GROVE-EUR
2026-08-13 10:55:48,596 - trader.multi_market - INFO -
================================================================================

"""

CYCLE = """
2026-08-13 14:24:14,543 - trader.multi_market - INFO -
================================================================================
2026-08-13 14:24:14,544 - trader.multi_market - INFO - Checking 6 markets...
2026-08-13 14:24:14,545 - trader.multi_market - INFO - ================================================================================
2026-08-13 14:24:16,811 - trader.multi_market - INFO -
================================================================================

2026-08-13 14:24:16,812 - trader.multi_market - INFO - Portfolio Summary: 3/6 markets active
2026-08-13 14:24:16,812 - trader.multi_market - INFO - Active markets: USELESS-EUR, XAN-EUR, GROVE-EUR
"""

RESCAN = """
2026-08-13 14:22:17,706 - trader.main - INFO -
================================================================================
2026-08-13 14:22:17,707 - trader.main - INFO - PERIODIC MARKET RESCAN (every 6 hours)
2026-08-13 14:22:17,715 - trader.main - INFO - ================================================================================
2026-08-13 14:22:17,732 - trader.main - INFO - STEP 1: Scanning ALL altcoins to find top 50 candidates
2026-08-13 14:22:17,745 - trader.main - INFO - Fetching complete altcoin list...
2026-08-13 14:22:18,127 - trader.main - INFO - Found 414 total altcoins under €10.0
2026-08-13 14:22:18,134 - trader.main - INFO - Quick-scoring all 414 markets...
2026-08-13 14:23:23,520 - trader.main - INFO -
Selected top 50 markets from 413 candidates
2026-08-13 14:23:23,521 - trader.main - INFO - Top 10 markets by quick-score:
2026-08-13 14:23:23,528 - trader.main - INFO - 1. NOT-EUR: score=1.000, volume=€137897, vol=16.8%
2026-08-13 14:23:23,534 - trader.main - INFO - 2. SWELL-EUR: score=1.000, volume=€21178, vol=16.5%
2026-08-13 14:23:23,550 - trader.main - INFO -
Cached top 50 markets for 6 hours
2026-08-13 14:23:23,556 - trader.main - INFO - STEP 2: Detailed analysis to find top 3 markets from candidates
2026-08-13 14:23:28,309 - trader.main - INFO - Performing detailed analysis on 30 markets...
2026-08-13 14:23:28,739 - trader.main - INFO -
Analyzing COTI-EUR:
2026-08-13 14:23:28,741 - trader.main - INFO - Volume (24h): €1730195.57 | Score: 1.00
2026-08-13 14:23:28,743 - trader.main - INFO - Volatility: 55.1% | Score: 1.00
2026-08-13 14:23:28,745 - trader.main - INFO - Sharpe Ratio: 0.06 | Score: 0.06
2026-08-13 14:23:28,746 - trader.main - INFO - Sortino Ratio: 0.05 | Score: 0.05
2026-08-13 14:23:28,746 - trader.main - INFO - Bid-Ask Spread: 0.426% | Score: 0.15
2026-08-13 14:23:28,747 - trader.main - INFO - Volume Consistency: 3.79x avg
2026-08-13 14:23:28,748 - trader.main - INFO - Final Score: 0.442
2026-08-13 14:23:29,460 - trader.main - INFO -
Analyzing HOME-EUR:
2026-08-13 14:23:29,461 - trader.main - INFO - Volume (24h): €748748.20 | Score: 1.00
2026-08-13 14:23:29,466 - trader.main - INFO - Volatility: 26.3% | Score: 1.00
2026-08-13 14:23:29,475 - trader.main - INFO - Sharpe Ratio: -0.01 | Score: 0.00
2026-08-13 14:23:29,476 - trader.main - INFO - Sortino Ratio: -0.01 | Score: 0.00
2026-08-13 14:23:29,487 - trader.main - INFO - Bid-Ask Spread: 0.195% | Score: 0.61
2026-08-13 14:23:29,488 - trader.main - INFO - Volume Consistency: 0.28x avg
2026-08-13 14:23:29,488 - trader.main - INFO - Penalty Applied: LOW_VOLUME (volume 0.3x normal)
2026-08-13 14:23:29,489 - trader.main - INFO - Final Score: 0.461
2026-08-13 14:23:44,253 - trader.main - INFO -
Rejecting DEGEN-EUR: Spread too wide (0.98% > 0.5%)
2026-08-13 14:23:44,255 - trader.main - INFO -
Selected top 3 markets:
2026-08-13 14:23:44,262 - trader.main - INFO - 1. ICX-EUR (score: 0.546)
2026-08-13 14:23:44,269 - trader.main - INFO - 2. 2Z-EUR (score: 0.527)
2026-08-13 14:23:44,278 - trader.main - INFO - 3. MOVE-EUR (score: 0.522)
2026-08-13 14:23:44,279 - trader.multi_market - INFO - Market re-selection queued: ICX-EUR, 2Z-EUR, MOVE-EUR
2026-08-13 14:23:44,280 - trader.main - INFO - Market rescan completed
"""

ROTATIONS = """
2026-08-13 14:24:14,525 - trader.multi_market - INFO - Rotating in 2Z-EUR
2026-08-13 14:24:14,543 - trader.multi_market - INFO - Market rotation applied. Now trading: ICX-EUR, MOVE-EUR, USELESS-EUR, XAN-EUR, GROVE-EUR, 2Z-EUR
2026-08-13 20:26:09,629 - trader.multi_market - INFO - Rotating out ICX-EUR (no open position, no longer selected)
"""


class TestPrices:
    def test_ticker_line_recorded_in_prices(self):
        conn, _ = run(MONITORING_BLOCK)
        row = one(conn, "SELECT * FROM prices")
        assert row['ts'] == '2026-08-13 09:10:03.098'
        assert row['market'] == 'MOVE-EUR'
        assert row['price'] == pytest.approx(0.005406)

    def test_market_symbols_starting_with_digit(self):
        conn, _ = run("2026-08-13 14:24:19,087 - trader.market - INFO - Fetching ticker for 2Z-EUR: €0.041476")
        assert one(conn, "SELECT market FROM prices")['market'] == '2Z-EUR'


class TestChecks:
    def test_monitoring_block_becomes_one_check_row(self):
        conn, _ = run(MONITORING_BLOCK)
        row = one(conn, "SELECT * FROM checks")
        assert row['ts'] == '2026-08-13 09:10:02.661'
        assert row['market'] == 'MOVE-EUR'
        assert row['rsi'] == pytest.approx(54.65)
        assert row['macd'] == pytest.approx(0.000015)
        assert row['macd_signal'] == pytest.approx(0.000017)
        assert row['candle_price'] == pytest.approx(0.005486)
        assert row['lower_bb'] == pytest.approx(0.005361)
        assert (row['sig1'], row['sig2'], row['sig3']) == (0, 0, 0)
        assert row['ticker_price'] == pytest.approx(0.005406)
        assert row['outcome'] == 'monitoring'
        assert row['upper_bb'] is None
        assert row['buy_signal_reason'] is None

    def test_holding_block_records_sell_side_fields(self):
        conn, _ = run(VANRY_BUY_BLOCK + VANRY_HOLDING_BLOCKS)
        row = one(conn, "SELECT * FROM checks WHERE outcome = 'holding' AND ts = '2026-08-17 18:37:20.805'")
        assert row['upper_bb'] == pytest.approx(0.000728)
        assert row['position_pl_pct'] == pytest.approx(0.0)
        assert row['entry_price'] == pytest.approx(0.000737)
        assert (row['sell_rsi_cond'], row['sell_macd_cond']) == (0, 0)
        assert row['buy_signal_reason'] == 'Moderate Oversold + Momentum'

    def test_lines_from_other_threads_are_attributed_by_market_name(self):
        conn, _ = run(INTERLEAVED_VET_THEN_RVN)
        vet = one(conn, "SELECT * FROM checks WHERE market = 'VET-EUR'")
        assert vet['outcome'] == 'holding'
        assert vet['error_msg'] is None
        assert vet['ticker_price'] == pytest.approx(0.006540)  # not ZIG's 0.039440
        assert vet['position_pl_pct'] == pytest.approx(6.54)
        assert vet['sell_macd_cond'] == 1

    def test_execute_trade_error_is_attributed_to_current_block(self):
        conn, _ = run(INTERLEAVED_VET_THEN_RVN)
        rvn = one(conn, "SELECT * FROM checks WHERE market = 'RVN-EUR'")
        assert rvn['outcome'] == 'error'
        assert rvn['error_msg'] == 'single positional indexer is out-of-bounds'
        assert rvn['rsi'] is None

    def test_position_limit_block_outcome(self):
        conn, _ = run(POSITION_LIMIT_BLOCK)
        row = one(conn, "SELECT * FROM checks")
        assert row['outcome'] == 'blocked_position_limit'
        assert row['sig2'] == 1
        assert row['buy_signal_reason'] == 'Moderate Oversold + Momentum'

    def test_buy_and_sell_blocks_have_trade_outcomes(self):
        conn, _ = run(VANRY_BUY_BLOCK + VANRY_SELL_BLOCK)
        outcomes = [r['outcome'] for r in conn.execute("SELECT outcome FROM checks ORDER BY ts")]
        assert outcomes == ['bought', 'sold']
        sold = one(conn, "SELECT * FROM checks WHERE outcome = 'sold'")
        assert sold['sell_signal_reason'] == 'Stop Loss (-5.65%)'


class TestTrades:
    def test_round_trip_trade(self):
        conn, _ = run(VANRY_BUY_BLOCK + VANRY_HOLDING_BLOCKS + VANRY_SELL_BLOCK)
        t = one(conn, "SELECT * FROM trades")
        assert t['market'] == 'VANRY-EUR'
        assert t['entry_ts'] == '2026-08-17 18:36:18.258'
        assert t['entry_reason'] == 'Moderate Oversold + Momentum'
        assert t['entry_price'] == pytest.approx(0.000737)
        assert t['amount'] == pytest.approx(13575.88922074)
        assert t['entry_rsi'] == pytest.approx(47.72)
        assert t['entry_macd'] == pytest.approx(-0.000005)
        assert t['entry_macd_signal'] == pytest.approx(-0.000006)
        assert t['entry_candle_price'] == pytest.approx(0.000699)
        assert t['entry_lower_bb'] == pytest.approx(0.000671)
        assert t['exit_ts'] == '2026-08-17 18:58:16.979'
        assert t['exit_reason'] == 'stop_loss'
        assert t['exit_reason_raw'] == 'Stop Loss (-5.65%)'
        assert t['exit_price'] == pytest.approx(0.000695)
        assert t['pl_eur'] == pytest.approx(-0.61)
        assert t['pl_pct'] == pytest.approx(-6.13)
        assert t['gross_pl_pct'] == pytest.approx(-5.65)
        assert t['gross_pl_eur'] == pytest.approx(-0.5648)
        assert t['fees_eur'] == pytest.approx(0.0250 + 0.0236)
        assert t['hold_minutes'] == pytest.approx(21.9787, abs=1e-3)
        # Position P/L lines while held: +0.00, +2.08, -5.65
        assert t['mfe_pct'] == pytest.approx(2.08)
        assert t['mae_pct'] == pytest.approx(-5.65)
        assert t['n_checks_held'] == 3
        assert t['pre_log'] == 0
        assert t['price_precise'] == 0  # €0.000737 printed with 6 decimals

    def test_position_still_open_at_end_has_null_exit(self):
        conn, _ = run(VANRY_BUY_BLOCK)
        t = one(conn, "SELECT * FROM trades")
        assert t['entry_ts'] == '2026-08-17 18:36:18.258'
        assert t['exit_ts'] is None
        assert t['exit_reason'] is None
        assert t['pl_eur'] is None
        assert t['fees_eur'] == pytest.approx(0.0250)

    def test_position_loaded_from_previous_run(self):
        conn, _ = run(PRELOADED_ICX)
        t = one(conn, "SELECT * FROM trades")
        assert t['pre_log'] == 1
        assert t['entry_ts'] is None
        assert t['entry_reason'] == 'pre_log'
        assert t['entry_price'] == pytest.approx(0.016907)
        assert t['amount'] == pytest.approx(591.4709883480216)
        assert t['exit_reason'] == 'technical'
        assert t['pl_eur'] == pytest.approx(-0.24)
        assert t['pl_pct'] == pytest.approx(-2.40)
        assert t['hold_minutes'] is None
        assert t['price_precise'] == 1

    def test_take_profit_reason_normalised(self):
        text = VANRY_BUY_BLOCK + VANRY_SELL_BLOCK.replace(
            'Stop Loss (-5.65%)', 'Take Profit (+15.20%)')
        conn, _ = run(text)
        assert one(conn, "SELECT exit_reason FROM trades")['exit_reason'] == 'take_profit'


class TestPortfolio:
    def test_balance_lines(self):
        conn, _ = run(VANRY_BUY_BLOCK)
        row = one(conn, "SELECT * FROM balance")
        assert row['ts'] == '2026-08-17 18:36:18.245'
        assert row['fee'] == pytest.approx(0.025)
        assert row['balance'] == pytest.approx(967.26)

    def test_cycle_row(self):
        conn, _ = run(CYCLE)
        row = one(conn, "SELECT * FROM cycles")
        assert row['ts'] == '2026-08-13 14:24:14.544'
        assert row['n_markets'] == 6
        assert row['n_active'] == 3
        assert row['active_markets'] == 'USELESS-EUR,XAN-EUR,GROVE-EUR'

    def test_rotations(self):
        conn, _ = run(ROTATIONS)
        rows = [tuple(r) for r in conn.execute("SELECT ts, market, action FROM rotations ORDER BY ts")]
        assert rows == [('2026-08-13 14:24:14.525', '2Z-EUR', 'in'),
                        ('2026-08-13 20:26:09.629', 'ICX-EUR', 'out')]


class TestRescans:
    def test_rescan_row(self):
        conn, _ = run(RESCAN)
        r = one(conn, "SELECT * FROM rescans")
        assert r['rescan_id'] == 1
        assert r['ts'] == '2026-08-13 14:22:17.732'
        assert r['periodic'] == 1
        assert r['n_altcoins'] == 414
        assert r['n_analyzed'] == 30

    def test_market_scores(self):
        conn, _ = run(RESCAN)
        coti = one(conn, "SELECT * FROM market_scores WHERE market = 'COTI-EUR'")
        assert coti['rescan_id'] == 1
        assert coti['ts'] == '2026-08-13 14:23:28.739'
        assert coti['volume_24h'] == pytest.approx(1730195.57)
        assert coti['volume_score'] == pytest.approx(1.0)
        assert coti['volatility_pct'] == pytest.approx(55.1)
        assert coti['sharpe'] == pytest.approx(0.06)
        assert coti['sortino_score'] == pytest.approx(0.05)
        assert coti['spread_pct'] == pytest.approx(0.426)
        assert coti['spread_score'] == pytest.approx(0.15)
        assert coti['volume_consistency'] == pytest.approx(3.79)
        assert coti['penalty'] is None
        assert coti['final_score'] == pytest.approx(0.442)
        assert coti['rejected_reason'] is None
        home = one(conn, "SELECT * FROM market_scores WHERE market = 'HOME-EUR'")
        assert home['sharpe'] == pytest.approx(-0.01)
        assert home['penalty'] == 'LOW_VOLUME (volume 0.3x normal)'

    def test_rejected_market_score_row(self):
        conn, _ = run(RESCAN)
        degen = one(conn, "SELECT * FROM market_scores WHERE market = 'DEGEN-EUR'")
        assert degen['rejected_reason'] == 'spread'
        assert degen['spread_pct'] == pytest.approx(0.98)
        assert degen['final_score'] is None

    def test_selection_and_quick_scores(self):
        conn, _ = run(RESCAN)
        sel = [tuple(r) for r in conn.execute("SELECT rescan_id, rank, market, score FROM selections ORDER BY rank")]
        assert sel == [(1, 1, 'ICX-EUR', 0.546), (1, 2, '2Z-EUR', 0.527), (1, 3, 'MOVE-EUR', 0.522)]
        q = one(conn, "SELECT * FROM quick_scores WHERE rank = 1")
        assert (q['market'], q['score'], q['volume'], q['volatility_pct']) == ('NOT-EUR', 1.0, 137897.0, 16.8)


class TestErrorsAndCoverage:
    def test_errors_aggregated_by_template(self):
        conn, _ = run(INTERLEAVED_VET_THEN_RVN)
        delisted = one(conn, "SELECT * FROM errors WHERE template LIKE '%delisted%'")
        assert delisted['count'] == 2
        assert delisted['first_ts'] == '2026-09-18 12:08:43.907'
        assert delisted['last_ts'] == '2026-09-18 12:08:48.907'
        assert delisted['logger'] == 'trader.enhanced_strategy'
        assert delisted['level'] == 'ERROR'
        assert 'RVN-EUR' in delisted['example']
        assert 'RVN-EUR' not in delisted['template']
        assert delisted['markets'] == 'RVN-EUR:2'

    def test_error_markets_listed_by_count(self):
        text = """
2026-09-18 12:08:43,907 - trader.enhanced_strategy - ERROR - Error fetching current price: ticker RVN-EUR: API error (code 219): This market has been delisted.
2026-09-18 12:08:48,907 - trader.enhanced_strategy - ERROR - Error fetching current price: ticker RVN-EUR: API error (code 219): This market has been delisted.
2026-09-18 12:08:49,000 - trader.enhanced_strategy - ERROR - Error fetching current price: ticker ICX-EUR: API error (code 219): This market has been delisted.
"""
        conn, _ = run(text)
        assert one(conn, "SELECT markets FROM errors")['markets'] == 'RVN-EUR:2,ICX-EUR:1'

    def test_every_line_counted_exactly_once(self):
        text = VANRY_BUY_BLOCK + VANRY_HOLDING_BLOCKS + VANRY_SELL_BLOCK + RESCAN + CYCLE + INTERLEAVED_VET_THEN_RVN
        conn, summary = run(text)
        assert summary.lines == len(lines(text))
        total = conn.execute("SELECT SUM(count) FROM line_stats").fetchone()[0]
        assert total == summary.lines
        assert summary.line_stats.get('unrecognised', 0) == 0

    def test_unknown_lines_land_in_unrecognised(self):
        text = MONITORING_BLOCK + "2026-08-13 09:10:04,000 - trader.enhanced_strategy - INFO - Something brand new: 42"
        conn, summary = run(text)
        row = one(conn, "SELECT count FROM line_stats WHERE category = 'unrecognised'")
        assert row['count'] == 1
        assert summary.unrecognised.most_common(1)[0][0] == 'trader.enhanced_strategy - INFO - Something brand new: N'
