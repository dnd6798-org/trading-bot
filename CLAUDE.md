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

**NOTE (2026-08 session, finding 10): the BTC/USD + ETH/USD-only universe
described above is being reopened** — see "Current status" and finding 10
below. Treat the 2-asset scope as under active revision, not settled,
until the new milestone lands.

## Current status

**Milestone: finding 11's 10-asset rotational Donchian ensemble was
formally REJECTED** (pooled net-of-fees -11.11%, 2/5 folds net-positive,
not close on either leg of the adopt bar). Root cause diagnosed in the
planning chat: a redundant 20d/55d OR-entry that silently ran as a bare
20-day system, a 4-slot cap that bound harder than the reference design's
own limits, and two universe symbols (ADA/PEPE) with too little history
to participate. **Finding 12, IN PROGRESS: a bounded, one-time redesign
retry** — single 55-day channel, 8-slot cap at 12.5%/slot, ADA/PEPE
dropped and backfilled with two full-history replacements. If finding 12
also fails the bar, no further breadth iteration is planned without a
fresh instruction — next step would be a broader planning-chat
conversation, not another variant. See finding 11's UPDATE and finding 12
below for full detail.

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
9. New strategy family: RSI(14) regime-filtered mean-reversion, daily
   candles, long-only — replacing MACD D1H1 after finding 8's rejection,
   and the first mean-reversion strategy tried in this repo (findings 1-8
   were all trend-following). Entry: RSI(14) on daily candles crosses down
   below 30, gated by a daily-200-SMA regime filter (close above the SMA
   at entry — restricts entries to dips within an uptrend, per the
   session's brief, a from-the-start design choice referencing external
   research on why naive mean-reversion fails, not a filter added after
   seeing results). Exit: RSI(14) reverts above 50 OR a 10-day time-stop,
   whichever comes first — a third, distinct exit philosophy from the ATR
   fixed stop/TP (findings 1-7) and finding 8's price-action trailing
   exit, implemented as its own function (`resolve_exit()`) per
   instruction, kept separate from the trade-simulation loop. Added
   `compute_rsi()` to `src/signal_generation.py` and built `scripts/
   backtest_rsi_meanreversion.py`; ran BTC/USD and ETH/USD through the
   same 5-fold anchored walk-forward harness and fee model as findings
   5-8 (2021-01-03 → present), unchanged — fixed-rule strategy, not a
   parameter grid (RSI(14)/30/50/200-SMA/10-day are the specified
   parameters, not tuned this round).

   **Result: signal starvation, not a fee-drag or edge-quality result.**
   Raw daily RSI<30 cross-downs over the full 5.6yr history: BTC 25, ETH
   28 (days at the RSI<30 *level*, not just the cross: BTC 82, ETH 98).
   But requiring the joint condition (cross-down AND close above the
   daily-200 SMA) collapses this to BTC 5 raw signals, ETH 0. Days above
   the 200-SMA are roughly a coin flip on their own (BTC 53.0%, ETH 47.6%
   of the 1,842-day seeded history) — the scarcity isn't the regime filter
   being restrictive in general, it's that severe/sharp oversold RSI
   dips specifically cluster in the *below*-200-SMA regime (genuine
   bear-market drawdowns), not as pullbacks within uptrends. Confirmed via
   a standalone diagnostic against the real fetched data, not just the
   backtest's own trade count.

   BTC pooled net-of-fees / gross-of-fees: +3.25% / +3.72% on 3 pooled
   trades, 1/5 folds net-positive, 2/5 net-negative, 2/5 no trades at all.
   Per-fold: fold 1 0 trades; fold 2 1 trade, 100% win, rsi_revert exit,
   net +5.57%; fold 3 1 trade, 0% win, time_stop exit, net -1.59%; fold 4
   1 trade, 0% win, time_stop exit, net -0.61%; fold 5 0 trades. ETH: 0
   trades in every fold and pooled — the joint entry condition never
   fired once across 5.6 years of ETH daily data.

   3 trades (BTC) and 0 trades (ETH) over 5.6 years is far too thin to
   support any conclusion about edge, positive or negative — not
   comparable to findings 5-8's much larger pooled trade counts, and this
   result should be read as "insufficient sample size," not as evidence
   for or against the underlying rule. Judgment calls (flagged, not
   self-adjudicated — full detail in the module docstring):
   (a) Entry implemented as a downward RSI *cross* (RSI[i-1]>=30,
       RSI[i]<30), not a bare "RSI<30" level check — matches the brief's
       "drops below 30" language and the crossing convention every other
       entry signal in this repo already uses. A level check would allow
       more raw signals (the 82/98 level-day counts above) but wasn't
       what was specified.
   (b) Position sizing has the same gap as finding 8 — no natural
       stop-distance for the spec §4.1 1%-risk formula, since this exit
       is RSI-level/time-based, not price-based. Sized flat at
       `max_position_pct` (25% of equity), identical resolution to
       finding 8; `r_multiple` is a nominal scorecard only, not tied to
       actual sizing.
   (c) Fold boundaries anchored off the daily candle series directly —
       this strategy trades daily bars only, so there's no dual-timeframe
       anchor ambiguity the way finding 8 had to flag.
   (d) The 10-day time-stop is read as 10 daily candles ("trading days"),
       consistent with how findings 4 and 8 already treat one daily
       candle as one trading day for 24/7 crypto.
   **No adopt/reject verdict rendered — raw numbers only, per instruction;
   decision deferred to the planning chat. Given the near-zero trade
   count, the planning chat may want "insufficient sample size to
   evaluate" as a distinct outcome from adopt/reject.**
10. **Step back further** (separate planning-chat review, not a new
    backtest — no code written for this entry). After finding 9 left RSI
    mean-reversion inconclusive rather than cleanly rejected, a review
    across findings 5, 7, 8, and 9 identified a common structural gap:
    every one of those families shared a fixed 1-2 asset universe
    (BTC/USD + ETH/USD only), not necessarily a bad indicator each time.
    Research reviewed — the Zarattini/Pagani/Barbon SFI paper on crypto
    trend-following, and Man Group institutional research — points at
    portfolio breadth (trading a basket of 10-15 liquid coins, not 1-2)
    as the mechanism that clears crypto's transaction-cost hurdle for
    trend-following: enough uncorrelated entries/exits in flight that fee
    drag stops dominating a thin trade count, the failure mode common to
    findings 1, 3, 5, 7, and 8. **This reopens the BTC/USD +
    ETH/USD-only universe locked since the original spec — the user has
    explicitly signed off on this scope change.** This does not reverse
    any prior adopt/reject verdict (findings 5, 7, 8 stay rejected on
    their own terms; finding 9 stays inconclusive) — it's a scope
    decision for what gets tested next, not a re-litigation of what's
    already closed.

    **NEW MILESTONE, IN PROGRESS: pivot to a 10-asset rotational Donchian
    ensemble.** No code written yet this session. New infrastructure
    needed, nothing in the codebase currently handles either:
    (a) multi-symbol data ingestion — `data_ingestion.py`'s
        `fetch_historical_candles`/`TRADING_PAIRS` are BTC/ETH-only today;
    (b) rotational position-slot management, capped at 4 concurrent
        positions across the 10-asset universe.

    **Known future blocker, explicitly NOT this milestone:** the existing
    correlation / open-risk-budget guardrail (spec §4.3) was designed for
    a 2-asset universe and does not generalize to 10 assets. Does not
    block backtesting this milestone — a simple 4-position-cap
    placeholder is used instead — but WILL block any live-trading
    promotion of this strategy family until the guardrail is redesigned.
    Do not attempt to solve this now; flagged for awareness only.
11. **10-asset rotational Donchian ensemble** (finding 10's milestone,
    executed). Two parts:

    **Universe selection** — `scripts/select_universe.py` (one-off, not
    meant to be maintained), queried Alpaca's live `/v2/assets?
    asset_class=crypto` (38 active tradable USD pairs) and ranked 31
    non-stablecoin candidates by trailing-30-day average daily dollar
    volume, computed from real fetched hourly candles (not a training-
    data guess). **Caveat flagged and confirmed real, not a units bug:**
    this volume is Alpaca's own crypto-venue order flow, not aggregated
    global market volume (Alpaca runs its own crypto exchange) — BTC/USD
    showed ~$94k/day on this measure, ETH/USD ~$39k/day. Arguably the
    right number to rank on anyway (it's the liquidity the bot would
    actually trade against), but flagged since it reads oddly low next to
    global BTC volume. Top 8 non-stablecoin, non-BTC/ETH by this measure:
    XRP/USD, SOL/USD, UNI/USD, AVAX/USD, AAVE/USD, LINK/USD, PAXG/USD,
    PEPE/USD. **User adjustment after review:** PAXG/USD (Pax Gold, a
    gold-tracking token, not stablecoin-classified so not auto-excluded)
    was hand-swapped out for the next-ranked candidate, ADA/USD — PAXG
    tracks gold spot price, not crypto market dynamics, which breaks the
    premise of a crypto trend ensemble despite being liquid. **Locked
    final universe (10 symbols):** BTC/USD, ETH/USD, XRP/USD, SOL/USD,
    UNI/USD, AVAX/USD, AAVE/USD, LINK/USD, ADA/USD, PEPE/USD.

    **Signal** — long entry on daily close breaking above the 20-day OR
    55-day causal Donchian high; exit ATR trailing stop fixed at 2.5x
    (finding 7's middle grid value) — fixed rule, not a parameter grid.
    **MATH NOTE, flagged not self-resolved:** because a causal 55-day
    window always contains the most recent 20 days as a subset, the
    55-day leg is provably redundant — "close > upper_20 OR close >
    upper_55" is mathematically identical to "close > upper_20" alone at
    every index, confirmed both analytically and by a dedicated test
    (`test_dual_channel_entry_55d_leg_never_adds_signals_beyond_20d_leg`
    in `tests/test_backtest_donchian_ensemble.py`). Implemented literally
    (both bands computed, OR'd) per the specified rule rather than
    silently simplified to a 20-day-only signal.

    **Portfolio construction** — rotational, capped at 4 concurrent open
    positions across the 10-symbol universe, backed by a SHARED $100
    capital pool (a deliberate difference from findings 6-9, which
    backtested each symbol independently against its own full $100 — here
    the real account only has $100 total, and the 4-slot cap is standing
    in for the not-yet-generalized cross-symbol risk guardrail, spec
    §4.3). New signals beyond the 4-slot cap are skipped and logged, not
    queued. Position sizing reuses finding 7's formula (1% equity risk /
    2.5x ATR stop distance, capped at 25% notional), applied per-asset off
    the shared equity value at the moment each position opens — no
    portfolio-level vol-targeted sizing this round, per instruction.
    Exits are processed before entries within each simulated day so a
    slot freed by an exit can be reused by a new entry the same day
    (verified by a dedicated test). Slot-fill priority when multiple
    signals cluster on the same day: fixed universe-list order (BTC, ETH,
    then the 8 ranked-liquidity symbols) — an arbitrary, flagged
    tie-break, not signal-strength ranked.

    **New infrastructure:** `scripts/backtest_donchian_ensemble.py` — new
    `EnsembleTrade` dataclass (adds a `symbol` field); new
    `simulate_rotational_ensemble()`, a day-by-day portfolio loop over a
    shared calendar built from the UNION of each symbol's available
    dates, since several universe symbols have far shorter Alpaca history
    than BTC/ETH's 2021-01-03 start: XRP/USD from 2024-01-01, AVAX/USD
    from 2021-11-18, AAVE/USD from 2021-07-15, PEPE/USD from 2025-01-29,
    and ADA/USD from only 2026-02-13. ADA/USD (175 daily candles) and
    PEPE/USD (554) are markedly thinner than the rest of the universe
    (BTC/ETH ~2042) — a real data-availability constraint, flagged, not a
    bug. Reuses completely unchanged: `compute_donchian_levels()`
    (`backtest_donchian.py`), `compute_atr()` (`signal_generation.py`),
    `resample_candles()`/`summarize()`/`_print_table()`/fee constants/
    position-sizing constants/`ATR_PERIOD` (`backtest.py`),
    `compute_fold_boundaries()` (`backtest_walkforward.py` — same 5-fold,
    365-day-anchor, 2021-01-03 setup as findings 5-9, dates unchanged).

    **Fold-slicing judgment call, flagged** (methodology only — the fold
    BOUNDARY DATES from `compute_fold_boundaries()` are untouched): because
    up to 4 positions can be open concurrently, trade entry order and
    exit/equity-realization order can diverge — impossible in every
    single-position-at-a-time script (findings 1-9), where entry order,
    exit order, and equity-curve order are always identical. The existing
    `slice_trades_by_folds()` pattern silently assumes trades are
    list-ordered by `entry_timestamp`, matching their equity-curve
    position — true everywhere else, false here. This script's
    `slice_ensemble_trades_by_folds()` buckets by `exit_timestamp`
    instead, matching how `trades`/`equity_curve` are actually built
    (equity only moves at trade close) — confirmed by a dedicated test
    (`test_slice_ensemble_trades_by_folds_buckets_by_exit_not_entry_
    timestamp`) using a trade that enters in fold 1's window but exits in
    fold 2's, proving it lands in fold 2.

    **Result — portfolio-level, 5-fold anchored walk-forward
    (2022-01-03 → 2026-08-06 pooled test window, same boundaries as
    findings 5-9):** pooled net-of-fees **-11.11%**, pooled gross-of-fees
    -5.23%, **2/5 folds net-positive** (fold 2 +3.70%, fold 4 +10.68%;
    fold 1 -9.61%, fold 3 -0.95%, fold 5 -14.54%), 139 pooled trades, max
    drawdown 15.91%. 186 signals were skipped for no free slot over the
    full history (169 within the pooled test window) against 168 total
    trades taken (139 pooled) — the 4-slot cap bound often, roughly as
    many signals turned away as taken.

    Per-symbol diagnostics (pooled, informational only, not part of the
    adopt/reject bar): net-positive contributors were ETH/USD (+$5.31, 23
    trades), BTC/USD (+$4.34, 26 trades), AVAX/USD (+$3.19, 11 trades),
    XRP/USD (+$1.49, 9 trades); net-negative were SOL/USD (-$7.42, 16
    trades), AAVE/USD (-$7.05, 18 trades), LINK/USD (-$5.37, 18 trades),
    UNI/USD (-$4.43, 14 trades), PEPE/USD (-$2.16, 2 trades), ADA/USD
    (-$0.39, 2 trades). Skip counts concentrated on AVAX/USD (39),
    LINK/USD (31), AAVE/USD (29), UNI/USD (28) — turned away by the slot
    cap far more often than BTC/USD (9) or ETH/USD (4); this reflects
    slot-occupancy duration over time, not the fixed tie-break priority
    order (tie-breaks only apply among signals firing the same day).

    **No adopt/reject verdict rendered — raw numbers only, per
    instruction; decision deferred to the planning chat**, same
    convention as findings 6, 8, and 9. 7 new tests added
    (`tests/test_backtest_donchian_ensemble.py`), full suite (77 tests)
    passing.

    **UPDATE (separate planning chat, post-session): formally REJECTED.**
    Pooled net-of-fees -11.11%, pooled gross -5.23%, 2/5 folds
    net-positive against a pre-committed bar of positive pooled net-of-fees
    AND ≥4/5 folds positive — not a close call on either leg.

    **Root-cause diagnosis (completed in the planning chat by researching
    the actual mechanics of the reference design — the Turtle System
    1/System 2 structure and the SFI ensemble paper — not by re-examining
    this result after the fact):** three construction flaws.
    (1) The 20d/55d OR-combination is mathematically redundant — a 55-day
    Donchian high is always ≥ the 20-day high on the same series, so the
    55-day leg could never fire uniquely under OR logic (this repo's own
    MATH NOTE above already proved this; the planning-chat review
    confirmed it's also the actual root cause, not just a curiosity). The
    test silently ran as a bare 20-day system the entire time.
    (2) The 4-slot cap across 10 assets was tighter than the reference
    design's own per-market unit limits applied portfolio-wide, and the
    diagnostics above confirm it bound hard — 169 of 337 total signals
    were skipped for lack of a slot.
    (3) ADA (175 candles) and PEPE (554 candles) had too little history to
    meaningfully participate across a 5-fold window spanning 2022-2026.

12. **NEW MILESTONE, IN PROGRESS: redesigned rotational Donchian ensemble
    retry**, addressing finding 11's three diagnosed flaws directly, not a
    fresh strategy family:
    (1) drop the fake OR-ensemble in favor of a single clean 55-day
        Donchian channel (no 20-day leg at all);
    (2) widen the rotational cap from 4 to 8 slots at 12.5% of equity per
        slot (same 100% max gross exposure as finding 11's 4×25%);
    (3) drop ADA/USD and PEPE/USD for insufficient history and backfill
        with the next two most liquid full-history candidates from
        finding 11's ranked universe list (`scripts/select_universe.py`
        output) — exact symbols to be confirmed against actual fetched
        history depth before locking in, not assumed from the volume
        ranking alone.
    Volatility-based position sizing remains explicitly deferred — not
    part of this round.

    **IMPORTANT CONSTRAINT, binding regardless of finding 12's outcome:**
    this is a bounded, ONE-TIME retry, not an open-ended tuning loop. If
    finding 12 also fails the pre-committed portfolio-level bar, no third
    breadth iteration is planned — the next step is a broader strategic
    conversation in the planning chat, not another variant. Do not
    propose or build a finding 13 breadth variant without a fresh,
    explicit instruction to do so.

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
backtest_rsi_meanreversion.py` (RSI(14) regime-filtered mean-reversion —
daily-only, long-only; new indicator `compute_rsi()` added to
`src/signal_generation.py`; new trade-simulation loop
`simulate_rsi_meanreversion()` plus a standalone `resolve_exit()` function
for the RSI-revert-OR-time-stop exit, kept separate per instruction so all
three exit philosophies (ATR fixed, price-action trailing, RSI/time-stop)
stay independently readable; imports `compute_fold_boundaries()`
unchanged but duplicates fold-slicing/pooling as its own
`slice_trades_by_folds()`, same approach as `backtest_donchian.py`'s and
`backtest_macd_d1h1.py`'s copies — see finding 9 and the module docstring
for the judgment calls made), `scripts/select_universe.py` (one-off
universe-liquidity ranking against live Alpaca asset/volume data, not
meant to be maintained — see finding 11), `scripts/
backtest_donchian_ensemble.py` (10-asset rotational Donchian ensemble —
new `EnsembleTrade` dataclass, `simulate_rotational_ensemble()` day-by-day
portfolio loop, `slice_ensemble_trades_by_folds()` exit-timestamp-keyed
fold slicer; see finding 11 and the module docstring for the full set of
judgment calls made), `scripts/
sanity_check_daily_signal.py` (independent one-off check, not meant to be
maintained). No `.env` or locked spec parameters touched. Nothing merged
or promoted — still `paper` branch working state.

### Not yet decided (blocks next steps)

Four strategy families tested against the original BTC/USD + ETH/USD,
1-2 asset universe are closed or inconclusive on their own terms — none
of these verdicts are reversed by finding 10's scope pivot below: the EMA
crossover (+ daily-50 SMA filter, finding 5 — does not clear the adopt
bar), Donchian breakout long-only (finding 7 — pooled returns positive
but folds-consistency never clears), MACD D1H1 (finding 8 — pooled
net-of-fees sharply negative on both symbols, 0/5 folds positive on
either, severe fee drag from the high-turnover price-action exit), and
RSI(14) regime-filtered mean-reversion (finding 9 — inconclusive,
sample-starved: 3 pooled BTC trades, 0 ETH trades over 5.6 years).

Finding 10 (step-back review, see above) identified the common thread
across all four as a fixed 1-2 asset universe, not necessarily a bad
indicator each time — crypto trend-following research (Zarattini/Pagani/
Barbon SFI paper; Man Group) points at portfolio breadth (10-15 liquid
coins) as the mechanism that clears the transaction-cost hurdle. Finding
11 executed that pivot and was **formally REJECTED** (pooled net-of-fees
-11.11%, 2/5 folds net-positive) — root cause diagnosed as three
construction flaws (redundant OR-entry, over-tight slot cap, thin-history
symbols), not a rejection of the portfolio-breadth thesis itself.

**Finding 12 (in progress) is a bounded, one-time retry** fixing those
three flaws directly: single 55-day Donchian channel, 8-slot cap at
12.5%/slot, ADA/PEPE dropped and backfilled from the ranked universe
list. **If finding 12 also fails the adopt bar, no third breadth
iteration is planned** — treat that as a hard stop on this line of
attack absent a fresh, explicit instruction; the next step would be a
broader planning-chat conversation about strategy direction, not another
universe/cap/entry variant.

### Pre-coding checklist state

**Finding 11 (10-asset rotational Donchian ensemble, 4-slot/25%, 20d-OR-
55d entry) is CLOSED — rejected.** **Finding 12 (redesigned retry:
55d-only entry, 8-slot/12.5% cap, ADA/PEPE backfilled) is the active
milestone, IN PROGRESS** — universe backfill candidates need confirming
against actual fetched history depth before locking in; signal/portfolio
code changes not yet made. This is understood to be a bounded, one-time
retry per the "IMPORTANT CONSTRAINT" in finding 12 above — do not spin up
a further breadth variant if finding 12 also fails without a fresh
instruction to do so. The correlation/open-risk-budget guardrail redesign
(spec §4.3, 2-asset → 10-asset) remains explicitly OUT of scope
regardless of finding 12's outcome — do not attempt it without a
separate, current instruction.

### Blocked/pending, unrelated to backtest

`execution.py`'s OCO-fallback design is still waiting on a strategy
family reaching an adopt decision before it makes sense to start — on
top of its own separate crypto bracket-order design gap (see "Hard
rules" below). The correlation/open-risk-budget guardrail redesign
needed to generalize spec §4.3 from 2 assets to 10 (finding 10) is also
blocked/pending — not started, and explicitly not part of the current
milestone.

**Next milestone:** finding 12's redesigned rotational Donchian ensemble
retry (in progress) — see finding 12 and "Not yet decided" above. Bounded
to one attempt; no further breadth iteration planned if it also fails,
absent a fresh instruction.

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
