# CLAUDE.md

This file is read fresh at the start of every coding session. It is the
code-phase equivalent of `trading-bot-spec-v6.md` — the source of truth
for how to work in this repo, not what to build (that's the spec).

**If this file and chat history disagree, this file wins.** Update it
whenever a real decision is made during a coding session — don't rely on
conversation history to carry context forward.

---

## What this project is

Automated crypto day-trading bot. BTC/USD + ETH/USD, 9/21 EMA crossover on
1h candles, ATR-based exits, trend-following. Starting on $100 paper-proven
test capital via Alpaca. Full architecture: `trading-bot-spec-v6.md`.
Process/session discipline: `session-playbook-v6.md`. Both live in project
knowledge — read them if this file references something you need more
detail on.

## Current status

**Milestone: backtest / signal-validation (spec §2, playbook v6 §7) —
IN PROGRESS, not complete, no decision locked yet.**

`src/config.py`, `src/halt_state.py`, `src/signal_generation.py` (EMA/ATR/
volume + long-only crossover detection), `src/data_ingestion.py`'s
historical fetch (`fetch_historical_candles`, via Alpaca crypto market
data), `scripts/backtest.py`, and `scripts/backtest_trend_filter.py` are
real and working, with passing tests. Everything else in `src/` is still
a stub with a docstring pointing to the spec section it implements —
`execution.py`, `position_management.py`, `risk_filter.py`'s real checks,
and `data_ingestion.py`'s live fetch are untouched.

### Findings so far (2026-08 session, spans several rounds)

1. Baseline 9/21 EMA crossover + volume confirmation, fee-aware (Alpaca
   0.25%/leg taker + 5bps/leg slippage placeholder), is net-negative on
   both BTC/USD and ETH/USD across every ATR multiplier tested
   (1.5x-3.0x), at every timeframe tested (1h, 4h, daily), over the full
   available history (2021-01-03 → present, ~5.6 years).
2. Ruled out: insufficient data, a bad/unrepresentative time window, and
   a signal-generation bug. An independent, from-scratch daily sanity
   check (`scripts/sanity_check_daily_signal.py`, deliberately not
   reusing any of `backtest.py`'s logic) confirmed the crossover/volume
   logic — 17 vs. 19 signals, with the gap fully explained by
   day-boundary alignment, not a bug.
3. Root cause identified: gross-of-fees returns are roughly flat-to-weak
   *everywhere* (best result found: BTC daily +3.44% gross over 5.5yr) —
   this is a genuine weak/absent edge in the bare crossover, not
   primarily a fee-drag artifact, though fee drag does compound it badly
   at 1h (net -38% to -52% on ~300-380 trades/symbol over the full
   history).
4. Tested a higher-timeframe trend filter (daily 50-SMA and daily 200-SMA)
   on top of the 4h signal (`scripts/backtest_trend_filter.py`): daily-200
   is untestable with the current validation window — price stayed below
   it for the entire 180-day holdout (zero trades, not disproven). Daily-50
   shows partial, thin improvement (BTC calibration losses roughly halved;
   ETH 2 of 4 ATR variants turn slightly net-positive in validation), but
   sample sizes (5-8 validation trades) are too small to call validated.
5. Built a 5-fold anchored walk-forward harness (`scripts/
   backtest_walkforward.py`) to get past finding 4's thin sample size —
   ~1yr initial training window, then 5 contiguous ~1yr test folds across
   2022-01-03 → 2026-08-06, same daily-50 filter/fee model/ATR sweep
   unchanged. Result: **daily-50 filter does NOT clear the adopt bar**
   (pooled net-of-fees positive AND ≥4/5 folds positive). Every symbol ×
   ATR-multiplier combo (8 total) had a negative pooled net-of-fees
   return. Best cases: BTC 1.5x (pooled net -4.77% on 37 trades, gross
   +0.66%, 2/5 folds positive) and ETH 3.0x (pooled net -1.93% on 37
   trades, gross +2.19%, 4/5 folds positive — majority-positive but
   pooled still net-negative, so still fails). Fee drag consistently
   turns a roughly-flat-to-weakly-positive gross result net-negative,
   consistent with finding 3. Fold 3 (2023-11-04→2024-10-04) was the
   worst fold for both symbols, especially ETH (-5.6% to -7.8% net on
   most ATR variants) — a possible adverse-regime concentration worth
   flagging, not investigated further this session. Fold 5 (most recent
   ~1yr) sat 81-84% below the daily-200 SMA for both symbols, consistent
   with finding 4's daily-200 holdout result. Per-fold trade counts
   (5-10) are still thin individually, but pooled counts (32-43 per
   combo) are a real improvement over finding 4's 5-8.
6. New strategy family: Donchian channel breakout (long AND short,
   `close` vs. prior-N-day highest-high/lowest-low) with an ATR
   trailing-stop exit (not a fixed opposite-band exit), replacing the
   crossover family after finding 5. Built `scripts/backtest_donchian.py`
   and ran the full pre-registered grid — channel N ∈ {20, 55}d, ATR
   trail multiple ∈ {2.0x, 2.5x, 3.0x}, BTC/USD + ETH/USD, same fee model
   and same 5-fold walk-forward boundaries as finding 5, unchanged — 12
   combos. Raw pooled net-of-fees / gross-of-fees / folds-net-positive:
   BTC 20d/2.0x +2.38%/+7.30%/3-5, 20d/2.5x -4.14%/-0.68%/2-5,
   20d/3.0x -3.98%/-1.44%/3-5, 55d/2.0x +2.53%/+5.11%/3-5,
   55d/2.5x +0.17%/+2.03%/2-5, 55d/3.0x +2.02%/+3.40%/3-5. ETH
   20d/2.0x +15.23%/+18.87%/5-5, 20d/2.5x +7.75%/+10.28%/3-5,
   20d/3.0x +11.56%/+13.38%/4-5, 55d/2.0x +17.84%/+19.72%/5-5,
   55d/2.5x +11.87%/+13.19%/5-5, 55d/3.0x +11.10%/+12.15%/5-5. ETH results
   are notably stronger than anything seen in findings 1-5, but several of
   the best combos (55d channel especially) run on only 3-8 trades/fold —
   a sample-size caveat, not yet independently verified. **No adopt/reject
   verdict has been rendered on this — the requesting session explicitly
   asked for raw numbers only, decision deferred to the user/spec chat.**
7. Finding 6 simulated shorts, but Alpaca doesn't support short-selling
   crypto — so those numbers aren't directly tradeable. Added a
   `--long-only` flag to `scripts/backtest_donchian.py` (gates out
   `short_indices` at the call site; `simulate_donchian()` and
   `slice_trades_by_folds()` untouched) and reran the same 12-combo grid,
   long-only. Raw pooled net-of-fees / gross-of-fees / folds-net-positive:
   BTC 20d/2.0x +4.56%/+7.48%/2-5, 20d/2.5x +2.53%/+4.67%/2-5,
   20d/3.0x +0.62%/+2.25%/2-5, 55d/2.0x +3.80%/+5.37%/2-5,
   55d/2.5x +3.48%/+4.57%/2-5, 55d/3.0x +3.55%/+4.33%/2-5. ETH
   20d/2.0x +8.77%/+10.77%/3-5, 20d/2.5x +4.86%/+6.29%/3-5,
   20d/3.0x +6.10%/+7.22%/3-5, 55d/2.0x +8.62%/+9.62%/3-5,
   55d/2.5x +5.67%/+6.37%/3-5, 55d/3.0x +7.35%/+7.90%/3-5. Every long-only
   pooled net% stayed positive (unlike finding 5's crossover work), but
   trade counts dropped sharply from finding 6 — BTC 55d combos in
   particular are now critically thin: fold 1 has only 1 trade and fold 5
   only 1-2 trades, for every BTC 55d/ATR combo. ETH 55d combos are
   similarly thin (fold 1: 2 trades, fold 5: 1 trade, across all three ATR
   multiples). 20d combos are healthier (BTC 4-11/fold, ETH 3-6/fold) but
   still thinner than finding 6's both-directions numbers. **No
   adopt/reject verdict rendered — raw numbers only, per instruction.**
   **UPDATE (separate planning chat, post-session): formally REJECTED.**
   Every pooled net return was positive, but the folds-consistency leg of
   the pre-committed adopt bar never cleared on any of the 12 combos (BTC
   2/5 folds positive on all six combos, ETH 3/5 on all six) — same
   failure mode as the EMA crossover in finding 5. Donchian breakout
   (long-only) is now a closed line, same status as the crossover family.
8. New strategy family: MACD(12,26,9) daily-regime + hourly-entry
   ("D1H1"), long-only, price-action trailing-stop exit (hold while each
   new hourly candle closes green; exit at the close of the first that
   closes red) — replacing Donchian long-only after finding 7's rejection.
   Added `compute_macd()` to `src/signal_generation.py` and built
   `scripts/backtest_macd_d1h1.py`; ran BTC/USD and ETH/USD through the
   same 5-fold anchored walk-forward harness, fee model, and fold-boundary
   function as findings 5-7 (2021-01-03 → present), unchanged — this is a
   single fixed-rule strategy, not a parameter grid (MACD 12/26/9 is the
   standard convention, not tuned this round). Raw pooled net-of-fees /
   gross-of-fees / folds-net-positive: BTC -67.06%/+7.84%/0-5 (790 pooled
   trades), ETH -66.87%/+3.05%/0-5 (756 pooled trades). Per-fold trade
   counts are large and none are thin this time (BTC 133-174/fold, ETH
   134-162/fold), but win rates are low (8.0-16.0%) — exiting on the very
   first red hourly candle is a tight, high-frequency exit rule, and fee
   drag on that much turnover turns a roughly-flat-to-weak gross edge
   sharply net-negative (same fee-drag mechanism as finding 3, far more
   pronounced here because of trade frequency). Confirmed: the daily
   regime is evaluated once per calendar day off the most recently fully
   closed daily candle (causal lag `i // 24 - 1`, same pattern finding 4's
   SMA filter already used), never recomputed intraday — this alignment
   property has explicit test coverage
   (`test_hourly_index_maps_to_prior_daily_index_and_is_constant_within_a_day`
   in `tests/test_backtest_macd_d1h1.py`), not just asserted. Judgment
   calls (flagged, not self-adjudicated — full detail in the module
   docstring): (a) position sizing has no natural stop-distance to size a
   1%-risk position off, since the exit is price-action-based with no
   fixed initial stop — sized flat at `max_position_pct` (25% of equity)
   instead; `r_multiple` on each trade is a nominal scorecard against the
   standard 1%-of-equity risk amount, not tied to actual sizing. (b) Fold
   boundaries used the same `compute_fold_boundaries()` call/params/
   dataset as findings 5-7, but anchored off the hourly candle series'
   actual start/end (the primary traded timeframe here) rather than a
   resampled daily/4h series — can only shift boundaries by a sub-day
   amount out of 5.6 years, but flagged rather than silently decided.
   Dual-timeframe ingestion turned out not to need new fetch
   infrastructure: `resample_candles(hourly, 24)` (already used by
   findings 4-7) gives the daily series for free from the same hourly
   fetch. **No adopt/reject verdict rendered — raw numbers only, per
   instruction; decision deferred to the planning chat.**
   **UPDATE (separate planning chat, post-session): formally REJECTED.**
   Both symbols failed on both legs of the adopt bar — pooled net-of-fees
   sharply negative (BTC -67.06%, ETH -66.87%) despite mildly positive
   gross (+7.84% / +3.05%), and 0/5 folds net-positive on either symbol.
   Root cause: severe fee drag from the high-turnover price-action exit
   (exiting on the first red hourly candle), not a fold-consistency
   near-miss like findings 5/7 — this is a clearer, harder rejection than
   either prior closed line. MACD D1H1 is now a closed line alongside the
   EMA crossover and Donchian breakout (long-only).

### Code state

`scripts/backtest.py` (baseline signal + fee model + calibration/
validation split + `--candle-hours` resampling), `scripts/
backtest_trend_filter.py` (SMA filter variant, reuses `backtest.py`'s
trade mechanics unchanged via `simulate()`'s `precomputed_signals`
override), `scripts/backtest_walkforward.py` (5-fold anchored
walk-forward harness, reuses `backtest.py`'s `simulate()`/`summarize()`
and `backtest_trend_filter.py`'s daily-50 filter unchanged — only adds
`compute_fold_boundaries()` and `run_multi_fold_walk_forward()`),
`scripts/backtest_donchian.py` (Donchian breakout + ATR trailing stop —
long+short, new trade-simulation loop `simulate_donchian()` since the
crossover family's `simulate()` is long-only with a fixed stop/TP and
can't express a trailing stop; imports `compute_fold_boundaries()`
unchanged but does NOT call `run_multi_fold_walk_forward()`, since that
function is hardwired to call `simulate()` — instead duplicates its
fold-slicing/pooling logic as `slice_trades_by_folds()`, same approach,
parallel code, documented in the module docstring; also has a
`--long-only` flag, added for finding 7, that empties `short_indices`
at the call site — `simulate_donchian()`/`slice_trades_by_folds()`
unchanged, default behavior with no flag still reproduces finding 6),
`scripts/backtest_macd_d1h1.py` (MACD D1H1 — daily-regime filter +
hourly-entry + price-action trailing-stop exit; new indicator
`compute_macd()` added to `src/signal_generation.py`; new trade-
simulation loop `simulate_macd_d1h1()` since neither `simulate()` nor
`simulate_donchian()` can express a dual-timeframe entry gate or a
price-action exit; imports `compute_fold_boundaries()` unchanged but
duplicates fold-slicing/pooling as its own `slice_trades_by_folds()`,
same approach and rationale as `backtest_donchian.py`'s copy — see finding
8 and the module docstring for the judgment calls made), `scripts/
sanity_check_daily_signal.py` (independent one-off check, not meant to be
maintained). No `.env` or locked spec parameters touched. Nothing merged
or promoted — still `paper` branch working state.

### Not yet decided (blocks next steps)

Three strategy families are now closed/rejected: the EMA crossover
(+ daily-50 SMA filter, finding 5 — does not clear the adopt bar), Donchian
breakout long-only (finding 7 — pooled returns positive but
folds-consistency never clears), and MACD D1H1 (finding 8 — pooled
net-of-fees sharply negative on both symbols, 0/5 folds positive on
either, severe fee drag from the high-turnover price-action exit).

**Next milestone (from the planning chat, not yet started): regime-
filtered mean-reversion.** Daily entry when RSI(14) < 30, gated by a
price-above-200-day-SMA regime filter (same "regime filter" shape as
finding 4/8's daily filters, but now a mean-reversion entry instead of a
trend-following one). Exit at RSI(14) > 50 OR a 10-day time-stop,
whichever comes first. No code has been written for this yet this
session — do not start it without a fresh scoped brief confirming fee
model, fold boundaries, and RSI period/thresholds are locked (same
reuse-unless-flagged approach as findings 6-8).

### Pre-coding checklist state

**Not cleared for a new coding milestone.** Per this file's own
convention (a session's "Done" = tests passing + code committed +
spec/playbook updated *on an actual decision*), no decision was locked
this session — so `session-playbook-v6.md`'s pre-coding checklist should
be treated as not satisfied until the open decision above is resolved
elsewhere. Don't start `execution.py` or any other new milestone without
checking for updated guidance first.

### Blocked/pending, unrelated to backtest

`execution.py`'s OCO-fallback design is still waiting on the signal
decision above before it makes sense to start — on top of its own
separate crypto bracket-order design gap (see "Hard rules" below).

**Next milestone:** regime-filtered mean-reversion (RSI(14) < 30 daily
entry, price-above-200-SMA regime filter, exit at RSI > 50 or a 10-day
time-stop) — named in the planning chat, not yet started. Confirm a
scoped brief before beginning.

## Hard rules — never do these

- **Never commit directly to `main`.** All work happens on `paper` or a
  feature branch off it. `main` is only updated through the promotion
  pipeline (spec §3.3): automated tests + soak period + Telegram approval.
- **Never remove or weaken a guardrail check** in `risk_filter.py` without
  an explicit, current instruction to do so in the session. The numbers in
  `.env` (1% risk/trade, 25% max position, 3% daily loss, 6 trades/day cap,
  1.5% combined open-risk, 10% max drawdown) are locked decisions (spec
  §4.1–4.3) — treat them as load-bearing, not tunable defaults.
- **Never let a promotion to `main`/live happen without the Telegram
  approve step.** Even if paper results look great. No auto-merge, no
  timeout-based promotion.
- **Never commit `.env` or any real credential.** `.gitignore` already
  excludes it; `.env.example` is the documented template with blanked
  values. If you ever need to add a new required env var, add it to
  `.env.example` too, in the same commit.
- **Never implement `execution.py`'s order placement** until the crypto
  bracket-order design gap (documented in that file's docstring) is
  resolved and folded into the spec. Alpaca doesn't support bracket/OCO
  orders for crypto — only market/limit/stop_limit. The fallback
  (software-emulated OCO) needs to be locked in before this module is
  built for real, not improvised mid-session.
- **Never auto-resume trading after a crash/restart.** `halt_state.py`
  must be checked on every boot; if halted, stay halted until a human
  clears it via Telegram. This mirrors the "restart ≠ resume" rule that's
  also locked for the DigitalOcean droplet itself (spec §2, §4.5).

## Coding conventions

- One coding session = one milestone, scoped to a single pipeline stage
  (spec §3.1: data ingestion → signal generation → risk filter → execution
  → position management; then §3.2 journaling/governance; then §3.3
  promotion pipeline). Don't sprawl across stages in one session.
- Every module's docstring should reference the spec section it implements
  (see existing stubs for the pattern) — this keeps code and spec
  traceable to each other without needing chat history.
- Commit frequently, in small working units. A session that loses context
  partway through should cost nothing — the next session picks up from
  `CLAUDE.md` + `git log` + current file state.
- "Done" for a session = tests passing + code committed +
  (`trading-bot-spec-v6.md` or `session-playbook-v6.md` updated, if an
  actual decision was made, not just an implementation detail).

## Environment

- `TRADING_ENV` in `.env` controls paper vs. live — one codebase, config
  difference only (spec §2, v6). Never fork logic on this; branch on the
  flag inside `config.py`-derived values if behavior must differ.
- Default assumption for any session unless told otherwise: **you are
  working against paper**, never live, regardless of what's technically
  possible with the credentials present.

## Division of labor (session-playbook-v6.md §8)

Claude Code executes directly in this repo: writes code, runs tests,
handles git add/commit/push, opens PRs from `paper`. The human's role is
approvals only — reviewing/merging PRs into `main`, and Telegram
approve/reject for the promotion pipeline. Propose and execute freely
within the guardrails above; anything that crosses one of the "never do
this" rules requires an explicit, current go-ahead first.
