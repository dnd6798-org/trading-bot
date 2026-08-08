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
1h candles, ATR-based exits, trend-following. Full architecture:
`trading-bot-spec-v6.md`. Process/session discipline:
`session-playbook-v6.md`. Both live in project knowledge — read them if
this file references something you need more detail on.

**NOTE (2026-08 session, capital reframing, separate decision from the
findings below):** paper-validation notional is locked at **$10,000**
(percentage-based backtest results, including all findings below, are
unaffected by this — it does not invalidate anything already run).
Real-money go-live capital stays at **$100** for a short initial period,
but that period is explicitly for validating the *operational pipeline*
(execution, risk filters, halt/resume, promotion flow), not the strategy
itself. The project's near-term goal is now stated explicitly (spec
updated separately): validating a strategy, not generating near-term
income — $100 was never going to produce meaningful monthly income at any
realistic return rate. Treat "starting capital" language elsewhere in this
file as referring to the old $100-only framing where it hasn't been
updated yet; the $10,000/$100 split above is the current decision.

**NOTE (2026-08 session, finding 10): the BTC/USD + ETH/USD-only universe
described above is being reopened** — see "Current status" and finding 10
below. Treat the 2-asset scope as under active revision, not settled,
until the new milestone lands.

## Current status

**Milestone: finding 13 was formally REJECTED** (pooled net-of-fees
-15.22% vs. finding 12's -6.72%, pooled gross-of-fees -13.51% vs. -1.65%,
1/5 folds net-positive vs. 2/5, trade count collapsed 154→54 — worse than
finding 12 on every dimension). **Root-cause diagnosis (planning chat,
post-session): the gross-return degradation rules out fee drag as the
explanation.** The Monday-only entry gate decoupled signal-*checking* from
signal-*timing* on a fast 55-day breakout rule — a breakout that fires
mid-week is simply missed or picked up late, not deferred — causing
systematically missed/delayed entries. **This is an implementation flaw
in how "lower frequency" was tested, not evidence that lower entry
frequency is a bad idea.** Separately: trade count was so low (44-54
trades total) that neither the slot cap nor the risk budget ever bound,
so finding 13 provides **no real evidence against equal-risk-contribution
sizing itself** — that mechanism was implemented and unit-tested but never
meaningfully exercised. Verification note (already recorded, reconfirmed):
finding 12's sizing was never flat — confirmed range 2.91%-12.50% of
equity, cap binding narrowly and mostly on BTC/USD only.

**Honest context established this session, now a PERMANENT process
requirement:** across all seven strategy variants tested to date (findings
1/3, 5, 7, 8, 9, 11, 12, 13), none has beaten simple buy-and-hold on
BTC/ETH (~+100% each over the 5.6-year test window) while every active
strategy tested has been net-negative. **Buy-and-hold for the relevant
universe/period MUST be reported alongside every backtest result from now
on** — not just net/gross/folds-positive, every future finding needs a
buy-and-hold comparison line so a strategy's real bar is "beats
buy-and-hold," not just "clears the pooled-net-positive/folds-consistency
bar" in isolation.

**Milestone: finding 14 (corrected long-horizon design) was EXECUTED.**
100-day Donchian channel (up from 55-day), daily entries (reverted from
finding 13's weekly gate), 3.0x ATR trailing stop (widened from 2.5x),
finding 13's equal-risk-contribution sizing kept unchanged. **Result is
genuinely mixed, reported raw per instruction, no verdict self-rendered:**
pooled net-of-fees **+0.94%**, pooled gross-of-fees **+3.29%** — the
first finding in this whole session where the pooled net-of-fees number
is positive — but only **3/5 folds net-positive** against the
pre-committed ≥4/5 bar, so the pre-committed adopt bar is NOT cleared
(fails on the folds-consistency leg specifically, not the net-return
leg). **The strategy beats both buy-and-hold comparisons** for the same
pooled test window (10-asset equal-weighted buy-and-hold: -41.62%;
BTC/ETH-only buy-and-hold: -4.48%) — the first time any strategy tested
this session has beaten buy-and-hold on either measure. Important
clarifying note, not a contradiction: this buy-and-hold figure is for the
pooled fold TEST window only (2022-01-03 → 2026-08-07, apples-to-apples
with the strategy's own pooled number), not the "~+100%" BTC/ETH figure
quoted earlier in this file for the FULL 5.6-year history (2021-01-03 →
present) — that full-history figure includes 2021's rally, which sits in
the reserved training period and is excluded here. The fold-test-window
buy-and-hold happened to be a genuinely bad stretch for buy-and-hold (2022
bear market in fold 1, a second broad drawdown in fold 5), which is why
the strategy's modest positive result cleared it while still failing its
own internal folds-consistency bar. Per the binding constraint set at
finding 13/14's kickoff (this outcome — fails the pre-committed adopt bar
— was one of the two pre-specified branches, even though it does beat
buy-and-hold): **finding 14 is the TRUE final planned iteration on this
strategy family — no finding-15 variant should be started without a
fresh, explicit instruction. The next step is a broader strategic
conversation in the planning chat, not another backtest variant.** Full
detail, including per-fold/per-symbol numbers and the thin-fold caveat, is
in finding 14 below.

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

12. **Redesigned rotational Donchian ensemble retry (finding 11's
    milestone, executed)**, addressing finding 11's three diagnosed flaws
    directly, not a fresh strategy family.

    **Backfill symbol selection.** ADA/USD and PEPE/USD dropped
    (insufficient history — 175 and 554 daily candles). Reused
    `scripts/select_universe.py`'s ranked liquidity output, re-run this
    session (`--top-n 15`) to see candidates beyond the original top 8:
    the next four by trailing-30d dollar volume after LINK/USD were
    PAXG/USD ($4,743/day — stays excluded, gold-tracking per finding 11's
    standing judgment call), PEPE/USD and ADA/USD (being dropped), then
    SHIB/USD ($2,602/day), CRV/USD ($2,436/day), BONK/USD ($2,370/day),
    DOGE/USD ($2,294/day), WIF/USD ($1,977/day), BCH/USD ($1,792/day).
    Checked actual fetched history depth (2021-01-03 → present) for all
    six before picking, not assumed from the ranking alone: SHIB 1,241
    daily candles (from 2023-03-14), CRV 1,084 (from 2023-08-18), BONK 172
    (from 2026-02-16), DOGE 2,041 (from 2021-01-03), WIF 169 (from
    2026-02-19), BCH 2,037 (from 2021-01-03). SHIB/CRV rank higher on
    liquidity but only cover ~2-3 of the 5.6-year dataset (roughly
    half-to-60% of BTC/ETH's ~2,040-candle depth) — not "full or
    near-full" per the instruction's bar. BONK/WIF are even thinner than
    PEPE was. **DOGE/USD and BCH/USD are the highest-ranked candidates
    that also clear full-history depth** (2,041 and 2,037 candles,
    matching BTC/ETH's start date) — locked in as the two backfills.
    **Final universe (10 symbols):** BTC/USD, ETH/USD, XRP/USD, SOL/USD,
    UNI/USD, AVAX/USD, AAVE/USD, LINK/USD, DOGE/USD, BCH/USD.

    **Implementation** (`scripts/backtest_donchian_ensemble.py`, same file
    as finding 11, not a new script — repair, not a rebuild):
    (1) `compute_dual_channel_long_entry_indices()` replaced with
        `compute_channel_long_entry_indices()` — single 55-day
        `compute_donchian_levels()` call, 20-day band removed from the
        entry logic entirely (not left in as dead code). Exit unchanged:
        2.5x ATR trailing stop.
    (2) `MAX_CONCURRENT_POSITIONS` raised 4 → 8; new `SLOT_MAX_POSITION_PCT`
        (12.5%) replaces the import of `backtest.py`'s
        `DEFAULT_MAX_POSITION_PCT` (25%) as `simulate_rotational_ensemble()`'s
        sizing-cap default — 8 × 12.5% keeps the same ~100% max gross
        exposure finding 11's 4 × 25% had. Same skip-and-log behavior when
        all 8 slots are full, same per-trade risk-based sizing formula
        (finding 7's, unresized inputs otherwise), same exits-before-entries
        ordering, same universe-list-order slot-priority tie-break, same
        exit-timestamp-keyed fold-slicing — none of that infrastructure
        needed to change. 2 tests updated in
        `tests/test_backtest_donchian_ensemble.py` (function rename +
        single-channel behavior — the old dual-channel-redundancy test no
        longer applies once the 20-day leg is removed); full suite (77
        tests) still passing.

    **Result — portfolio-level, 5-fold anchored walk-forward
    (2022-01-03 → 2026-08-06 pooled test window, same boundaries as
    findings 5-11):** pooled net-of-fees **-6.72%**, pooled gross-of-fees
    -1.65%, **2/5 folds net-positive** (fold 3 +3.06%, fold 4 +11.57%;
    fold 1 -7.75%, fold 2 -5.50%, fold 5 -6.91%), 123 pooled trades (154
    total trades over the full history), max drawdown 15.27%. Only 11
    signals were skipped for no free slot over the full history (all 11
    within the pooled test window, vs. finding 11's 169) — the wider
    8-slot cap essentially stopped binding, confirming finding 11's
    diagnosis on that flaw specifically.

    Per-symbol diagnostics (pooled, informational only, not part of the
    adopt/reject bar): net-positive contributors were XRP/USD (+$5.78, 6
    trades), ETH/USD (+$5.67, 12 trades), AVAX/USD (+$3.36, 9 trades),
    BTC/USD (+$2.69, 15 trades), DOGE/USD (+$0.93, 14 trades); net-negative
    were UNI/USD (-$4.47, 14 trades), LINK/USD (-$4.61, 15 trades), SOL/USD
    (-$5.13, 11 trades), AAVE/USD (-$5.47, 14 trades), BCH/USD (-$6.30, 13
    trades) — one of the two backfill symbols (BCH/USD) landed as the
    single worst pooled contributor; the other (DOGE/USD) was mildly
    positive. Skip counts concentrated on AVAX/USD (6), AAVE/USD (4),
    XRP/USD (1) — far lower magnitude than finding 11's skip counts across
    the board.

    **No adopt/reject verdict rendered at execution time — raw numbers
    only, per instruction; decision deferred to the planning chat**, same
    convention as findings 6, 8, 9, and 11.

    **IMPORTANT CONSTRAINT, still binding regardless of the planning
    chat's verdict on this result:** this was a bounded, ONE-TIME retry,
    not an open-ended tuning loop. Do not propose or build a finding-12
    breadth variant (a third slot-cap/entry-window/universe tweak) without
    a fresh, explicit instruction to do so — see finding 13 below for what
    was authorized instead.

    **UPDATE (separate planning chat, post-session): formally REJECTED.**
    Pooled net-of-fees -6.72%, pooled gross-of-fees -1.65%, 2/5 folds
    net-positive against the pre-committed bar of ≥4/5 — an improvement
    over finding 11 (-11.11% net, -5.23% gross) but not a pass.

    **Root-cause diagnosis (planning chat):** the three fixes had uneven
    effect. (1) The 8-slot cap fix worked completely — skipped signals
    dropped from finding 11's 169 to 11, confirming that flaw is resolved.
    (2) The single-lookback and full-history-universe fixes worked only
    *partially* — gross-of-fees drag shrank sharply (-5.23% → -1.65%),
    meaning the underlying signal is now close to fee-neutral before
    costs. This changes the diagnosis: the dominant problem is **no longer
    primarily fee drag** (findings 1-11's recurring failure mode) — it's
    now closer to a **signal-quality problem**, i.e. the strategy isn't
    capturing enough of the underlying trend to clear the bar even before
    costs are heavy. This is a materially different failure mode than
    every prior rejection in this session, not a rerun of the same issue.

13. **Final planned iteration on the multi-asset Donchian ensemble family
    (executed)**, testing the two remaining untested pieces of the
    original reference research (Turtle/SFI-style trend systems) that
    findings 11-12 deliberately deferred: (a) portfolio-level risk-budget
    position sizing, replacing finding 7-12's flat per-trade risk-based
    formula capped at a fixed notional %; (b) weekly entry evaluation
    instead of daily (exits/trailing-stop still monitored daily).
    Motivated directly by finding 12's signal-quality diagnosis: if fee
    drag is no longer the dominant problem, the two design elements most
    likely to change *signal quality* itself were the remaining untested
    candidates, not portfolio mechanics (slot cap, universe) which were
    already working as intended.

    **Required verification step (run first, before any new code) —
    `scripts/verify_finding12_sizing.py`**, a one-off diagnostic script
    (same convention as `sanity_check_daily_signal.py`/
    `select_universe.py`) that re-derives finding 12's exact entry-sizing
    formula unchanged, logging per-trade notional/equity% at entry
    against $100 (finding 12's actual capital, for an apples-to-apples
    check) — no sizing logic was touched by this step, read-only
    diagnostics only. **Result: the informal "flat sizing" assumption the
    milestone kickoff was built on was WRONG.** Across 154 entries over
    the full 5.6yr history, position size ranged 2.91%-12.50% of equity
    (mean 6.99%, stdev 2.11%) — meaningful, ATR-driven variation, not a
    flat default. The 12.5% notional cap bound only 7/154 times (4.5%
    overall) and concentrated almost entirely on one symbol: BTC/USD
    (6/20 trades capped, 30%) and ETH/USD (1/17, 6%); every other symbol
    (XRP, SOL, UNI, AVAX, AAVE, LINK, DOGE, BCH) was capped zero times.
    BCH/USD vs. XRP/USD (the two symbols specifically named for contrast)
    both showed real per-trade variation and neither ever hit the cap.
    This reframed what Part 2 actually needed to fix: not "sizing is
    flat," but "the notional cap has a narrow, BTC-specific failure mode
    that suppresses its risk contribution below target while every other
    symbol's risk-based size already sails under the cap untouched."

    **Part 2 — proposed and implemented sizing method: equal-risk-
    contribution / portfolio-level risk-budget sizing.** Per-trade risk
    target stays the existing 1%-of-equity formula (`DEFAULT_RISK_PER_
    TRADE_PCT`, spec §4.1's locked number, unchanged) — the change is
    what happens when a trade must be shrunk. Finding 12's mechanism
    (`SLOT_MAX_POSITION_PCT`, a flat 12.5%-of-equity NOTIONAL ceiling per
    slot, unrelated to how much risk the portfolio had already committed
    elsewhere) is replaced with a portfolio-level `TOTAL_PORTFOLIO_RISK_
    BUDGET_PCT` (8% = `MAX_CONCURRENT_POSITIONS`(8) x 1%, the same
    worst-case aggregate-risk envelope finding 12's 8-slot x 12.5% design
    implied, carried forward rather than freshly chosen). At each new
    entry: `available_budget = equity * 8% - sum(risk_amount of currently
    open positions)`; the new trade's risk is `min(1%-of-equity target,
    available_budget)` — shrunk only when the shared budget is actually
    running low, not against an arbitrary fixed % untied to portfolio
    state. A loose 100%-of-equity notional backstop
    (`NOTIONAL_SANITY_CAP_PCT`) stays underneath purely as a leverage/
    numerical safety net for a pathological near-zero-ATR edge case — kept
    separate and flagged so it isn't mistaken for a reintroduction of
    finding 12's per-slot design. `MAX_CONCURRENT_POSITIONS`=8 (the
    count-based structural cap) is untouched, per instruction.
    Implemented in `simulate_rotational_ensemble()` (backward-compatible:
    new `total_risk_budget_pct`/`notional_sanity_cap_pct` params default
    to finding-12-equivalent derivations when not given).

    **Part 3 — weekly entry cadence.** New `compute_weekly_entry_
    evaluation_dates()` selects a single fixed real calendar weekday
    (Monday, arbitrary but deterministic — same judgment-call convention
    as findings 11-12's slot-priority tie-break) from the shared calendar;
    `simulate_rotational_ensemble()`'s new `entry_eval_dates` parameter
    (default `None` = every day, preserving finding 12's exact behavior
    for any caller that doesn't pass it) gates the entries section only —
    the exits/trailing-stop section is untouched, still evaluated daily
    for every open position, every day. A signal that fires on a
    non-evaluation day is simply never picked up (not deferred/queued to
    the next Monday) — the entry condition (`close > 55d high`) is
    re-checked fresh each Monday, so it only fires if still true that day.

    **Notional:** this run used $10,000 (`PAPER_VALIDATION_CAPITAL`, the
    locked paper-validation notional, capital-reframing note above) —
    a local constant in this script only, NOT a change to `backtest.py`'s
    shared `DEFAULT_CAPITAL` ($100), which every earlier finding's numbers
    still depend on. Percentage results are unaffected by the switch, it
    only makes position-size dollar reporting realistic. Universe (10
    symbols), single 55-day channel, 2.5x ATR trailing stop, long-only,
    fee model, and fold boundaries are all unchanged from finding 12.

    **Result — portfolio-level, 5-fold anchored walk-forward
    (2022-01-03 → 2026-08-06 pooled test window, same boundaries as
    findings 5-12):** pooled net-of-fees **-15.22%**, pooled gross-of-fees
    **-13.51%**, **1/5 folds net-positive** (fold 3 +0.22% net/+0.86%
    gross; folds 1, 2, 4, 5 all net-negative: -3.01%, -4.47%, -6.90%,
    -1.93%), 44 pooled trades (54 total trades over the full history),
    max drawdown 15.22%. Win rates were low across every fold (0%, 0%,
    50%, 22.2%, 0%). **Zero signals were skipped for any reason** (no
    free slot, no risk budget) over the entire history — a sharp contrast
    with finding 12's 11 skips and finding 11's 169: with only 44-54
    total trades ever open across 10 symbols and 5.6 years, the portfolio
    essentially never had enough concurrent positions for either the
    8-slot structural cap or Part 2's risk-budget mechanism to bind. Part
    2's sizing logic is implemented and unit-tested (5 new/updated tests
    in `tests/test_backtest_donchian_ensemble.py`) but this particular run
    never exercised its shrink-under-pressure path in practice.

    **Trade count collapsed sharply vs. finding 12:** 54 total trades here
    vs. finding 12's 154 (full history, same universe/channel/exit) — a
    ~65% drop, the direct, expected mechanical effect of weekly entry
    gating (292 Monday-evaluation days vs. 2042 daily days in the shared
    calendar). Some raw daily breakout signals persist across multiple
    consecutive days (the entry condition can stay true after the
    triggering day if price keeps closing above the 55-day high), so more
    than the naive 1-in-7 fraction of signals survived, but the majority
    were still lost. Both gross (-13.51%) and net (-15.22%) came in
    substantially worse than finding 12's gross -1.65%/net -6.72% —
    unlike finding 12's diagnosis (fee drag shrinking, signal quality the
    remaining problem), here BOTH degraded, and fee drag alone
    (gross-to-net gap: -1.71 points pooled) does not explain most of the
    decline. Read as raw numbers only, not diagnosed further this
    session: **this result does not, on its face, support the hypothesis
    that weekly entry evaluation and risk-budget sizing would improve
    signal quality** — per-symbol diagnostics (pooled, informational
    only): net-positive contributors were UNI/USD (+$165.69, 2 trades),
    ETH/USD (+$103.94, 6 trades), AAVE/USD (+$51.29, 6 trades);
    net-negative were AVAX/USD (-$154.26, 2), LINK/USD (-$196.99, 3),
    XRP/USD (-$205.97, 2), SOL/USD (-$261.02, 4), BCH/USD (-$319.37, 4),
    DOGE/USD (-$320.92, 6), BTC/USD (-$330.83, 9) — BTC/USD, the symbol
    verification flagged as most affected by finding 12's notional cap,
    is now the single worst pooled contributor, though with only 9 trades
    this is far too thin to attribute to the sizing change specifically
    without a dedicated ablation (not run this session).

    **No adopt/reject verdict rendered — raw numbers only, per
    instruction; decision deferred to the planning chat**, same
    convention as findings 6, 8, 9, 11, and 12. 5 tests
    added/updated in `tests/test_backtest_donchian_ensemble.py`
    (1 rewritten for the new notional-sanity-backstop behavior, 4 new:
    risk-budget shrinkage, risk-budget exhaustion with free slots,
    weekly-cadence gating x2), full suite (82 tests) passing.

    **UPDATE (separate planning chat, post-session): formally REJECTED.**
    Pooled net-of-fees -15.22% (vs. finding 12's -6.72%), pooled
    gross-of-fees -13.51% (vs. -1.65%), 1/5 folds net-positive (vs. 2/5),
    trade count collapsed 154→54 — worse than finding 12 on every
    dimension, not a close call.

    **Root-cause diagnosis (planning chat, researching the actual
    mechanics of what changed rather than re-examining the result after
    the fact):** the gross-return degradation is the key diagnostic
    signal — finding 12's rejection had gross close to fee-neutral
    (-1.65%) with net doing the damage (fee drag). Finding 13's gross
    (-13.51%) is itself sharply negative, which rules out fee drag as the
    story here. **The actual cause: the Monday-only entry gate decoupled
    signal-*checking* from signal-*timing* on a fast 55-day breakout
    rule.** A Donchian breakout is a specific-day event (close crosses the
    channel high); checking for it only once a week means a breakout that
    fires mid-week is simply missed entirely, or picked up several days
    late (after the move has already partly happened) on the next Monday
    — not deferred or queued the way a slower-moving signal would
    tolerate. **This is an implementation flaw in how "lower entry
    frequency" was tested, not evidence that lower frequency itself is a
    bad idea** — finding 14 (below) expresses the same "trade less often"
    goal structurally instead, via a longer channel, rather than via
    calendar-gating a fast one. Separately: trade count was so thin
    (44-54 trades total across the whole run) that neither the 8-slot cap
    nor Part 2's risk budget ever bound in practice (0 skips of any kind)
    — so this result is **not evidence against equal-risk-contribution
    sizing**, which was implemented and unit-tested but never
    meaningfully stress-tested by real portfolio pressure this round.

    Per finding 13's binding "IMPORTANT CONSTRAINT" (set at kickoff), no
    finding-14 variant would normally be authorized without a fresh,
    explicit instruction — that instruction has now been given (see
    finding 14 below): a corrected long-horizon design, not a repeat of
    finding 13's approach.

14. **Corrected long-horizon design (finding 14's milestone, executed)** —
    the TRUE final planned iteration on this strategy family (see "Current
    status" above for the full binding constraint). Same 10-asset
    universe, same fee model, same 5-fold anchored walk-forward harness/
    boundary function as findings 5-13, unchanged. Three changes from
    finding 13, all in `scripts/backtest_donchian_ensemble.py` (same file,
    repaired in place again, not a new script):
    (a) `CHANNEL_LENGTH` lengthened 55d → 100d — a longer, slower breakout
        window, replacing finding 13's calendar-gated weekly check (the
        thing diagnosed as the actual flaw) with a structural fix to the
        same "trade less often" goal;
    (b) entries evaluated DAILY again, not weekly-gated — `main()` no
        longer calls `compute_weekly_entry_evaluation_dates()` or passes
        `entry_eval_dates` to `simulate_rotational_ensemble()` (defaults
        to `None` = every day). The function and parameter are both KEPT
        in the file (still unit-tested) for any future caller, just not
        invoked this round — directly reverses finding 13's Part 3
        mechanism, since that mechanism (not the underlying "lower
        frequency" idea) was diagnosed as the cause of finding 13's
        failure;
    (c) `ATR_MULTIPLIER` widened 2.5x → 3.0x.
    Finding 13's Part 2 (equal-risk-contribution / portfolio-level
    risk-budget sizing, `TOTAL_PORTFOLIO_RISK_BUDGET_PCT` = 8% = 8 slots x
    1%) is KEPT UNCHANGED — no sizing code touched this round; finding
    13's diagnosis found no evidence against it, so it is carried forward
    rather than reverted alongside Part 3.

    **New, permanent addition this finding: buy-and-hold benchmark
    functions** `compute_buy_and_hold_symbol_return()` and
    `compute_buy_and_hold_portfolio_return()`, both new in this file.
    Equal-weighted, buy-at-window-start/hold-to-window-end, never
    rebalanced (portfolio return = simple average of per-symbol %
    returns, which is exactly what that convention produces), computed
    independently for each of the 5 folds' own test-window boundaries
    (not compounded fold-to-fold) plus once more for the full pooled
    window (fold 1 test_start → fold 5 test_end) — the same convention
    the strategy's own pooled number already uses, so the two are
    directly comparable. Reported for both the full 10-asset universe and
    a `BUY_AND_HOLD_BTC_ETH_ONLY` subset. Judgment call, flagged: for a
    symbol whose own history starts after a window's nominal start date
    (XRP/USD from 2024-01-01, AVAX/USD from 2021-11-18, AAVE/USD from
    2021-07-15), that symbol's entry is its first available close ON OR
    AFTER the window start rather than excluding it from that fold's
    average — a partial-window return, included at equal weight anyway.
    BTC/USD and ETH/USD have full history for every fold, so the
    BTC/ETH-only comparison carries no such caveat. New
    `THIN_FOLD_TRADE_THRESHOLD` (5) flags any fold with fewer trades than
    that as "THIN" directly in the results table, per the session's
    explicit ask to report thin folds plainly rather than fold them into
    a clean pass/fail number.

    **Result — portfolio-level, 5-fold anchored walk-forward (2022-01-03
    → 2026-08-07 pooled test window — one day later than findings 5-13's
    quoted 2026-08-06 due to this run's real-time data fetch happening a
    day later, a negligible calendar drift, not a boundary-logic
    change):** pooled net-of-fees **+0.94%**, pooled gross-of-fees
    **+3.29%**, **3/5 folds net-positive** (fold 3 +0.91%, fold 4 +6.22%,
    fold 5 +2.21%; fold 1 -0.14%, fold 2 -7.25%), 65 pooled trades (86
    total trades over the full history), max drawdown 8.97%. Per-fold
    trade counts: fold 1 = 1 (**flagged THIN** — below the 5-trade
    threshold, read as inconclusive not evidence either way), fold 2 =
    10, fold 3 = 24, fold 4 = 23, fold 5 = 6 (just above the threshold,
    still fairly thin). **Known risk flagged at kickoff — reported
    honestly: it partially materialized.** The 100-day channel did NOT
    sample-starve as severely as finding 9's RSI mean-reversion (65
    pooled trades vs. finding 9's 3), but it is thinner than finding
    12/13's 55-day-channel predecessor (123 pooled trades) and fold 1 in
    particular is too thin (n=1) to read as anything but inconclusive.
    12 signals were skipped, all for `no_slot_available` (concentrated on
    XRP/USD=8, ETH/USD=4) — the 8-slot cap bound modestly this round,
    unlike finding 13's zero skips of any kind, but **zero skips were for
    `no_risk_budget_available`** — so, same as finding 13, this run still
    provides no direct evidence that the risk-budget sizing mechanism's
    shrink-under-pressure path was meaningfully stress-tested, even
    though the slot cap itself bound a little.

    **Buy-and-hold comparison (new, mandatory this finding forward):**
    pooled 10-asset equal-weighted **-41.62%**, pooled BTC/ETH-only
    **-4.48%** — the strategy's pooled net-of-fees (+0.94%) beats BOTH,
    the first strategy tested this session to beat either buy-and-hold
    measure. Per-fold buy-and-hold swung wildly (10-asset / BTC-ETH-only):
    fold 1 -69.70%/-64.14% (2022 bear market), fold 2 +146.25%/+74.41%,
    fold 3 +39.74%/+52.72%, fold 4 +102.81%/+77.61%, fold 5
    -61.91%/-48.38% (a second broad drawdown in the most recent window).
    Per-symbol pooled buy-and-hold: XRP/USD +61.6%, BTC/USD +40.2%,
    ETH/USD -49.1%, BCH/USD -50.2%, SOL/USD -56.1%, DOGE/USD -59.4%,
    AAVE/USD -65.6%, LINK/USD -65.6%, UNI/USD -78.0%, AVAX/USD -94.0% —
    most of the 10-asset universe collapsed hard over this specific
    window, which is why the 10-asset buy-and-hold benchmark is so
    deeply negative and easy for the strategy to clear; this is a
    materially harder period for buy-and-hold than the "~+100%"
    full-5.6-year figure quoted earlier in this file (see "Current
    status" for why those two figures aren't in conflict). The
    strategy's much lower pooled max drawdown (8.97%) versus
    buy-and-hold's fold-level swings (as wide as -69.70% to +146.25%)
    is a real risk-adjusted difference worth noting, though not part of
    the pre-committed adopt bar.

    Per-symbol diagnostics (pooled, informational only, not part of the
    adopt/reject bar): net-positive contributors were ETH/USD (+$607.59,
    4 trades), AVAX/USD (+$268.65, 6 trades), LINK/USD (+$149.11, 7
    trades), UNI/USD (+$14.39, 5 trades); BTC/USD landed slightly
    net-negative (-$21.84 net on 10 trades) despite positive gross
    (+$28.75) — fee drag tipped it, not a signal-quality issue
    specifically; net-negative were DOGE/USD (-$25.16, 8 trades),
    XRP/USD (-$154.13, 3 trades), BCH/USD (-$181.94, 8 trades), AAVE/USD
    (-$226.54, 8 trades), SOL/USD (-$337.84, 6 trades, worst pooled
    contributor).

    **No adopt/reject verdict rendered — raw numbers only, per
    instruction; decision deferred to the planning chat**, same
    convention as findings 6, 8, 9, 11, 12, and 13. On the pre-committed
    bar specifically: pooled net-of-fees is positive (clears that leg)
    but only 3/5 folds are net-positive (misses the ≥4/5 leg) — so the
    bar as a whole is not cleared, even though the strategy beats both
    buy-and-hold benchmarks for the same window. Per the binding
    constraint set at finding 13/14's kickoff, this — failing the
    pre-committed adopt bar — is one of the two pre-specified outcomes
    that closes this strategy family: **no finding-15 variant without a
    fresh, explicit instruction.** 8 tests added/updated in
    `tests/test_backtest_donchian_ensemble.py` (2 rewritten for the
    100-day channel, 6 new for the buy-and-hold helpers), full suite
    (88 tests) passing.

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
`EnsembleTrade` dataclass, `simulate_rotational_ensemble()` day-by-day
portfolio loop, `slice_ensemble_trades_by_folds()` exit-timestamp-keyed
fold slicer; built for finding 11, repaired in place for finding 12's
retry — single-channel `compute_channel_long_entry_indices()`, 8-slot
cap, backfilled `UNIVERSE` list; repaired in place again for finding 13 —
`simulate_rotational_ensemble()`'s sizing now uses a portfolio-level
`total_risk_budget_pct` (replacing finding 12's flat `max_position_pct`
notional cap, removed) with a separate `notional_sanity_cap_pct` leverage
backstop, plus a new `entry_eval_dates` param and
`compute_weekly_entry_evaluation_dates()` helper for weekly entry gating;
local `PAPER_VALIDATION_CAPITAL` ($10,000) used for finding 13's run
instead of `backtest.py`'s shared $100 `DEFAULT_CAPITAL`; repaired in
place a third time for finding 14 — `CHANNEL_LENGTH` 55→100,
`ATR_MULTIPLIER` 2.5→3.0, `main()` no longer calls
`compute_weekly_entry_evaluation_dates()`/passes `entry_eval_dates`
(function and parameter both kept, just unexercised by `main()` now),
risk-budget sizing untouched; new `compute_buy_and_hold_symbol_return()`/
`compute_buy_and_hold_portfolio_return()` and `THIN_FOLD_TRADE_THRESHOLD`/
`BUY_AND_HOLD_BTC_ETH_ONLY` constants for the new mandatory buy-and-hold
reporting — see findings 11-14 and the module docstring for the full set
of judgment calls made), `scripts/verify_finding12_sizing.py` (one-off,
finding 13's required
pre-code verification — re-derives finding 12's exact sizing formula
unchanged with per-trade notional/equity% logging added, not meant to be
maintained), `scripts/sanity_check_daily_signal.py` (independent one-off
check, not meant to be maintained). No `.env` or locked spec parameters
touched. Nothing merged or promoted — still `paper` branch working state.

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

**Finding 12 (executed, bounded one-time retry) was formally REJECTED.**
Single 55-day Donchian channel, 8-slot cap at 12.5%/slot, ADA/PEPE dropped
and backfilled with DOGE/USD and BCH/USD. Pooled net-of-fees -6.72%,
pooled gross-of-fees -1.65%, 2/5 folds net-positive — an improvement over
finding 11 (-11.11% net, -5.23% gross) but not a pass. Diagnosis: the
slot-cap fix fully resolved finding 11's binding-cap flaw (skips 169→11),
and the single-lookback/full-history-universe fixes shrank gross drag
sharply — the problem is **no longer primarily fee drag**, it's now a
**signal-quality problem** (not capturing enough of the underlying trend).
Per finding 12's binding "IMPORTANT CONSTRAINT," no further slot-cap/
entry-window/universe variant of this ensemble is authorized.

**Finding 13 (executed) was formally REJECTED** — worse than finding 12 on
every dimension (pooled net -15.22% vs. -6.72%, gross -13.51% vs. -1.65%,
1/5 folds vs. 2/5, trade count 154→54). Root-cause diagnosis (planning
chat): the weekly Monday-only entry gate, not the risk-budget sizing
change, caused the failure — gross degrading (not just net) rules out fee
drag, and points instead at a signal-timing flaw specific to gating a fast
55-day breakout rule to a weekly check. Equal-risk-contribution sizing
itself was never meaningfully exercised (0 skips of any kind) and is not
discredited by this result — see finding 13's UPDATE above for the full
diagnosis. Buy-and-hold context established this session (see "Current
status"): none of the seven variants tested to date have beaten
buy-and-hold on BTC/ETH (~+100% each over the test window) — this is now
a mandatory comparison line for every future finding.

**Finding 14 (100-day channel, daily entries, 3.0x ATR stop, sizing kept
from finding 13) was EXECUTED — mixed result, no verdict self-rendered.**
Pooled net-of-fees +0.94%, pooled gross-of-fees +3.29%, only 3/5 folds
net-positive (misses the ≥4/5 leg of the pre-committed adopt bar even
though the net-return leg clears). Beats both buy-and-hold comparisons
for the same window (10-asset -41.62%, BTC/ETH-only -4.48%) — the first
strategy this session to do so — but that does not override the
pre-committed bar, which the binding constraint set at kickoff already
covered: failing the adopt bar (regardless of the buy-and-hold result)
closes this strategy family. Fold 1 (n=1 trade) is explicitly flagged
THIN/inconclusive, not folded into the headline number. See finding 14
above for full per-fold/per-symbol detail. **No finding-15 variant
without a fresh, explicit instruction — the next step is a broader
planning-chat conversation about strategy direction, not another
backtest variant.**

### Pre-coding checklist state

**Finding 11 (10-asset rotational Donchian ensemble, 4-slot/25%, 20d-OR-
55d entry) is CLOSED — rejected.** **Finding 12 (redesigned retry:
55d-only entry, 8-slot/12.5% cap, ADA/PEPE backfilled with DOGE/BCH) is
CLOSED — rejected** (pooled net-of-fees -6.72%, 2/5 folds net-positive;
diagnosis: signal-quality problem, not fee drag — see finding 12's UPDATE
above). **Finding 13 (risk-budget sizing + weekly entry evaluation) is
CLOSED — formally REJECTED** (pooled net-of-fees -15.22%, pooled
gross-of-fees -13.51%, 1/5 folds net-positive; worse than finding 12 on
every dimension — root cause: the weekly entry gate's signal-timing flaw,
not the sizing change — see finding 13's UPDATE above). **Finding 14
(100-day channel, daily entries, 3.0x ATR stop, sizing kept from finding
13) is CLOSED — executed, mixed result** (pooled net-of-fees +0.94%
positive, but only 3/5 folds net-positive — misses the pre-committed
adopt bar on the folds-consistency leg; beats both buy-and-hold
comparisons for the same window regardless — see finding 14 above for
full detail). Per the binding constraint set at kickoff, this closes the
strategy family — no finding-15 variant without a fresh, explicit
instruction. Every future finding, including any new strategy family,
MUST report a buy-and-hold comparison alongside net/gross/folds-positive
(see "Current status" and Coding Conventions). The correlation/
open-risk-budget guardrail redesign (spec §4.3, 2-asset → 10-asset)
remains explicitly OUT of scope — do not attempt it without a separate,
current instruction.

### Blocked/pending, unrelated to backtest

`execution.py`'s OCO-fallback design is still waiting on a strategy
family reaching an adopt decision before it makes sense to start — on
top of its own separate crypto bracket-order design gap (see "Hard
rules" below). The correlation/open-risk-budget guardrail redesign
needed to generalize spec §4.3 from 2 assets to 10 (finding 10) is also
blocked/pending — not started, and explicitly not part of the current
milestone.

**Next milestone: none authorized yet.** Finding 14 (corrected
long-horizon design — 100-day Donchian channel, daily entries, 3.0x ATR
trailing stop, finding 13's equal-risk-contribution sizing kept
unchanged), the TRUE final planned iteration on this strategy family, has
been executed (see "Current status" and finding 14 above for the full
result: pooled net-of-fees +0.94% but only 3/5 folds positive — misses
the pre-committed adopt bar; beats both buy-and-hold comparisons
regardless). Per the binding constraint set at finding 13/14's kickoff,
this result closes the strategy family — do not start a finding-15
variant without a fresh, explicit instruction. The next step is a
broader planning-chat conversation about strategy direction, not another
backtest variant. Any future finding, in this family or a new one, MUST
report a buy-and-hold comparison alongside net/gross/folds-positive —
mandatory from finding 13 forward, not optional.

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
- **PERMANENT, as of finding 13 (2026-08 session): every backtest report
  must include a buy-and-hold comparison** for the same symbol universe
  and test period, reported alongside net-of-fees/gross-of-fees/
  folds-net-positive — not a one-off for that finding. Established
  because none of the seven strategy variants tested through finding 13
  beat buy-and-hold on BTC/ETH (~+100% each over the 5.6-year test
  window) while every active strategy tested was net-negative; without
  this comparison a result can clear the pooled-net-positive/
  folds-consistency adopt bar while still being a worse choice than doing
  nothing. Applies to finding 14 onward and any future strategy family.

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
