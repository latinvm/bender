# Bender Strategy Improvement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the bug fixes from the Aug–Oct log analysis safely, calibrate the replay simulator against a clean virtual run, test whether lower costs (spread-aware, limit orders, 1-hour candles) give the strategy an edge, and adopt only what passes a fixed gate.

**Architecture:** Four phases with gates between them.
- **Phase 1** finishes branch `log-analysis`: the review fixes, signal 3, and a PR.
- **Phase 2** adds tools that read the new `decisions-*.jsonl` logs and the virtual wallet, then measures how far the replay is from reality during a 14-day virtual run.
- **Phase 3** extends the replay with spread, limit-order and hourly-candle models and judges every configuration against the calibrated margin.
- **Phase 4** turns winning configurations into settings. Live limit orders get their own design.

**Tech Stack:** Python 3.12+, pandas, numpy, pandas-ta, sqlite3, pytest, ruff. No new dependencies.

**Spec:** [docs/analysis/2026-10-28-log-analysis.md](../analysis/2026-10-28-log-analysis.md). Phase 1 also covers the code-review findings on the uncommitted `src/` changes; those findings are restated in each task, because they are not in the spec.

## Global Constraints

- Python `>=3.12`. No new runtime or dev dependencies. `tools/` is dev-only and not packaged.
- `venv/bin/ruff check src tests tools` is clean (line length 160). `venv/bin/python -m pytest -q` is green. Unit tests never use the network.
- Fees: virtual mode charges `VIRTUAL_TRADING_FEE` 0.25% per side. Bitvavo's base tier on EUR markets is **0.25% taker / 0.15% maker** (bitvavo.com/en/fees, checked 2026-10-28).
- Log and wallet timestamps are UTC (the bot runs in a UTC container). Replay prices come from Bitvavo 5-minute candles in `data/analysis/` (gitignored).
- Real-money rules:
  - Never place an order on a market flagged delisted.
  - Never change a real position automatically.
  - Logging must never raise into the trading loop.
- Log files: `logs/YYYY-MM-DD.log` and `logs/decisions-YYYY-MM-DD.jsonl`.
- Decision gate:
  - Pass: average net P/L per trade ≥ `CALIBRATION_MARGIN_PP` in **every** period, with ≥ 200 trades in each period.
  - Margin: start at 0.4, then replace it with the Phase 2 measurement.
  - Periods: before = 15 May–12 Aug, live A = 13 Aug–30 Sep, live B = 1–28 Oct.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Pushing and opening the PR wait for explicit approval.

## Review Focus

1. **Logs directory moved or deleted while running, unwritable at midnight:** trading continues and the failure is reported, not raised. Task 2 adds `test_rollover_into_a_missing_directory_recreates_it` and `test_unwritable_rollover_is_reported_not_raised`.
2. **Delisting seen by the TUI price thread while the trading thread is mid-cycle, in real mode:** no order is placed and the position is closed at most once, on the trading thread. Task 3 adds `test_delisting_seen_by_price_polling_is_handled_by_the_trading_thread` and `test_buy_signal_on_a_market_delisted_mid_cycle_places_no_order`.
3. **Decision log cut off mid-line (bot killed), or records without indicators (error, delisted):** the loader keeps the good lines, counts the skipped ones, and fills NaN for missing indicators. Task 6 adds `test_loads_records_and_skips_a_truncated_last_line` and `test_records_without_indicators_have_nan`.
4. **A limit order that never fills:** no trade, no fee, and the reserved slot is released. Task 10 adds `test_unfilled_limit_entry_expires_without_a_trade`.
5. **A wallet trade with no matching decision record** (restart, missing day file): it is kept with no exit reason and counted as unmatched in calibration. Task 6 adds `test_unmatched_exit_gets_no_reason`; Task 7 adds `test_trades_without_snapshots_are_skipped_and_counted`.

---

## Phase 1 — Ship the fixes

### Task 1: Commit the analysis branch as it stands

**Files:** everything currently uncommitted on `log-analysis` (`git status --short`).

- [ ] **Step 1: Verify.** Run `venv/bin/python -m pytest -q && venv/bin/ruff check src tests tools`. Expected: `322 passed, 5 deselected` (or more) and `All checks passed!`.
- [ ] **Step 2: Commit the trading fixes.**
  ```bash
  git add src/ tests/test_candle_order.py tests/test_delisting.py tests/test_decision_log.py \
          tests/test_enhanced_strategy.py tests/test_multi_market_strategy.py \
          tests/test_phase2_risk_and_backtest.py tests/test_safety_fixes.py
  git commit -m "Fix candle order, handle delisted markets, add decision log and daily log files"
  ```
- [ ] **Step 3: Commit the tools.**
  ```bash
  git add tools/ tests/test_log_analysis_*.py .github/workflows/ci.yml
  git commit -m "Add log analysis tools: parser, candle cache, replay, report"
  ```
- [ ] **Step 4: Commit the docs.**
  ```bash
  git add docs/ README.md
  git commit -m "Document the lessons from the Aug-Oct paper-trading run, add project status, and this plan"
  ```

### Task 2: Logging can never break trading

Review findings this task fixes:
- `DailyFileHandler.emit` lets `OSError` from reopening the file escape at the day change, and does so on every call after it. With `logs/` moved, the first log line after midnight kills the strategy thread.
- `_record_decision` is called outside `try`.
- `LOG_LEVEL` in `.env` is ignored, because `setup_logger` runs before `load_dotenv`.
- Tests that call `main()` write into the real `logs/`.

**Files:**
- Modify: `src/trader/logger.py` (`DailyFileHandler.__init__`, `DailyFileHandler.emit`)
- Modify: `src/trader/enhanced_strategy.py` (`execute_trade`)
- Modify: `src/trader/main.py` (start of `main()`)
- Create: `tests/conftest.py`
- Test: `tests/test_decision_log.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `DailyFileHandler(directory, prefix='', suffix='.log', clock=time.time)`. The signature is unchanged, but `directory` is resolved to an absolute path at construction.

- [ ] **Step 1: Write the failing tests** in `tests/test_decision_log.py`, in `TestDailyFileHandler`:
  ```python
  def test_rollover_into_a_missing_directory_recreates_it(self, tmp_path):
      logs = tmp_path / 'logs'
      day1 = time.mktime((2026, 8, 13, 23, 59, 0, 0, 0, -1))
      handler = DailyFileHandler(logs, clock=lambda: day1)
      handler.handle(self._record(day1, 'first'))
      shutil.rmtree(logs)
      handler.handle(self._record(day1 + 120, 'second'))   # must not raise
      handler.close()
      assert (logs / '2026-08-14.log').read_text().strip() == 'second'

  def test_unwritable_rollover_is_reported_not_raised(self, tmp_path):
      logs = tmp_path / 'logs'
      day1 = time.mktime((2026, 8, 13, 23, 59, 0, 0, 0, -1))
      handler = DailyFileHandler(logs, clock=lambda: day1)
      handler.handle(self._record(day1, 'first'))
      shutil.rmtree(logs)
      logs.write_text('a file where the directory should be')
      errors = []
      handler.handleError = errors.append
      handler.handle(self._record(day1 + 120, 'second'))   # must not raise
      assert len(errors) == 1
  ```
  Add a test in `TestDecisionRecords`:
  ```python
  def test_failing_decision_record_does_not_break_the_cycle(self, capture):
      strategy = make_strategy(FALLING)
      with patch('trader.enhanced_strategy.decision_logger.info', side_effect=OSError('disk full')):
          strategy.execute_trade()
      strategy.market_ops.place_market_order.assert_called_once()
  ```
  Add a test in `tests/test_main.py`. It checks call order rather than reading a temporary `.env`, because `load_dotenv()` finds `.env` by walking up from the calling module, not from the working directory.
  ```python
  def test_dotenv_is_loaded_before_logging_is_set_up(monkeypatch):
      calls = []
      monkeypatch.setattr('sys.argv', ['main.py'])
      monkeypatch.setattr('trader.main.load_dotenv', lambda *a, **k: calls.append('load_dotenv'))
      def stop(*a, **k):
          calls.append('setup_logger')
          raise SystemExit
      monkeypatch.setattr('trader.main.setup_logger', stop)
      with pytest.raises(SystemExit):
          main()
      assert calls == ['load_dotenv', 'setup_logger']
  ```
- [ ] **Step 2: Run them.** `venv/bin/python -m pytest -q tests/test_decision_log.py tests/test_main.py`. Expected: FAIL. The two handler tests raise `FileNotFoundError`/`FileExistsError`, the decision test raises `OSError`, and the dotenv test fails because `trader.main` has no attribute `load_dotenv`.
- [ ] **Step 3: Implement.**
  - `DailyFileHandler.__init__` stores `Path(directory).resolve()`.
  - `emit` wraps the rollover, a `self.directory.mkdir(parents=True, exist_ok=True)` whenever `self.stream is None`, and `super().emit(record)` in `try: ... except Exception: self.handleError(record)`.
  - `execute_trade` wraps the `_record_decision(...)` call in `try/except Exception` and logs one `logger.warning` per failure.
  - `main()` calls `load_dotenv()` (from `dotenv`) as its first statement.
- [ ] **Step 4: Isolate the tests' logs.** In `tests/conftest.py`, add an autouse fixture `isolated_logs(tmp_path, monkeypatch)`:
  - Before the test: `monkeypatch.setattr('trader.logger.log_dir', tmp_path / 'logs')`.
  - After `yield`: remove and close every handler added during the test on `logging.getLogger('trader')` and `logging.getLogger('trader.decisions')`.
- [ ] **Step 5: Run the suite.** `venv/bin/python -m pytest -q`. Expected: all pass, and `logs/decisions-<today>.jsonl` gains no new lines during the run (check its line count before and after).
- [ ] **Step 6: Commit.** `git commit -am "Never let logging failures reach the trading loop; read LOG_LEVEL from .env"`, adding `tests/conftest.py` first.

### Task 3: Delisting is handled on the trading thread and stops the current decision

Review findings this task fixes:
- When `get_current_price` detects a delisting, the decision already in progress continues on the stale price:
  - In virtual mode it raises `KeyError` after the position was closed.
  - In real mode it still calls `place_market_order`.
- The TUI thread closes virtual positions itself.
- `get_current_prices` iterates `self.strategies` while rotation deletes from it.
- Bitvavo now answers a delisted market's **candles** with error **205** (`MarketNotFoundError`); only the **ticker** gives 219. The existing tests only cover 219 on candles.

**Files:**
- Modify: `src/trader/enhanced_strategy.py` (`get_current_price`, `_mark_delisted`, `execute_trade`, `_decide_and_act`, `_price_based_exit`, `should_sell`)
- Modify: `src/trader/multi_market_strategy.py` (`get_current_prices`)
- Test: `tests/test_delisting.py`

**Interfaces:**
- Produces:
  - `EnhancedStrategy.get_current_price(self, use_cache: bool = True, cache_max_age: float = 30.0, raise_if_delisted: bool = False) -> Optional[float]`. Trading paths pass `raise_if_delisted=True`. The TUI keeps the default, which only sets the flag.
  - `EnhancedStrategy._mark_delisted(self, error) -> None` sets `self.delisted` and logs once. It never touches positions.
  - The virtual position is released only inside `execute_trade` (trading thread), exactly once. Its decision record has `action == 'delisted'`.

- [ ] **Step 1: Write the failing tests** in `tests/test_delisting.py`:
  ```python
  def realistic_delisted_ops(candles_error=True):
      ops = Mock()
      if candles_error:
          ops.get_historical_candles.side_effect = MarketNotFoundError('candles RVN-EUR: market parameter is invalid.')
      else:
          ops.get_historical_candles.return_value = []
      ops.get_ticker.side_effect = MarketDelistedError('ticker RVN-EUR: This market has been delisted.')
      return ops

  def test_realistic_delisting_closes_virtual_position_once(wallet_holding_rvn, caplog):
      strategy = EnhancedStrategy(realistic_delisted_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)
      strategy.last_price = 0.021
      with caplog.at_level(logging.INFO):
          strategy.execute_trade(); strategy.execute_trade()
      assert wallet_holding_rvn.get_active_positions() == []
      assert len(wallet_holding_rvn.get_trade_history()) == 1
      actions = [json.loads(r.getMessage())['action'] for r in caplog.records if r.name == 'trader.decisions']
      assert actions == ['delisted']
      assert not [r for r in caplog.records if 'Error executing trade' in r.getMessage()]

  def test_real_mode_never_orders_on_a_delisted_market():
      with patch('trader.enhanced_strategy.TradeDatabase') as db_class:
          db_class.return_value.get_active_positions.return_value = [
              {'market': 'RVN-EUR', 'amount': 500.0, 'entry_price': 0.02}]
          strategy = EnhancedStrategy(realistic_delisted_ops(candles_error=False), 'RVN-EUR')
      strategy.last_price = 0.018   # -10%: the stop-loss would fire on the stale price
      strategy.execute_trade(); strategy.execute_trade()
      strategy.market_ops.place_market_order.assert_not_called()
      assert 'RVN-EUR' in strategy.positions

  def test_delisting_seen_by_price_polling_is_handled_by_the_trading_thread(wallet_holding_rvn):
      strategy = EnhancedStrategy(realistic_delisted_ops(), 'RVN-EUR', virtual_wallet=wallet_holding_rvn)
      strategy.last_price = 0.021
      strategy.get_current_price(use_cache=False)          # TUI thread
      assert len(wallet_holding_rvn.get_active_positions()) == 1
      strategy.execute_trade()                              # trading thread
      assert wallet_holding_rvn.get_active_positions() == []

  def test_buy_signal_on_a_market_delisted_mid_cycle_places_no_order():
      ops = realistic_delisted_ops()
      ops.get_historical_candles.side_effect = None
      ops.get_historical_candles.return_value = candles(FALLING)          # RSI 0: buy signal
      strategy = EnhancedStrategy(ops, 'NEW-EUR', virtual_wallet=Mock(get_active_positions=Mock(return_value=[])))
      strategy.execute_trade()
      ops.place_market_order.assert_not_called()

  def test_price_polling_survives_rotation_during_iteration():
      ops = Mock()
      ops.get_ticker.return_value = {'price': '1.0'}
      multi = MultiMarketStrategy(ops, ['A-EUR', 'B-EUR'],
                                  virtual_wallet=Mock(get_active_positions=Mock(return_value=[])))
      def rotate_out_b(**kwargs):
          multi.strategies.pop('B-EUR', None)
          return 1.0
      multi.strategies['A-EUR'].get_current_price = rotate_out_b
      multi.get_current_prices()   # must not raise RuntimeError
  ```
  `candles` and `FALLING` come from `tests/test_decision_log.py`; `MarketNotFoundError` comes from `trader.exceptions`.
- [ ] **Step 2: Run them.** `venv/bin/python -m pytest -q tests/test_delisting.py`. Expected: the five new tests FAIL. Typical errors: `KeyError: 'RVN-EUR'`, `place_market_order` called, the position closed by the polling call, `RuntimeError: dictionary changed size`.
- [ ] **Step 3: Implement.**
  - `get_current_price`: on `MarketDelistedError`, or when it is already delisted, call `_mark_delisted`. Then raise if `raise_if_delisted`, otherwise return `last_price`.
  - All trading-path price fetches pass `raise_if_delisted=True`: the buy branch, the sell branch, `_price_based_exit`, and `should_sell` when it fetches the ticker.
  - In `execute_trade`, catch `MarketDelistedError` before `MarketNotFoundError`. On `MarketNotFoundError`, probe once with `get_current_price(use_cache=False, raise_if_delisted=True)`: a 219 goes to the delisting path, and anything else is logged as `error`.
  - The delisting path, used both on catching the error and at the start of `execute_trade` when `self.delisted` is already set:
    1. Close the virtual position once.
    2. Record one `delisted` decision.
    3. Return.
  - `_mark_delisted` no longer closes positions.
  - `get_current_prices` iterates over `list(self.strategies.items())`.
- [ ] **Step 4: Run the suite.** `venv/bin/python -m pytest -q`. Expected: all pass, including the existing ten delisting tests.
- [ ] **Step 5: Commit.** `git commit -am "Handle delisting on the trading thread and abort the in-flight decision"`

### Task 4: Signal 3 requires MACD above its signal line

The spec, §2.3, §3 and recommendation 3: the absolute 0.000001 margin makes "momentum" true for sub-cent coins, causing buy-then-sell churn. Strict MACD cut the loss on the live schedule from −0.53% to −0.19% per trade.

**Files:**
- Modify: `src/trader/enhanced_strategy.py` (`should_buy`, signal 3 line)
- Modify: `tools/log_analysis/replay.py` (`Rules.near_support_macd_margin` default)
- Modify: `tools/log_analysis/analyze.py` (`AUG_OCT_RULES`, `VARIANTS`, section 3 runs)
- Modify: `README.md` (the "Signal 3" bullet under "Multi-Signal Buy Strategy")
- Test: `tests/test_enhanced_strategy.py`, `tests/test_log_analysis_replay.py`

**Interfaces:**
- Produces:
  - `Rules()` mirrors the new live code, with `near_support_macd_margin == 0.0`.
  - `analyze.AUG_OCT_RULES = Rules(near_support_macd_margin=0.000001)` reproduces the Aug–Oct bot.

- [ ] **Step 1: Write the failing tests.** In `tests/test_enhanced_strategy.py`, build a one-row indicator frame with `close=0.010`, `BBL_20_2.0_2.0=0.0100`, `RSI_14=55` and `BBU_20_2.0_2.0=0.012`, then:
  ```python
  def test_near_support_requires_macd_above_signal(strategy):
      df = one_row(macd=1e-9, macd_signal=2e-9)        # bearish by a hair: Aug-Oct code bought here
      assert strategy.should_buy(df) == (False, "")

  def test_near_support_with_rising_macd_buys(strategy):
      df = one_row(macd=2e-9, macd_signal=1e-9)
      assert strategy.should_buy(df) == (True, "Near Support + Momentum")
  ```
  In `tests/test_log_analysis_replay.py`:
  ```python
  def test_aug_oct_margin_is_reproducible():
      s = SimpleNamespace(rsi=55.0, macd=1e-9, macd_signal=2e-9, close=0.0100, bb_lower=0.0100, bb_upper=0.012,
                          trend_1d=0.0, trend_7d=0.0)
      assert buy_reason(s, Rules()) is None
      assert buy_reason(s, AUG_OCT_RULES) == NEAR_SUPPORT
  ```
- [ ] **Step 2: Run them.** `venv/bin/python -m pytest -q tests/test_enhanced_strategy.py tests/test_log_analysis_replay.py`. Expected: the first and third FAIL, and `AUG_OCT_RULES` fails to import.
- [ ] **Step 3: Implement.**
  - Signal 3 becomes `(price < lower_bb * 1.01) and (macd > macd_signal)`.
  - The `Rules.near_support_macd_margin` default becomes `0.0`, with a comment saying Aug–Oct used `0.000001`.
  - Add `AUG_OCT_RULES` to `replay.py`.
  - In `analyze.py`:
    - Build every `VARIANTS` entry from `AUG_OCT_RULES` with `dataclasses.replace(...)`, so a regenerated report reproduces the published numbers.
    - Rename `live rules` to `Aug-Oct live rules`.
    - Rename `signal 3 strict MACD` to `current rules (strict signal 3)`, now `Rules()`.
    - The section 3 runs use these labels:

      | Old label | New label | Rules |
      |---|---|---|
      | `as live` | unchanged | `AUG_OCT_RULES` |
      | `fixed candles, live rules` | `fixed candles, Aug-Oct rules` | `AUG_OCT_RULES` |
      | `fixed candles, signal 3 strict MACD` | `fixed candles, current rules` | `Rules()` |
  - README: signal 3 is "Price < Lower BB × 1.01 AND MACD > Signal".
- [ ] **Step 4: Run the suite** `venv/bin/python -m pytest -q`, then regenerate sections 3–4 to check reproducibility:
  ```bash
  venv/bin/python -m tools.log_analysis.analyze --log-db data/analysis/bender_2026-08-13.db \
      --candles data/analysis/candles_5m.db --out /tmp/bender-check --sections 3,4
  ```
  Expected (as in the spec):

  | Row | Expected |
  |---|---|
  | `Aug-Oct live rules` | −0.69 / +0.39 / −0.86 |
  | `fixed candles, Aug-Oct rules` | −0.53% |
  | `fixed candles, current rules` | −0.19% |
- [ ] **Step 5: Commit.** `git commit -am "Signal 3: require MACD above its signal line (no absolute margin)"`

### Task 5: Open the pull request

- [ ] **Step 1: Verify.** Run `venv/bin/python -m pytest -q && venv/bin/ruff check src tests tools`. Expected: green.
- [ ] **Step 2: Ask for approval to push.** Then run `git push -u origin log-analysis`.
- [ ] **Step 3: Open the PR.** Use `gh pr create --base main --title "Lessons from the Aug-Oct paper-trading run: candle order, delisting, decision log, analysis tools"`. The body opens with what the paper-trading run was for and what it found, then summarises the spec's bugs (§2), the changes (§6) and the test counts, and links the analysis document. It ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

## Phase 2 — Calibrate the replay against a clean virtual run

### Task 6: Load decision logs and virtual-wallet trades

**Files:**
- Create: `tools/log_analysis/decisions.py`
- Test: `tests/test_log_analysis_decisions.py`

**Interfaces:**
- Produces:
  - `load_decisions(paths: Iterable[Path]) -> tuple[pd.DataFrame, int]` returns the frame and the number of skipped lines.
    - Columns: `ts, market, action, reason, price, entry_price, candle_ts, candle_close, rsi, macd, macd_signal, bb_lower, bb_upper`.
    - `ts`/`candle_ts` are naive UTC `datetime64`, missing fields are NaN, and the frame is sorted by `ts`.
  - `load_wallet_trades(db_path: Path, utc_offset_hours: float = 0.0) -> pd.DataFrame`, from table `virtual_trades`.
    - Columns: `market, entry_ts, entry_price, exit_ts, exit_price, pl_eur, pl_pct, fees_eur, pre_log`. `pre_log` is always 0.
    - Times are shifted by `-utc_offset_hours`. Open trades have NaN exits.
  - `attach_exit_reasons(trades: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame` adds `exit_reason`.
    - Values: `'technical'|'take_profit'|'stop_loss'|'delisted'|None`.
    - Taken from the `sell` decision for the same market within 2 minutes of `exit_ts`, by reason prefix: `Technical` → technical, `Take Profit` → take_profit, `Stop Loss` → stop_loss.
    - A `delisted` decision gives `delisted`.
  - The column names match the parser's `trades` table, so Task 7 accepts both.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_loads_records_and_skips_a_truncated_last_line(tmp_path):
      f = tmp_path / 'decisions-2026-11-01.jsonl'
      f.write_text(json.dumps(BUY) + '\n' + json.dumps(MONITOR) + '\n' + '{"ts": "2026-11-01T10:0')
      df, skipped = load_decisions([f])
      assert len(df) == 2 and skipped == 1
      assert df.ts.iloc[0] == pd.Timestamp('2026-11-01 10:00:00.123')   # +00:00 converted, naive UTC

  def test_records_without_indicators_have_nan(tmp_path):
      f = tmp_path / 'decisions-2026-11-01.jsonl'
      f.write_text(json.dumps(ERROR) + '\n')   # {"ts", "market", "action": "error", "reason", "price": null, "entry_price": null}
      df, _ = load_decisions([f])
      assert np.isnan(df.rsi.iloc[0]) and pd.isna(df.candle_ts.iloc[0])

  def test_wallet_trades_from_a_real_wallet(tmp_path):
      wallet = VirtualWallet(db_path=str(tmp_path / 'w.db'), initial_balance=100.0)
      wallet.record_buy('ABC-EUR', price=1.0, amount=10.0, fee=0.025)
      wallet.record_sell('ABC-EUR', price=1.1, amount=10.0, fee=0.0275)
      [row] = load_wallet_trades(tmp_path / 'w.db').itertuples()
      assert row.entry_price == 1.0 and row.exit_price == 1.1
      assert row.pl_pct == pytest.approx((11 - 0.0275 - 10 - 0.025) / 10 * 100)

  EXIT = pd.DataFrame([dict(market='ABC-EUR', exit_ts=pd.Timestamp('2026-11-01 12:00:00'))])

  def sell_at(ts):
      return pd.DataFrame([dict(market='ABC-EUR', ts=pd.Timestamp(ts), action='sell', reason='Stop Loss (-5.10%)')])

  def test_exit_reason_comes_from_the_matching_sell_decision():
      assert attach_exit_reasons(EXIT, sell_at('2026-11-01 12:00:30')).exit_reason.tolist() == ['stop_loss']

  def test_unmatched_exit_gets_no_reason():
      out = attach_exit_reasons(EXIT, sell_at('2026-11-01 12:05:00'))
      assert len(out) == 1 and out.exit_reason.iloc[0] is None
  ```
  `BUY` and `MONITOR` are dicts in the exact format `EnhancedStrategy._record_decision` writes. Copy one from `tests/test_decision_log.py` output.
- [ ] **Step 2: Run them.** `venv/bin/python -m pytest -q tests/test_log_analysis_decisions.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `tools/log_analysis/decisions.py`.** The `json.loads` per line skips `JSONDecodeError` and counts it. `pd.to_datetime(..., utc=True).dt.tz_localize(None)` produces the naive UTC times.
- [ ] **Step 4: Run them.** Expected: PASS. Then `venv/bin/ruff check tools tests`.
- [ ] **Step 5: Commit.** `git add tools/log_analysis/decisions.py tests/test_log_analysis_decisions.py && git commit -m "Load decision logs and virtual wallet trades"`

### Task 7: Replay calibration report

**Files:**
- Create: `tools/log_analysis/validation.py` (move `exit_agreement` out of `analyze.py`)
- Create: `tools/log_analysis/calibrate.py`
- Modify: `tools/log_analysis/analyze.py` (section 3 imports `exit_agreement`)
- Test: `tests/test_log_analysis_validation.py`

**Interfaces:**
- Consumes: Task 6 frames, `replay.window_snapshot`, `window_snapshots`, `buy_reason`, `sell_reason`, `Rules`, and `candles.CandleStore`/`fetch_candles`.
- Produces:
  - `exit_agreement(trades: pd.DataFrame, snapshots: dict[str, pd.DataFrame], rules: Rules, fee_rate: float = 0.0025) -> dict`.
    - `trades` needs the columns `market, entry_ts, entry_price, exit_ts, exit_reason, pl_pct`. Rows with `pre_log == 1` or no exit are ignored.
    - It returns `trades, of, same_time_pct, same_reason_pct, pl_correlation, live_avg_pl, sim_avg_pl, optimism_pp`, where `optimism_pp = sim_avg_pl - live_avg_pl`.
  - `decision_agreement(decisions: pd.DataFrame, candles_for: Callable[[str], pd.DataFrame], rules: Rules, sample: int = 3000, seed: int = 7) -> dict`.
    - It samples decisions with `rsi` present and `entry_price` null (flat, so a buy was possible).
    - It recomputes each with `window_snapshot(candles_for(market), candle_ts)`.
    - It returns `compared, indicator_match_pct` (RSI within 1 and close within 0.2%), and `buy_agreement_pct`. Here logged buy = action in `{'buy', 'blocked_position_limit', 'blocked_risk', 'no_price'}`, compared with `buy_reason(snap, rules) is not None`.
  - CLI: `python -m tools.log_analysis.calibrate --decisions 'logs/decisions-*.jsonl' --wallet data/virtual_trades.db --candles data/analysis/candles_5m.db --out data/analysis/calibration [--utc-offset 0]`.
    - It fetches candles for any market missing from the store, from the first decision minus 2 days to the last plus 1 day.
    - It writes `calibration.json` and `calibration.md`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_exit_agreement_recovers_a_known_exit():
      snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.0, 0.94], rsi=[30, 50, 50, 50])}  # SL at t3
      trades = pd.DataFrame([dict(market='A-EUR', entry_ts=T0, entry_price=1.0, exit_ts=T0 + 3 * FIVE_MIN,
                                  exit_reason='stop_loss', pl_pct=(0.94 * 0.9975 - 1.0025) * 100, pre_log=0)])
      result = exit_agreement(trades, snaps, Rules())
      assert result['same_time_pct'] == 100 and result['same_reason_pct'] == 100
      assert result['optimism_pp'] == pytest.approx(0, abs=1e-9)

  def test_trades_without_snapshots_are_skipped_and_counted():
      trades = pd.DataFrame([dict(market=m, entry_ts=T0, entry_price=1.0, exit_ts=T0 + 3 * FIVE_MIN,
                                  exit_reason='stop_loss', pl_pct=-6.0, pre_log=0) for m in ('A-EUR', 'B-EUR')])
      snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.0, 0.94], rsi=[30, 50, 50, 50])}
      result = exit_agreement(trades, snaps, Rules())
      assert (result['trades'], result['of']) == (1, 2)

  def test_decision_agreement_matches_logged_buy():
      candles = candle_frame(np.linspace(2.0, 1.0, 300))           # falling: RSI ~0, buy signal
      t = candles.index[-1]
      snap = window_snapshot(candles, t)
      decisions = pd.DataFrame([dict(ts=t, market='A-EUR', action='buy', entry_price=np.nan, candle_ts=t,
                                     rsi=snap.rsi, candle_close=snap.close)])
      result = decision_agreement(decisions, lambda m: candles, Rules(), sample=10)
      assert result['indicator_match_pct'] == 100 and result['buy_agreement_pct'] == 100
  ```
  Move `candle_frame` and `flat_snapshots` from `tests/test_log_analysis_replay.py` to `tests/log_analysis_helpers.py` and import them in both files.
- [ ] **Step 2: Run them.** `venv/bin/python -m pytest -q tests/test_log_analysis_validation.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement.**
  - Move `exit_agreement` from `analyze.py` into `validation.py`, generalised to the interface above (it currently filters `pre_log` itself and hard-codes `Rules()`).
  - Add `decision_agreement`, then `calibrate.py`'s `main(argv=None) -> int`, following `analyze.main`'s structure.
- [ ] **Step 4: Run the suite** `venv/bin/python -m pytest -q`, then regenerate section 3 as in Task 4 Step 4. Expected: the trade-by-trade line is unchanged (69% / 86% / 0.54).
- [ ] **Step 5: Commit.** `git add tools/log_analysis/validation.py tools/log_analysis/calibrate.py tests/ && git commit -am "Add replay calibration against decision logs"`

### Task 8: Calibration run (operational)

- [ ] **Step 1:** After the PR is merged, run the fixed bot with a clean wallet: `trader virtual --monitor --reset`, with default settings.
- [ ] **Step 2:** Let it run for at least 14 days and 100 closed trades; extend until both are met.
- [ ] **Step 3:** Run `venv/bin/python -m tools.log_analysis.calibrate --decisions 'logs/decisions-*.jsonl' --wallet data/virtual_trades.db --candles data/analysis/candles_5m.db --out data/analysis/calibration`.
- [ ] **Step 4: Gate.** Both `indicator_match_pct` and `buy_agreement_pct` must be ≥ 95. If either is lower, stop: the replay does not describe the bot, so investigate before any Phase 3 decision.
- [ ] **Step 5:** Set `CALIBRATION_MARGIN_PP` in `tools/log_analysis/analyze.py` (Task 12) to `max(0.4, optimism_pp)`.
- [ ] **Step 6:** Write the numbers to `docs/analysis/YYYY-MM-DD-calibration.md`, then commit.

---

## Phase 3 — Can lower costs give the strategy an edge? (replay only)

Phase 3 can be built during the Task 8 run. Only the final gate decision waits for the calibrated margin.

### Task 9: Spread and fee model in the replay

The spec, §8 and recommendation 5: virtual fills ignore the bid-ask spread, which the scorer allows up to 0.5%.

**Files:**
- Modify: `tools/log_analysis/replay.py` (new `Costs`, `replay`, `_close`)
- Modify: `tools/log_analysis/analyze.py` (new `median_spreads`, callers of `replay`)
- Test: `tests/test_log_analysis_replay.py`, `tests/test_log_analysis_analyze.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Costs: taker_fee: float = 0.0025; maker_fee: float = 0.0015; half_spread: float = 0.0`, and `TAKER = Costs()`.
  - `replay(snapshots, rules=LIVE_RULES, schedule=None, max_positions=3, stake=10.0, costs: Costs = TAKER, spreads: Optional[dict[str, float]] = None, occupied=(), fill=None) -> pd.DataFrame`.
    - This replaces the `fee_rate` parameter.
    - `spreads[market]` is a half-spread fraction that overrides `costs.half_spread`.
    - Market orders buy at `price * (1 + hs)` and sell at `price * (1 - hs)`.
    - `pl_eur = stake * (exit_fill / entry_fill) * (1 - exit_fee) - stake * (1 + entry_fee)`.
    - `entry_price`/`exit_price` in the result are the fill prices.
    - Stop-loss and take-profit compare `snap.price` with the entry fill.
  - `median_spreads(conn) -> dict[str, float]`: per market, the median of `market_scores.spread_pct` where it is not null, divided by 200.

- [ ] **Step 1: Write the failing tests:**
  ```python
  def test_half_spread_is_paid_on_both_sides():
      snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.2], rsi=[30, 50, 50])}
      [t] = replay(snaps, rules=Rules(take_profit_pct=15.0), costs=Costs(half_spread=0.001)).itertuples()
      assert t.entry_price == pytest.approx(1.001) and t.exit_price == pytest.approx(1.2 * 0.999)
      assert t.pl_eur == pytest.approx(10 * (1.2 * 0.999 / 1.001) * 0.9975 - 10 * 1.0025)

  def test_per_market_spread_overrides_the_default():
      # spreads={'A-EUR': 0.002}, costs half_spread 0.0 -> entry_price 1.002

  def test_median_spreads_from_scores():
      conn = sqlite3.connect(':memory:')
      conn.execute('CREATE TABLE market_scores (market TEXT, spread_pct REAL)')
      conn.executemany('INSERT INTO market_scores VALUES (?, ?)', [('A-EUR', 0.1), ('A-EUR', 0.3), ('A-EUR', 0.2), ('B-EUR', None)])
      assert median_spreads(conn) == {'A-EUR': pytest.approx(0.001)}
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (`Costs` and `median_spreads` missing).
- [ ] **Step 3: Implement.** Update every `replay(...)` call in `analyze.py` (they used the default fee, so they stay `TAKER`, with no spread). `test_take_profit_trade_pays_fees_both_ways` must still pass unchanged.
- [ ] **Step 4: Run the suite** and Task 4 Step 4's reproducibility check. Expected: green, and identical numbers.
- [ ] **Step 5: Commit.** `git commit -am "Replay: spread and maker/taker fee model"`

### Task 10: Limit-order entries and take-profits in the replay

**Files:**
- Modify: `tools/log_analysis/replay.py` (`Rules`, `SNAPSHOT_COLUMNS`, `window_snapshot`, `full_series_snapshots`, `replay`)
- Test: `tests/test_log_analysis_replay.py`

**Interfaces:**
- Produces:
  - New `Rules` fields:
    - `entry_order: str = 'market'` (`'market'|'limit'`)
    - `limit_offset_pct: float = 0.5`
    - `limit_timeout: pd.Timedelta = pd.Timedelta(minutes=15)`
    - `take_profit_order: str = 'market'` (`'market'|'limit'`)
  - `SNAPSHOT_COLUMNS` gains `'low', 'high'`, taken from the bar.
- Fill rules:
  - **Limit buy:** set at the signal bar to `snap.price * (1 - limit_offset_pct / 100)`. It is pending through `t + limit_timeout` (inclusive) and fills at the limit price on the first later bar with `low <= limit`. It pays `maker_fee` and no spread.
  - **Pending slots:** a pending order counts toward `max_positions`.
  - **Expiry:** expired orders are removed at the start of each bar, before any market is evaluated. They leave no trade and pay no fee.
  - **Limit take-profit:** checked first on each bar while held. It fills at `entry * (1 + take_profit_pct / 100)` when `high` reaches it, with `maker_fee` and no spread, and `exit_reason='take_profit'`.
  - **Other exits:** all other exits are market orders (taker fee plus spread).

- [ ] **Step 1: Write the failing tests.** Give `flat_snapshots` optional `low`/`high` arguments that default to the price.
  ```python
  def test_limit_entry_fills_when_price_trades_through():
      snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.0], rsi=[30, 50, 50], low=[1.0, 0.994, 1.0])}
      [t] = replay(snaps, rules=Rules(entry_order='limit', limit_offset_pct=0.5)).itertuples()
      assert t.entry_t == T0 + FIVE_MIN and t.entry_price == pytest.approx(0.995)

  LIMIT = Rules(entry_order='limit', limit_offset_pct=0.5, limit_timeout=pd.Timedelta(minutes=10))

  def test_unfilled_limit_entry_expires_without_a_trade():
      snaps = {'A-EUR': flat_snapshots([1.0] * 4, rsi=[30, 50, 50, 50])}   # lows never reach 0.995
      assert replay(snaps, rules=LIMIT).empty                              # no fill, no fee

  def test_expired_limit_order_releases_its_slot():
      snaps = {'A-EUR': flat_snapshots([1.0] * 5, rsi=[30, 50, 50, 50, 50]),
               'B-EUR': flat_snapshots([1.0] * 5, rsi=[50, 50, 50, 30, 50], low=[1.0, 1.0, 1.0, 1.0, 0.99])}
      trades = replay(snaps, rules=LIMIT, max_positions=1)
      assert trades.market.tolist() == ['B-EUR']    # A's order expired after T0+10min, B ordered at T0+15min

  def test_pending_limit_order_reserves_a_slot():
      snaps = {m: flat_snapshots([1.0, 1.0], rsi=[30, 50], low=[1.0, 0.99]) for m in ('A-EUR', 'B-EUR')}
      trades = replay(snaps, rules=LIMIT, max_positions=1)
      assert trades.market.tolist() == ['A-EUR']

  def test_limit_take_profit_fills_at_target_with_maker_fee():
      snaps = {'A-EUR': flat_snapshots([1.0, 1.0, 1.05], rsi=[30, 50, 50], high=[1.0, 1.0, 1.16])}
      [t] = replay(snaps, rules=Rules(take_profit_order='limit', take_profit_pct=15.0)).itertuples()
      assert t.exit_price == pytest.approx(1.15) and t.exit_reason == 'take_profit'
      assert t.pl_eur == pytest.approx(10 * 1.15 * (1 - 0.0015) - 10 * 1.0025)
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (unknown `Rules` fields).
- [ ] **Step 3: Implement** pending orders in `replay` as a dict `pending[market] = (limit, deadline, reason)` beside `open_positions`. Slots count `len(open_positions) + len(pending) + held_elsewhere`.
- [ ] **Step 4: Run the suite** and Task 4 Step 4's reproducibility check. Expected: green, and identical numbers.
- [ ] **Step 5: Commit.** `git commit -am "Replay: limit-order entries and take-profits"`

### Task 11: Hourly candles in the studies

**Files:**
- Modify: `tools/log_analysis/analyze.py` (`--interval`, `bars_for`, `_study_market`, `_signal_edges`, worker argument tuples)
- Test: `tests/test_log_analysis_analyze.py`

**Interfaces:**
- Produces:
  - `bars_for(horizon: pd.Timedelta, interval: str) -> int`, using `candles.INTERVAL_MS`.
  - `analyze --interval 1h` allows only the sections `4,5,7`; others exit with an error naming the allowed sections.
  - The "at least a day of data" check becomes `len(window) < bars_for(pd.Timedelta(days=1), interval)`.
  - The minimum history (`< 500` candles) becomes `bars_for(pd.Timedelta(days=4), interval)` for `1h`.

- [ ] **Step 1: Write the failing tests:**
  ```python
  @pytest.mark.parametrize('horizon, interval, bars', [('4h', '5m', 48), ('24h', '1h', 24), ('1h', '1h', 1)])
  def test_bars_for(horizon, interval, bars):
      assert bars_for(pd.Timedelta(horizon), interval) == bars

  def test_rule_study_runs_on_hourly_candles_and_skips_markets_without_data(tmp_path):
      store = CandleStore(tmp_path / 'c1h.db')
      store.save('A-EUR', hourly_random_walk('2026-05-01', '2026-10-29'))   # helper in tests/log_analysis_helpers.py
      store.save('EMPTY-EUR', [])
      md, result = rule_study(['A-EUR', 'EMPTY-EUR'], str(tmp_path / 'c1h.db'), interval='1h')
      assert {r['period'] for r in result['stats']} == set(PERIODS)
      assert {r['markets'] for r in result['stats']} == {1}
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (`bars_for` missing, `interval` unknown).
- [ ] **Step 3: Implement.** Thread `interval` through `rule_study(markets, candles_db, interval='5m')`, `signal_edges(markets, candles_db, interval='5m')` and their workers. The `_signal_edges` horizons become `bars_for(...)` of 1 h, 4 h and 24 h.
- [ ] **Step 4: Fetch hourly candles.**
  ```bash
  venv/bin/python -m tools.log_analysis.candles --markets-file <monitored markets, one per line> \
      --interval 1h --start 2026-05-01 --end 2026-10-29 --db data/analysis/candles_1h.db
  ```
  Get the market list with `SELECT DISTINCT market FROM checks`. Expected: 145 markets fetched, 3 with 0 candles (RVN, ICX, VANRY).
- [ ] **Step 5: Run the suite.** Expected: green.
- [ ] **Step 6: Commit.** `git commit -am "Analysis: run rule studies on any candle interval"`

### Task 12: Cost experiments and the decision gate

**Files:**
- Modify: `tools/log_analysis/analyze.py` (new section `'7'`, `CALIBRATION_MARGIN_PP`, `passes_gate`, `--candles-1h`)
- Modify: `docs/analysis/` (new results document)
- Test: `tests/test_log_analysis_analyze.py`

**Interfaces:**
- Consumes: Task 9's `Costs`/`median_spreads`, Task 10's `Rules` fields, and Task 11's `interval`.
- Produces:
  - `CALIBRATION_MARGIN_PP = 0.4`.
  - `passes_gate(stats_by_period: dict[str, dict], margin_pp: float = CALIBRATION_MARGIN_PP, min_trades: int = 200) -> bool`. It is true only if every period in `PERIODS` is present with `trades >= min_trades` and `avg_pl_pct >= margin_pp`.
  - `cost_experiments(markets, candles_5m, candles_1h, spreads) -> tuple[list, dict]`. It is section 7, and it is per market and independent, like section 4. The grid:
    - **Interval:** `5m`, `1h`.
    - **Orders:**
      - `market`: taker plus the logged median spread.
      - `limit`: `entry_order='limit'`, `limit_offset_pct=0.5`, `limit_timeout` = 3 bars, `take_profit_order='limit'`.
    - **Rules:**
      - `current rules`: `Rules()`.
      - `TP 3 / SL 3, no technical exit`.
      - `RSI<30 only, TP 5 / SL 3, no technical exit`.
    - **Output:** a table of average net P/L per trade by period, plus trades per period and a `passes gate` column.
    - **Extra row group:** `current rules, market orders, 5m`, split by spread tercile (the markets' median logged spread).

- [ ] **Step 1: Write the failing tests:**
  ```python
  GOOD = dict(trades=250, avg_pl_pct=0.6)

  def test_gate_requires_every_period():
      assert passes_gate({p: GOOD for p in PERIODS}, margin_pp=0.4)
      assert not passes_gate({p: GOOD for p in list(PERIODS)[:2]}, margin_pp=0.4)

  def test_gate_rejects_thin_or_marginal_periods():
      stats = {p: GOOD for p in PERIODS}
      assert not passes_gate({**stats, 'live B (1-28 Oct)': dict(trades=150, avg_pl_pct=1.0)}, margin_pp=0.4)
      assert not passes_gate({**stats, 'live B (1-28 Oct)': dict(trades=250, avg_pl_pct=0.39)}, margin_pp=0.4)
  ```
- [ ] **Step 2: Run them.** Expected: FAIL (`passes_gate` missing).
- [ ] **Step 3: Implement** `passes_gate`, `cost_experiments`, a `--candles-1h` CLI argument (required for section 7), and section `'7'` in `main`'s section map.
- [ ] **Step 4: Run the experiments.**
  ```bash
  venv/bin/python -m tools.log_analysis.analyze --log-db data/analysis/bender_2026-08-13.db \
      --candles data/analysis/candles_5m.db --candles-1h data/analysis/candles_1h.db \
      --out data/analysis --sections 7
  ```
- [ ] **Step 5: Write `docs/analysis/YYYY-MM-DD-cost-experiments.md`:**
  - The table.
  - Which configurations pass the gate at the current margin.
  - Which still need the Task 8 margin.
  - One line per Phase 4 task saying go or no-go.
- [ ] **Step 6: Commit.** `git add tests/ tools/ docs/analysis/ && git commit -m "Analysis: cost experiments and decision gate"`

---

## Phase 4 — Adopt what passes (each task runs only if its gate passes)

### Task 13: `CANDLE_INTERVAL` setting

**Gate:** a `1h` row passes in Task 12, with the margin from Task 8.

**Files:**
- Modify: `src/trader/config.py` (`TradingStrategyConfig.candle_interval: str = '5m'`, env `CANDLE_INTERVAL`)
- Modify: `src/trader/enhanced_strategy.py` (`__init__(..., candle_interval: str = '5m')`, and `get_historical_data(self, interval: Optional[str] = None, limit: int = 100)` defaulting to `self.candle_interval`)
- Modify: `src/trader/multi_market_strategy.py` (passes `candle_interval` through `__init__` and `_create_strategy`)
- Modify: `src/trader/main.py` (wire the config)
- Modify: `README.md` (the configuration block)
- Test: `tests/test_config.py`, `tests/test_enhanced_strategy.py`, `tests/test_multi_market_strategy.py`

**Interfaces:**
- Produces: the allowed values are `('5m', '15m', '30m', '1h')`. Anything else raises `ValueError("CANDLE_INTERVAL must be one of 5m, 15m, 30m, 1h")` from `get_config`.

- [ ] **Step 1: Write the failing tests:**
  - `test_candle_interval_from_env` (`'1h'` parsed)
  - `test_invalid_candle_interval_is_rejected` (raises with the exact message)
  - `test_strategy_requests_configured_interval`: `market_ops.get_historical_candles.assert_called_with('TEST-EUR', interval='1h', limit=100)`
  - `test_multi_market_passes_candle_interval`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the suite.** Expected: green.
- [ ] **Step 5: Commit.** `git commit -am "Configurable candle interval (CANDLE_INTERVAL)"`

### Task 14: `MAX_SPREAD_PCT` setting

**Gate:** in Task 12, the lowest spread tercile does better than the highest in every period.

**Files:**
- Modify: `src/trader/config.py` (`max_spread_pct: float = 0.5`, env `MAX_SPREAD_PCT`)
- Modify: `src/trader/main.py` (`find_best_markets(market_ops, top_n=3, max_candidates=10, top_50_markets=None, max_spread_pct: float = 0.5)`; both call sites pass `strategy_config.max_spread_pct`)
- Modify: `README.md`
- Test: `tests/test_main.py`, `tests/test_config.py`

**Interfaces:**
- In `find_best_markets`:
  - Rejection becomes `spread_pct > max_spread_pct`. This replaces the hard-coded `0.5` at `main.py:325`.
  - `spread_score = max(0, min(1.0, 1.0 - spread_pct / max_spread_pct))`. This replaces the hard-coded value at `main.py:295`.
- The rejection log line says `({spread_pct:.2f}% > {max_spread_pct}%)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_spread_above_configured_max_is_rejected`: the order book has a 0.3% spread and `max_spread_pct=0.2`, and the market is not in the result.
  - `test_max_spread_pct_from_env`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the suite.** Expected: green.
- [ ] **Step 5: Commit.** `git commit -am "Configurable spread limit (MAX_SPREAD_PCT)"`

### Task 15: Live limit orders (design first)

**Gate:** a `limit` row passes in Task 12.

This is not planned in detail here. Live limit orders change real-money order handling: resting orders, partial fills, cancels and timeouts, and reconciling pending orders after a restart. If the gate passes, write a design with superpowers:brainstorming, then plan it separately. `MarketOperations.place_limit_order` and `cancel_order` already exist.

---

## Go / no-go for real money

Every one of these must hold before `trader trade` is used:

1. Phase 1 is merged.
2. The Task 8 calibration passes its gate.
3. At least one configuration passes the Task 12 gate with the calibrated margin.
4. That configuration has run in virtual mode for at least 30 days with net P/L ≥ 0 after fees.

Then start with the smallest `TRADE_AMOUNT` Bitvavo accepts.
