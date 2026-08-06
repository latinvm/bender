# Bender — Full Codebase Review & Improvement Plan

**Date:** 2026-08-06
**Status:** Phases 0-2 implemented on branch `hardening/phases-0-2` (2026-08-06). Phase 2.4 delivered as an unwired primitive (`MarketOperations.place_stop_loss_order`) pending live verification.
**Scope:** Complete review of `src/trader/` (~3,600 LOC, 15 modules), tests (191 tests), docs, packaging, and repo hygiene.
**Verdict:** Solid hobby project with genuinely good bones — but the **real-money path is not safe to run today**. Two critical bugs (full-balance liquidation in `test_trade`, virtual trades polluting the real trades DB) must be fixed before `trader trade` is ever used again.

---

## 1. State of the Tool

### Scorecard

| Area | Grade | Notes |
|---|---|---|
| Project structure | B+ | Clean `src/` layout, separated concerns, small focused modules |
| Documentation | B | Rich README + 3 docs; some drift from code (Signal 2 threshold) |
| Test suite | B- | 191 tests, 187 pass; 4 are live-API tests that don't belong in the unit suite |
| Virtual trading | B | Works, transactional wallet, fee modelling; minor P/L edge cases |
| **Real trading safety** | **F** | Full-balance sell bug, DB cross-contamination, no reconciliation, no graceful shutdown |
| Backtester | D | Leaks live ticker prices into historical decisions; no fees/slippage |
| Packaging / CI | D | No `install_requires`, wrong `python_requires`, no CI, unused deps |
| Error handling | C | Everything funnels into `APIConnectionError`; Bitvavo error-dicts unchecked |

### What's genuinely good

- Clean separation: exchange client → market ops → strategy → persistence → UI.
- The virtual wallet (`virtual_wallet.py`) is the best module: transactional, fee-aware, with a transactions ledger and a TUI checksum invariant (`tui.py:42-44`) that self-verifies accounting.
- `VirtualMarketOperations` mirrors the real API surface (duck-typed), so strategies run unchanged in both modes.
- Two-step market selection (cheap scan → detailed scoring with Sharpe/Sortino/spread/volume-consistency) is a sensible design.
- Repo hygiene is good: `.env`, `*.db`, `logs/` all gitignored, no secrets or artifacts tracked.
- The upstream Bitvavo rate-limit bug is patched thoughtfully (`bitvavo.py`), with docs.

---

## 2. Findings

### CRITICAL — do not run `trader trade` until these are fixed

**C1. `test_trade` sells your entire holding of the asset — [market.py:390-398](../../src/trader/market.py#L390-L398)**
The real-mode startup test trade buys a minimum amount, then fetches `get_available_balance(base)` and sells **everything**. If you already hold that coin (e.g. 50,000 VET) and it gets picked as market #1, Bender liquidates the whole position at market. It also spends real fees + spread on *every* startup.
*Fix:* sell only the filled amount from the buy order response; make the real-money test trade opt-in (`--test-trade`), defaulting to a read-only connectivity check.

**C2. Virtual trades are written to the real trades DB — [enhanced_strategy.py:223](../../src/trader/enhanced_strategy.py#L223) and [:244](../../src/trader/enhanced_strategy.py#L244)**
`EnhancedStrategy` always constructs `TradeDatabase()` and records entries/exits there, even when a `virtual_wallet` is injected. Consequence chain:
1. Virtual session buys → phantom `ACTIVE` rows accumulate in `data/trades.db`.
2. Later real session: [main.py:468-472](../../src/trader/main.py#L468-L472) reports them as "positions from previous session", and [multi_market_strategy.py:41-45](../../src/trader/multi_market_strategy.py#L41-L45) adopts them as orphaned markets.
3. The strategy will then place **real sell orders for coins that were never actually bought**.
*Fix:* the strategy must write to exactly one store — the virtual wallet in virtual mode, `TradeDatabase` in real mode. Inject the store; never instantiate `TradeDatabase()` implicitly.

**C3. Recorded fills are fiction — [enhanced_strategy.py:214-223](../../src/trader/enhanced_strategy.py#L214-L223)**
Entry price = pre-trade ticker price and amount = requested amount; the order response (`fills`, `filledAmount`, `feePaid`) is ignored. Real-mode P/L, stop-loss, and take-profit all compute from prices you didn't actually get. Fees aren't stored at all in `TradeDatabase` (`get_total_costs()` hardcodes `0.0`), so real P/L is systematically overstated.
*Fix:* parse fills from the order response; persist weighted-average fill price, filled amount, fee, and order ID.

**C4. No graceful shutdown — [main.py:596-605](../../src/trader/main.py#L596-L605)**
The strategy runs in a **daemon** thread while the TUI owns the main thread. Pressing `q` kills the process instantly — potentially between placing an order and recording it (order placed, DB never updated). There's no signal handling and no stop event; non-monitor mode relies on `KeyboardInterrupt` mid-`time.sleep`.
*Fix:* a shared `threading.Event`; strategy loop checks it between markets and never between "order placed" and "order recorded"; TUI quit sets it and joins the thread with a timeout.

**C5. No position reconciliation in real mode**
On startup, positions come solely from the local SQLite DB. Nothing verifies them against actual exchange balances (`get_balance()` exists but is unused for this). Manual trades, partial fills, or the C2/C4 bugs above all cause silent drift — and the bot will happily "sell" positions it doesn't hold or ignore ones it does.
*Fix:* on startup, reconcile DB positions against exchange balances; refuse to trade (or require `--force`) on mismatch.

### HIGH — correctness and robustness

**H1. Bitvavo error-dict responses are unchecked — [market.py:66-78](../../src/trader/market.py#L66-L78) and throughout**
The Bitvavo library returns `{'errorCode': ..., 'error': ...}` dicts instead of raising. Only `place_market_order` checks for this; `get_ticker` KeyErrors on `'price'` and surfaces as the cryptic `APIConnectionError: 'price'` — which is exactly what the 4 failing tests show. *Fix:* one `_check_response()` helper applied to every API call, mapping error codes to the existing typed exceptions (including rate-limit code 105 → dedicated handling).

**H2. Backtester leaks live prices into historical decisions — [backtester.py:74](../../src/trader/backtester.py#L74) → [enhanced_strategy.py:129](../../src/trader/enhanced_strategy.py#L129)**
`should_sell()` calls `get_current_price()` (live ticker!) for stop-loss/take-profit P/L. During a backtest over January data, exit decisions are made against **today's** price. Backtest results are meaningless for any strategy that exits via SL/TP — which is this strategy. Also: no fees, no slippage, fixed 1-unit position, 1,440-candle (~60 day) cap contradicting the README's year-long example.
*Fix:* strategies must take price as an input (or a price-provider), never fetch it themselves during signal evaluation; backtester simulates through `VirtualWallet` with the configured fee.

**H3. NaN poisons market scoring — [main.py:60-66](../../src/trader/main.py#L60-L66)**
`calculate_sortino_ratio` with no negative returns: `np.std([])` → `NaN`, `NaN == 0` is `False`, so it returns `mean/NaN = NaN`. The NaN propagates through `min`/`max` clamps into `total_score`, silently corrupting the ranking (these are the RuntimeWarnings in the test run). Ironically an all-gains market scores worst. *Fix:* return a capped high value (or `0.0` by explicit choice) when there are no downside returns; add `np.isnan` guards before scoring; unit-test both ratios.

**H4. `round()` can round order amounts UP — [market.py:246](../../src/trader/market.py#L246)**
Rounding to precision can exceed the available balance on sells (order rejected) or the intended spend on buys. *Fix:* floor to `orderSizeIncrement` using `Decimal` quantization, not `round()`.

**H5. Non-portable SQL — [virtual_wallet.py:280-287](../../src/trader/virtual_wallet.py#L280-L287)**
`UPDATE ... ORDER BY entry_time ASC LIMIT 1` requires SQLite compiled with `SQLITE_ENABLE_UPDATE_DELETE_LIMIT`. Works on this machine; crashes on standard builds. *Fix:* `SELECT id ... LIMIT 1` then `UPDATE ... WHERE id = ?`.

**H6. Fragile trade↔position matching — [database.py:104-113](../../src/trader/database.py#L104-L113)**
`record_trade_exit` joins on `(market, amount, entry_price)` — ambiguous for duplicate entries, and floating-point equality on price/amount. *Fix:* link positions to trades by foreign key `trade_id`; store the exchange order IDs.

**H7. The periodic rescan thread is a no-op feature — [main.py:555-574](../../src/trader/main.py#L555-L574)**
It refreshes `_top_50_cache` every N hours, but `markets` and the strategy objects are fixed at startup and never re-derived. The bot trades its launch-time markets forever. *Fix (Phase 2):* wire re-selection into the loop — rotate out markets with no open position, keep markets holding positions until they exit.

**H8. Packaging is broken — [setup.py](../../setup.py)**
No `install_requires` (a bare `pip install .` yields a broken install), `python_requires=">=3.7"` while the code uses `tuple[bool, str]` annotations (3.9+; README says 3.8+). `pytz`, `sqlalchemy`, and `typing-extensions` are declared in requirements.txt but **never imported**. `pandas-ta` is unmaintained (last release 2021) and is the main blocker for newer Python/numpy. *Fix:* migrate to `pyproject.toml`, declare real deps, set `requires-python = ">=3.10"`, drop the three unused deps, and plan a `pandas-ta` exit (compute RSI/MACD/BB in ~40 lines of pandas, or use `ta`).

### MEDIUM

- **M1. Four live-API tests in the unit suite** (`test_price_cache.py`, `test_tui_debug.py`, `test_position_pl_consistency.py`): they build a real `BitvavoClient` with dummy creds and fail offline — the suite is red on every clean checkout. Mark with `@pytest.mark.integration` (deselect by default) or mock the client. Some also write to the *real* `data/virtual_trades.db` via `get_config()` — tests should never touch the user's data dir.
- **M2. Docs/code drift on Signal 2:** code is `rsi < 50` ([enhanced_strategy.py:81](../../src/trader/enhanced_strategy.py#L81)); the log line one row below and the README both say "RSI < 55". Strategy thresholds are scattered magic numbers — hoist them into `TradingStrategyConfig` so code, logs, and docs can't diverge.
- **M3. `main()` is a 300-line god function** ([main.py:342-655](../../src/trader/main.py#L342-L655)) mixing CLI parsing, mode selection, stats display, thread orchestration, and TUI startup. Split into `cli.py` (argparse w/ subcommands), `app.py` (wiring), `stats.py` (reporting). Use module-level `logger = logging.getLogger(...)` instead of the `logger = None` global mutated inside `main()`.
- **M4. Duplicate `TradeDatabase` instances everywhere** — `main()`, `MarketOperations.__init__`, each `EnhancedStrategy`, `MultiMarketStrategy` each construct their own (and each constructor call re-runs `get_config()`/`load_dotenv()`). Construct once, inject everywhere. Bollinger column names (`BBL_20_2.0_2.0`) are pandas-ta-version-specific — resolve them dynamically.
- **M5. No CI.** black/flake8/isort/mypy are in requirements-dev.txt but there's no config and nothing enforces them. Add GitHub Actions: lint + unit tests on Python 3.10–3.13, coverage report.
- **M6. Client-side-only stop-loss.** SL/TP are evaluated every `STRATEGY_INTERVAL` (60s) from a possibly 30s-cached price; if the process dies, there is **no** protection. Long-term: place exchange-side stop orders where supported, or at least document the exposure prominently.
- **M7. Money as `float`.** Fine for a €10-a-position hobby bot; a known correctness ceiling. Prefer `Decimal` at order-construction boundaries (pairs with H4).

---

## 3. Improvement Plan

Phased so each phase lands independently and the repo is releasable after every phase. Order matters: safety first, then trust the numbers, then make the strategy smarter.

### Phase 0 — Make real-money mode safe *(do before anything else; ~1 day)*

> Also protects existing users: until released, the README should carry a warning not to use `trader trade`.

- [x] **0.1 Fix full-balance sell** — `market.py::test_trade`: parse the buy order's `filledAmount` and sell exactly that. Add unit test: prior balance 1,000 units + test buy of 30 → sell order must be 30.
- [x] **0.2 Gate the real test trade** — new `--test-trade` flag; default startup does a read-only check (`time()`, `balance()`, `markets()`). Update README.
- [x] **0.3 Stop DB cross-contamination** — `EnhancedStrategy`: accept a single `trade_store`; write to `TradeDatabase` **only** when no virtual wallet is present (`main.py` passes the right one). Add regression test: virtual-mode buy leaves `trades.db` untouched.
- [x] **0.4 Record actual fills** — parse `fills`/`filledAmount`/`feePaid` from order responses (virtual response at [virtual_market.py:136-154](../../src/trader/virtual_market.py#L136-L154) already fakes this shape — good); persist fill price, amount, fee, order ID. Schema: add `fee`, `order_id` columns (additive `ALTER TABLE`).
- [x] **0.5 Graceful shutdown** — `threading.Event` shared by strategy loop, rescan thread, TUI quit handler + `SIGINT`/`SIGTERM` handlers. Strategy checks the event between markets; order-place + DB-record are never separated by a check.
- [x] **0.6 Startup reconciliation (real mode)** — compare DB positions to `get_balance()`; on mismatch log a table and exit unless `--force`.
- [x] **0.7 Floor order amounts** — replace `round()` with `Decimal` floor-to-increment; test the round-up case explicitly.

### Phase 1 — Trustworthy numbers & green tests *(~1–2 days)*

- [x] **1.1 Central Bitvavo response validation** — `_check_response()` in `bitvavo.py` applied by every `MarketOperations` call; error dicts → typed exceptions; test with canned error payloads.
- [x] **1.2 Fix Sortino/Sharpe NaN** (H3) + unit tests for all-positive, all-negative, empty, and constant return series.
- [x] **1.3 Quarantine live-API tests** — `pytest.ini` with `markers = integration`, `addopts = -m "not integration"`; mark the 4 files; point their DB paths at `tmp_path`. Suite must pass offline on a clean checkout.
- [x] **1.4 Portable SQL** in `virtual_wallet.record_sell` (H5) and FK-linked trade/position rows (H6).
- [x] **1.5 Single source of truth for strategy thresholds** — move RSI/MACD/BB thresholds into `TradingStrategyConfig` (env-overridable, like SL/TP already are); fix the Signal-2 log line and README to match code.
- [x] **1.6 Packaging** — `pyproject.toml` (deps, `requires-python = ">=3.10"`, entry point), delete `setup.py`, drop `pytz`/`sqlalchemy`/`typing-extensions`, pin versions, add a constraints/lock file.
- [x] **1.7 CI** — GitHub Actions: `ruff check` + `ruff format --check` (replaces black/flake8/isort with one tool) + `pytest -m "not integration" --cov`. Badge in README.

### Phase 2 — Risk management & a backtester you can believe *(~3–5 days; aligns with FEATURE_ROADMAP "Critical Priorities")*

- [x] **2.1 Portfolio safeguards** — daily loss limit and max-drawdown halt (config: `MAX_DAILY_LOSS_PCT`, `MAX_DRAWDOWN_PCT`); when tripped: close nothing automatically, stop opening, alert loudly.
- [x] **2.2 Wire market re-selection to the rescan** (H7) — after each rescan, rotate out selected markets with no open position; never drop a market holding a position.
- [x] **2.3 Honest backtester** — strategies receive prices instead of fetching them (fixes H2); simulate through `VirtualWallet` with configured fees; support cached/offline candle data beyond the 1,440-candle API cap; report Sharpe/max-DD/win-rate so parameter changes (like the recent RSI 55→50) are evidence-based instead of vibes-based.
- [x] **2.4 Crash-resilient stops** — investigate Bitvavo `stopLoss` order support; fall back to documented exposure + reconciliation on restart.

### Phase 3 — Architecture & observability *(incremental, as touched)*

- [ ] **3.1 Explicit interface** — a `Protocol` (e.g. `ExchangeOperations`) that both `MarketOperations` and `VirtualMarketOperations` satisfy; mypy in CI enforces it.
- [ ] **3.2 Decompose `main.py`** (M3) and inject one shared `TradeDatabase` (M4).
- [ ] **3.3 Notifications** — pluggable alert hook (Telegram/webhook) for: trade executed, SL/TP hit, safeguard tripped, reconciliation mismatch, crash.
- [ ] **3.4 Structured decision logging** — one machine-parsable line per cycle per market (indicators, signals, action) so strategy behaviour can be analysed after the fact.

### Phase 4 — Polish (only if the project keeps growing)

- Dockerfile + systemd unit docs for 24/7 operation; config validation with helpful errors (pydantic-settings); replace `pandas-ta` (unmaintained) with self-computed indicators; TUI candle chart; per-market strategy parameters.

### Explicitly NOT recommended (YAGNI)

- Multi-exchange support, async rewrite, web dashboard, ML-based signals — the roadmap's "Advanced Features" section already lists some of these; none are worth it before Phases 0–2 make the current single-exchange loop safe and measurable.

---

## 4. Suggested first PR

Phase 0 alone (items 0.1–0.7) is one focused PR (~300 lines with tests) and removes every known way this bot can lose money *by accident* rather than by strategy. Items 0.1 + 0.3 are the two bugs I'd fix within the hour if real trading were imminent.
