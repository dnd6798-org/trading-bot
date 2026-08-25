# CLAUDE.md

This file is read fresh at the start of every coding session. It is the
code-phase equivalent of `trading-bot-spec-v6.md` — the source of truth
for how to work in this repo, not what to build (that's the spec).

**If this file and chat history disagree, this file wins.** Update it
whenever a real decision is made during a coding session — don't rely on
conversation history to carry context forward.

**NEW (2026-08-12 session): `RULES.md` now exists at the repo root,
governing process/communication discipline between claude.ai and Claude
Code — separate from strategy content, which stays in the spec.** Read
`RULES.md` at the start of every session, before starting any work, in
addition to this file. Two rules from it worth restating here since they
directly affect how every future session reports work: (1) every
milestone report must include exact commit hashes and exact test
pass/fail counts — never "done" or "tests pass" without the number; (2)
no fact (file names, version numbers, commit hashes, function/variable
names, line numbers) should be stated as a placeholder or approximation —
if unconfirmed, say so explicitly rather than presenting a guess as
settled.

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

**NOTE (2026-08 session, spec v23, multi-track pivot): the crypto-only
framing in this section's opening paragraph is now historical, not
current.** The crypto strategy search (findings 1-14) concluded without
an adopted strategy — see "Current status" below for the full pivot. The
project now runs three parallel tracks (GEM+circuit-breaker, ETF
trend-following, options premium-selling) under spec v23, which
supersedes `trading-bot-spec-v6.md` as the source-of-truth spec document
(both live in project knowledge, not this repo). Older sections of this
file that still say "spec v6" or describe the crypto-only scope reflect
what was true when they were written — not edited retroactively, per this
file's own convention of preserving historical record rather than
rewriting it.

**NOTE (2026-08 session, spec v24): spec v23 has since been superseded by
spec v24** (Track B's completed result now lives at v24 §10.1, Track A's
design/bar at v24 §10.2) — same convention, mentions of "spec v23"
elsewhere in this file reflect what was true when written, not edited
retroactively.

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

**The crypto strategy search (findings 1-14) is now formally CONCLUDED
and preserved as historical record below, unedited — no crypto work is
planned for the foreseeable future.** The "broader strategic conversation
in the planning chat" flagged above happened; the outcome is the
multi-track pivot described here, not a return to crypto.

**Last session (planning chat): Dual Momentum / GEM (classic Gary
Antonacci design — monthly rotation among SPY/EFA/AGG/BIL) was locked as
the next candidate strategy, but was NOT backtested yet** — locking the
candidate was as far as that session went.

**This session, before backtesting GEM, its design was reconsidered.**
GEM's canonical form has no interim exit — once a monthly rotation signal
picks a holding, it's held untouched until the next month-end signal,
even if it draws down hard mid-month. The user does not want a strategy
where a losing position can't be acted on until the next scheduled
signal. Rather than force a single answer to "fix GEM's exit vs. abandon
GEM," **the project now runs three parallel, independently-evidenced
tracks, each tested against its own pre-committed bar:**
  - **Track A:** GEM plus a portfolio-level drawdown circuit breaker.
  - **Track B:** a multi-asset ETF trend-following strategy with a real,
    continuously-monitored ATR stop-loss.
  - **Track C:** options premium-selling, where max loss is defined at
    entry (structurally unrelated to the interim-exit problem, included
    as a third, independent line of evidence).
Full reasoning for the three-track split is in spec v23 §2 (project
knowledge, not this repo) — treat that section as the source of truth for
*why*, this file records *what was decided and when*.

**NEW MILESTONE, STARTING NOW: Track B.** Reuses the exact
Donchian-breakout-plus-ATR-trailing-stop mechanism already built and
tested for the crypto search — specifically this file's finding 14
design (100-day channel, 3.0x ATR trailing stop, equal-risk-contribution
sizing; spec v23 refers to this same design as "finding 15" — flagged,
not silently resolved: the external spec's own numbering and this file's
session-numbered findings list have drifted by one somewhere outside this
repo's visibility, but the design parameters match exactly, so there is
no ambiguity about *which* mechanism is being reused) — ported to a
diversified 8-ETF universe on Alpaca's commission-free stock/ETF product,
replacing BTC/USD + ETH/USD. Full design and the pre-committed adopt bar
for this milestone are in spec v23 §10.1 (project knowledge) — treat that
section as the source of truth for this milestone; no implementation
started yet, this update only records the decision to start per this
file's own "update whenever a real decision is made" rule. Track A and
Track C are locked as concepts but not yet started.

**UPDATE (2026-08-11 session): the three-track plan is now fully
CONCLUDED.** Track A (GEM + drawdown circuit breaker) was **rejected** —
both circuit-breaker variants and base GEM itself are dominated by a
simple static 60/40 SPY/AGG buy-and-hold on both return and drawdown (see
Track A finding 4). Track B (8-ETF Donchian breakout + ATR trailing stop)
**passed** — pooled net-of-costs +73.64%, 3/3 folds net-positive, true
max drawdown 5.69% versus the 8-ETF buy-and-hold blend's 26.47% over the
same pooled window (see "Track B findings" and the drawdown follow-up).
Track C (SPY put credit spread) was **rejected** — a near-breakeven miss
(pooled net-of-cost -0.38%, fold 1 negative) on a capital-constrained
structure, though its stress-test risk-control mechanism (worst-case loss
bounded at exactly the intended 2%-of-equity budget across three real
historical crash windows) was independently validated (see "Track C
findings" 5).

**Track B is therefore the project's sole surviving candidate, and the
project is now moving into deployment-prep engineering, not further
strategy search.**

**NEW MILESTONE, STARTING NOW: close Track B's one known backtest gap.**
The original Track B backtest never exercised the risk-budget
shrink-under-pressure path — `MAX_CONCURRENT_POSITIONS` was set to 8,
exactly equal to the full 8-symbol universe size, so the slot-count cap
could never bind on its own and the portfolio-level risk budget was never
the thing doing the shrinking (same unexercised-mechanism caveat already
flagged for the crypto ensemble in findings 13/14). This is a
**diagnostic milestone, not a re-test of Track B's already-passed
verdict** — the goal is to confirm the risk-budget mechanism behaves as
designed under real pressure, not to re-litigate the adopt decision. Full
design in spec v29 §10.1 (project knowledge) — treat that section as the
source of truth for this milestone.

**UPDATE: Track B risk-budget stress-test milestone EXECUTED.** Two
required checks, both done:

1. **Unit-level correctness** — a new synthetic scenario in
   `tests/test_backtest_donchian_ensemble.py`
   (`test_simulate_rotational_ensemble_binds_both_slot_cap_and_risk_budget_in_one_scenario`):
   6 symbols fire on the same day against `max_positions=4`,
   `total_risk_budget_pct=3.5%` on $100 equity — 3 symbols get their full
   1% target, a 4th is correctly SHRUNK (not rejected) to the $0.50
   remaining in the budget, and the last 2 are correctly SKIPPED for
   `no_slot_available` once the 4th slot fills (verified the slot check
   runs before the budget check, so this reason is reported even though
   the budget is also exhausted at that point). No crash, no
   over-allocation, no incorrect rejection of the shrinkable 4th trade.
   Two companion tests exercise a new, purely-additive `entry_sizing_log`
   instrumentation parameter added to `simulate_rotational_ensemble()`
   (backtest_donchian_ensemble.py) for this milestone: one confirms the
   shrink is correctly attributed to the risk budget specifically (not
   conflated with the separate notional-backstop path — see below), the
   other confirms the parameter is fully backward-compatible (defaults to
   `None`, return signature unchanged) so every existing caller (Track A,
   Track B, the crypto ensemble, all prior tests) is unaffected. 3 new
   tests, full suite (145 tests) passing.

2. **Real-data behavioral check** — new one-off script
   `scripts/stress_test_track_b_risk_budget.py` (not meant to be
   maintained, same convention as `select_universe.py`/
   `verify_finding12_sizing.py`) reran Track B's exact real
   2016-01-04→2026-08-11 8-symbol data through `simulate_rotational_
   ensemble()` with `MAX_CONCURRENT_POSITIONS` cut 8→4 and the risk
   budget cut proportionally (4×1%=4%, was 8%). Result: 196 trades taken,
   88 signals skipped (all `no_slot_available` — the slot cap now
   genuinely binds), and **14 of 196 entries were correctly shrunk by the
   risk budget**, all 14 spot-checked and verified exactly
   (`granted_risk_amount == available_risk_budget` in every case, to
   floating precision) — the shrink-under-pressure path works correctly
   when actually exercised. A portfolio-wide check confirmed no entry
   ever pushed committed risk above the budget cap, and max concurrent
   open positions never exceeded 4 — both PASS across the full run, not
   just the spot-checked subset. Per instruction, no net/gross/folds
   numbers from this reduced-cap rerun were reported or evaluated as an
   adopt/reject bar — this is diagnostic only.

   **Unexpected finding (the main thing this milestone actually
   surfaced): the risk budget is not the only thing that can shrink a
   trade, and the OTHER mechanism is not the rare edge case it was
   documented as.** `NOTIONAL_SANITY_CAP_PCT` (100% of equity,
   `backtest_donchian_ensemble.py`) — described in every prior finding as
   a "loose... essentially never binds for these liquid symbols" leverage
   backstop — bound on 13 of the 196 entries in the reduced-cap rerun,
   **all 13 on AGG**. Rerunning Track B's ORIGINAL unchanged 8-slot/8%
   configuration with the same new instrumentation confirmed this isn't a
   reduced-cap artifact: **13 of AGG's 15 total trades (87%) in the real,
   already-passed Track B backtest hit this same backstop, each one sized
   to EXACTLY 100% of account equity** — silently true in the result
   already reported as a pass, just invisible before this milestone's
   instrumentation existed. Root cause: AGG (bonds) has a very small ATR
   relative to its price, so the 1%-of-equity risk-based sizing formula
   demands an oversized position off AGG's tight stop distance, and the
   100%-notional backstop — not the risk budget — is what actually caps
   it. This does NOT change any trade Track B took or its reported
   returns (the resize arithmetic itself is correct, confirmed by the
   spot-check above) and does NOT reopen Track B's verdict, but it does
   mean the "~8% worst-case aggregate risk exposure" mental model
   documented alongside this strategy is incomplete: a single AGG
   position could, and repeatedly did, consume the entire account's
   notional on its own — a real concentration/leverage consideration
   flagged for whatever picks Track B up next (execution.py, guardrail
   rescaling), not resolved in this milestone. Corrected in place, not
   silently rewritten: the stale "essentially never binds"/"only the risk
   budget can shrink a trade" claims in both `backtest_etf_donchian.py`'s
   and `backtest_donchian_ensemble.py`'s module docstrings now carry an
   explicit correction note pointing to this finding, per this repo's own
   convention of flagging discovered inaccuracies rather than rewriting
   history.

   **No further action taken this milestone** — per instruction, scope
   stayed limited to the stress test itself. `execution.py`, guardrail
   rescaling, and paper-soak infrastructure remain untouched and are the
   logical next steps, but require a fresh, explicit instruction to
   start — in particular, any of that follow-on work should account for
   the notional-backstop finding above, not just the risk-budget
   mechanism this milestone was originally scoped to check.

**UPDATE: milestone confirmed complete and committed (23f8e02, full
suite 145/145 passing).** Both required checks passed: the unit test
correctly shrinks a symbol to remaining budget rather than rejecting it
outright, and correctly skips further signals once slots fill; the
real-data rerun (8→4 slots/budget) produced 196 trades, 88 skipped for
`no_slot_available`, and 14 correctly shrunk entries, all 14 spot-checked
exact.

**Reframing of the notional-backstop finding above, now that it's been
sat with: this is a real sizing-formula defect, not a documentation
issue.** 13 of AGG's 15 trades in Track B's original passed 8-slot
backtest were undiversified, 100%-of-account-equity positions, not
risk-budgeted allocations — because AGG's low ATR-to-price ratio causes
the risk-based sizing formula to demand an oversized position, and the
100%-of-equity notional backstop (not the risk budget) is what actually
governed those trades' size. This does NOT reopen Track B's passed
verdict — pooled net +73.64%, 3/3 folds stands as the historical record,
unchanged — but it needs to be understood and fixed before it's
inherited by guardrail rescaling and `execution.py`, not carried forward
silently.

**NEW MILESTONE, STARTING NOW: quantify, root-cause, and fix the
notional backstop.** Four parts: (1) quantify the backstop's binding
frequency across all 8 Track B symbols, not just AGG (AGG was the only
symbol observed to trigger it in the stress-test run, but that run
wasn't designed to rule out other symbols at the margin); (2) confirm the
root cause (low ATR-to-price ratio driving an oversized risk-based
position, per the stress-test's working diagnosis — confirm rather than
assume); (3) design a real, bounded max-single-position-notional cap to
replace the 100%-of-equity fallback; (4) rerun Track B with the fix
applied to see whether pooled return/drawdown are sensitive to it. Full
design in spec v30 §10.2 (project knowledge) — treat that section as the
source of truth for this milestone.

**UPDATE: Track B notional-concentration milestone EXECUTED.** All four
required parts done, diagnostic and fix-design only — does NOT reopen
Track B's passed verdict (pooled net +73.64%, 3/3 folds, as originally
tested, stands as the historical record).

1. **Full 8-symbol quantification** — new one-off script
   `scripts/quantify_track_b_notional_concentration.py` reran Track B's
   ORIGINAL, unmodified configuration (max_positions=8, risk_budget=8%,
   notional_cap=100%) over the complete real 2016-01-04→present history
   with the (now-extended) `entry_sizing_log` instrumentation, capturing
   every one of 219 real trades' entry ATR/price/notional detail, not
   just AGG's. Result — every symbol's UNCAPPED (natural, pre-any-cap)
   position-sizing demand, as % of equity:

   | symbol | n | capped | mean unc% | median unc% | max unc% | mean ATR/px% |
   |---|---|---|---|---|---|---|
   | AGG | 15 | 13 (86.7%) | 129.0% | 131.9% | 161.5% | 0.280% |
   | SPY | 36 | 0 | 34.1% | 34.0% | 53.7% | 1.045% |
   | QQQ | 35 | 0 | 26.7% | 26.5% | 45.2% | 1.316% |
   | IWM | 31 | 0 | 23.3% | 22.0% | 41.6% | 1.532% |
   | EFA | 32 | 0 | 35.7% | 34.9% | 54.6% | 1.005% |
   | GLD | 26 | 0 | 32.4% | 32.7% | 44.4% | 1.104% |
   | DBC | 26 | 0 | 26.7% | 25.3% | 42.0% | 1.340% |
   | VNQ | 18 | 0 | 26.0% | 26.6% | 33.7% | 1.317% |

   **AGG is uniquely affected — confirmed, not assumed.** Zero of the
   other 7 symbols ever tripped the 100% cap across the full 10.6-year
   history (0/204 non-AGG entries), and the global max uncapped demand
   across all 204 non-AGG entries was **54.6%** (EFA) — a clean, wide gap
   below AGG's own minimum value of 56.3% and its 100%+ range where 13 of
   15 entries actually sit. AGG's mean ATR-to-price ratio (0.280%) is
   4.4x lower than every other symbol's mean (1.228%) — the direct
   numerical signature of the root cause below.

2. **Root cause — confirmed two ways, not assumed:** (a) algebraically,
   `notional_pct_of_equity` for any trade whose risk wasn't already
   shrunk by the portfolio risk budget collapses exactly to
   `risk_pct / (ATR_MULTIPLIER × atr_to_price_fraction)` — verified
   against all 219 real logged entries, max absolute error 0.000000
   percentage points; (b) empirically, Spearman rank correlation between
   `atr_to_price_pct` and `uncapped_notional_pct_of_equity` across all
   219 entries = **−1.0000** (perfect inverse rank correlation — expected
   given (a) is an exact, monotonic algebraic identity, not just a
   trend). **Trailing-stop-distance interaction, checked as asked:**
   `ATR_MULTIPLIER` (3.0x) sits in the SAME denominator term as the
   ATR-to-price ratio (`stop_distance = ATR_MULTIPLIER × ATR`) — a
   *smaller* multiplier would make the oversized-notional effect WORSE
   for a given ATR/price ratio, not better; Track B's actual 3.0x (wider
   than the crypto ensemble's earlier 2.5x, finding 14's change) was
   already mitigating this somewhat, not causing it.

3. **Cap threshold — 55% of equity, NOT the kickoff's example 20-25%
   range, with the deviation explicitly quantified rather than silently
   overridden.** A threshold sweep across both populations (same
   quantification script) shows why: at 20-25%, the cap binds on
   **66-87% of the 204 non-AGG entries** — i.e. it would systematically
   resize the large majority of every OTHER symbol's normal, healthy,
   risk-based trades, not just fix AGG's pathological case:

   | threshold | non-AGG entries affected | AGG entries affected |
   |---|---|---|
   | 20% | 177/204 (86.8%) | 15/15 (100%) |
   | 25% | 135/204 (66.2%) | 15/15 (100%) |
   | 30% | 86/204 (42.2%) | 15/15 (100%) |
   | 40% | 26/204 (12.7%) | 15/15 (100%) |
   | 50% | 8/204 (3.9%) | 15/15 (100%) |
   | **55%** | **0/204 (0.0%)** | **15/15 (100%)** |
   | 60-75% | 0/204 (0.0%) | 14/15 (93.3%) |
   | 100% (old default) | 0/204 (0.0%) | 13/15 (86.7%) |

   55% is the cleanest break in the data: one point above the true
   empirical non-AGG ceiling (54.6%), it fully and surgically covers
   AGG's pathology (all 15 of its trades, not just the 13 the old 100%
   cap caught — 2 more, at 56.3%/79.2% uncapped demand, were previously
   invisible because they happened to fall under the old 100% threshold
   despite being far above every other symbol's own ceiling) while
   affecting zero trades for the other 7 symbols. Implemented as
   `MAX_SINGLE_POSITION_NOTIONAL_PCT = 55.0` in
   `backtest_etf_donchian.py` only (a Track-B-specific override passed as
   `notional_sanity_cap_pct`, same convention as `ETF_SLIPPAGE_BPS` — the
   shared `simulate_rotational_ensemble()`'s own 100% default, still used
   by Track A/the crypto ensemble, is untouched), with a new
   `--max-position-notional-pct` CLI flag (`--max-position-notional-pct
   100` reproduces Track B's original passed behavior exactly).

4. **Rerun sensitivity — real, non-trivial, but does NOT threaten Track
   B's verdict.** Reran the full real 2016-2026 backtest three ways
   (100% = original baseline sanity check, 55% = the fix, 25% = the
   kickoff's example, for transparency):

   | cap | pooled net | pooled gross | folds net-positive | pooled max DD | AGG net_pnl |
   |---|---|---|---|---|---|
   | 100% (baseline) | 72.63% | 84.89% | 3/3 | 5.69% | $331.55 |
   | **55% (the fix)** | **71.24%** | **82.41%** | **3/3** | **5.70%** | **$213.36** |
   | 25% (kickoff example) | 47.80% | 55.09% | 3/3 | 5.15% | $85.24 |

   (Baseline pooled net here, 72.63%, differs from the 73.64% originally
   reported in "Track B findings" 1 by ~1 point — expected re-fetch
   drift, ~4 more trading days of real data now included in the fetch
   window than the original session's run, same category as finding
   14's "one day later" note, not attributable to any code change this
   milestone made.) **At 55%, pooled return moves by only −1.4 points and
   max drawdown is essentially flat (+0.01 points) — folds-net-positive
   stays 3/3.** AGG's own net P&L contribution drops from $331.55 to
   $213.36 (**−35.6%**) — this is the concrete answer to "how much of
   AGG's contribution depended on the undiversified concentration": about
   a third of what was previously reported as AGG's contribution came
   from a single symbol sitting at up to 100% of account notional, not
   from a properly risk-budgeted position; the other ~64% reflects a
   genuine, correctly-sized edge that survives the fix. **At the
   kickoff's example 25%, by contrast, pooled net drops by 25 points
   (72.63%→47.80%)** — confirming numerically that 20-25% would have been
   a much bigger, less targeted change than intended, consistent with
   point 3's binding-frequency table.

   **No adopt/reject verdict rendered or implied — this was a sensitivity
   check, not a new profitability test, per instruction.** Folds-positive
   held at 3/3 under all three settings tested; the fix is recommended
   for adoption on correctness/concentration-risk grounds (a single
   symbol should not structurally reach 100% of account notional), not
   because it changed the return story.

5. **Other symbols beyond AGG: none found affected.** Explicitly checked
   and confirmed negative (point 1 above) — this is a single-symbol
   (AGG) issue in the current 8-ETF universe, not a broader pattern, as
   of this real-data run.

6. **No other bugs or unexpected behavior found** beyond the notional-
   backstop severity itself (already reported in the prior milestone and
   fully quantified here). The risk-budget shrink mechanism (previous
   milestone's subject) and the slot-count cap both continued to behave
   correctly throughout every rerun in this milestone (0 signals skipped
   in the 8-slot original-config quantification run, matching the
   already-known "risk budget never bound in Track B's original run"
   fact).

**UPDATE: Track B guardrail rescaling is now LOCKED (spec v32,
chat-side design — this repo update records the decision per this file's
own "update whenever a real decision is made" rule, no code changed this
session).** The legacy spec §4.2 guardrail numbers (1% risk/trade, 25%
max position, 3% daily loss, 6 trades/day cap, 1.5% combined open-risk,
10% max drawdown — the ones locked in "Hard rules" below) were sized for
intraday BTC/ETH crypto trading and do not transfer cleanly to Track B's
actual cadence (daily-bar signal evaluation across an 8-symbol universe,
~2-3 trades/month pooled, per "Track B findings"). New Track-B-specific
OVERRIDES, additive alongside the global `.env` numbers (which stay
untouched and still govern crypto/Track A) and alongside the already-
implemented `MAX_CONCURRENT_POSITIONS=8`/`MAX_SINGLE_POSITION_NOTIONAL_
PCT=55%`:

- `MAX_TRADES_PER_DAY_TRACK_B = 8` (was global 6) — matches the 8-symbol
  universe size. Can never legitimately bind (only 8 symbols exist, each
  fires at most once per day) — retained purely as a defense-in-depth
  duplicate-order/scheduler-bug catcher, on a separate code path from the
  slot cap, not as an active trading constraint.
- `MAX_DAILY_LOSS_PCT_TRACK_B = 4%` (was global 3%) — rescaled from "3x
  per-trade risk cap" (the crypto framing) to roughly half the new total
  open-risk budget below, sized for several concurrent positions gapping
  through their stops on the same shock day, not sequential intraday
  losses (which don't happen at daily-bar cadence).
- `MAX_TOTAL_OPEN_RISK_PCT_TRACK_B = 8%` (was 1.5% for BTC+ETH combined)
  — deliberately UNDISCOUNTED (= 8 slots x 1% per-trade cap), matching
  exactly what Track B's original backtest validated (the slot cap never
  bound in that run — see "Track B findings" — and no cross-symbol
  correlation discount was applied there either) rather than introducing
  a new, never-backtested correlation discount at this stage.
- `MAX_DRAWDOWN_PCT` stays at the global **10%**, unchanged — not
  cadence-dependent, so no Track-B override needed.

**Portfolio-level concentration cap: decided NOT to add as a hard
trading guardrail.** The notional-concentration milestone's 55%
single-position cap (spec v30 §10.2, above) was proven to be a
sizing-FORMULA-pathology fix (AGG's low ATR-to-price ratio demanding an
oversized position), not a diversification control — and Track B's
passed backtest never had, or needed, any concentration constraint.
Instead: a soft, non-blocking Telegram monitoring alert fires when
combined notional across positions in the same asset-class grouping
exceeds ~60-65% of equity — visibility for a human, not an enforced
trading rule.

**This closes deployment-prep item 2 (spec §2). Next up: the
`execution.py` build for Track B** — still blocked on its own separate
crypto bracket-order design gap being irrelevant for Track B specifically
(Alpaca DOES support real bracket/OCO orders for stocks/ETFs, unlike
crypto — see "Hard rules" below), but no longer blocked on guardrail
numbers being undefined. Not started this session.

**UPDATE: the rescaled Track B guardrails above are now IMPLEMENTED as
config overrides (spec v32), same pattern as `MAX_SINGLE_POSITION_
NOTIONAL_PCT` — Track-B-only, shared defaults untouched for Track
A/crypto.** This was a genuine, scoped `risk_filter.py` implementation
step (not just config), since "correctly gate at their new values" and
"correctly halts trading" needed real check logic to test against — see
that module's new "BUILD-SESSION SCOPE NOTE" for exactly what was and
wasn't implemented.

1. **Config** — `src/config.py` gained `get_track_b_guardrail_config()`,
   returning the SAME `GuardrailConfig` dataclass as `get_guardrail_
   config()` (not a new type), with `max_trades_per_day`/`max_daily_
   loss_pct`/`max_combined_open_risk_pct` rescaled to 8/4.0/8.0 and
   `max_risk_per_trade_pct`/`max_position_size_pct`/`max_drawdown_pct`
   passed through unchanged from the global config. Three new optional
   env vars (`MAX_TRADES_PER_DAY_TRACK_B`, `MAX_DAILY_LOSS_PCT_TRACK_B`,
   `MAX_TOTAL_OPEN_RISK_PCT_TRACK_B`), added to both `.env` and
   `.env.example` with the locked defaults — not `required=True` like
   the global guardrail vars, so a `.env` predating this session still
   works via code-level defaults matching the locked values exactly.

2. **`risk_filter.py`** — implemented exactly the 3 checks that
   correspond to the 3 rescaled numbers: `check_trade_count_limit()`
   (pure gate, `today_trade_count < guardrails.max_trades_per_day`),
   `check_daily_loss_limit()` (gates on `guardrails.max_daily_loss_pct`;
   on breach, calls `halt_state.set_halt()` itself — the SAME,
   already-tested, persisted-until-a-human-clears-it mechanism every
   other halt reason uses, not a new one built for Track B — rather than
   returning a bool for some undefined caller to act on, matching the
   module's own "centralized, auditable in one file" framing), and
   `check_combined_open_risk_budget()` (sums open positions'
   `.risk_pct`, returns remaining budget against `guardrails.max_
   combined_open_risk_pct`, or `None` if exhausted — the same equal-
   risk-contribution concept already validated in the Track B backtest,
   `simulate_rotational_ensemble()`'s `total_risk_budget_pct`, ported to
   the live check). `check_drawdown_limit()` and `evaluate()` (the
   single-entry-point wiring) are deliberately left `NotImplementedError`
   — no Track-B override for the former, execution.py-adjacent scope for
   the latter, per this milestone's explicit instruction not to proceed
   into `execution.py`. `account_state`/`open_positions` are duck-typed
   to the minimal attributes each check needs (`day_start_equity`/
   `equity`; `.risk_pct`) — a full `AccountState`/`Position` type is
   deferred to the `execution.py` milestone, flagged in both functions'
   docstrings rather than silently invented here.

3. **Soft concentration monitoring — asset-class grouping confirmed with
   the user BEFORE implementation** (same "flag it, don't guess"
   convention as the 55% notional-cap threshold deviation, spec v30
   §10.2), not assumed. Pulled the real 8-symbol Track B universe from
   `scripts/backtest_etf_donchian.py`'s `UNIVERSE` (SPY, QQQ, IWM, EFA,
   AGG, GLD, DBC, VNQ) and proposed 3 grouping options plus a custom-spec
   option; **confirmed grouping:**

   | group | symbols |
   |---|---|
   | Domestic Equities | SPY, QQQ, IWM |
   | International Equities | EFA |
   | Bonds | AGG |
   | Alternatives | GLD, DBC, VNQ |

   Flagged and confirmed as understood, not silently accepted: International
   Equities and Bonds are singleton groups and can structurally never
   trigger the alert alone, since a single position is capped at 55%
   notional (`MAX_SINGLE_POSITION_NOTIONAL_PCT`, spec v30 §10.2), below
   the 65% alert threshold — only Domestic Equities and Alternatives can
   realistically ever fire it with the current universe. New
   `check_asset_class_concentration()` in `risk_filter.py` — explicitly
   NOT part of the `RiskDecision` approve/reject flow, never rejects or
   resizes a trade, purely sums each group's open positions'
   `.notional_pct_of_equity` (deliberately the same field name as the
   Track B backtest's `entry_sizing_log`, spec v29 §10.1 — not a
   coincidence) and fires `telegram_bot.send_message()` (still its own
   `NotImplementedError` stub — tests redirect it via monkeypatch, same
   convention as `halt_state`) when a group exceeds `CONCENTRATION_
   ALERT_THRESHOLD_PCT` (65.0). Returns the triggered group names for
   logging only.

4. **Tests** — new `tests/test_risk_filter.py`, 17 tests: config
   layering (3 fields overridden, 3 passed through, global config
   unaffected); `check_trade_count_limit`/`check_combined_open_risk_
   budget` gating side-by-side at the global vs. Track B values,
   including a same-input-opposite-outcome test for each (the clearest
   proof the override actually changes behavior rather than being
   unused); `check_daily_loss_limit` halting via the REAL `halt_state.py`
   mechanism (not mocked, redirected to a `tmp_path` file via
   monkeypatch) including a same-loss-opposite-halt-outcome test between
   global (3%, breaches) and Track B (4%, doesn't) thresholds, plus a
   zero-day-start-equity edge case; `check_asset_class_concentration`
   firing exactly at >65% (not at exactly 65%), never touching the
   position list or returning anything but a plain list, the singleton-
   group non-triggering behavior, and a regression guard that the
   grouping constant covers exactly the 8 confirmed symbols. Full suite
   (167 tests) passing.

**UPDATE: two real gaps corrected, both surfaced by the user's own
closing-clarification questions on this milestone, not caught before
being asked.**

1. **`MAX_TRADES_PER_DAY_TRACK_B=8`'s "can never legitimately bind"
   claim was ambiguous, not verified.** `check_trade_count_limit()`'s
   parameter was named the generic `today_trade_count` — nothing in the
   code specified whether it should count entries only or entries+exits,
   and the "structural ceiling" reasoning (one entry per symbol per day,
   8 symbols) only holds for entries-only: an ordinary shock day where
   all 8 slots exit AND all 8 refill with new entries produces 8 real
   entries (within the cap) but 16 total trade events (would exceed it
   if both counted). Fixed: renamed to `today_entry_count` (also in
   `evaluate()`), docstring now states the entries-only contract
   explicitly and explains why, module docstring's §4.2 line updated.
   Two new tests pin this: a signature-inspection regression guard on
   the parameter name, and a scenario test showing the SAME day (4 real
   entries + 8 exits already processed) produces opposite `check_trade_
   count_limit()` outcomes depending on which count is passed —
   `True` (correct, entries-only) vs. `False` (wrongly blocked, if exits
   were also counted). No counting logic exists yet to have actually
   miscounted anything live (execution.py isn't built) — this was a
   contract-ambiguity fix, not a behavioral bug fix.

2. **`MAX_SINGLE_POSITION_NOTIONAL_PCT` (55%, spec v30 §10.2) and
   `GuardrailConfig.max_position_size_pct` were NOT wired to a single
   source, and had already drifted (25% vs. 55%).** `get_track_b_
   guardrail_config()` was written to pass `max_position_size_pct`
   through unchanged from the global config (staying at the legacy
   crypto-era 25%) — missed that this field is the exact same spec
   §4.1 concept ("max notional position size") as `MAX_SINGLE_POSITION_
   NOTIONAL_PCT`, which already existed as its own, disconnected
   constant in `scripts/backtest_etf_donchian.py`. **Fixed:**
   `MAX_SINGLE_POSITION_NOTIONAL_PCT` moved to `src/config.py` as the
   one canonical definition (full quantification-grounded rationale
   moved with it); `get_track_b_guardrail_config()` now overrides
   `max_position_size_pct` to this constant (4 of 6 fields rescaled for
   Track B now, not 3); `backtest_etf_donchian.py` imports the same
   constant instead of defining its own local `= 55.0` copy. Two new
   tests: one confirming `get_track_b_guardrail_config()` now returns
   55% (not the stale 25%) for this field, one asserting the backtest
   script's constant and `config.py`'s constant are literally the same
   value pulled from the same import, not two numbers that happen to
   agree today. Full suite (170 tests) passing after both fixes.

**MILESTONE CLOSED: Track B guardrail rescaling is COMPLETE and LOCKED
(spec v33), committed as `0641b09` on `paper`, 170/170 tests passing.**
Final Track B guardrail overrides (via `get_track_b_guardrail_config()`,
`src/config.py`):

| guardrail | global (crypto/Track A) | Track B |
|---|---|---|
| max trades/day | 6 | 8 (ENTRIES ONLY — `today_entry_count`, explicitly documented to exclude exits after the contract-ambiguity fix above) |
| max daily loss | 3% | 4% |
| max total open-risk budget | 1.5% | 8% (undiscounted, = 8 slots x 1% per-trade cap) |
| max position notional | 25% | 55% (now the single canonical source — `MAX_SINGLE_POSITION_NOTIONAL_PCT`, `src/config.py` — imported by both `risk_filter.py` and `backtest_etf_donchian.py` after the real drift found and fixed above; the live guardrail path had been silently using the legacy 25% instead of 55%) |
| max risk per trade | 1% | unchanged (1%) |
| max drawdown | 10% | unchanged (10%) |

**Portfolio-level concentration: no hard guardrail added, by design.**
Soft, non-blocking Telegram alert only (`check_asset_class_
concentration()`), firing when combined notional in a group exceeds 65%,
using the 4-group asset-class split confirmed with the user before
implementation: Domestic Equities {SPY, QQQ, IWM}, International
Equities {EFA}, Bonds {AGG}, Alternatives {GLD, DBC, VNQ}. International
Equities and Bonds are singleton groups that structurally can never
trigger the alert alone (a single position is capped at 55%, below the
65% threshold) — **this is correct, not a gap**, since the alert's
purpose is catching multi-position correlated clustering, not bounding
any single position (that's `MAX_SINGLE_POSITION_NOTIONAL_PCT`'s job).

**Explicit open prerequisite for the next milestone:** `check_drawdown_
limit()` and `evaluate()` in `risk_filter.py` are still
`NotImplementedError` — correctly out of scope for this milestone, but
must be implemented as the FIRST task of the `execution.py` milestone,
since `execution.py` cannot function without a working `evaluate()`.

**UPDATE: the `execution.py` design session (claude.ai chat interface) is
COMPLETE. Full architecture LOCKED, ready for implementation — this is
now the source of truth for the `execution.py` milestone, superseding
the generic spec §3.1 description where the two disagree (that
description is crypto-era/intraday; Track B's actual design differs
deliberately, per below).**

- **Cadence:** daily, ~30-60 min post-market-close — NOT the continuous
  intraday loop spec §3.1 originally described (that applies to crypto,
  not Track B).

- **Signal computation:** import directly from
  `scripts/backtest_donchian_ensemble.py` / `scripts/
  backtest_etf_donchian.py` — including `universe_order` for the
  slot-priority tie-break (fixed list order: SPY, QQQ, IWM, EFA, AGG,
  GLD, DBC, VNQ — not signal-strength ranked, confirmed against the code
  during pre-design fact-checking). No reimplementation, specifically to
  avoid the kind of constant drift already found and fixed once (the
  `MAX_SINGLE_POSITION_NOTIONAL_PCT` duplication, spec v32/v33
  clarification pass).

- **Entry: market order, submitted post-close, filled at next session's
  open.** Market-on-close is structurally impossible for this strategy
  — the Donchian signal needs the close to confirm it fired, and MOC
  orders must be submitted before the close. Next-open is the only
  honest live equivalent. This is a genuine overnight gap versus the
  backtest's same-day-close fill assumption (confirmed by direct code
  trace: `backtest_donchian_ensemble.py` fills at the SAME bar's close
  that generated the signal, no next-bar-open fill anywhere in that
  path) — NOT just execution friction, and tracked as its own metric,
  separate from the existing 5bps/leg slippage placeholder: **"signal-
  to-fill overnight gap."**

- **Stop mechanism — fully traced against the actual backtest code before
  locking this design, not assumed:** the backtest's "trailing stop" is
  a STATIC level per session, checked once against that day's low, and
  only moves once daily (post-close, computed for the next session) —
  never an intraday-trailing mechanism. `extreme_close` (highest CLOSE
  since entry, confirmed NOT highest high) and `prior_atr` are both
  anchored to T-1 for a given day T's check; the bump to include T's own
  close only happens after that day's check clears (see the three
  fact-check exchanges that traced this line-by-line). Consequences
  locked into the design:
  - **Order type: plain `stop`, not Alpaca's native `trailing_stop`** —
    the ATR recompute is a once-daily software job; the resting order
    itself is static and broker-checked all session, matching the
    backtest exactly (a native trailing-stop order would trail
    continuously intraday, which the backtest never does).
  - **`extreme_close_0` anchors to the SIGNAL day's close (`close_T`),
    not the fill day's** — matches the backtest's first stop check
    (which uses `atr[T]` against T+1's low) and avoids a one-directional
    bug where anchoring to the fill day would make the live stop looser
    than the backtest's on breakout-then-reversal trades.
  - **Initial stop (`close_T - 3.0*ATR(T)`) is fully computable before
    the entry order is even submitted** — both inputs are known from the
    signal-day close, before the next-open fill happens.
  - **Time-in-force: GTC, not DAY** — a deliberate deviation from a
    literal day-by-day replica. A DAY stop expires at close regardless
    of whether the next day's recompute job actually runs; GTC means a
    stale-but-present stop always rests if the recompute job fails,
    never zero protection.
  - **Replace via Alpaca's order-replace (PATCH), not cancel-then-
    resubmit** — avoids a window with no resting stop. Ratchet-only:
    replace only when the new level is more favorable, matching
    `extreme_close`'s max()-only ratchet in the backtest.

- **Position sizing: computed AFTER fill confirmation**, using the
  actual fill price and the pre-computed fixed stop price
  (`qty = risk_budget / (fill_price - stop_price)`) — pins realized
  per-trade risk at exactly 1% regardless of gap size, at the cost of
  entry and stop being two separate order submissions rather than one
  atomic bracket. The resulting gap-size variance in notional SIZE (not
  risk) should be watched during soak review alongside the overnight-gap
  metric — same root cause (the next-open fill), two different visible
  symptoms.

- **Unprotected-window safeguard:** since entry and stop can't be
  bundled atomically (Alpaca doesn't support bracket/OCO for this
  structure any more than it does for crypto — see "Hard rules" below,
  a related but distinct gap), the period between fill confirmation and
  stop submission succeeding is the system's highest-risk failure state.
  Requires retry logic on stop submission and an immediate, distinct
  Telegram alert if it fails or is delayed — NOT folded into generic
  error handling.

- **Position/state source of truth: Alpaca's account and order state
  directly — no local position database.** Local storage is for
  signal-lookback market data and audit logs only.

- **Guardrail integration point:** candidate signals generated post-close
  (day T) are passed through `risk_filter.evaluate()` before any entry
  order is submitted for T+1. **This is a hard prerequisite:
  `evaluate()` and `check_drawdown_limit()` are still
  `NotImplementedError` and must be built as the FIRST task of this
  milestone** — carried forward unchanged from the guardrail-rescaling
  milestone's closing note.

- **Fail-safe behavior:** a data/API failure halts new ENTRIES for that
  day only. Already-open positions stay protected by their resting GTC
  stop orders independent of bot uptime — the GTC choice above is what
  makes this fail-safe property hold.

**UPDATE: `execution.py` milestone EXECUTED — this design is now
IMPLEMENTED, not just locked.** Two prerequisite `risk_filter.py`
methods, then the full Track B daily execution pipeline, then a real
paper-account dry run. 43 new tests (`tests/test_execution.py`), 8 new
tests (`tests/test_risk_filter.py`, `check_drawdown_limit()`/
`evaluate()`), full suite 225/225 passing.

1. **`risk_filter.py` prerequisites — DONE, per instruction (do not
   proceed past this step until implemented and tested).**
   `check_drawdown_limit()`: peak-to-trough equity check against the
   global 10% threshold (no Track-B override — confirmed identical
   across `get_guardrail_config()`/`get_track_b_guardrail_config()`,
   per `config.get_track_b_guardrail_config()`'s own docstring), halts
   via the same `halt_state.set_halt()` mechanism as `check_daily_loss_
   limit()`. `evaluate()`: the single-entry-point orchestrator — runs
   daily-loss, drawdown, trade-count, and open-risk-budget checks in
   that order (daily-loss/drawdown can each halt independently; both
   run regardless of an earlier halt in the same call, cheap and
   idempotent) and returns a `RiskDecision` whose `position_size` field
   carries the GRANTED risk % (min of the 1% per-trade target and
   whatever's left of the open-risk budget). The 5th named guardrail
   (position notional cap, §4.1) is deliberately NOT a pass/fail gate
   in `evaluate()` — same reasoning `check_combined_open_risk_budget()`
   already documented for itself: the actual notional a given risk %
   produces depends on the entry ATR-to-price ratio, unknowable until
   sizing time, so it's enforced downstream in `execution.py`'s sizing
   step reading `guardrails.max_position_size_pct` directly.

2. **Signal generation** — `execution.py` imports `build_symbol_series()`
   from `scripts/backtest_etf_donchian.py` (Track B's own already-locked
   backtest module) rather than reimplementing, per instruction. That
   module itself reuses `simulate_rotational_ensemble()` et al. from
   `scripts/backtest_donchian_ensemble.py`, so the live signal path
   traces back to the exact same `compute_donchian_levels()`/
   `compute_atr()` primitives the Track B backtest validated,
   transitively, with no second copy anywhere. `universe_order` (fixed
   list order: SPY, QQQ, IWM, EFA, AGG, GLD, DBC, VNQ) is the
   slot-priority tie-break — no separate slot-count gate exists in
   `execution.py`, since `MAX_CONCURRENT_POSITIONS` equals the full
   8-symbol universe size, so the cap is structurally satisfied by
   "skip any symbol already holding a position" alone (confirmed, not
   assumed, in the guardrail-rescaling milestone).

3. **Entry order flow — the flagged qty-before-fill tension, resolved
   as a documented judgment call, NOT confirmed with the user.** Per
   the pre-implementation flag: the locked design's "qty computed AFTER
   fill confirmation" cannot be literally true — Alpaca requires a qty
   on the entry order at submission time, before the next-session fill
   price is known. Resolution implemented: `estimate_pre_fill_qty()`
   substitutes the signal day's own close (`close_T`, the same anchor
   the stop price already uses) as a pre-fill proxy for the unknown
   fill price; the entry order is submitted and filled at that qty and
   is NEVER resubmitted or resized afterward; `compute_realized_risk()`
   computes what risk was ACTUALLY taken post-fill, purely for
   reporting — any deviation from the 1% target is treated as an
   accepted, tracked consequence of the next-open-fill design, the same
   "signal-to-fill overnight gap" the locked design already names for
   TIMING, just showing up here as notional-SIZE variance instead (same
   root cause, two visible symptoms). **This is very likely not what
   the locked design's sentence intended and should get a real
   chat-interface design-call confirmation before this module is
   trusted with live capital** — flagged in `execution.py`'s module
   docstring, not silently treated as settled.

   **A second, related design gap was discovered during implementation
   (not anticipated by the locked brief) and is flagged the same way:**
   bridging the overnight submit-to-fill gap ACROSS separate daily-job
   invocations. The brief's "submitted post-close... stop submitted
   immediately after fill confirms" can't hold across a single ~30-60
   min post-close job when the fill itself doesn't happen until hours
   (or, over a weekend, days) later — a single process call can't block
   that long. Resolution implemented: `poll_order_until_terminal()`'s
   default timeout is short (60s, only enough to catch an IMMEDIATE
   outcome — a reject or an actual same-session fill during market
   hours); `confirm_entry_fill()` now distinguishes THREE outcomes, not
   two — filled, genuinely-rejected, and PENDING (still open with zero
   fill, the ordinary expected state for a next-session-open fill, not
   a failure, no alert); a new `protect_unprotected_fills()` runs as
   the FIRST phase of every `run_daily_execution_job()` call, finding
   any Alpaca position with no resting stop yet and recomputing its
   stop price purely from ITS OWN entry date's signal-day close/ATR
   (`compute_stop_price_for_entry_date()` — the formula only ever
   depends on public price history for the entry date, so it's always
   re-derivable on demand and never needs to be persisted, consistent
   with "no local position database"). **Net effect, reported plainly:
   a position that fills between two daily runs can now be unprotected
   for up to about one full trading day** — worse than the locked
   design's apparent assumption of near-immediate post-fill protection.
   This is a real, material gap in the locked design as read literally,
   not introduced by this implementation; a genuinely correct fix
   likely needs a THIRD, separate scheduled invocation shortly after
   each session's open (calling `protect_unprotected_fills()` on its
   own) — not built this milestone, flagged for the same design-call as
   the qty gap above.

4. **Stop order flow** — `submit_stop_order()` (plain `stop`, TIF=GTC,
   qty not notional — confirmed the existing sizing code already
   outputs qty). `submit_stop_order_with_retry()`: retries with backoff
   (default 3 retries, `(5, 15, 30)`s) then fires an immediate, distinct
   `URGENT — UNPROTECTED POSITION` Telegram alert on total failure,
   deliberately not folded into generic error handling, per instruction.
   Daily ratchet (`ratchet_position_stop()`): recomputes `extreme_close`
   since entry and the T-1-anchored-ATR candidate stop, replaces via
   Alpaca's PATCH `replace_order_by_id()` (not cancel-then-resubmit)
   only when strictly more favorable (`compute_ratcheted_stop_price()`'s
   max()-only ratchet, identical formula to `simulate_rotational_
   ensemble()`'s exit block).

5. **Fail-safe behavior — verified, not just asserted from the order
   type.** `run_daily_execution_job()`'s only try/except around data
   fetch means any data/API failure skips BOTH the daily ratchet and
   new entries for that run, but touches no resting order — confirmed
   directly in the dry run (see below) via `replace_stop_order_if_
   favorable()`'s unfavorable-candidate branch, which correctly declined
   to call Alpaca's replace endpoint at all. The daily ratchet itself
   runs even while `halt_state.py` reports halted (only ever tightens
   protection, never opens new risk); new entries are skipped entirely
   while halted.

6. **Tests — all required categories covered, 43 tests in
   `tests/test_execution.py`:** sizing/stop-anchoring math (signal-day-
   close anchoring, T-1-anchored ATR reference via a deliberately
   large decoy today's-ATR value, ratchet-only max()-logic, the
   notional second-stage cap); a simulated unprotected-window failure
   (`submit_stop_order_with_retry` exhausting all attempts — both in
   isolation and end-to-end via `submit_entry_and_stop`, confirming the
   URGENT alert fires and `stop_order_submitted=False` while the
   entry's real fill is still correctly reported); the new pending-fill
   three-way classification (a still-open zero-fill order must NOT be
   treated as rejected); and `protect_unprotected_fills()`'s discovery/
   protect/alert-on-unrecoverable paths.

7. **End-to-end paper-account dry run — EXECUTED against the real paper
   account (`scripts/dry_run_execution_track_b.py`, one-off, not meant
   to be maintained, same convention as `select_universe.py`). Market
   was closed at run time (2026-08-11 ~18:03 ET) — used a marketable
   extended-hours LIMIT order as a DRY-RUN-ONLY expedient (documented
   in the script, NOT how production Track B submits entries) so the
   full flow could be validated in one sitting rather than waiting for
   next open.** Result: real entry filled (1 share SPY @ $770.72), real
   GTC stop order submitted and resting ($765.72), the ratchet-only
   replace correctly DECLINED an unfavorable candidate (no API call
   made). **New, real finding from live testing, not previously known:**
   Alpaca rejects a PATCH replace on an order still in `accepted` status
   (HTTP 422, "cannot replace order in accepted status") — a
   newly-submitted stop needs a short settle window before it's
   replaceable. Not expected to matter in real production use (the
   daily ratchet runs once per day, long after any same-day-submitted
   stop has settled), and already fail-safe by construction —
   `run_daily_execution_job()`'s per-position try/except around
   `ratchet_position_stop()` turns any such exception into a safe no-op
   (alert + "existing resting stop unchanged"), not a crash — but
   flagged in `replace_stop_order_if_favorable()`'s docstring since it
   was unknown before this dry run. The script cleaned up after itself
   (cancelled the stop, closed the position via a second extended-hours
   limit order since the plain-market close order predictably sat
   PENDING outside market hours) — paper account left flat, +$0.13 net
   P&L from the round trip, no residual test position.

**Not yet done:** the fill-protection gap (see the UPDATE immediately
below — design is now LOCKED as an event-driven listener, superseding
the "third scheduled invocation" idea originally flagged in gap 2, but
still not implemented in this repo); `data_ingestion.py`'s
live/streaming fetch (`fetch_latest_candle()`, `validate_data()`); spec
§3.2 journaling/audit-log persistence of `run_daily_execution_job()`'s
returned log dict; and the crypto/Track A bracket-order gap
(`place_entry_order()`/`place_exit_orders()`, still `NotImplementedError`,
unrelated to Track B and explicitly untouched).

**UPDATE (2026-08-12 session, claude.ai chat-side design session only —
no code written this session): the fill-protection gap's design is now
LOCKED, ready for implementation, which is the next milestone.** Closes
the gap flagged above: a position filling between two daily
`run_daily_execution_job()` invocations could sit unprotected for up to
~1 trading day. Replaces the "third, separate near-open scheduled
invocation" idea originally flagged with a persistent, event-driven
listener on Alpaca's `trade_updates` WebSocket stream instead — locked
architecture:

1. New module `fill_listener.py`, running as its own standalone systemd
   service, separate from the daily job's service — holds both a
   `TradingStream` (event receipt) and a `TradingClient` (order actions,
   reused from `execution.py`).
2. Standardizes on alpaca-py's `alpaca.trading.stream.TradingStream`
   (confirmed already a dependency via `execution.py`'s
   `TrailingStopOrderRequest` usage).
3. Connection lifecycle: subclasses `TradingStream` as
   `MonitoredTradingStream`, overriding `_start_ws()` to add exponential
   backoff (`2^failures`, capped at 300s) before each reconnect attempt,
   plus Telegram alerting — URGENT at 5 consecutive failures,
   informational on recovery after hitting that threshold. Rationale:
   alpaca-py's built-in reconnect loop has no backoff (0.01s sleep
   between attempts, confirmed from source) and would otherwise
   spin-retry forever on both network failures and bad credentials.
4. Stop-price handoff: no local position DB, per the standing
   "position/state source of truth: Alpaca directly" design principle.
   The daily job's entry submission (`run_daily_execution_job()`,
   `execution.py`) must be updated to pass a `client_order_id` encoding
   symbol + signal date + the pre-computed stop price in cents, format
   `tb-{symbol}-{YYYYMMDD}-{stop_price_cents}`, e.g.
   `tb-SPY-20260812-45823`. The listener parses this on fill — no other
   state needed.
5. Handler logic: acts only on event in `{fill, partial_fill}`,
   `side == buy`, symbol in the 8-ETF Track B universe. Partial fills
   resize the stop to cumulative `filled_qty` via the existing
   replace-not-cancel ratchet mechanism; the final fill event finalizes
   it. Sell fills (exits) are logged only, no action taken.
6. Idempotency: extract a shared `has_resting_protective_stop(symbol)`
   helper out of `protect_unprotected_fills()` (currently implicit in
   its "unprotected" filtering) so both the listener and the daily
   fallback pass call the identical check — same fix pattern as the v32
   notional-cap drift bug ("Current status" above), applied proactively
   here instead of discovered after the fact.
7. `protect_unprotected_fills()` is unchanged in role: fallback for
   listener downtime, not replaced. Timing analysis: in normal operation
   the listener and the daily fallback never actually race, since fills
   happen at next-session open and the fallback runs hours later
   post-close the following day — the only real exposure window is the
   listener being down at the moment of a fill.
8. The listener ignores bot halt state entirely — it only reacts to
   fills that already happened and passed guardrails before submission;
   gating stop protection on halt state would be wrong given the
   existing fail-safe principle that open positions stay protected
   independent of bot uptime.
9. Open items flagged for verification DURING implementation, not
   assumed: exact `client_order_id` length limit for this account's
   Trading API (Alpaca's own docs disagree: 48 vs 128 chars), exact
   `TradeUpdate`/`Order` field names in the installed alpaca-py version,
   existing systemd unit naming convention, installed alpaca-py version
   pin.

This design session did NOT touch the other open gap from the
`execution.py` milestone (the entry-qty-before-fill sequencing tension,
resolved there with a pre-fill `close_T` proxy) — that remains a
separate, still-unconfirmed placeholder, per the "Blocked/pending"
section below.

**UPDATE: the fill-protection listener milestone was EXECUTED.** All 9
locked design points implemented as specified — `src/fill_listener.py`
is new and real (`MonitoredTradingStream` + `handle_trade_update()`);
`src/execution.py` gained `encode_client_order_id()`/
`decode_client_order_id()`, `has_resting_protective_stop()` (extracted
out of `protect_unprotected_fills()`, which now calls it — the shared
check point 6 required), and `submit_or_resize_stop_order_with_retry()`
(the listener's protection entry point; `submit_stop_order_with_retry()`
itself is unchanged and still used directly by `submit_entry_and_stop()`).
254/254 tests passing (29 new: 15 in `tests/test_execution.py`, 14 in
new `tests/test_fill_listener.py`).

**Point 9's open items — all verified this milestone, not assumed:**
- `client_order_id` max length: **128 characters**, confirmed empirically
  against the real paper account (submitted real, never-fillable,
  immediately-cancelled limit orders with lengths up to 256 — 128
  accepted, 129 rejected with Alpaca's own `"client_order_id must be no
  more than 128 characters"`). Resolves the docs' 48-vs-128 disagreement
  in favor of 128. The encoded format is ~22-30 characters for Track B's
  real 8-symbol universe either way.
- `TradeUpdate`/`Order` field names (installed alpaca-py **0.43.5**,
  confirmed via direct inspection of `alpaca.trading.models`): `TradeUpdate`
  has `.event` (`TradeEvent` enum or raw str), `.order` (a NESTED `Order`
  object — not flat fields on `TradeUpdate` itself), `.timestamp`,
  `.position_qty`, `.price`, `.qty` (this last pair describe the CURRENT
  execution, not the order's cumulative fill). The nested `Order` has
  `.symbol`, `.side` (`OrderSide` enum), `.filled_qty` (CUMULATIVE — what
  the listener uses, per point 5), `.filled_avg_price`,
  `.client_order_id`, `.status`. `TradeEvent.FILL`/`.PARTIAL_FILL` values
  are literally `"fill"`/`"partial_fill"` — matches the locked design's
  own naming exactly.
- `alpaca.trading.stream.TradingStream` confirmed present at the
  installed version (0.43.5); `requirements.txt` pins only a floor
  (`alpaca-py>=0.30.0`, no upper bound) — whether to add an upper/pinned
  bound given this module's dependence on `TradingStream`'s internal
  `_start_ws()` override point is flagged, not decided here.
- Systemd unit naming convention: **none exists** — no `.service` file is
  checked into this repo for either the daily job or this listener;
  deployment configuration lives on the droplet itself, out of scope for
  every deployment-adjacent milestone to date, this one included.

**Two things discovered during implementation, NOT anticipated by the
locked brief, both flagged in code rather than silently resolved:**
1. **`ReplaceOrderRequest.qty` is typed `Optional[int]`** in the installed
   alpaca-py version — unlike every order-SUBMISSION request's `qty`
   field in the same SDK (`StopOrderRequest`/`MarketOrderRequest`, both
   `Optional[float]`), confirmed directly against the pydantic model.
   A fractional partial-fill resize qty (Track B position sizing produces
   fractional shares) therefore cannot go through the PATCH replace path
   at all — `submit_or_resize_stop_order_with_retry()` does NOT silently
   round (would misrepresent the actual protected qty); it fails
   deterministically and falls through to the same URGENT Telegram alert
   path as any other resize failure. Safe (fails toward alerting a
   human), but unresolved — flagged for the same chat-interface
   design-call as `execution.py`'s other two open gaps.
2. **A new, narrow race**, distinct from the one this milestone was
   built to close: `submit_entry_and_stop()`'s own unconditional
   `submit_stop_order_with_retry()` call and the listener reacting to the
   SAME fill concurrently could in principle both attempt the FIRST stop
   submission for one symbol at once (`has_resting_protective_stop()`'s
   check-then-act pattern reduces but doesn't eliminate this). Not
   expected to matter in real production use — genuine same-session fills
   essentially never happen given Track B's post-close-only entry cadence
   — but not eliminated by this implementation either. Flagged in
   `execution.py`'s module docstring at the `client_order_id` encoding
   call site.

**Verification against the real paper account — both required tests,
both PASS:**
- **Integration** (`scripts/dry_run_fill_listener.py`, Part 1): a real
  `MonitoredTradingStream` connected live; a real fill-forcing order was
  submitted with an encoded stop price; the listener detected the fill
  over the real WebSocket and submitted a real resting stop — confirmed
  via a direct `GET` within ~0 seconds of the fill, stop price exactly
  matching the encoded target.
- **Restart-safety** (same script, Part 2): a second real fill was
  forced with the listener intentionally NOT running, confirmed genuinely
  unprotected (`has_resting_protective_stop()` → `False`), then
  `protect_unprotected_fills()` (the daily-job fallback) correctly
  protected it; a SYNTHETIC redelivered `trade_update` for that same
  already-protected fill was then fed directly into `handle_trade_update()`
  — no exception, and exactly 1 resting stop order afterward, not 2,
  confirming the idempotency guarantee against real Alpaca account state.
  **Methodology note, flagged in the script's own docstring:** Part 2's
  fallback step needed SYNTHETIC `symbol_data` (not fetched from Alpaca)
  because `protect_unprotected_fills()` recomputes a stop from the entry
  date's own historical daily bar, which structurally cannot exist yet
  for a fill that happened seconds ago in the same test session — a
  limitation of this DRY-RUN's same-session-fill technique, not of
  production behavior (real entries fill at next session's open, so by
  the time the following day's job runs, that day's bar is long
  published). Account left flat after both parts (verified: 0 open
  positions, 0 open orders).

**Not yet done, unchanged from before this milestone:** the crypto/Track
A bracket-order gap; `data_ingestion.py`'s live/streaming fetch; spec
§3.2 journaling persistence. This milestone did not touch any of those.

**UPDATE: fix-up session, three items, all pre-decided (not open
questions) — EXECUTED.** 261/261 tests passing (7 net new over the prior
254: several rewritten, one obsoleted, several added). No re-run of the
live paper-account integration/restart-safety script this session —
scope was explicitly the automated suite; the original milestone's live
verification (above) was not repeated against this fix-up's code.

1. **Fractional-qty partial-fill resize — replaced, not left as a
   fail-toward-alert gap.** `ReplaceOrderRequest.qty` being `Optional[int]`
   is a limitation of the SDK's replace/PATCH path specifically — Alpaca's
   order-submission endpoint supports fractional qty on stop orders
   directly (confirmed against Alpaca's fractional-trading docs, which
   cover market/limit/stop/stop-limit). `submit_or_resize_stop_order_
   with_retry()` no longer attempts a PATCH replace at all for a
   partial-fill follow-up — it submits a SECOND, ADDITIVE stop order at
   the same stop price, sized to just the newly-filled increment
   (cumulative `filled_qty` minus qty already covered by every resting
   stop for the symbol, via new `_sum_resting_stop_qty()`). Two resting
   stops at the same price for one symbol is an accepted, safe outcome —
   confirmed as instructed, not independently re-litigated: if the first
   fills and closes the position, the second is rejected by the broker as
   an oversell (no margin/shorting on this account), not silently
   mis-executed. Return contract changed to `(order, qty_submitted)` —
   `qty_submitted` is 0.0 for a genuine no-op (redelivered event), which
   item 3's notification gate depends on. **Flagged, NOT resolved by this
   fix-up:** `build_open_positions()`/`ratchet_position_stop()` still
   assume exactly one resting stop per symbol — if a partial fill ever
   actually produces two, the daily ratchet only ratchets whichever one
   `_find_resting_stop_order()`'s most-recent-first sort happens to pick,
   silently leaving the other stop at its original, increasingly-stale
   price. A genuinely new gap, surfaced by this fix-up, needing its own
   design call — not guessed at here.

2. **The `submit_entry_and_stop()` race — closed, not just documented.**
   Its stop-submission step now gates on `has_resting_protective_stop()`
   — the SAME shared check `protect_unprotected_fills()` and the
   listener's `submit_or_resize_stop_order_with_retry()` both use — before
   submitting; if a resting stop already exists (the listener won the
   race), it uses that instead of submitting a duplicate. All three
   stop-submission paths in `execution.py` now gate on the identical
   function. Same honest caveat as every other check-then-act use of this
   pattern already in this module: this closes the race to the same
   degree `protect_unprotected_fills()` and the listener already close it
   for each other (not via a distributed lock) — a true same-instant race
   remains theoretically possible, just no more so here than anywhere
   else this pattern is relied on.

3. **Routine-success Telegram notification — did NOT already exist,
   ADDED this session.** Before this fix-up, `handle_trade_update()` only
   ever sent a message on FAILURE (the URGENT alert inside
   `submit_stop_order_with_retry()`) — a successful protect was
   completely silent, confirmed by reading the code before answering
   rather than assumed. Now fires a single, non-urgent message whenever
   a call ACTUALLY submits or tops up a stop (`qty_submitted > 0` — a
   genuine no-op, e.g. a redelivered event, does NOT re-notify). Message
   format, confirmed against a live test assertion:
   `"fill_listener: protected {symbol} — qty {qty_submitted} @ stop
   {stop_price}, {elapsed:.1f}s after fill event."` — e.g. `"fill_
   listener: protected SPY — qty 10.0 @ stop 435.0, 2.5s after fill
   event."` For a top-up, `qty_submitted` is the INCREMENT just protected,
   not the fill's full cumulative qty (e.g. `"qty 3.0"` for an 8.0-qty
   partial fill topping up an existing 5.0-qty stop). Elapsed time is
   computed from `trade_update.timestamp` (the event's own timestamp
   field) to now; if the event carries no timestamp, the message says
   `"elapsed time unknown (no event timestamp)"` rather than fabricating
   a number.

**UPDATE: second fix-up session — multi-stop consolidation implemented,
live re-verification run, and a CRITICAL, UNRESOLVED problem discovered
in the process.** 265/265 tests passing (4 net new).

1. **Consolidation implemented as specified.** `build_open_positions()`
   now uses a new `_find_all_resting_stop_orders()` and takes the WORST
   (lowest) price across multiple resting stops for its `stop_price`/risk
   calculation (conservative — never overstates protection).
   `ratchet_position_stop()` now independently re-queries all resting
   stops for a symbol; when more than one exists (the top-up model's
   leftover state), it calls new `_consolidate_resting_stops()` instead
   of the single-stop PATCH-replace path: submits ONE new stop sized to
   the SUMMED qty of the old ones at `max(ratchet candidate, worst
   existing price)`, confirms it's genuinely resting via a fresh API
   query (`_confirm_order_resting()`), and only THEN cancels the old
   ones — new-before-cancel, exactly as specified. **Judgment call,
   flagged:** consolidation is UNCONDITIONAL whenever multiple stops are
   found, even if the ratchet price itself doesn't improve that cycle —
   otherwise "never more than one resting stop past the next daily job
   cycle" would depend on the position continuing to trend favorably
   every day rather than being a hard guarantee. 4 new unit tests (two-
   stop consolidation with new-before-cancel call-order proof; old stops
   left untouched on submission failure; old stops left untouched when
   the new stop can't be confirmed resting; consolidation still merges
   even when the ratchet price doesn't improve).

2. **Live re-verification — Parts 1 and 2 both PASS again; Part 3
   (added this session for the top-up/consolidation path) surfaced a
   real, load-bearing problem.** `scripts/dry_run_fill_listener.py`
   extended with a Part 3: a real fill, a real first stop (via
   `handle_trade_update()` called directly), a SYNTHETIC second
   partial-fill event to exercise the real TOP-UP path (per the
   milestone brief's own explicit fallback — a genuine broker-side
   second partial fill can't be reliably forced on this account for a
   small, liquid, immediately-fillable order), then a real
   `ratchet_position_stop()` call against the resulting real resting
   stops.

   **CRITICAL FINDING, confirmed twice — once inside the script's own
   run, once in an isolated follow-up experiment specifically to rule
   out a test-methodology artifact: Alpaca's real held-quantity
   validation REJECTS the new-before-cancel consolidation submission
   whenever the existing resting stops already fully cover the real
   position — exactly the scenario consolidation exists to handle.**
   Isolated repro: bought 2 real IWM shares, submitted two real resting
   SELL stops (qty 1 + qty 1, correctly summing to the real 2-share
   position, both accepted individually) — then submitting a THIRD new
   SELL stop (qty 2, the consolidated amount) while the first two were
   still resting was rejected: `"insufficient qty available for order
   (requested: 2, available: 0)"`, both existing stops listed in
   `related_orders`. Alpaca will not let a NEW sell order reserve share
   quantity that OTHER still-open sell orders already hold, even though
   no shares have actually been sold yet. The single-stop PATCH-replace
   path is NOT affected (modifying an existing order's own qty in place
   needs no NEW headroom) — this is specific to the multi-order merge.

   **Also confirmed, informational, NOT implemented:** cancelling all
   but one old stop FIRST, then PATCH-replacing the survivor's qty+price
   up to the consolidated values, WAS accepted by the real API in the
   same follow-up experiment. Not adopted here — it reintroduces a brief
   real coverage gap for the freed increment (between the cancel and the
   patch) and `ReplaceOrderRequest.qty`'s `Optional[int]` typing (the
   exact constraint fix-up #1 replaced the resize path to get away from)
   resurfaces for any fractional consolidated total.

   **Practical safety, confirmed:** this does NOT silently under-protect
   a position — `submit_stop_order_with_retry()` inside the consolidation
   path retries 4 times, fails, and correctly falls through to the
   existing URGENT alert path; the OLD stops are left resting and
   untouched throughout (per the fail-toward-alert convention already
   established for every other stop-submission path in this module).
   **But consolidation AS DESIGNED will never actually succeed in the
   scenario it exists for.** Flagged prominently in
   `_consolidate_resting_stops()`'s own docstring and this file — needs
   a fresh design-call confirmation on which alternative mechanism to
   adopt before consolidation should be trusted with live capital. NOT
   resolved this session, per the standing "flag it, don't guess"
   convention — the mechanism specified was implemented exactly as
   asked, tested thoroughly against a fake client (where it passes,
   since the fake client doesn't model Alpaca's held-quantity
   validation), and then found to not actually work live.

**UPDATE (next session, in progress): the new-before-cancel consolidation
mechanism above is being REPLACED, not patched.** Locked conclusion
carried forward from the finding above: no reordering of submit/cancel
around the SAME two primitives (a new separate order vs. Alpaca's
held-qty check) avoids this without reintroducing either a real coverage
gap or the `ReplaceOrderRequest.qty` fractional-typing constraint — so
`_consolidate_resting_stops()`'s actual mechanism is being swapped for a
different one this session, per a locked design given in a separate
message, not invented here. Until that lands, treat the CRITICAL finding
above as still the live, accurate status of `ratchet_position_stop()`'s
multi-stop path — `_consolidate_resting_stops()` in the current `paper`
HEAD (commit `9136c28`) does not actually work against a real account.

   Parts 1/2 (unaffected by this finding) both PASS again against
   current `paper` HEAD: real listener detects a real fill and submits a
   correctly-priced stop within ~0s (including the routine-success
   notification firing, confirmed in the live output); a fill submitted
   with the listener down is correctly picked up by
   `protect_unprotected_fills()`, and a redelivered event for that
   already-protected fill is confirmed a safe no-op. One incidental,
   real-market observation from this run (not a code bug): an
   extended-hours limit order missed its fill once on a stale quote
   despite the account clock reporting the pre-market window as open —
   the script's marketable-limit buffer was widened (0.2%/$0.50 →
   1%/$1.00) as a mitigation, not a fix for anything in `execution.py`/
   `fill_listener.py` itself. Account left flat after every part,
   verified via direct GET (0 positions, 0 open orders) — including
   after the two manual follow-up isolation experiments run outside the
   script itself.

**UPDATE (same session): the new-before-cancel consolidation mechanism has
been REMOVED and REPLACED with independent per-stop ratcheting — CLOSES
the multi-stop gap, per a locked design given separately, not invented
here.** `_consolidate_resting_stops()` and its `_confirm_order_resting()`
helper are deleted outright, not patched. `ratchet_position_stop()`'s
multi-stop branch (more than one resting stop found for a symbol — the
top-up model's leftover state) now computes ONE target price (off the
worst/lowest of the existing stops, same conservative basis consolidation
used) and applies it to EACH resting stop independently via its own
`ReplaceOrderRequest(stop_price=...)` — the same single-stop PATCH-replace
primitive already used and already confirmed working live, just invoked
once per order. No new order is ever submitted, nothing is ever
cancelled, and `qty` is never included in any of these replace calls —
confirmed by grep that `ReplaceOrderRequest.qty` has zero remaining
call sites in the ratchet path, so the `Optional[int]`-typing constraint
that motivated the original top-up-model fix-up is structurally
irrelevant here too. `build_open_positions()`'s existing worst-price rule
already keeps risk/state reporting correct with any number of resting
stops per symbol, so a symbol may now legitimately carry N
independently-ratcheted resting stops for its entire holding period —
an accepted, permanent state, not a leftover to be collapsed.

Tests: the 4 consolidation-specific tests (new-before-cancel call order,
summed-qty submission, submission-failure/confirmation-failure alerting,
unconditional-merge) were replaced with 3 new tests asserting the actual
new contract — each resting stop gets its own independent replace call;
the new price is applied to every stop that's actually improved by it
(a stop already above the new candidate is correctly left untouched,
proving the per-stop check isn't unconditional); no new order is ever
submitted and nothing is ever cancelled; qty is never present on any
replace call. Full suite: **264/264 passing** (265 - 4 removed + 3
added).

**Live re-verification — a REAL, NEW issue was found and fixed before
Part 3 could pass, not just a rerun of the prior round's script.** The
first live attempt this session hit a rejection on the TOP-UP call
itself (`"insufficient qty available for order (requested: 1, available:
0)"`), not just on the now-removed consolidation step — root-caused to a
pre-existing bug in `scripts/dry_run_fill_listener.py`'s own Part 3
methodology, not in `execution.py`: it only ever bought a REAL 1-share
position, then fed `handle_trade_update()` two synthetic events claiming
a cumulative qty of 2 — i.e. it was always asking Alpaca to rest sell
orders totalling more shares than the account actually held, which
happened to be tolerated once in the PRIOR round and was rejected
outright this time, confirming that tolerance was never a reliable API
guarantee. Fixed by buying the REAL full 2x qty up front so both
synthetic events' claimed cumulative totals are genuinely backed by real
shares at submission time (only the "one atomic fill reported as two
separate notification events" simplification remains synthetic, not the
share count). After that fix, Part 3 PASSED live end to end: a real
2-share IWM position, protected by two real independently-submitted
resting stops (qty 1 + qty 1, same price) via the real top-up path, then
`ratchet_position_stop()` correctly found both, independently PATCH-
replaced BOTH to the new ratcheted price, with neither merged nor
cancelled and both quantities unchanged (1 + 1, not resized). Parts 1/2
(unaffected by this milestone) both PASS again unchanged. Account
confirmed left flat after the full run (0 positions, 0 open orders,
verified via direct GET).

**Flagged, NOT resolved by this milestone (a real edge case, not
silently handled, per instruction):** the multi-stop replace loop in
`ratchet_position_stop()` does not wrap each per-order `replace_stop_
order_if_favorable()` call individually — if one resting stop's PATCH
succeeds and a LATER one for the same symbol then raises, the exception
propagates to `run_daily_execution_job()`'s per-position try/except,
whose alert text ("existing resting stop unchanged") would be
inaccurate for a partial success (one stop moved, another didn't). Not
observed in this session's live run (both replaces succeeded), and not
guessed at or silently patched here — needs its own design call (e.g.
should the alert distinguish partial success, should a partial failure
retry just the failed order) before being trusted with live capital.

**UPDATE (fourth fix-up, same milestone): this exact flagged gap is now
CLOSED — per-stop error isolation with accurate partial-success
reporting, per a locked design given separately, not invented here.**
Each per-order `replace_stop_order_if_favorable()` call inside
`ratchet_position_stop()`'s multi-stop branch is now wrapped in its own
try/except (a plain Python loop change, `_consolidate_resting_stops()`-
style new-before-cancel machinery is NOT reintroduced) — every resting
stop for the symbol is always attempted regardless of an earlier one's
outcome, and a per-order result (order id, old price, replaced True/
False, error or `None`) is collected for all of them. If nothing failed,
behavior is byte-for-byte unchanged from before this fix-up (no Telegram
message sent). If one or more failed (up to all): the outer per-position
try/except's URGENT-alert-shaped path in `run_daily_execution_job()` is
deliberately NOT reached — the multi-stop branch never raises now, so
that outer handler's all-or-nothing text can no longer misdescribe a
partial success. Instead a single, non-urgent summary is sent directly
from a new `_send_ratchet_failure_summary()`, naming which order(s)
ratcheted to the new price and which remain at their old price with the
specific error hit — reasoning: `build_open_positions()`'s worst-price
rule already means the symbol is exactly as protected after a partial
failure as it was before the attempt, and tomorrow's ratchet pass
retries the stragglers automatically, so nothing here needs to page a
human. The all-fail case uses the identical summary path (reporting "0
of N" ratcheted rather than being silently swallowed), so a persistent
per-symbol failure pattern stays visible in whatever channel `telegram_
bot.send_message()` records, even though it's deliberately never
URGENT. 3 new tests in `tests/test_execution.py` (all-succeed —
confirms zero Telegram messages and unchanged behavior; partial-failure
— confirms BOTH orders are attempted despite the first raising, confirms
the surviving order's replace call actually carried the new price,
confirms the summary names the successful order with its new price and
the failed order with its old price and exact error text; all-fail —
confirms both orders still attempted, confirms the summary explicitly
reports "0 of 2", confirms neither error is dropped), plus a new
`replace_order_by_id_fn` hook added to the test suite's `FakeTradingClient`
so a test can make a specific order id's replace call raise. Full suite:
**267/267 passing** (264 + 3). No live re-run performed for this
fix-up, per instruction — this is error-handling structure around a
replace primitive whose live behavior was already verified in the prior
fix-up's re-run, not new order-submission behavior.

**NEW MILESTONE, DESIGN LOCKED, NOT YET IMPLEMENTED: systemd units for
the daily job + the fill-protection listener (spec v34 §10.6).** Locked
in the claude.ai chat interface this session — no code or `.service`
file written yet, this update only records the decision to start, per
this file's own "update whenever a real decision is made" rule. Three
unit files needed:
  - `trading-bot-daily.service` (oneshot) — the systemd target for
    `run_daily_execution_job()` (`src/execution.py`).
  - `trading-bot-daily.timer` — the daily post-close schedule trigger
    for the above.
  - `trading-bot-listener.service` (`Restart=always`) — the systemd
    target for `run_listener()` (`src/fill_listener.py`), matching that
    module's already-locked "own standalone systemd service" design
    (spec v33 §10.5, "Current status" above).
Full unit file contents (`ExecStart`, `User`, `WorkingDirectory`,
`EnvironmentFile`, restart/backoff settings, etc.) are in spec v34
§10.6 (project knowledge, not this repo) and this session's chat
record — **not reproduced in this file**, per this repo's standing
convention that spec content is the source of truth for *what to
build* and `CLAUDE.md` records *what was decided and when*. The next
session implementing this milestone must read `RULES.md` first (this
session's own instruction, restated here so it survives into the next
session's context), then pull the exact file contents from spec v34
§10.6 before writing anything — not reconstruct them from memory or
from this summary.

**Pre-implementation verification checklist (per this session's
instruction: "verify against real source, do not assume; report any
deviation from the brief rather than silently resolving it") — three of
five items are droplet-only facts this Windows-local Claude Code session
has no way to check, flagged as such rather than guessed; two are local
repo facts checked directly this session:**

1. **Actual current deployment path and venv location on the droplet —
   NOT VERIFIABLE from this session/environment.** This repo has never
   recorded either fact — the existing "Systemd unit naming convention"
   note (fill-listener milestone, "Current status" above) already states
   plainly that "no `.service` file is checked into this repo...
   deployment configuration lives on the droplet itself, out of scope
   for every deployment-adjacent milestone to date." Confirmed still true
   by a fresh repo-wide search this session (no `/opt/`, `/home/`, or
   venv-path reference tied to the droplet anywhere in tracked files).
   **Must be obtained directly from the droplet (e.g. `pwd`, `which
   python`, the venv's actual location) before any unit file's
   `WorkingDirectory`/`ExecStart`/`EnvironmentFile` paths are written —
   do not assume a path by convention.**
2. **Whether `src/execution.py` and `src/fill_listener.py` have working
   `__main__` entrypoints — CHECKED THIS SESSION, and they DIFFER, a
   real finding, not a formality.** `src/fill_listener.py` has one
   (`if __name__ == "__main__": run_listener()`, line 337) — confirmed
   it builds a real `TradingClient`/`MonitoredTradingStream` and blocks
   forever via `stream.run()`, matching what `trading-bot-listener.service`
   needs to `ExecStart` directly. **`src/execution.py` has NO `__main__`
   block at all** — `run_daily_execution_job()` is fully implemented and
   tested (see above) but nothing in this repo invokes it as a process
   entrypoint; the only thing that calls it is the one-off
   `scripts/dry_run_execution_track_b.py`, which is explicitly a manual
   dry-run script, not a production entrypoint. **This is a real,
   concrete gap: `trading-bot-daily.service`'s `ExecStart` target does
   not exist yet and must be added (a small, real code change — e.g. a
   `__main__` block calling `run_daily_execution_job()` and persisting
   its returned log dict, the still-open spec §3.2 journaling item noted
   elsewhere in this file) before that unit file can point at anything
   real.**
3. **Whether halt-state-on-boot is checked in both entrypoints today —
   CHECKED THIS SESSION: it is checked in ONE of the two, and
   deliberately NOT in the other, by existing documented design, not an
   oversight.** `run_daily_execution_job()` DOES call `halt_state.
   load_halt_state()` — but only after the daily ratchet loop runs, and
   only to gate NEW ENTRIES for that run (the ratchet itself runs
   regardless of halt state, since it only ever tightens protection,
   never opens new risk — already documented in that function's own
   docstring). `run_listener()` (`src/fill_listener.py`) does NOT check
   `halt_state.py` at all, anywhere — confirmed by grep, and this is
   itself already explicitly documented in that module's own docstring:
   "gating stop protection on halt state would be wrong given the
   existing fail-safe principle that open positions stay protected
   independent of bot uptime/halt status." **Neither of these is a gap
   to fix** — both match this repo's standing "Never auto-resume trading
   after a crash/restart" hard rule's actual intent (gate NEW risk on
   halt, never gate EXISTING protection on it) — but the raw checklist
   question's honest answer is "checked in one, intentionally not the
   other," not a plain yes, and is restated here so the next session
   doesn't need to re-derive it.
4. **Real path of the `.env` file currently used for manual runs — NOT
   VERIFIABLE from this session/environment.** Every script in this repo
   (`src/config.py`'s `get_alpaca_config()` and everything built on it)
   loads `.env` via the working directory at invocation time, not a
   hardcoded path — so the real answer depends entirely on wherever
   manual runs on the droplet are actually invoked FROM, which is
   droplet-only information this session cannot see. **Must be confirmed
   directly on the droplet before `EnvironmentFile=` is set in either
   `.service` file** — do not assume it matches this repo's local
   `.env`/`.env.example` layout.
5. **systemd version on the droplet (`systemctl --version`) — NOT
   VERIFIABLE from this session/environment.** Must be run directly on
   the droplet before the unit files are finalized, since some directives
   (e.g. certain `Restart=`/backoff options `trading-bot-listener.
   service` needs for `Restart=always`) are version-gated in systemd and
   a mismatch would only surface at deploy time, not from anything
   checkable in this repo.

**Net: items 2 and 3 are answered and recorded above (with one real,
concrete follow-up gap surfaced — `execution.py` needs a `__main__`
entrypoint before this milestone can complete); items 1, 4, and 5 remain
open and must be checked directly on the droplet, not assumed, before
any unit file is finalized — flagged per this session's own instruction
rather than silently resolved or guessed at.** [RESOLVED — see the
"UPDATE (droplet-side verification..." block later in this milestone's
record: all three confirmed correct against the real droplet, matching
the convention this repo had adopted.]

**UPDATE (next session): the systemd-units milestone was EXECUTED —
`execution.py`'s missing `__main__` entrypoint is now built, all three
unit files exist as real, committed files, and a new dead-man's-switch
heartbeat was added. 275/275 tests passing (267 + 8 new: 2 in
`tests/test_config.py`, 6 in `tests/test_execution.py`). Droplet-only
items (1, 4, 5 above) remain unverifiable from this session — no SSH
access to any droplet exists from this Windows-local environment, no
droplet host/path was ever recorded anywhere in this repo (confirmed
again by a fresh search), and none was provided this session either.
Per this session's own explicit authorization ("your call, just be
explicit about which you chose and why"), `/opt/trading-bot` (venv at
`/opt/trading-bot/venv`, `.env` at `/opt/trading-bot/.env`) was adopted
as a CHOSEN CONVENTION, not a confirmed fact — flagged in-line in every
unit file's own header comment and in `deploy/systemd/README.md`, not
just here, so the caveat travels with the artifact.

1. **`src/execution.py` gained a real `__main__` block** — the
   `ExecStart` target `trading-bot-daily.service` needed and didn't have
   (per item 2's finding above). Calls `run_daily_execution_job()`,
   logs the returned run_log dict via `logging` (INFO level,
   `logging.basicConfig` configured so it lands in journald under
   `StandardOutput=journal`), then calls the new `send_daily_heartbeat()`.
   Deliberately does NOT add its own halt-state check — item 3 above
   already established `run_daily_execution_job()` checks
   `halt_state.load_halt_state()` internally (gates new entries only,
   ratchet still runs while halted), so a second check at the `__main__`
   level would be redundant, not a fix for a real gap. Full spec §3.2
   journaling (persisting the run_log dict somewhere durable, beyond
   journald's own retention) is explicitly NOT built here — out of scope
   for this milestone, flagged in the `__main__` block's own comment,
   same standing gap as before.

2. **New dead-man's-switch heartbeat (Step 3 of this milestone's
   brief).** `send_daily_heartbeat()` (`src/execution.py`) pings a new
   `UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL` (via `get_heartbeat_config()`,
   new in `src/config.py`) once at the end of a `run_daily_execution_job()`
   call, ONLY when `run_log["errors"]` is empty — a halted-but-error-free
   run still counts as a healthy ping (halting is an intentional,
   already-alerted state, not a job malfunction; this heartbeat's only
   job is proving the daily process itself is still alive and completing
   runs, a failure mode none of the existing in-job Telegram alerts can
   catch since those only fire from inside a run that's already
   happening). Best-effort: a failed ping (network blip, UptimeRobot
   outage) is logged and returns `False`, never raised — must never be
   mistaken for, or cause, a real job failure. New direct dependency
   `requests>=2.31.0` added to `requirements.txt` (previously only
   present transitively, confirmed 2.34.2 already installed in this
   repo's venv). New required-to-fill-in var
   `UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL` documented in `.env.example`.

   **Real, flagged deviation from the milestone brief, not silently
   resolved:** the brief's Step 3 describes this as "a *second*
   UptimeRobot heartbeat ping (separate monitor from the listener's
   *existing* liveness heartbeat)" — but a fresh repo-wide search this
   session (`grep -rni "uptimerobot\|heartbeat"`) found **no existing
   heartbeat/UptimeRobot mechanism anywhere in this repo**, in
   `src/fill_listener.py` or otherwise — every prior hit was the
   unrelated word "uptime" inside "independent of bot uptime" prose.
   The brief's premise that a listener-side liveness heartbeat already
   exists does not match the actual repo state. Per RULES.md's "Claude
   Code... does not make undocumented architecture or strategy decisions
   on its own" — a listener-side liveness heartbeat (ping interval,
   mechanism for a process that blocks forever in `TradingStream.run()`,
   env var naming) is itself a real, underspecified design question, not
   implementable from this brief's detail level. **Only the daily job's
   success-only heartbeat, the one piece this brief actually specified in
   full, was built.** The listener liveness heartbeat remains a real,
   open gap — needs its own claude.ai design pass before a future
   session builds it, not invented here.

   **Second flagged deviation:** `get_heartbeat_config()`
   (`src/config.py`) reads the URL with `required=False` even though
   `.env.example` documents it as a value that must be filled in for the
   heartbeat to actually function — a missing/blank URL logs a warning
   and skips the ping rather than crashing the entire daily job. Coupling
   a monitoring add-on to a hard crash of the job that still needs to
   protect/ratchet real open positions regardless of whether monitoring
   is configured would contradict this module's own established
   fail-toward-alert-never-toward-crash convention (see e.g.
   `submit_stop_order_with_retry()`'s URGENT-alert-on-exhaustion pattern,
   never a raised exception). Confirmed locally: running the real
   entrypoint with no URL configured produced exactly this — a logged
   warning, `send_daily_heartbeat()` returned `False`, exit code 0.

3. **Three unit files, new, committed: `deploy/systemd/trading-bot-
   daily.service`, `trading-bot-daily.timer`, `trading-bot-listener.
   service`** (plus `deploy/systemd/README.md` — install steps, the
   `tradingbot` system-user creation commands from Step 4, and the exact
   droplet-only verification commands for Step 5, none of which this
   session could run). Content matches the milestone brief's template
   exactly except for the header comments added to each file flagging
   the `/opt/trading-bot` path assumption and the systemd->=239
   requirement for `OnCalendar=`'s per-line timezone syntax (neither
   confirmed against a real droplet this session). `trading-bot-listener.
   service` additionally documents, in its own header, that its
   `WorkingDirectory=` must stay identical to `trading-bot-daily.
   service`'s: `halt_state.py`'s `HALT_STATE_PATH` defaults to a CWD-
   relative `halt_state.json`, so the two services silently seeing
   different halt-state files if their working directories ever diverged
   would be a real, dangerous gap — flagged, not just assumed fine.

4. **Step 4 (create the `tradingbot` system user, `chown` the deploy
   path) — NOT executed, droplet-only.** Exact commands (`useradd
   --system --no-create-home --shell /usr/sbin/nologin tradingbot`,
   `chown -R tradingbot:tradingbot /opt/trading-bot`) are documented in
   `deploy/systemd/README.md` for the droplet session to run directly —
   this Windows-local session has no way to execute them for real.

5. **Step 5 verification — partially done, partially droplet-only,
   reported exactly, not glossed over:**
   - **Local substitute for "manually trigger the daily timer once...
     confirm it runs to completion and exits 0" — DONE, against the
     real paper account** (no systemd on Windows to literally run
     `systemctl start`, so `python -m src.execution` was run directly
     instead, the same invocation the unit file's `ExecStart` uses).
     Real output: `run_daily_execution_job()` returned
     `{'date': '2026-08-14', 'protected': [], 'ratcheted': [],
     'entries_submitted': [], 'entries_skipped': [], 'errors': [],
     'halted': False}` — no open positions to ratchet, no qualifying
     entry signal fired today, zero errors — then the heartbeat step
     logged its "URL not set, skipping" warning exactly as designed.
     **Exit code: 0.**
   - **Local substitute for the listener's startup path** — `python -m
     src.fill_listener` run for 8 seconds (`timeout 8 ...`) against the
     real paper account's `trade_updates` WebSocket: no crash, no
     traceback, process was still blocking (as `run_listener()`'s
     `stream.run()` is designed to do) when the timeout killed it;
     confirmed no orphaned process remained afterward. This proves the
     entrypoint constructs its `TradingClient`/`MonitoredTradingStream`
     and subscribes without error — it does NOT prove or substitute for
     systemd's `Restart=always` behavior, which needs real systemd.
   - **Restart-safety test through systemd itself, manual daily-timer
     trigger through `systemctl`, and reboot-survival + post-reboot
     halt-state check — NOT performed, droplet-only, exact commands
     left in `deploy/systemd/README.md` for the droplet session.** This
     session has no SSH access or credentials for any droplet — these
     four checks remain genuinely unverified until run there.

**Explicit open items carried into the next droplet-side session, not
resolved here:** the three droplet-only facts from this milestone's
kickoff (real deployment path, real `.env` location, real systemd
version) plus this update's own two new open items (a design pass for
the listener's liveness heartbeat; the four droplet-only Step 5 checks)
— five items total, all requiring direct droplet access this Windows-
local session never had. [ALL FIVE NOW RESOLVED — see the "UPDATE
(droplet-side verification..." block later in this milestone's record.]

**UPDATE (claude.ai chat, same day, design only — no code written this
session): the listener liveness heartbeat's design is now LOCKED,
closing the open gap flagged immediately above** ("The listener liveness
heartbeat remains a real, open gap — needs its own claude.ai design pass
before a future session builds it, not invented here"). This is a
decision-record update only, per RULES.md §4's two-message handoff — the
implementation itself is a separate, not-yet-sent milestone brief.

**What this closes:** until now, nothing external could detect the
fill-protection listener process itself being down (as opposed to a
data/API failure the listener's own error handling already logs/alerts
for) — the daily job's heartbeat (systemd-units milestone, above) only
proves the DAILY process is alive, not the listener.

**Locked design:**
- A new periodic `asyncio` task, `heartbeat_loop()`, runs CONCURRENTLY
  with `MonitoredTradingStream._run_forever()` via `asyncio.gather()` —
  not as a separate thread/process, and not bolted onto the existing
  reconnect loop.
- Pings every 5 minutes.
- Gated on the stream's existing consecutive-failure counter (the same
  counter `MonitoredTradingStream`'s backoff/URGENT-alert-at-5-failures
  logic already tracks, spec v33 §10.5/"Current status" above) staying
  BELOW its 5-failure alert threshold — i.e. the heartbeat pings only
  while the connection itself is healthy by the listener's own existing
  definition of healthy, not on a bare "the process is still running"
  basis that could ping straight through a real outage.
- New env var `UPTIMEROBOT_LISTENER_HEARTBEAT_URL`, `required=False` —
  same fail-safe pattern already implemented for
  `UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL` (`get_heartbeat_config()`,
  `src/config.py`, systemd-units milestone above): a missing/blank URL
  skips the ping and logs a warning, never crashes the listener.
- UptimeRobot alert window: **15 minutes** (3 missed 5-minute pings,
  narrower than the daily job's ~26h window since this is a
  continuously-running process where a missed heartbeat is meaningful
  within minutes, not a once-daily job).

**Verified against actual installed source during design, not assumed —
this changes the listener's entrypoint shape, not just adds a task
alongside it:** `TradingStream.run()` (installed alpaca-py 0.43.5,
`alpaca/trading/stream.py`, already cited in `fill_listener.py`'s own
module docstring for the backoff-timing finding) wraps
`_run_forever()` in `asyncio.run()`, which owns and closes its own event
loop — `asyncio.run()` cannot be nested inside another coroutine's
`asyncio.gather()`. **Consequence: `run_listener()`'s entrypoint must
call `_run_forever()` directly inside its own `async def main()`,
gathered together with the new `heartbeat_loop()`, NOT call
`stream.run()`** (which is what `run_listener()` currently does — see
"Current status" above, fill-protection listener milestone). This is a
structural change to the entrypoint, not an additive one — flagged here
so the next session doesn't try to bolt `heartbeat_loop()` onto the
existing `stream.run()` call and silently fail to share the loop.

**Not yet implemented — this update is the design record only.** The
next session building this must: replace `run_listener()`'s
`stream.run()` call with an `async def main()` that
`asyncio.gather()`s `_run_forever()` and the new `heartbeat_loop()`;
add `heartbeat_loop()` and wire it to the existing consecutive-failure
counter; add `get_heartbeat_config()`'s `listener_url` field (or a
sibling function) for `UPTIMEROBOT_LISTENER_HEARTBEAT_URL`; document the
new var in `.env.example`; update `deploy/systemd/trading-bot-
listener.service`'s `README.md` if the entrypoint's async behavior
changes anything about how systemd should supervise it (not expected to,
since `Type=simple`/`ExecStart` stay the same either way, but confirm
rather than assume); and add tests proving the heartbeat only fires
below the 5-failure threshold and never on top of a stream that's
already down. This closes one of the two open items from the
systemd-units milestone's "Explicit open items" list above — the other
four droplet-only Step 5 checks are untouched by this update.

**UPDATE: the listener liveness heartbeat milestone is now IMPLEMENTED,
matching the locked design above exactly — committed as `4374ce7` on
`paper`, full suite 286/286 passing (275 + 11 new: 2 in
`tests/test_config.py`, 9 in `tests/test_fill_listener.py`).**

**CORRECTION, flagged not silently fixed (commit messages are immutable,
so this can't be corrected at the source): `4374ce7`'s own commit
message cites "spec v33/v34" for this design — that citation has no
textual basis in this repo (the design-lock section above, added by
`7faf995`, cites no spec version at all) and was Claude Code's own
unsupported inference, stitched from the two neighboring sections'
citations (spec v33 §10.5 = the original fill-listener; spec v34 §10.6 =
the systemd units) rather than from anything sourced. Per the user,
this design was actually locked under **spec v36** (project knowledge,
not this repo). Recorded here as the correction of record.

1. **Entrypoint restructured as the locked design required, verified
   before writing any new code, not assumed:** `run_listener()`
   (`src/fill_listener.py`) previously called `stream.subscribe_trade_
   updates(_handler)` followed by `stream.run()` — confirmed directly
   from the file before this milestone touched it, matching the locked
   design's premise exactly (it did NOT already drive `_run_forever()`
   inside its own `async def main()`). Now builds `async def main():
   await asyncio.gather(stream._run_forever(), heartbeat_loop(stream))`
   and calls `asyncio.run(main())`, wrapped in `try/except
   KeyboardInterrupt` for parity with the old `.run()` behavior (which
   caught it internally). `subscribe_trade_updates()` is still called
   synchronously before the event loop starts, unchanged.
2. **`heartbeat_loop(stream, interval_seconds=300, sleep_fn=asyncio.
   sleep, send_fn=send_listener_heartbeat)`** loops forever, sleeping 5
   minutes between ticks, delegating each tick to a new `_heartbeat_tick()`
   helper — factored out specifically so tests can exercise the gating
   logic directly without driving an infinite async loop to completion.
   `_heartbeat_tick()` pings via `send_fn()` only while `stream.
   _consecutive_failures < stream._alert_threshold` (both pre-existing
   `MonitoredTradingStream` attributes — no new counter introduced),
   else logs at info level and skips, exactly matching the locked
   design's "pings only while the connection itself is healthy by the
   listener's own existing definition of healthy" requirement.
3. **`send_listener_heartbeat()`** (`src/fill_listener.py`) and
   **`get_listener_heartbeat_config()`** (`src/config.py`) mirror
   `send_daily_heartbeat()`/`get_heartbeat_config()` exactly, per the
   locked design: reads `UPTIMEROBOT_LISTENER_HEARTBEAT_URL`,
   `required=False`; a missing/blank URL logs a warning and returns
   `False` rather than raising; the ping call itself is wrapped in its
   own `try/except` so a monitoring-side failure is logged and returns
   `False`, never propagates. `HeartbeatConfig` gained a new
   `listener_url: str | None = None` field alongside the existing
   `daily_job_url` — additive, backward-compatible.
4. **`UPTIMEROBOT_LISTENER_HEARTBEAT_URL` documented in `.env.example`**,
   same placeholder-value convention as `UPTIMEROBOT_DAILY_JOB_
   HEARTBEAT_URL`, with the comment describing its ~15-minute
   UptimeRobot alert-window recommendation on its own line above the
   `KEY=value` line — confirmed NOT to repeat the trailing-inline-comment
   parsing bug the systemd-units milestone's `EnvironmentFile=` handling
   had to avoid.
5. **`deploy/systemd/trading-bot-listener.service` needed no change** —
   confirmed, not assumed: its `ExecStart=... python -m src.fill_
   listener` still resolves to `run_listener()` via the module's
   unchanged `if __name__ == "__main__":` block; `Type=simple` and
   `Restart=always` are unaffected by the entrypoint's internal
   asyncio restructuring.

**Tests** (11 new): heartbeat fires when the failure count is below
threshold, skipped at/above threshold (both via `_heartbeat_tick()`
directly), `send_listener_heartbeat()` no-ops with a logged warning when
the URL is unset (never raises), pings the configured URL, falls back to
the env var when no URL arg is given, swallows a ping-call exception and
returns `False`; a `_heartbeat_tick()` test confirming a caller-supplied
`send_fn` exception is `send_listener_heartbeat()`'s own responsibility
to swallow, not a second safety net inside `_heartbeat_tick()` itself;
`heartbeat_loop()` pinging once per interval via injected `sleep_fn`/
`send_fn` (loop driven to completion via a `sleep_fn` that raises
`asyncio.CancelledError` after 3 ticks, since it would otherwise run
forever) and skipping the ping entirely while the injected stream is
unhealthy; plus 2 `get_listener_heartbeat_config()` tests
(`tests/test_config.py`) mirroring the existing `get_heartbeat_config()`
coverage pattern. This closes the second of the two open items from the
systemd-units milestone's "Explicit open items" list at the time this
paragraph was first written. **CORRECTION (see UPDATE immediately below):
the claim that the four droplet-only Step 5 checks "remain genuinely
unverified" was stale the moment it was written — they had, in fact,
already been run and passed live on the droplet on or immediately before
2026-08-21, before paper soak began. That result was never reported back
into this repo until the next session (see below), so this paragraph
stated an inaccurate "still open" status for a full session — the exact
gap RULES.md §4 now has a new bullet about (added the same session this
correction was made).**

**UPDATE (droplet-side verification, performed directly against the real
droplet on/immediately before 2026-08-21, guided by claude.ai, reported
back to Claude Code and recorded here on 2026-08-22 — this closes the
systemd-units milestone (spec v34 §10.6) FULLY; nothing droplet-side
remains open from it.**

**Droplet facts (confirms the `/opt/trading-bot` convention this repo
adopted without droplet access — see the "systemd-units milestone"
section above — was correct, not just a working assumption):**
DigitalOcean, region `nyc1`, Ubuntu 24.04.4 LTS, systemd 255, Python
3.12.3. Repo at `/opt/trading-bot`, venv at `/opt/trading-bot/venv`,
`.env` at `/opt/trading-bot/.env`, both owned by the `tradingbot` system
user. This also answers items 1, 4, and 5 of the "Pre-implementation
verification checklist" above (deployment path/venv location, `.env`
location, systemd version) — all three were flagged there as
NOT-VERIFIABLE-from-this-session; all three are now confirmed, and the
adopted convention matched reality exactly.

**All four Step 5 checks — PASS, all four, run live:**
1. **Manual daily-job trigger** — `systemctl start trading-bot-daily.
   service` ran to completion; a real Alpaca paper API call succeeded;
   `run_log` returned `{'errors': [], 'halted': False, ...}`.
2. **Restart-safety** — `kill -9` on the listener's live PID; systemd
   restarted it with a new PID within `RestartSec=10` (journal:
   `Failed with result 'signal'` → `Scheduled restart job` →
   `active (running)`).
3. **Reboot survival** — a real reboot; both `trading-bot-listener.
   service` and `trading-bot-daily.timer` came back `active`/`enabled`
   on their own with new PIDs, no manual intervention.
4. **Halt-state-on-boot** — `halt_state.set_halt()` called manually to
   simulate a pre-crash halt; confirmed persisted in `halt_state.json`
   and respected by `run_daily_execution_job()` across the real reboot
   (`run_log` showed `'halted': True`, entries skipped, ratchet step
   still executed — matching this repo's own documented "gate NEW risk
   on halt, never gate EXISTING protection on it" design intent, item 3
   of the pre-implementation checklist above).

**Net: all five items from the systemd-units milestone's "Explicit open
items" list (three droplet-only facts + the four Step 5 checks, the
listener-heartbeat design pass having already closed separately, above)
are now RESOLVED. The systemd-units milestone (spec v34 §10.6) is
CLOSED — no droplet-side work remains open from it.**

**NEW DECISION, LOCKED (spec v38 §10.8, claude.ai chat session — no code
written yet, this update only records the decision per this file's own
"update whenever a real decision is made" rule): the heartbeat-monitoring
provider is changing from UptimeRobot to Healthchecks.io (free Hobbyist
plan).** Rationale: UptimeRobot's heartbeat-monitor feature requires a
paid Solo-tier subscription (~$10-11/mo) — confirmed against their live
pricing page — whereas Healthchecks.io's Hobbyist plan is free ($0/mo,
20 checks available, this project needs 2: the daily job and the
listener), has native Telegram integration, and is purpose-built for the
dead-man's-switch pattern already implemented here.

**This does NOT change the heartbeat mechanism already implemented and
committed in `4374ce7`/`2dd168e`** — the 5-minute interval
(`heartbeat_loop()`), the gating condition (`stream._consecutive_failures
< stream._alert_threshold`), the `required=False` fail-safe read
(`get_heartbeat_config()`/`get_listener_heartbeat_config()`), and the
failure-isolation `try/except` around each ping call are all unchanged.
**Only the service the ping URLs point to changes, plus the env var
naming** (`UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL`/
`UPTIMEROBOT_LISTENER_HEARTBEAT_URL` will need renaming to something
provider-neutral, e.g. a `HEALTHCHECKS_*` prefix — exact names to be
specified in the follow-up milestone brief, not decided here). **Not yet
implemented — a follow-up milestone brief renaming the env vars (and
updating `.env.example`/`src/config.py`/`src/execution.py`/
`src/fill_listener.py` accordingly) is coming next; no code, test, or
`.env.example` change has been made for this decision yet.**

**UPDATE: the env var rename milestone was EXECUTED.** Verification
checkpoint run first, per instruction: confirmed the exact pre-rename
names (`UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL` in `.env.example`/
`get_heartbeat_config()`, `UPTIMEROBOT_LISTENER_HEARTBEAT_URL` in
`.env.example`/`get_listener_heartbeat_config()`), the exact field names
on `HeartbeatConfig` (`daily_job_url`, `listener_url` — unchanged, only
the env var strings they're read from changed), and the exact
ping-sending functions (`send_daily_heartbeat()`, `src/execution.py`;
`send_listener_heartbeat()`, `src/fill_listener.py`) — all matched the
brief exactly, no mismatch found.

Renamed: `UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL` ->
`HEALTHCHECKS_DAILY_HEARTBEAT_URL`, `UPTIMEROBOT_LISTENER_HEARTBEAT_URL`
-> `HEALTHCHECKS_LISTENER_HEARTBEAT_URL`, in `.env.example`,
`src/config.py` (both `_get(...)` calls), the two `log.warning(...)`
messages that embedded the old var name literally (`send_daily_
heartbeat()`/`send_listener_heartbeat()`), and every test referencing
the old names (`tests/test_config.py`, `tests/test_execution.py`,
`tests/test_fill_listener.py` — env var keys and the one log-message
substring assertion that had to track the renamed warning text; test
fixture URL values like `"https://uptimerobot.example/..."` were left
untouched as arbitrary opaque strings, not "env var names," per the
brief's explicit "do not change test behavior/assertions beyond the
name swap" scope). Also updated, as a consistency fix within the same
edit (not scope creep — leaving stale "UptimeRobot" prose directly next
to a newly-renamed `HEALTHCHECKS_*` var would itself be exactly the kind
of stale-fact drift RULES.md warns against): the "UptimeRobot" mentions
in `.env.example`'s comment prose, `get_heartbeat_config()`/
`get_listener_heartbeat_config()`'s docstrings, `send_daily_heartbeat()`/
`send_listener_heartbeat()`'s docstrings, and one mention in
`fill_listener.py`'s module docstring — each now reads "Healthchecks.io"
for the current mechanism, with a "Provider note (spec v38 §10.8)"
sentence added alongside stating the rename explicitly rather than
silently overwriting the history of what it used to be. Confirmed no
other file (including the real, gitignored local `.env`) referenced
either the old or new var names — the local `.env` was never filled in
with a real heartbeat URL, so nothing there could have drifted.

Behavior is byte-for-byte unchanged: the `required=False` fail-safe
read, the missing-URL warning-and-no-op path, the ping call's
`try/except` isolation, the 5-minute `heartbeat_loop()` interval, and
the `_heartbeat_tick()` gating logic (`stream._consecutive_failures <
stream._alert_threshold`) were not touched — this was a rename only,
confirmed by the unchanged 286/286 pass count (no test assertion on
behavior needed to change, only the literal strings each test
monkeypatches/asserts against).

Out of scope, per instruction, and not done: creating the actual
Healthchecks.io account, checks, or Telegram integration — that remains
a separate manual/claude.ai-side task.

**UPDATE (spec v39/playbook v39, next session): the heartbeat-monitoring
milestone (env var rename, `6f9a524`+`c322a67`) is now fully deployed and
live-verified end-to-end. No code changed this session — this update is
a status record only.**

1. **Healthchecks.io account setup — COMPLETE.** `trading-bot-listener`
   check: Simple schedule, Period 5 min, Grace 10 min, Telegram
   integration on. `trading-bot-daily-job` check: **corrected from the
   original plan during setup** — a plain Period=1 day schedule would
   have false-alarmed every weekend, since the daily job only runs
   weekdays; configured instead as a Cron schedule `0 17 * * 1-5`,
   timezone `America/New_York`, Grace 45 min, Telegram integration on.
   Droplet's `/opt/trading-bot/.env` updated with both real ping URLs;
   the stale `UPTIMEROBOT_DAILY_JOB_HEARTBEAT_URL` placeholder and its
   19-line comment block were removed (a `.env.bak` backup was taken
   first).

2. **Deployment gap found and fixed — a new category of gap, distinct
   from the repo-backup (local-not-pushed) gap flagged earlier this
   week.** The droplet was **6 commits behind `origin/paper`**, still
   sitting at `da81cee` (the systemd-units commit) — meaning the entire
   heartbeat feature (`4374ce7`, `2dd168e`, and everything after,
   through `c322a67`) had been committed, tested, and pushed weeks
   earlier but **never actually deployed to the droplet**. A plain
   `systemctl restart` after editing `.env` just relaunched the same
   stale pre-heartbeat code with no visible error — only silence (zero
   heartbeat log lines, the Healthchecks.io check never went green).
   Root-caused via `grep -n "heartbeat" src/fill_listener.py` on the
   droplet returning no matches, then `git log HEAD..origin/paper
   --oneline` showing the 6 missing commits. Fixed via `git pull origin
   paper` on the droplet (fast-forwarded `da81cee..c322a67` cleanly, 9
   files, no local drift, no new dependency introduced). Listener
   restarted with the current code (PID 80146, 17:08:47 UTC) and
   confirmed pinging Healthchecks.io successfully ~5 minutes later
   (dashboard went green with a real Last Ping timestamp).

3. **Permission incident found and fixed.** An earlier `git fetch`/`git
   status` run as root on the droplet left `.git/FETCH_HEAD`
   root-owned, which blocked the first `sudo -u tradingbot git pull`
   attempt with `"Permission denied."` Fixed via `chown -R
   tradingbot:tradingbot /opt/trading-bot/.git`. Confirmed via `find
   /opt/trading-bot -not -user tradingbot -not -group tradingbot` that
   no other repo files were affected (only `.env.bak`, expected).

4. **Two new permanent rules added to `RULES.md` §4 this session** (see
   that file — content authored in the claude.ai chat, not originated
   here, per the file's own §1/§6 convention and the process correction
   from earlier this week): droplet-deployed-state must be checked
   independently of push state before any droplet-side milestone is
   marked complete; git commands on the droplet must run as
   `sudo -u tradingbot`, never as root, to avoid leaving `.git`
   internals root-owned.

**Current live status:** `trading-bot-listener`'s heartbeat is confirmed
pinging successfully from the real droplet. `trading-bot-daily-job`'s
heartbeat is configured and Telegram-connected but has not yet received
its first ping — expected, since it's waiting on its next scheduled
weekday 17:00 ET run, not a gap.

**UPDATE (spec v40/playbook v40, next session): first paper-soak
check-in (2026-08-21 through 2026-08-25), droplet investigation only —
no code changes this session.** Soak confirmed healthy overall; six
items investigated and closed or recorded below.

1. **Listener SIGKILL incident, 2026-08-21 18:48:26 UTC.** The listener
   process was killed via SIGKILL (`status=9/KILL`, uncatchable by the
   app) 2m18s after starting. **Root cause NOT confirmed** — the kernel
   log (`journalctl -k`) had already rotated past the window by the time
   this was investigated, so OOM could not be proven directly. Droplet
   memory was found critically low at investigation time (458MB RAM, 0
   swap, 13MB free), making OOM a plausible but unproven cause.
   **Mitigation applied, not a proven fix for this specific incident:** a
   1GB swap file added at `/swapfile`, persisted in `/etc/fstab`,
   confirmed active via `swapon --show`. No further SIGKILL events since.
2. **Daily job's first-ever run crashed 2026-08-21 18:34:02 UTC** on
   `"Missing required env var: ALPACA_LIVE_API_KEY"`. **Fully traced and
   CLOSED as a one-time mid-provisioning `.env` editing artifact, not a
   code defect:** (a) `config.py`'s `get_alpaca_config()`/`TRADING_ENV`
   logic is correct — this error is only reachable if `TRADING_ENV` was
   explicitly non-`"paper"` in `.env` at that exact moment; (b) root was
   logged in continuously from 08-21 15:13:32 to ~19:02, spanning the
   incident, immediately followed by a reboot; (c) the job succeeded 10
   minutes later once `.env` reached its intended state. No live trade
   was ever at risk — the crash occurs before any Alpaca API call.
3. **Zero trades submitted across all 4 soak days (08-21, 08-24) —
   fully investigated and CONFIRMED as a genuine "no Donchian breakout
   across any of the 8 ETFs" market outcome, not a silent ingestion
   failure.** Traced the real call path: `run_daily_execution_job()`
   (`execution.py:1277`) -> `fetch_track_b_symbol_data()` ->
   `build_symbol_series()` (`scripts/backtest_etf_donchian.py`) ->
   `fetch_historical_stock_candles()` (`data_ingestion.py:76`), confirmed
   using `StockHistoricalDataClient`/`StockBarsRequest` on real daily
   bars for the 8-ETF Track B universe. Confirmed the fetch step's error
   handling sends a Telegram alert on any failure (not a silent
   swallow) — user confirmed no such alert was received either day.
   **Note for the record:** `data_ingestion.py` also contains a separate,
   older `fetch_historical_candles()` function for a 2-symbol crypto
   universe (BTC/USD, ETH/USD) — leftover from the rejected crypto
   track, confirmed genuinely dead code for Track B's live path, no
   action needed.
4. **Manual halt test found in logs at 2026-08-21 19:10:48 UTC**
   (`halt_reason`: `"manual test — verifying halt persists across
   restart"`), occurring during the same setup window as item 2 above.
   User was asked directly whether this was planned testing and said
   they are not sure. **RECORD AS UNCONFIRMED — do not describe this as
   a confirmed intentional test in any future context.** Current
   `halt_state.json` is clean (`halted: false`) regardless.
5. **New open item, not yet scoped, non-urgent:** the daily job
   currently logs only a single summary line per run (the final result
   dict) plus any warnings — no per-symbol fetch/signal visibility. This
   made investigating item 3 above harder than necessary (required
   source tracing across 3 files plus a Telegram-scrollback check,
   rather than reading logs directly). Flagged as a candidate future
   milestone: add DEBUG-level per-symbol fetch/signal logging to
   `run_daily_execution_job()`'s path. Not started — needs a fresh,
   explicit instruction.
6. **`trading-bot-daily-job`'s Healthchecks.io heartbeat is still not
   yet ping-verified** as of this session — the investigation ran before
   the 17:00 ET scheduled slot. Pending confirmation next session (see
   the spec v39/playbook v39 update above for `trading-bot-listener`'s
   heartbeat, already confirmed pinging). **UPDATE (same day, 2026-08-25):
   now LIVE-VERIFIED** — Healthchecks.io dashboard confirmed `trading-bot-
   daily-job` at "Last Ping: 18 minutes ago" following today's scheduled
   17:00 ET run, its first real ping ever. **The full heartbeat-monitoring
   milestone (design v37 -> code/rename v38 -> account setup + listener
   live-verify v39 -> daily-job live-verify v40) is now completely closed
   on both checks.**

**UPDATE (spec v41, claude.ai chat session, design only — no code
written yet): the first paper-soak check-in (v40) and the full
heartbeat-monitoring milestone (v37-v40) are both formally CLOSED as of
this session** — soak confirmed healthy 2026-08-21 through 2026-08-25
(SIGKILL incident mitigated with the swap file, root cause itself
unrecoverable since the kernel log had already rotated past it; the
one-time `ALPACA_LIVE_API_KEY` crash traced and closed as a
mid-provisioning `.env` edit artifact, not a code defect; the
zero-trades-across-4-days outcome traced end to end
(`run_daily_execution_job()` -> `fetch_track_b_symbol_data()` ->
`fetch_historical_stock_candles()`, `data_ingestion.py`) and confirmed as
a genuine "no breakout" market outcome, not an ingestion failure) — all
matching, not superseding, the detail already recorded above. Also
reconfirmed this session: `data_ingestion.py`'s crypto/intraday fetch
path (`fetch_historical_candles()`, `TRADING_PAIRS = ["BTC/USD",
"ETH/USD"]`) is dead code for Track B's live path, unrelated to and
requiring no changes for the item below.

**NEW DESIGN LOCKED, NOT YET IMPLEMENTED (spec v41 §10.10): a daily-job
per-symbol DEBUG logging enhancement**, closing the "new open item"
flagged in the v40 update above (`run_daily_execution_job()`'s
single-summary-line logging made investigating the zero-trades outcome
harder than necessary). Full design detail is in spec v41 §10.10
(project knowledge, not this repo) — this update only records the
decision to build it, per this file's own "update whenever a real
decision is made" rule; no code, test, or log-statement change has been
made for it yet. **The next message in this session is the milestone
brief for this build.**

**UPDATE (spec v42 §10.11): the milestone brief's pre-implementation
verification checkpoint surfaced one real, blocking data-availability
gap and two smaller structural points — all three now RESOLVED, per
instruction, before any code was written.**

1. **Fetch-step logging (v41 req #2): confirmed implementable exactly as
   specified, no changes needed.** `fetch_track_b_symbol_data()`
   (`execution.py`) already loops per-symbol — not a batched
   multi-symbol request — and `build_symbol_series()`'s returned dict
   already carries the full candle list, so bar count and first/last
   bar date are directly available at that loop.
2. **Signal-evaluation logging (v41 req #3): blocking gap resolved.**
   `generate_daily_candidates()` had no access to the actual Donchian
   upper/lower band values — only `entry_indices` (a boolean
   fired/not-fired set) and `atr` — because
   `compute_channel_long_entry_indices()` (`scripts/
   backtest_etf_donchian.py:230-247`) computed `upper`/`lower` via
   `compute_donchian_levels()` and then discarded them. **Resolved:**
   `upper` and `lower` are added as two new, additive keys to
   `build_symbol_series()`'s returned dict, populated from the
   `compute_donchian_levels()` call already made inside
   `compute_channel_long_entry_indices()` — no existing key changes, no
   existing caller's behavior changes. This was chosen over the
   alternative (recomputing the bands a second time independently
   inside `execution.py`) specifically to avoid a drift risk between two
   separate call sites on `channel_length`.
3. **Two smaller points, approved as proposed:** (a) the `if __name__ ==
   "__main__":` block (`execution.py:1411-1432`) is extracted into a
   callable `main()` function — same calls, same order, no behavior
   change — needed so `LOG_LEVEL` is testable and so a real
   `caplog`-based regression test can pin the existing INFO summary
   line's exact text (no such test existed before this milestone); (b)
   the DEBUG signal-check (close/upper/lower/signal) is computed for
   every universe symbol regardless of open-position status, purely for
   logging — the existing open-position skip that governs actual
   candidate generation in `generate_daily_candidates()` is untouched.

Implementation proceeds now, per instruction, against this resolved
design.

**UPDATE: the daily-job per-symbol DEBUG logging milestone (spec v41
§10.10 / v42 §10.11) is now IMPLEMENTED — committed as `e842ce6` on
`paper`.**

1. **`scripts/backtest_etf_donchian.py`** — `compute_channel_long_entry_
   indices()` now returns `(entry_indices, atr, upper, lower)` (was
   `(entry_indices, atr)`) — `upper`/`lower` are the same
   `compute_donchian_levels()` arrays it already computed internally for
   the entry check, previously discarded, now also returned; no
   recomputation, no drift risk against a second, independent call site.
   `entry_indices`/`atr` themselves are byte-for-byte unchanged.
   `build_symbol_series()` stores the two new values as additive
   `"upper"`/`"lower"` keys in its returned dict — every existing key
   (`symbol`/`candles`/`atr`/`entry_indices`/`date_index`) is untouched.
   3 existing tests in `tests/test_backtest_etf_donchian.py` updated to
   unpack the 2 new return values (one gained real assertions on
   `upper`/`lower`'s computed values, verified against the fixture's
   actual window rather than guessed).
2. **`src/config.py`** gained `get_log_level()` — reads `LOG_LEVEL`,
   `required=False`, default `"INFO"` (reproducing the level
   `execution.py`'s `__main__` hardcoded before this milestone exactly).
   `LOG_LEVEL` documented in `.env.example`.
3. **`src/execution.py`**:
   - `fetch_track_b_symbol_data()` gained one `log.debug(...)` line per
     symbol at its existing per-symbol loop — bar count + first/last bar
     date, or an explicit `"0 bars returned"` message — using data
     (`series["candles"]`) already available at that point, no new
     fetch or computation needed.
   - `generate_daily_candidates()` gained one `log.debug(...)` line per
     universe symbol (close, `donchian_upper`, `donchian_lower`, and a
     synthesized `signal=entry_signal`/`no_signal` label, or an explicit
     `"no data for {today}"` message when the symbol has no series/no
     bar for today) — per the resolved design, computed BEFORE the
     `open_symbols` skip, so a symbol already holding a position still
     gets a DEBUG line; candidate-generation behavior itself
     (open_symbols skip, entry_indices/atr checks) is unchanged.
   - The `if __name__ == "__main__":` block is now a callable `main()`
     (same calls, same order: `logging.basicConfig(level=get_log_level(),
     ...)` — was `level=logging.INFO` — then `run_daily_execution_job()`,
     the INFO summary `log.info(...)`, then `send_daily_heartbeat()`).
     `if __name__ == "__main__": main()` is the only remaining top-level
     script code.
4. **Explicitly out of scope, confirmed untouched:** the broad
   `try/except` around the fetch step in `run_daily_execution_job()`
   (no new per-symbol error isolation added); `data_ingestion.py`'s
   crypto/intraday `fetch_historical_candles()` path (confirmed dead
   code for Track B, not touched).

**Tests: 10 new (286 -> 296), full suite passing.**
`tests/test_execution.py` (8): fetch-step DEBUG bar-count/date-
range logging, fetch-step `"0 bars returned"` logging, no fetch-step
DEBUG output at INFO level; signal-evaluation DEBUG logging with real
Donchian band values (both an `entry_signal` and a `no_signal` case in
one test), signal-evaluation `"no data for {today}"` logging, signal-
evaluation DEBUG logging still firing for an already-open-position
symbol (candidate list unaffected), no signal-evaluation DEBUG output at
INFO level; and the `main()` regression test — confirms `get_log_level()`
's return value reaches `logging.basicConfig()` unchanged, AND pins the
existing INFO summary line's literal format string and args
(`record.msg == "run_daily_execution_job() result: %s"`,
`record.args == fixed_run_log`) so a future accidental format change
would fail loudly, not just compare today's rendered string. One
real, pre-existing Python `logging` quirk surfaced while writing this
test, not a bug in this milestone's code: `Logger._log()` special-cases
a single `Mapping` argument, storing it directly on `record.args` rather
than wrapping it in a 1-tuple — true of the original, unchanged
`log.info("...: %s", run_log)` call as much as after this milestone.
`tests/test_config.py` (2): `get_log_level()` default/set. Full suite:
296/296 passing.

`src/config.py`, `src/halt_state.py`, `src/signal_generation.py` (EMA/ATR/
volume + long-only crossover detection), `src/data_ingestion.py`'s
historical fetch (`fetch_historical_candles`, via Alpaca crypto market
data), `scripts/backtest.py`, and `scripts/backtest_trend_filter.py` are
real and working, with passing tests. `risk_filter.py` is now FULLY
implemented — `check_trade_count_limit()`, `check_daily_loss_limit()`,
`check_combined_open_risk_budget()`, `check_asset_class_concentration()`,
`check_drawdown_limit()`, and `evaluate()` are all real and tested; no
`NotImplementedError` remains in this file. **`src/execution.py` is now
real and tested for Track B** (see above) — the legacy crypto/Track A
bracket-order-blocked functions (`place_entry_order()`/
`place_exit_orders()`) remain `NotImplementedError`, unchanged, still
correctly blocked on the separate crypto OCO-emulation gap ("Hard
rules"). **`src/fill_listener.py` is now real and tested** (see above) —
`MonitoredTradingStream`/`handle_trade_update()`, verified against the
real paper account. `position_management.py` and `data_ingestion.py`'s
live fetch remain untouched stubs.

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

### Track B findings

1. **8-ETF rotational Donchian ensemble (executed)** — Track B's first
   backtest, spec v23 §10.1. Universe: SPY, QQQ, IWM, EFA, AGG, GLD, DBC,
   VNQ. Signal/exit/sizing unchanged from finding 14/15 (100-day causal
   Donchian channel, long-only; 3.0x ATR(14) Chandelier-style trailing
   stop; equal-risk-contribution sizing off spec §4.1's real 1%-of-equity
   risk formula, shrunk under a portfolio-level risk budget when needed —
   the first backtest since the original EMA crossover with a genuine
   ATR-based stop distance to size off, so the flat-25%-notional fallback
   MACD D1H1/RSI-mean-reversion needed was not used here). Fee model:
   0% commission (Alpaca stock/ETF) + 5bps/leg slippage (wider than GEM's
   2bps — DBC/VNQ are less liquid than the core equity ETFs in this
   universe, an explicit judgment call). `MAX_CONCURRENT_POSITIONS` = 8
   (= full universe size, a judgment call — the kickoff didn't pin N; at
   N=8 the slot-count cap never binds on its own, so the 8%
   portfolio-level risk budget is the only sizing constraint that can
   actually shrink a trade). Capital: $10,000 (`PAPER_VALIDATION_CAPITAL`,
   reused unchanged from the crypto ensemble file).

   **Data window** (see "Current status" above for the full deviation
   record): requested 2006-02-03 (DBC inception), actually available
   **2016-01-04 → 2026-08-07** (~10.6yr) — this account's Alpaca stock
   data floor, confirmed uniform across all 8 tickers, decided before any
   result existed. 3 anchored folds (not 5) — initial train 365d, then 3
   contiguous test windows, exact boundaries computed at runtime: fold 1
   test 2017-01-03→2020-03-15, fold 2 test 2020-03-15→2023-05-27, fold 3
   test 2023-05-27→2026-08-07.

   **Result:** pooled net-of-costs **+73.64%**, pooled gross-of-costs
   **+85.97%**, **3/3 folds net-positive** (fold 1 +27.97%/71 trades,
   fold 2 +14.60%/56 trades, fold 3 +16.99%/76 trades — no fold flagged
   THIN, all comfortably above the 5-trade threshold), 219 total trades
   (207 pooled), pooled max drawdown 5.69% (materially lower than any
   crypto finding's drawdown — 8-16% was typical there). **Zero signals
   were skipped for any reason** (no free slot, no risk budget) — same
   caveat as findings 13/14: this run does not exercise the risk-budget
   shrink-under-pressure path, so it provides no direct evidence on that
   mechanism specifically, only on the base signal/exit/full-target-sizing
   combination.

   **PDT / same-day round-trip check (new — crypto has no PDT
   restriction): PASS, 0 of 219 trades entered and exited on the same
   calendar day**, confirmed against the actual produced trade list, not
   just asserted from the mechanism's design (exits are processed using
   only positions already open at the start of each day's iteration, so a
   position opened today cannot be exit-checked until a later day).

   **Buy-and-hold comparison (mandatory, CLAUDE.md permanent
   requirement):** pooled 8-ETF equal-weight blend **+164.01%** — the
   strategy's pooled net-of-costs (+73.64%) does NOT beat this benchmark,
   the first Track B/crypto-lineage result to underperform buy-and-hold
   on its primary comparison (findings 1-13 also underperformed, but
   finding 14/15 had beaten it). Per-symbol pooled buy-and-hold: QQQ
   +504.8%, GLD +260.6%, SPY +243.5%, IWM +122.5%, EFA +86.9%, DBC
   +84.7%, VNQ +18.9%, AGG -9.8% — QQQ's extreme post-2016 run alone
   pulls the equal-weight blend up sharply; the strategy's 100-day
   breakout + 3x ATR trailing-stop structurally gives back a large share
   of a strong, low-volatility grind-up trend like QQQ's compared to
   simply holding it, which is a large part of the net gap.

   **Concentration check (per-symbol, pooled, informational only):**
   net-positive contributors were GLD (+$3,246.40, 25 trades — the single
   largest contributor, ~44% of total net profit), QQQ (+$2,263.30, 33
   trades), SPY (+$1,866.79, 33 trades), DBC (+$754.05, 25 trades), AGG
   (+$331.55, 14 trades); net-negative were VNQ (-$269.24, 17), EFA
   (-$302.26, 32), IWM (-$581.68, 28). 5 of 8 symbols net-positive — more
   broad-based than finding 14/15's crypto result (there, a single symbol
   ETH/USD contributed MORE than the entire pooled net gain, meaning
   every other symbol net-netted negative in aggregate); here GLD+QQQ
   together account for ~75% of net profit but no single symbol exceeds
   the total, and the negative contributors are shallow, not offsetting a
   dominant winner the way finding 14/15's structure did.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction; decision deferred to the planning chat**, same convention
   as every crypto finding. 6 tests added
   (`tests/test_backtest_etf_donchian.py`), full suite (94 tests)
   passing. Scope: backtest-only per instruction — `execution.py`,
   guardrail integration, and Track A/Track C are untouched.

### Track A findings

1. **Base GEM (Dual Momentum), no circuit breaker (executed).** Spec v22
   §10.1's design, locked as a candidate in a prior planning-chat session
   but never backtested before this run. Universe: SPY, EFA (risky pair,
   relative momentum), AGG (defensive holding), BIL (absolute-momentum
   reference rate only, never held). New script `scripts/backtest_gem.py`.

   **Data-correctness fix, confirmed empirically before writing any
   simulation code, not a style choice:** GEM's signal is a trailing
   12-month TOTAL-RETURN comparison, so `src/data_ingestion.py`'s
   `fetch_historical_stock_candles()` gained an `adjustment` parameter
   (default `RAW`, preserving Track B's already-passed behavior exactly)
   — Track A calls it with `Adjustment.ALL` (splits + dividends). RAW
   prices are demonstrably wrong for this signal: BIL's raw series has an
   uncorrected ~2x split discontinuity, and AGG's raw price-only return
   is negative over a window where its true dividend-inclusive return is
   positive — RAW would silently invalidate the absolute-momentum filter,
   not just shift results slightly.

   **Data window:** same account-level 2016-01-04 floor Track B found,
   confirmed for all 4 Track A tickers before any code was written (per
   explicit instruction, flagged before proceeding rather than silently
   applied). GEM's own 12-month lookback is treated as pure indicator
   warm-up, not a training/tuning period (GEM's parameters are fixed,
   externally-evidenced, same epistemic status as Track B's carried-over
   100d/3.0x) — usable window starts at the first evaluation point with a
   full 12-month lookback: **2017-01-31 -> 2026-07-31** (115 live monthly
   evaluation points). **2 anchored folds** (not Track B's 3 — user
   instruction, given GEM's monthly cadence and low turnover risk the
   same sample-starvation failure mode as crypto finding 9 if split
   finer): fold 1 test 2017-01-31→2021-10-29, fold 2 test
   2021-10-29→2026-07-31.

   **Adopt bar (user instruction, stricter than Track B's ≥N/2 folds):**
   pooled net-of-cost positive AND BOTH folds individually positive.

   **Result:** pooled net-of-cost **+138.90%**, pooled gross-of-cost
   **+143.39%**, 19 total holding periods (19 pooled), **18 of 19 asset
   switches** (position-change events; the 19th holding period is the
   final still-open position, marked-to-market as "eol"). **Fold 1:
   net +4.60%, 6 trades, 6 switches. Fold 2: net +128.39%, 13 trades, 12
   switches.** Both folds well above the 3-switch thin-sample threshold —
   no sample-starvation flag raised. As raw facts (not self-judged):
   pooled net-of-cost is positive AND both folds are individually
   positive.

   **Concentration note, informational:** fold 2's return is dominated by
   two long, favorable SPY holds — 2020-05-29→2022-05-31 (+$4,130.16) and
   2023-11-30→2025-04-30 (+$3,450.19) — together larger than fold 2's
   entire net gain, meaning other fold-2 holdings netted negative in
   aggregate. This is a real result, not a bug, but it means fold 2's
   headline number leans heavily on two multi-year holds landing well,
   not on an average across many similar switches.

   **IMPORTANT CAVEAT, confirmed by code inspection before reporting, not
   asserted from memory:** `max_drawdown_pct` (fold 1: 11.25%, fold 2:
   2.84%, pooled: 11.25%) is computed by `summarize()` iterating over
   `equity_curve`, which for GEM only gets a new entry when a holding
   period CLOSES — unlike Track B's daily-bar equity curve, where trades
   were short enough that this was a minor approximation. GEM can hold a
   single position for up to two years (the 2020-05-29→2022-05-31 SPY
   hold above); ANY intra-holding drawdown during that stretch is
   completely invisible to this metric. **The reported drawdown numbers
   are a lower bound on true risk, not a mark-to-market drawdown** — this
   matters directly for evaluating the circuit-breaker variants later,
   since a circuit breaker's whole purpose is reacting to intra-holding
   drawdown the base monthly signal can't see by construction. A
   continuous daily mark-to-market drawdown was flagged as a valuable
   follow-up diagnostic, not yet built (would need its own read-only
   script, same category as the Track B buy-and-hold-drawdown follow-up).

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction; decision deferred to the planning chat**, same convention
   as every other finding. 14 tests added (`tests/test_backtest_gem.py`),
   full suite (108 tests) passing. Circuit-breaker variants (15%/20%
   thresholds, spec v24 §10.2) are NOT yet implemented — exact trigger/
   action/reset mechanics were not available in this repo and were asked
   of the user before proceeding; see "Not yet decided" below.

2. **Continuous daily equity tracking + circuit-breaker variants
   (executed).** `simulate_gem()` rewritten from a month-end-only loop to
   a full day-by-day continuous simulation (see module docstring's
   "CONTINUOUS DAILY SIMULATION" section) — needed both to report a true
   mark-to-market drawdown for base GEM and to drive the breaker, which
   checks drawdown from the ALL-TIME-PEAK strategy equity every day (user
   instruction), exits fully to BIL on breach, and resumes automatically
   at the next scheduled monthly evaluation regardless of price recovery
   — an explicit, logged backtest simplification (real deployment would
   need manual review per spec §7/halt_state.py's convention, so a live
   resume would likely be slower and more conservative than this
   simulates).

   **True (continuous) max drawdown for base GEM: pooled 33.79%** (fold 1:
   33.79%, fold 2: 21.73%) — nearly 3x the trade-close-sampled 11.25%
   reported in finding 1, confirming that caveat mattered as much as
   flagged. Net/gross returns for base GEM are unchanged (19 trades,
   pooled net +138.90%) — the continuous curve is purely additive
   reporting there, since no breaker was active to change outcomes.

   **Circuit-breaker variants — result, raw facts:**

   | variant | pooled net | true max DD (global peak) | switches | breaches |
   |---|---|---|---|---|
   | Base GEM | +138.90% | 33.79% | 18 | 0 |
   | +15% breaker | +3.74% | 20.77% | 92 | 91 |
   | +20% breaker | +2.63% | 28.90% | 81 | 78 |

   Both breaker variants: pooled net-of-cost positive, but **fold 1 is
   net-NEGATIVE for the 20% variant (-3.02%)** — fails the pre-committed
   bar (both folds individually positive) on that leg; the 15% variant
   clears both folds (+0.96%, +2.75%) but by a much thinner margin than
   base GEM's own folds.

   **ROOT-CAUSE DIAGNOSIS, quantified against the actual produced trade
   list, not inferred from the headline numbers alone — this is the
   single most important thing to understand about this result:** of the
   91 circuit_breaker exits in the 15% variant, only **2 are genuine
   multi-day breach events** (SPY held 203 days before a real breach on
   2018-12-20, pnl -$972; EFA held 78 days before a real breach on
   2026-03-20, pnl -$281). **The other 89 are zero-day same-day
   re-breaches** — the position resumes at a scheduled evaluation and is
   immediately force-closed again on the SAME day, before any price can
   move at all. The 20% variant shows the identical pattern: 78 breaches,
   only 1 genuine (SPY held 377 days, breaching 2020-03-12 — this one is
   the real COVID crash, a legitimate protective event), 77 zero-day.

   **Mechanism (verified, not speculated):** the breach trigger compares
   CURRENT equity against the ALL-TIME peak, and per instruction there is
   no cooldown and no peak reset on resume. Once a real breach occurs and
   equity falls meaningfully behind the historic peak, resuming a
   position (which starts its own P&L at exactly 1.0x, zero elapsed time)
   does NOT reset the PORTFOLIO-level drawdown-from-peak check — if
   overall equity is already more than the threshold below the all-time
   peak at the moment of resume, day 0 of the new position already reads
   as "in breach," forcing an immediate re-exit regardless of what the
   newly-resumed asset does next. With no mechanism ever able to close
   that gap (real growth requires holding a risky asset for more than
   zero days, which this trap prevents), **the strategy falls into a
   permanent monthly whipsaw for essentially the rest of the backtest**
   after the first genuine breach — resume, instantly re-breach, park in
   BIL a month earning small T-bill carry, repeat. This is a faithful,
   correct execution of the literal instructed rules (all-time-peak
   trigger, unconditional resume, no cooldown) — NOT an implementation
   bug — but it means the "circuit breaker" is not functioning as a
   crash-protection overlay after its first genuine trigger; it is
   functioning as a near-permanent monthly-fee-drag mechanism instead.
   **Quantified cost of the whipsaw alone:** 15% variant — the 89
   zero-day re-breach trades sum to -$915.72 net, and $937.27 of the
   variant's $1,895.44 total fees (≈49%) came from circuit_breaker exits
   specifically. 20% variant — 77 zero-day trades sum to -$760.11 net,
   $770.57 of $1,584.26 total fees (≈49%) from circuit_breaker exits.
   Roughly half of all transaction costs paid across the entire 9.6-year
   backtest, in both variants, came from this one degenerate mechanism.

   **This reframes what the headline pooled-net numbers actually mean:**
   +3.74%/+2.63% is not "the breaker gave up some of base GEM's upside in
   exchange for genuine crash protection" — it is "the breaker correctly
   caught the one real drawdown event in each variant's path, then got
   permanently stuck whipsawing for years afterward." The true_dd%
   figures (20.77%/28.90%) look superficially reasonable (not wildly
   above their own thresholds) precisely BECAUSE the breaker keeps
   snapping equity back near the threshold every time it fires — that
   containment is real, but it comes from never allowing the strategy to
   compound again, not from a clean, one-time protective exit.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction; decision deferred to the planning chat.** Given the
   diagnosis above, the planning chat may want to treat "resume
   unconditionally with no cooldown/peak-reset" as a distinct open design
   question from "does GEM + a drawdown overlay work at all" — this
   result is not strong evidence against the latter on its own. 3 tests
   added/updated in `tests/test_backtest_gem.py` for the breaker
   mechanics (breach trigger, no-rebreach-while-breached, unconditional
   resume, daily curve construction, post-fee equity in the daily curve),
   full suite (111 tests) passing.

   **UPDATE (this session, immediately following): these two variants
   (the "v1" all-time-peak, never-reset design) are formally REJECTED —
   specification flaw, not a strategy verdict.** User instruction: reset
   the tracked peak to current equity at the moment of resuming (not at
   breach), since the alternative was a permanent lockout, not stricter
   protection. See finding 3 below for the corrected ("v2") variants —
   `scripts/backtest_gem.py` no longer reproduces the v1 behavior; these
   numbers are preserved here as historical record only, per this file's
   convention of not rewriting past findings.

3. **Circuit-breaker variants, corrected (v2, peak-reset-on-resume)
   (executed).** Same 15%/20% thresholds, same daily all-time-peak-style
   trigger and unconditional-exit-to-BIL action as finding 2 — the ONLY
   change is that the tracked peak now resets to current equity at the
   moment of resuming trading, not at breach and not before (see
   `simulate_gem()`'s "PEAK-RESET FIX" docstring section for the full
   mechanics). This deliberately changes what the guardrail promises:
   it now bounds drawdown SINCE THE LAST RESUME, not cumulative drawdown
   from the strategy's true all-time peak — a correctness fix, not a
   loosening, since the v1 alternative was a lockout.

   **Result — night and day versus v1:**

   | variant | pooled net | pooled gross | fold1 net | fold2 net |
   |---|---|---|---|---|
   | Base GEM | +138.90% | +143.39% | +4.60% | +128.39% |
   | +15% breaker v2 | +120.09% | +125.13% | +9.60% | +100.81% |
   | +20% breaker v2 | +133.38% | +138.48% | +3.07% | +126.42% |

   **Both v2 variants clear the pre-committed bar this time** (pooled net
   positive AND both folds individually positive) — v1's 20% variant had
   failed on fold 1 (-3.02%); v2's 20% variant fold 1 is now +3.07%.

   **Per-fold trade/switch/breach counts:** 15% variant — fold 1: 8
   trades (6 switches, 2 breaches), fold 2: 15 trades (12 switches, 2
   breaches). 20% variant — fold 1: 7 trades (6 switches, 1 breach), fold
   2: 15 trades (13 switches, 1 breach). Both comfortably above the
   3-position-change thin-sample threshold in every fold.

   **Requested diagnostics, all confirmed:**
   - **Worst single reset-cycle leg drawdown** (sanity check — should
     land near the threshold): 15% variant 18.42%, 20% variant 24.64% —
     both sit modestly above their own threshold (expected: a breach
     fires once drawdown reaches/exceeds the threshold, so the triggering
     day's own move can carry slightly past it before the exit executes),
     not wildly beyond it. Sanity check passes.
   - **True cumulative drawdown from the strategy's actual all-time peak**
     (global, never resets — the number that shows whether repeated
     reset cycles could still let a large loss accumulate): **15%
     variant 24.58% pooled, 20% variant 24.94% pooled — both LOWER than
     base GEM's own 33.79%.** This is the header result: the corrected
     breaker provides real cumulative risk reduction, not just a
     per-episode cap that could still be circumvented by accumulating
     losses across many reset cycles.
   - **Genuine multi-day breach count vs. residual same-day whipsaw
     resumes:** 15% variant — 4 breach exits, **all 4 genuine
     multi-day holds** (203d, 374d, 710d, 490d), **0 zero-day
     whipsaws**. 20% variant — 2 breach exits, **both genuine** (377d,
     141d), **0 zero-day whipsaws**. Confirms the fix eliminated the v1
     whipsaw pattern entirely, not just reduced it.
   - **Transaction costs, breaker-attributable (breach+resume) vs. normal
     monthly rotation:** 15% variant — $102.68 breaker-attributable vs.
     $236.80 normal rotation (total $339.48; breaker ≈30% of costs, down
     from v1's ≈49%). 20% variant — $47.54 breaker-attributable vs.
     $281.39 normal (total $328.93; breaker ≈14% of costs). The breaker
     is now a minor cost driver, not the dominant one.

   **Base GEM's true continuous drawdown (33.79% pooled), included here
   for direct side-by-side context, not just as a baseline number:** both
   breaker variants meaningfully reduce this (24.58%/24.94%) while
   capturing MOST of base GEM's return (120.09%/133.38% of 138.90% —
   roughly 86%/96%) — a genuinely favorable return-vs-drawdown trade
   this time, unlike v1's "give up 97% of the return for a
   still-not-clean drawdown number."

   One breach in the 15% variant closed at a net PROFIT relative to its
   own entry (SPY 2019-02-28→2020-03-09, +$100.09) — the position had
   risen substantially before pulling back more than 15% from its own
   post-resume peak, a legitimate trailing-stop-like dynamic, not an
   anomaly.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction; decision deferred to the planning chat.** 10 tests
   added/updated in `tests/test_backtest_gem.py` (the peak-reset
   regression test is the load-bearing one — it directly reproduces the
   v1 whipsaw setup and confirms a modest post-resume decline no longer
   re-triggers), full suite (118 tests) passing.

4. **Buy-and-hold context (executed) — mandatory per this file's own
   permanent requirement (established at crypto finding 13, carried
   forward to every track since), requested explicitly before any final
   evaluation of Track A.** New one-off script `scripts/compute_gem_
   benchmarks.py` (not meant to be maintained, same convention as
   `compute_buy_and_hold_drawdown.py`) computes buy-and-hold SPY and a
   static 60/40 SPY/AGG portfolio, both return AND max drawdown, over
   the IDENTICAL pooled window Track A's own findings use
   (2017-01-31 → 2026-07-31, reproduced from real fetched data via the
   same month-end/warm-up logic `backtest_gem.py` uses, not hardcoded).
   Same `Adjustment.ALL` dividend+split-adjusted data as GEM's own
   signal, for the same correctness reason (AGG's return is mostly
   distributions). **Judgment call, flagged:** both benchmarks are
   buy-at-window-start/hold-to-window-end with NO rebalancing, matching
   every other buy-and-hold figure already reported in this repo
   (Track B's convention) — a monthly- or annually-REBALANCED 60/40 is
   at least as common a convention for this specific benchmark and was
   NOT built; the reported 60/40 number lets its SPY/AGG weights drift
   with relative performance from the initial 60/40 split.

   **Result:**

   | benchmark | return | max drawdown |
   |---|---|---|
   | Buy-and-hold SPY (100%) | +279.61% | 33.79% |
   | Static 60/40 SPY/AGG (no rebalance) | +174.82% | 23.16% |
   | Base GEM (no circuit breaker) | +138.90% | 33.79% |
   | GEM + 15% circuit breaker (v2) | +120.09% | 24.58% |
   | GEM + 20% circuit breaker (v2) | +133.38% | 24.94% |

   **None of the three GEM variants beat either buy-and-hold benchmark on
   return.** Base GEM's drawdown (33.79%) is IDENTICAL to buy-and-hold
   SPY's own — not a bug (verified independently: buy-and-hold SPY's
   drawdown was computed fresh from SPY's own price series, no shared
   code path with GEM's simulation) but explained by base GEM's own trade
   log (finding 1 above): GEM was continuously holding 100% SPY through
   2019-02-28→2020-03-31, which spans the Feb-Mar 2020 COVID crash — so
   GEM's worst drawdown and SPY's worst drawdown are driven by the exact
   same underlying price move, with GEM adding no diversification benefit
   during that specific stretch. The two breaker variants get closer to
   the 60/40 blend's drawdown (24.58%/24.94% vs. 23.16%) but still
   underperform its return (120.09%/133.38% vs. 174.82%) — on this
   window, the simplest possible static allocation dominates every GEM
   variant tested on a return basis, and roughly matches the breaker
   variants on drawdown.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction; decision deferred to the planning chat.**

### Track C findings

1. **Options historical data availability check (executed) — first step
   per instruction, not a backtest.** Before locking any fold structure or
   adopt bar for the SPY put credit spread strategy (spec v25 §2, §10.5),
   checked what this account's Alpaca options data plan actually makes
   available, given both prior equity tracks hit an undiscovered data
   floor (stock data truncated at 2016-01-04, Track B finding) and options
   data is generally sparser industry-wide. New one-off script
   `scripts/check_options_data_availability.py` (same non-maintained
   convention as `select_universe.py`/`verify_finding12_sizing.py`/
   `compute_gem_benchmarks.py`).

   **Account approval:** `options_approved_level` = 3, `options_trading_level`
   = 3 on the paper account (equity $100,000, unrelated to the $10,000
   paper-validation notional used for backtest position sizing) — level 3
   covers defined-risk multi-leg spreads, so no approval-level blocker for
   the put credit spread structure.

   **Two different floors found, NOT the same — the contract-metadata one
   is a trap, flagged explicitly:** `GetOptionContractsRequest(status=
   'inactive')` search suggested SPY contract metadata is queryable back
   to expirations on/after ~2024-01-03. But testing actual
   `get_option_bars()` calls directly against manually-constructed OCC
   symbols (bypassing the contract-search floor entirely) found **zero
   bars for every SPY expiry/strike/call-or-put tested before 2024-01-18**
   — including near-ATM strikes on the same 2024-01-03 expiry the
   contract-metadata search said it could find — and **dense, continuous
   daily coverage from 2024-01-18 onward** (confirmed via a full-life scan
   of a March 2024 expiry: 40 bars, one per trading day, listing date to
   expiry, real volume throughout). **The real, usable floor for
   backtesting is 2024-01-18, not the ~2024-01-03 the contract-metadata
   search implied** — the lesson carried forward from Track B (derive the
   usable window from actual data timestamps, not from a search endpoint's
   own reported range) applied a second time, and would have been wrong a
   second time if not checked directly.

   **Ceiling:** confirmed current through 2026-08-07 (session date
   2026-08-09, same ~2-day lag pattern as the equity feeds) via a
   long-dated LEAPS contract still trading. **Feed parameter (OPRA vs.
   INDICATIVE) makes no difference** — both returned identical bar counts
   and date ranges, so this floor is a genuine account/data-plan
   limitation, not a feed-tier artifact.

   **Usable window: 2024-01-18 → 2026-08-07, roughly 2.5 years.** This is
   shorter than both prior tracks (Track A ~9.5yr usable, Track B
   ~10.6yr) — most likely because Alpaca's options market-data product
   itself is newer than its equity data, not an account-tier restriction
   specific to this account (the floor lines up with when Alpaca is
   generally understood to have launched options market data, not with
   any SPY-specific listing gap — SPY options have traded for decades).
   2.5 years is short enough that fold structure needs care to avoid the
   sample-starvation failure mode findings 9 (crypto RSI mean-reversion,
   3 trades) and 13 (weekly-gated Donchian, 44-54 trades) already hit in
   this repo — flagged for the next step, not resolved here per
   instruction ("not a full backtest yet").

   **No fold structure or adopt bar decided this step — reporting
   availability only, per instruction.** Next step (separate, explicit
   go-ahead needed): design the put credit spread mechanics (strike
   selection, DTE, credit target) and fold structure against this
   confirmed 2.5-year window.

2. **Field-level availability check (executed) — extends finding 1, same
   step, not a new milestone.** Finding 1 confirmed the DATE floor for
   daily bars; this checked what FIELDS actually exist historically,
   since a credit-spread strategy needs enough to reconstruct
   approximately what a ~30-delta put would have cost/paid at any past
   date. Same script, extended in place (not a new file, same one-off
   convention). Checked via SDK introspection (`OptionHistoricalDataClient`'s
   method surface, `Bar`/`Trade`/`Quote`/`OptionsSnapshot`/`OptionsGreeks`
   model fields) AND confirmed live against the account, not assumed from
   the SDK alone.

   **Result: only trade-derived data has a historical record. Bid/ask and
   IV/greeks do not.** Confirmed available historically (2024-01-18
   forward, same floor as finding 1): daily OHLCV bars
   (open/high/low/close/volume/trade_count/vwap) and raw historical trade
   prints (`get_option_trades()` — price/size/timestamp/exchange/
   conditions/tape, tick-level). Confirmed NOT available historically at
   any date, checked directly rather than inferred: bid/ask
   (`OptionHistoricalDataClient` has no historical-quotes method at all —
   only `get_option_latest_quote`, current-moment only) and implied
   volatility/greeks (`implied_volatility`/`greeks` fields exist only on
   `OptionsSnapshot`, which is also latest-only — there is no
   timestamp-indexed historical counterpart anywhere in this SDK surface).

   **Practical implication for the strategy design (flagged, not
   resolved — this is a design input for the next step, not a decision
   made here):** a ~30-delta put's historical price cannot be looked up
   directly. It would need to be reconstructed: use the underlying's
   historical price + the option's own historical trade/bar price to
   back out an implied vol via Black-Scholes (treating the historical
   trade/bar close as a stand-in for the true price, since no historical
   bid/ask/mid exists to anchor to), then derive an approximate delta
   from that IV to identify which strike was ~30-delta on a given day.
   This is a real step down in fidelity from a strategy that could just
   read historical delta/IV off the data feed directly, and introduces
   its own estimation error (no way to distinguish a historical print
   from being on the bid, ask, or in between).

   **Secondary findings, both confirmed live against the account, both
   informational — neither blocks backtesting since they're about
   real-time/live access, not historical data:**
   - This account's OPRA (real-time consolidated options feed) agreement
     is NOT signed — a live snapshot request with `feed=OPRA` returns a
     403 (`"OPRA agreement is not signed"`). Historical bar requests with
     `feed=OPRA` do NOT hit this error (confirmed working in finding 1's
     ceiling check) — the restriction is specific to live/real-time
     snapshot access, not historical data, so it doesn't affect this
     track's backtesting plan, but would need resolving before any live
     put-credit-spread trading.
   - Even on the INDICATIVE feed (the one that works), live IV/greeks
     coverage was sparse in a 5-strike same-expiry sample tested just now
     — only 1 of 5 nearby SPY strikes had non-null `implied_volatility`/
     `greeks` on its snapshot, the other 4 returned a valid bid/ask quote
     but `None` for IV/greeks. Read as "Alpaca's snapshot greeks
     computation appears to require a fresher/more liquid quote than bare
     quote availability guarantees," not further diagnosed. Reinforces
     the finding above rather than contradicting it — greeks access is
     unreliable even live, let alone historically.

   **Gaps/data-quality notes, informational, from the same probing:**
   - Per-contract coverage within the usable window is NOT uniform even
     for near-ATM strikes — one specific tested contract
     (`SPY240117C00475000`, a Jan 2024 monthly) returned zero bars AND
     zero trade prints despite being well inside the confirmed
     2024-01-18+ floor window; other contracts in the same test batch had
     dense coverage. Some individual strike/expiry combinations may
     simply have no prints at all, not just thin ones — worth checking
     per-contract when the actual credit-spread mechanics are designed,
     not assuming every 30-delta candidate on every historical date will
     have data.
   - Far-dated series (e.g., a Dec 2027 LEAPS expiry) get listed
     progressively — bars for that whole expiry only start ~2025-01-02/03
     regardless of strike, well after the account's general 2024-01-18
     options-data floor. Confirmed this is a listing-timing artifact (two
     different strikes on the same far expiry both start on the same
     later date), not a data gap — but means a point-in-time historical
     options chain must be queried as of each historical date, not
     assumed from today's active contract list.

   **No fold structure or adopt bar decided this step either — reporting
   availability only, per instruction.** Same next step as finding 1:
   design the put credit spread mechanics and fold structure, pending a
   separate, explicit go-ahead — this finding is input to that design
   (specifically, how strikes get selected without historical delta),
   not a substitute for it.

3. **Design locked and executed: SPY put credit spread pooled backtest +
   separate stress-test scenario analysis (spec v25 §10.5).** Design
   (user instruction, this session): short leg nearest strike to spot *
   0.95, long leg (protection) nearest strike BELOW the short leg to
   spot * 0.92, nearest listed monthly (3rd-Friday) expiry in a 30-45 DTE
   band, continuous monthly rolling (new entry the day after the prior
   cycle resolves), held to expiration always (no early close). Two
   deliberate simplifications, both user instruction, to avoid
   compounding estimation error on top of finding 2's confirmed absence
   of historical bid/ask/IV/greeks: strikes selected by fixed %-OTM, NOT
   delta (delta would need a Black-Scholes IV inversion off a bar-close
   price standing in for a true mid — one estimation layer not built);
   both entry credit AND expiration payoff use REAL historical data
   directly (entry credit = real historical daily-bar close per leg on
   the entry date; expiration payoff needs NO option data at all — held
   to expiration, a spread's value is fully determined by the
   UNDERLYING's real closing price via intrinsic value, so there is no
   Black-Scholes anywhere in this implementation). New
   `scripts/backtest_put_credit_spread.py` and `scripts/stress_test_pcs.py`
   (the required stress-test overlay, deliberately a separate script/
   report per instruction — its numbers are never blended into the
   pooled backtest table). New `src/data_ingestion.py` functions
   `fetch_option_contracts()` (queries a chain by ITS OWN target
   expiration date directly, both 'active' and 'inactive' status merged
   — sidesteps finding 2's progressive-listing problem entirely, since a
   contract's own metadata is static regardless of when it's queried,
   rather than needing an explicit "as of" filter) and
   `fetch_option_bars()` (reuses the existing `Candle` dataclass — an
   option daily bar has the same OHLCV shape as stock/crypto, and finding
   2 already confirmed there's nothing else historically available to
   add). Chain queried per-expiration (never from "today's" list), with
   two independent, logged data-gap fallbacks per leg (nearest available
   date within 5 days, then nearest available strike, up to 6 candidates)
   — per instruction, a missing data point is logged and worked around,
   never silently skipped. Sizing: spec §4.1's REAL formula (unlike
   MACD D1H1/RSI mean-reversion/GEM, this strategy has a genuine,
   structurally-defined max loss to size off, so no flat-notional
   fallback was needed) — risk_amount = equity × 1%, contracts =
   floor(risk_amount / ((width − credit) × 100)). Fees: $0/contract
   commission (per instruction) + a flagged, unmeasured slippage
   judgment call ($0.10/share = $10/contract per leg, entry only, same
   epistemic status as every other slippage placeholder in this repo).
   2 anchored folds (user instruction, GEM's convention) over
   [2024-01-18, last available data], reusing `compute_fold_boundaries()`
   (backtest_walkforward.py) and `slice_trades_by_folds()`
   (backtest_donchian.py) completely unchanged — this strategy is
   single-position and strictly sequential, so entry order and exit/
   equity-realization order are always identical, exactly what that
   slicer already assumes. 22 new tests
   (`tests/test_backtest_put_credit_spread.py`,
   `tests/test_stress_test_pcs.py`), full suite (140 tests) passing.

   **RESULT — the pooled backtest produced ZERO trades. Not a
   signal-quality result: a capital/strike-width sizing mismatch,
   confirmed quantitatively, not just observed as an empty table.**
   28 monthly cycles were built from real data (2024-01-18 → 2026-08-10,
   the account's confirmed options-data window) with real entry credit
   and real expiration payoffs computed successfully for every one —
   only 2 were skipped at the data-fetch stage (`no_contracts_for_expiry`),
   and the data-gap fallback machinery worked as designed (used on 1/28
   cycles for the short leg, 4/28 for the long leg — never needed on more
   than a small minority). But EVERY SINGLE ONE of the 28 cycles was then
   skipped at the sizing stage (`sizing_floor_zero`), both net-of-cost and
   gross-of-cost: mean max loss per contract across the 28 real cycles was
   **$1,710** (range $1,261–$2,085, driven by the 5%/8%-OTM design's own
   ~$15–22 strike width on SPY at $476–$744 spot over this window) against
   a 1%-of-$10,000 risk budget of **$100** — the budget covers only
   **~5.8%** of one contract's structural max loss. This is a deterministic
   arithmetic fact of the strike-width/capital combination, not sampling
   noise or an edge case — it recurred on all 28/28 cycles regardless of
   how much real credit was collected (real gross credit ranged
   $0.45–$2.60/share, i.e. $45–$260/contract, itself a small fraction of
   the $1,500–2,000 width side of the loss). Pooled/per-fold net% and
   gross% both read 0.00% because there is no trade to generate a return
   from — this must NOT be read as "the strategy broke even" or as any
   information about signal quality; the backtest never got the chance to
   evaluate the signal at all. Buy-and-hold SPY over the same pooled
   window was +55.99% (fold 1 +10.48%, fold 2 +41.20%), reported per the
   permanent buy-and-hold requirement, though it isn't a meaningful
   comparison here for the same reason. Secondary, non-blocking
   methodology note: 19/28 cycles needed the DTE-band-widen fallback
   (actual DTE outside [30,45]) — mechanically explained, not a bug: the
   "roll the day after the prior expiry" cadence lands each new entry
   right after a 3rd-Friday, and the very next monthly 3rd-Friday is
   almost always 27-29 DTE (just under the 30-day floor) while the one
   after that is 55-63 DTE (well over the 45-day ceiling), so the exact
   [30,45] band is structurally hard for a pure "roll immediately" cadence
   to land inside — flagged for awareness, not a cause of the zero-trade
   result (which is 100% sizing-driven regardless of DTE).

   **Stress-test scenario analysis (SPY underlying price only, no options
   data needed — separate report, not blended into the numbers above)
   independently confirms the same structural mismatch, via a completely
   different mechanism (real 2018/2020/2022 crash data instead of
   2024-2026 real credit):** all three windows (Feb 2018 "Volmageddon",
   Feb-Mar 2020 COVID crash, Sept-Oct 2022 bear-market low) breached to
   **100% of the structural max loss** (short strike fully breached and
   the trough fell past the long strike in every case: SPY fell -8.6%,
   -30.8%, -9.8% respectively against a short strike only 5% OTM) — and
   all three ALSO sized to **0 contracts** under the same 1%-of-$10,000
   budget against each window's own structural width ($900, $1,000,
   $1,100 max loss per contract respectively). Every judgment call this
   script had to make (entry timing = last trading day before the window,
   strikes rounded to the nearest $1 since no chain data exists that far
   back, structural width used as "max loss" since real credit isn't
   knowable pre-2024) is flagged explicitly in the module docstring, not
   silently resolved.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction, same convention as every other finding in this repo.**
   Both pieces are reported back for the user to validate together before
   any adoption call, per the session's own framing — this finding
   record does not pre-judge what should happen next (e.g. whether the
   sizing formula, the strike widths, or the capital basis should change)
   since no instruction to do so has been given yet.

4. **Redesigned rerun (executed): two pre-registered changes, reasoned
   independently of finding 3's zero-trade result, not a reaction to
   it.** (a) Strike zone narrowed from the fixed 5%/8%-OTM target to a
   NARROWEST-ACHIEVABLE search within a 2-4% OTM zone — checked against
   the real chain per cycle (not assumed), via new
   `select_narrow_spread_strikes()` (replaces
   `select_spread_strikes()`, removed, not left in as dead code — a full
   design replacement, per the session's framing). (b) Sizing raised to
   a **defined-risk-specific 2%** of equity per spread
   (`PCS_RISK_PER_TRADE_PCT`), justified because a credit spread's max
   loss is contractually fixed at entry — scoped explicitly to this file
   only, `DEFAULT_RISK_PER_TRADE_PCT`/`risk_filter.py`/`.env` (spec
   §4.1's global 1%) are untouched. `scripts/stress_test_pcs.py` updated
   to match both changes (strike zone; sizing), with a flagged,
   carried-over assumption: since no options chain exists before
   2024-01-18, the stress test's $1 strike increment is asserted from
   the main backtest's own confirmed-real result (see below), not
   independently guessed for 2018/2020/2022. 8 tests
   updated/added across both test files, full suite (142 tests) passing.

   **Real strike-availability check (done before any code changed, per
   instruction): SPY lists $1 strikes uniformly throughout the 2-4% OTM
   zone**, confirmed across 3 sampled real expiries spanning the whole
   backtest window (2024-02-20, 2025-07-21, 2026-06-22) — every in-zone
   strike's immediate lower neighbor was exactly $1 away, no exceptions.
   The rerun confirmed this holds across all 28 real cycles too: achieved
   width was **exactly $1.00 for all 28** (min=mean=max=$1.00), and the
   truly-narrowest in-zone candidate had usable data every time (0/28
   needed a wider fallback candidate) — the liquidity-fallback machinery
   built for finding 3 was never actually exercised at this width.

   **Result — the sizing floor-to-zero problem is GONE, but a NEW,
   DIFFERENT bottleneck replaced it: net credit is too thin relative to
   the slippage assumption on most cycles, not too small to size.**
   Sizing diagnostics: 0/28 cycles skipped for zero-sizing (net OR gross
   — a complete reversal from finding 3's 28/28), net-of-cost contracts
   per trade ranged 1-2 (mean 1.86) whenever a trade was actually sized.
   But of the 28 cycles, only **7 net trades** were sized (26/28
   sized gross-of-cost — so 19 cycles had SOME real positive credit
   before slippage but not after): real gross credit on a $1-wide,
   ~3%-OTM spread was consistently a few cents to ~$0.11/share, and the
   $0.10/leg (2 legs = $0.20/share) slippage placeholder — chosen before
   this session's redesign, when spreads were expected to be ~$18 wide
   with much more premium — consumes most or all of that thin credit.
   21 cycles were skipped at the simulation stage, ALL for the same
   reason (`non_positive_credit`). This is flagged as a real, honest
   tension: the slippage assumption was never revisited when the
   strike-selection redesign shrank spread width by ~18x, and it now
   plausibly dominates the trade economics — not asserted as certainly
   wrong, since no real bid/ask exists to check it against (finding 2),
   but worth the user's attention before any further iteration.

   **Pooled backtest — portfolio-level, 2 anchored folds
   (2024-01-18 → 2026-07-17):** pooled net-of-cost **-3.34%**, pooled
   gross-of-cost **+1.70%** (gross is positive — the underlying edge
   collects real credit more often than not; net is negative because of
   the slippage/thin-credit tension above), **0/2 folds net-positive**
   (fold 1 -1.70%, fold 2 -1.67%, both flagged THIN at 3 and 4 trades
   respectively, below the 5-trade threshold). Win rate 71.4% (5 wins,
   2 losses) — but the 2 losses were both `expired_itm_max_loss` (-$186,
   -$194), large enough to outweigh five small wins ($4-$22 each) in the
   pooled total. Buy-and-hold SPY over the same window: **+55.99%**
   (fold 1 +10.48%, fold 2 +41.20%) — the strategy does not come close on
   a return basis, though this is a defined-risk premium-selling
   strategy, not a directional one, so a direct return comparison to
   buy-and-hold is of limited relevance on its own (reported per the
   permanent requirement regardless). **Pre-committed bar (pooled
   net-of-cost positive AND both folds individually positive): NOT
   cleared** — fails on both legs this time, a real result now that
   there are real trades to evaluate, not the finding-3 non-result.

   **Stress test — all 3 windows now size to real, non-zero contracts**
   (2 contracts each, unchanged across all three since width is
   uniformly $1): Feb 2018 total loss $200 (2.00% of equity), Feb-Mar
   2020 $200 (2.00%), Sept-Oct 2022 $200 (2.00%) — every window still
   breached to 100% of the (now $1, not ~$1,000) structural max loss,
   but because sizing is no longer floored to zero, the worst-case loss
   is now visibly BOUNDED at exactly the intended 2%-of-equity risk
   budget in all three real historical crashes — the sizing mechanism is
   working as designed at this width, confirmed against three
   independent real crash windows, not just the one that happened to be
   in the 2024-2026 pooled data.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction.** Unlike finding 3 (an empty, uninformative result), this
   rerun gives real evidence: pooled net-of-cost is negative and neither
   fold clears the bar, gross-of-cost is positive, and the shortfall is
   traceable to a specific, named, flagged mechanism (slippage assumption
   vs. thin real credit) rather than an unexplained gap — the user can
   judge whether that mechanism itself deserves scrutiny (e.g., is
   $0.10/leg still the right slippage assumption for a $1-wide spread)
   before deciding on adoption, without needing another full rerun to
   find out where the gap comes from.

5. **Slippage recalibration + final rerun (executed) — the TRUE final
   structural change to this design, per instruction (no finding-6
   variant without a fresh, explicit instruction, same binding-constraint
   convention as the crypto search's finding 13/14 kickoff).** Finding
   4 flagged, but didn't resolve, a real tension: `PCS_SLIPPAGE_PER_LEG_
   DOLLARS` ($0.10/leg) was calibrated for finding 3's ~$18-wide design
   and never rescaled after finding 4 shrank achieved width to $1.
   Recalibrated to **$0.02/leg (2 standard minimum exchange ticks)** —
   justified by real market structure (options priced under $3 trade in
   $0.01 increments under standard exchange tick rules; a $1-wide,
   penny-credit SPY spread falls squarely in that category), reasoned
   independently of finding 4's -3.34% result, not a reaction to it.
   Only the pooled backtest was rerun (stress test result stands,
   already concluded per instruction — its sizing conclusion doesn't
   depend on entry-credit slippage at all, since it uses the structural
   width as max loss, not real credit). Only the constant changed; no
   other mechanic touched.

   **Real trade count is now substantial, not thin: 26 of 28 cycles
   sized into a real net trade** (only 2 skipped, both
   `non_positive_credit` — a near-complete reversal from finding 4's
   7/28) — comfortably above the ~10-15 trade floor flagged as the bar
   for a real test, reported explicitly per instruction.

   **Result — portfolio-level, 2 anchored folds
   (2024-01-18 → 2026-07-17):** pooled net-of-cost **-0.38%**, pooled
   gross-of-cost **+1.70%** (unchanged from finding 4 — gross never
   depended on the slippage assumption), win rate **88.5%** (23 wins, 3
   losses, 0 flat). **Fold 1: -0.92% (14 trades, 85.7% win rate). Fold
   2: +0.55% (12 trades, 91.7% win rate) — POSITIVE**, unlike finding 4
   where both folds were negative. Confirmed directly from the trade
   list, not estimated: 23 winning trades summed to **+$475.99** (small,
   consistent gains, mostly $4-$54 per trade — one trade had exactly $0
   credit and $0 pnl, both `expired_otm`); the 3 losing trades (all
   `expired_itm_max_loss`) summed to **-$514.00**; net **-$38.00** on
   $10,000 starting capital. This is the fat-tail profile a premium-
   selling strategy is structurally expected to produce — frequent small
   wins funded by rare, large, capped losses — and here the ~2 years of
   small wins fell just short of covering three tail losses, not by a
   wide margin. Buy-and-hold SPY over the same window: +55.99% (reported
   per the permanent requirement; a direct return comparison remains of
   limited relevance for a defined-risk premium strategy, same caveat as
   finding 4).

   **Pre-committed bar (pooled net-of-cost positive AND both folds
   individually positive): NOT cleared** — pooled net-of-cost is
   negative (though only slightly: -0.38%, a $38 shortfall on $10,000)
   and fold 1 is negative even though fold 2 is positive. Both legs of
   the bar fail on the letter of the rule, but this is now unambiguously
   a real, adequately-sampled test of the underlying signal (26 trades,
   not 7 or 0) — the two prior findings' zero/thin-trade problems are
   fully resolved, and this result is not attributable to a
   sizing-floor or slippage-calibration artifact the way findings 3 and
   4 were.

   **No adopt/reject verdict rendered — raw numbers only, per
   instruction, same convention as every other finding in this repo.**
   Per the user's own explicit framing at this step's kickoff, this is
   the concluding result for Track C's put credit spread design — no
   further structural iteration (finding 6) is authorized without a
   fresh, explicit instruction.

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

**Track B:** `scripts/backtest_etf_donchian.py` (new — 8-ETF rotational
Donchian ensemble; imports `EnsembleTrade`/`simulate_rotational_ensemble()`/
`slice_ensemble_trades_by_folds()`/`per_symbol_diagnostics()`/the
buy-and-hold helpers/`PAPER_VALIDATION_CAPITAL`/`THIN_FOLD_TRADE_THRESHOLD`
directly from `backtest_donchian_ensemble.py` unchanged — none of that
infrastructure needed modification, it was already generic over
symbol_data/universe_order; adds its own `compute_channel_long_entry_
indices()` reparameterized on `channel_length` rather than reading that
file's module global, `build_symbol_series()` for daily-native stock
data — no hourly-fetch-then-resample step needed — and
`check_no_same_day_round_trips()`, the new PDT guard). `src/
data_ingestion.py` gained `fetch_historical_stock_candles()` (Alpaca
`StockHistoricalDataClient`, `TimeFrame.Day`, same paper keys as the
crypto path via `get_alpaca_config()` — a separate client/product from
`fetch_historical_candles()`'s `CryptoHistoricalDataClient`, not a
modification to it). See "Track B findings" above for the full result and
judgment calls made.

**Track B risk-budget stress-test milestone (spec v29 §10.1):**
`simulate_rotational_ensemble()` (`backtest_donchian_ensemble.py`) gained
one new, purely-additive parameter, `entry_sizing_log=None` — logs
target-vs-granted risk per accepted entry and attributes any shrink to
either the risk budget or the notional sanity backstop specifically, when
a list is passed; default `None` changes no behavior and no return
signature for any existing caller. New one-off diagnostic script
`scripts/stress_test_track_b_risk_budget.py` (not meant to be
maintained). 3 new tests in `tests/test_backtest_donchian_ensemble.py`.
See "Current status" above for the full result, including the notional-
backstop finding (AGG sized to 100% of equity on 13/15 trades) and the
resulting docstring corrections in both `backtest_etf_donchian.py` and
`backtest_donchian_ensemble.py`.

**Track B notional-concentration milestone (spec v30 §10.2):**
`entry_sizing_log` (`backtest_donchian_ensemble.py`) extended with 5 more
fields (`entry_price`, `entry_atr`, `atr_to_price_pct`,
`uncapped_notional_pct_of_equity`, `notional_pct_of_equity`) — still
purely additive/opt-in, no change to any existing behavior. New one-off
script `scripts/quantify_track_b_notional_concentration.py` (not meant to
be maintained). `backtest_etf_donchian.py` gained
`MAX_SINGLE_POSITION_NOTIONAL_PCT = 55.0` (a Track-B-only override of the
shared function's 100% default) and a `--max-position-notional-pct` CLI
flag, wired into both the net and gross `simulate_rotational_ensemble()`
calls in `main()`. 5 new tests (3 in
`tests/test_backtest_donchian_ensemble.py`, 2 in
`tests/test_backtest_etf_donchian.py`), full suite (150 tests) passing.
See "Current status" above for the full quantification, root-cause
confirmation, cap-threshold rationale, and rerun sensitivity results.

**Track B guardrail-implementation milestone (spec v32):**
`src/config.py` gained `get_track_b_guardrail_config()` (returns the same
`GuardrailConfig` dataclass, 4 fields rescaled after the clarification-
pass fix below, 2 passed through). Three new optional env vars (`.env`,
`.env.example`): `MAX_TRADES_PER_DAY_TRACK_B`, `MAX_DAILY_LOSS_PCT_
TRACK_B`, `MAX_TOTAL_OPEN_RISK_PCT_TRACK_B`. `src/risk_filter.py` —
previously 100% stub — gained real implementations of `check_trade_
count_limit()` (parameter `today_entry_count`, entries-only contract),
`check_daily_loss_limit()` (calls `halt_state.set_halt()` on breach),
`check_combined_open_risk_budget()`, and a new, explicitly non-blocking
`check_asset_class_concentration()` plus the confirmed `TRACK_B_ASSET_
CLASS_GROUPS`/`CONCENTRATION_ALERT_THRESHOLD_PCT` constants (fires via
`src/telegram_bot.py`'s `send_message()`, itself still a stub — tests
monkeypatch it). `check_drawdown_limit()` and `evaluate()` remain
`NotImplementedError`, out of scope. **Clarification-pass fix (same
session): `MAX_SINGLE_POSITION_NOTIONAL_PCT` (spec v30 §10.2) moved from
`backtest_etf_donchian.py` into `src/config.py` as the single canonical
source — now also backs `get_track_b_guardrail_config()`'s `max_
position_size_pct` override (55%, was silently left at the stale global
25%), and the backtest script imports the same constant instead of
defining its own copy.** New `tests/test_risk_filter.py` (20 tests after
the clarification-pass additions), full suite (170 tests) passing. See
"Current status" above for the full implementation detail, the confirmed
asset-class grouping, and both clarification fixes.

**Track A:** `scripts/backtest_gem.py` (base GEM signal + monthly
holding-period simulator; `GemTrade` dataclass, `simulate_gem()`,
`compute_gem_fold_boundaries()`, `slice_gem_trades_by_folds()` — a
different trade model from every prior finding, see the module docstring
for why GEM's continuous monthly-rotation holding periods needed their
own simulation loop rather than reusing Track B's rotational-ensemble
infrastructure). `src/data_ingestion.py`'s `fetch_historical_stock_
candles()` gained an `adjustment` parameter (default `Adjustment.RAW`,
Track B's behavior unchanged; Track A passes `Adjustment.ALL` — see
"Track A findings" above for why RAW is actively wrong for a total-return
signal like GEM's). `simulate_gem()` was rewritten a second time (finding
3) from month-end-only to a full day-by-day continuous loop — new
`compute_max_drawdown_pct()`, `slice_continuous_drawdown_by_folds()`,
`compute_leg_max_drawdowns()`, `attribute_breaker_costs()` helpers, a
new `reset_dates` return value, and a new `"resume"` exit_reason
(distinct from `"switch"`, needed to attribute transaction costs to the
breaker mechanism specifically) — see "Track A findings" 2 and 3 above
for the full result, the max-drawdown-understates-risk caveat, the v1
whipsaw diagnosis, and the v2 peak-reset fix.

**Track C:** `scripts/check_options_data_availability.py` (new, one-off,
not meant to be maintained — same convention as `select_universe.py`/
`verify_finding12_sizing.py`/`compute_gem_benchmarks.py`). Confirms SPY
options account approval level and probes `get_option_bars()` directly
against manually-constructed OCC symbols to find the real historical bar
floor, rather than trusting `GetOptionContractsRequest`'s contract-search
range (which turned out to disagree with the real bar-data floor by 15
days — see "Track C findings" above). Extended in place (finding 2, same
file) to also probe `get_option_trades()` (historical tick data — works,
same floor), confirm no historical-quotes method exists on
`OptionHistoricalDataClient`, and confirm `implied_volatility`/`greeks`
exist only on the latest-only `OptionsSnapshot`, checked live against the
account rather than assumed from the SDK.

New this session (finding 3 — first production strategy code for Track
C): `scripts/backtest_put_credit_spread.py` (the pooled monthly-rolling
backtest) and `scripts/stress_test_pcs.py` (the separate stress-test
scenario report). `src/data_ingestion.py` gained `fetch_option_contracts()`
and `fetch_option_bars()` — see "Track C findings" 3 above for the full
result (28/28 cycles built successfully from real data, then 28/28
skipped at sizing: a capital/strike-width mismatch, not a signal-quality
result) and every judgment call made. `execution.py` remains untouched —
still no live-trading integration for this or any track.

### Not yet decided (blocks next steps)

**UPDATE: this is now resolved — Track A is CLOSED.** Track A
circuit-breaker mechanics (all-time-peak-style trigger checked daily,
exit to BIL, unconditional resume at next scheduled evaluation) were
specified and executed, diagnosed as causing a permanent whipsaw in their
original (v1) form, and corrected (v2, peak-reset-on-resume) — see "Track
A findings" 2 and 3 above. v2 clears the pre-committed bar on both
thresholds and meaningfully reduces true cumulative drawdown versus base
GEM (24.58%/24.94% vs 33.79%) while keeping most of the return —
BUT Track A finding 4's mandatory buy-and-hold comparison (see above)
showed all three GEM variants (base, v2-15%, v2-20%) underperform a
simple static 60/40 SPY/AGG buy-and-hold on BOTH return and drawdown over
the same window. Verdict rendered: Track A is CONCLUDED, no adopt, no
further GEM work planned. Track C (options premium-selling) has since
started — see "Blocked/pending" below.

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

**UPDATE: `execution.py` is no longer blocked for Track B — see "Current
status" for the full executed milestone.** `place_entry_order()`/
`place_exit_orders()` (the legacy crypto/Track A OCO-fallback path) stay
`NotImplementedError`, still correctly blocked on the separate crypto
bracket-order design gap (see "Hard rules" below) — that gap is
irrelevant to Track B specifically, since Track B's exit is a single ATR
trailing stop with no take-profit leg at all, so there's nothing to
OCO-emulate. The correlation/open-risk-budget guardrail redesign needed
to generalize spec §4.3 from 2 assets to 10 (finding 10) remains
blocked/pending — not started, and explicitly not part of any Track B
milestone to date.

**New, explicitly flagged and NOT yet resolved:** two real design gaps
surfaced while implementing/dry-running `execution.py` this session (full
detail in "Current status") —
  1. the entry-qty-before-fill sequencing tension (Alpaca needs a qty at
     submission time; the locked design's risk-pinned formula needs the
     unknown fill price) is resolved here with a pre-fill close_T proxy,
     documented as a placeholder, not confirmed with the user;
  2. bridging the overnight submit-to-fill gap across separate daily-job
     invocations means a newly-filled position can now sit unprotected
     for up to about a full trading day before `protect_unprotected_
     fills()` (run at the START of the next `run_daily_execution_job()`
     call) catches it up — a genuinely correct fix likely needs a THIRD,
     separate scheduled invocation shortly after each session's open,
     not built this milestone.
Both need a real chat-interface design-call confirmation before this
module should be trusted with live capital — do not treat either as
settled without a fresh, explicit instruction.

**UPDATE (2026-08-12 session): gap 2 (bridging the overnight
submit-to-fill gap across daily-job invocations) now has a LOCKED design
— a `fill_listener.py` event-driven WebSocket listener, superseding the
"third scheduled invocation" idea — see "Current status" above for the
full locked architecture. Not yet implemented; implementation is the
next milestone.** Gap 1 (the entry-qty-before-fill sequencing tension,
resolved in `execution.py` with a pre-fill `close_T` proxy) is untouched
by this design session and remains an unconfirmed placeholder.

**UPDATE: gap 2 is now IMPLEMENTED and verified against the real paper
account** — `src/fill_listener.py`, see "Current status" above for the
full result (254/254 tests, integration + restart-safety both PASS). A
same-session fill is now protected within seconds via the listener
instead of waiting up to ~1 trading day for the daily fallback — the
fallback (`protect_unprotected_fills()`) is unchanged and still the
backstop for listener downtime. Two NEW gaps surfaced during this
implementation (not present in the locked design) remain open, both
flagged in code: `ReplaceOrderRequest.qty`'s `Optional[int]` typing
makes a fractional partial-fill resize fail toward alert rather than
silently succeed, and a narrow race between `submit_entry_and_stop()`'s
own stop submission and the listener reacting to the same fill
concurrently (expected to be immaterial in production given Track B's
post-close-only entry cadence, but not eliminated). Gap 1
(entry-qty-before-fill) remains untouched and still needs a real
chat-interface design-call confirmation.

**Crypto strategy family: CLOSED, no further milestones.** Finding 14
(corrected long-horizon design — 100-day Donchian channel, daily entries,
3.0x ATR trailing stop, finding 13's equal-risk-contribution sizing kept
unchanged), the TRUE final planned iteration on this strategy family, was
executed (see "Current status" and finding 14 above for the full result:
pooled net-of-fees +0.94% but only 3/5 folds positive — misses the
pre-committed adopt bar; beats both buy-and-hold comparisons regardless).
Per the binding constraint set at finding 13/14's kickoff, this result
closed the strategy family — no finding-15 crypto variant without a
fresh, explicit instruction. Any future crypto finding, in this family or
a new one, MUST report a buy-and-hold comparison alongside
net/gross/folds-positive — mandatory from finding 13 forward, not
optional, and this requirement carries over to every non-crypto track
below too.

**Track B (8-ETF Donchian breakout with ATR trailing stop) is COMPLETE
and PASSED.** Pooled net +73.64% over 3/3 folds net-positive, max
drawdown 5.69% versus the 8-ETF buy-and-hold blend's 26.47% over the same
pooled test window (return-per-unit-of-drawdown roughly 2x buy-and-hold's
— see "Track B findings" below and the drawdown follow-up for full
detail, including the pooled-test-window-vs-full-window distinction).
**Logged as a viable candidate, NOT yet deployed to paper/live trading.**
Full detail in spec v24 §10.1 (project knowledge — v24 supersedes v23 as
of this update) and commit 593a54f. Multi-asset ETF Donchian breakout +
ATR trailing stop, reusing finding 14/15's signal/exit/sizing mechanism
unchanged, ported to an 8-ETF universe (SPY, QQQ, IWM, EFA, AGG, GLD,
DBC, VNQ) on Alpaca's commission-free stock/ETF product, replacing
BTC/USD + ETH/USD. New script `scripts/backtest_etf_donchian.py`; new
`src/data_ingestion.py` function `fetch_historical_stock_candles()`
(Alpaca `StockHistoricalDataClient`, daily bars — a separate client/
product from the crypto path, same paper keys).

**Data-window deviation, decided BEFORE any backtest ran (not in
response to results):** the kickoff specified a 2006-02-03 (DBC
inception) start, ~20 years of history. This account's Alpaca stock data
is truncated at **2016-01-04** regardless of requested start date or feed
parameter (SIP/IEX both truncate identically) — confirmed empirically
across all 8 tickers, including GLD/AGG/QQQ whose real inception dates
are 2004/2003/1999, so this is an account/data-plan tier limit, not a
per-symbol gap. User decision: proceed with the available ~10.6-year
window (2016-01-04 → present) and drop from 5 anchored folds to 3
(rather than risk fold-level sample starvation on a shorter span).
**This means the window excludes the 2008 financial crisis and the 2020
COVID crash's lead-in — a result here is evidence about post-2016
regimes only**, not the same breadth-of-regime claim the original
20-year design would have supported. If more history is later available
(paid data-plan upgrade), this backtest should be rerun — the current
result is not final evidence on the original 20-year design. **This
data-truncation discovery was not previously known and now informs
Track A's kickoff too** (see below) — any future non-crypto track must
check actual data depth before locking a test window, not assume the
originally-specified window is available.

**NEW MILESTONE, STARTING NOW: Track A.** Dual Momentum/GEM — the design
already specified in spec v22 §10.1 (monthly SPY/EFA relative-momentum +
BIL absolute-momentum filter into AGG), which has never actually been
backtested (it was superseded by the three-track pivot before its first
run) — plus a new portfolio-level drawdown circuit-breaker overlay,
tested at two thresholds. Full design and the pre-committed bar are in
spec v24 §10.2 (project knowledge) — treat that section as the source of
truth. Per instruction, actual Alpaca data depth for SPY/EFA/AGG/BIL must
be checked and any truncation flagged BEFORE locking a test window or
running any backtest — see below for that check's result. Track C
remains locked as a concept but not yet started — do not begin it without
a fresh, explicit instruction to switch tracks.

**UPDATE: Track A is now fully CONCLUDED (base GEM + both v2
circuit-breaker variants — see Track A findings 1-4 above).** None of the
three variants beat a simple static 60/40 SPY/AGG buy-and-hold on return
or drawdown; the 60/40 blend dominates on both. No further GEM work is
planned. This closes Track A the same way the crypto search closed at
finding 14 — a concluded line, not an open one.

**NEW MILESTONE, STARTING NOW: Track C.** Options premium-selling — the
third and final track (spec v23 §2's original three-track split). The
originally-specified structure (cash-secured put-writing, modeled on
Cboe's PUT index) turned out to need far more capital than the $10,000
paper-validation notional supports at SPY's current price (~$50-60k to
cash-secure one contract) — pivoted to a defined-risk **put credit
spread** instead: same premium-collection thesis, a fraction of the
capital, but an honest step down in evidence quality (Cboe's PUT index
tracks pure cash-secured puts, not spreads — there is no equivalent
published long-run index for the spread structure specifically). Logged
in spec v25 §2 and §10.5. Per the same "check data depth before locking a
window" lesson Track B/A already had to apply twice, the first step is
checking Alpaca's actual SPY options historical data availability on this
account — not assumed, given both prior equity tracks hit an undiscovered
floor and options data is generally sparser industry-wide. **Result (see
Track C finding 1 below): usable window confirmed as 2024-01-18 →
2026-08-07, ~2.5 years — shorter than either prior track.**

**UPDATE (this session): the pooled backtest and stress-test overlay
were both executed (see "Track C findings" 3 above) — and the SAME
capital-mismatch problem that originally forced the pivot away from
cash-secured puts (needing ~$50-60k to cash-secure one contract) has
resurfaced in the credit-spread structure too, just less visibly: under
spec §4.1's real 1%-of-equity sizing formula (applied literally, per
instruction), the 5%/8%-OTM strike design's ~$1,710 average max loss per
contract against a $100 (1% of $10,000) risk budget means EVERY cycle
sizes to zero contracts — 28/28 in the pooled backtest, all 3/3 in the
independent stress-test scenarios. This is a deterministic capital/
strike-width arithmetic fact, not a signal-quality finding — the
backtest never got to evaluate whether the underlying signal is any good
at all. No adopt/reject verdict rendered, no fix proposed or applied —
reported as raw numbers per instruction, decision on how to proceed
deferred to the user.

**UPDATE: the user's two pre-registered fixes (see "Track C findings" 4
above) resolved the zero-trade problem — narrower, real-chain-checked
strikes (2-4% OTM zone, $1 achievable width, confirmed real not assumed)
plus a 2%-of-equity defined-risk sizing override (spec §4.1's global 1%
untouched everywhere else). Both the pooled backtest and the stress test
now produce real, non-zero trades/contracts.** Pooled backtest: 7 real
net trades from 28 cycles, pooled net-of-cost -3.34% (gross-of-cost
+1.70%), 0/2 folds net-positive — the pre-committed bar is NOT cleared,
but this is now a real, informative result rather than an empty table.
The net/gross gap is traced to a specific, named mechanism: real credit
on a $1-wide spread is a few cents to ~$0.11/share, and the existing
$0.10/leg slippage placeholder (chosen before the width redesign, when
spreads were expected ~$18 wide) consumes most of it on 19/28 cycles —
flagged, not resolved, since there's no real bid/ask to check the
slippage assumption against (finding 2). Stress test: all 3 crash
windows now size to 2 contracts each, and the worst-case loss is visibly
bounded at exactly 2.00% of equity in every one — the sizing mechanism
is confirmed working as designed. No adopt/reject verdict rendered.

**UPDATE: Track C's put credit spread design is now CONCLUDED (see
"Track C findings" 5 above) — the user's own explicit framing at this
step's kickoff, no finding-6 structural variant without a fresh, explicit
instruction.** Final recalibration: the $0.10/leg slippage placeholder
(sized for finding 3's ~$18-wide design) was never rescaled after finding
4 shrank width to $1 — recalibrated to $0.02/leg (2 standard minimum
exchange ticks, real market-structure justification) and the pooled
backtest rerun alone (stress test stands unchanged). Real trade count is
now substantial (26/28 cycles, not 7/28 or 0/28): pooled net-of-cost
**-0.38%**, gross-of-cost +1.70%, win rate 88.5% (23 wins summing
+$475.99, 3 losses summing -$514.00, net -$38.00 on $10,000). Fold 1
negative (-0.92%), fold 2 positive (+0.55%) — the pre-committed bar
(pooled net positive AND both folds individually positive) is NOT
cleared, but this is now a real, adequately-sampled result, not a
sizing-floor or slippage-calibration artifact. No adopt/reject verdict
rendered — decision on Track C's put credit spread deferred to the user.

## Hard rules — never do these

- **Never commit directly to `main`.** All work happens on `paper` or a
  feature branch off it. `main` is only updated through the promotion
  pipeline (spec §3.3): automated tests + soak period + Telegram approval.
- **Never remove or weaken a guardrail check** in `risk_filter.py` without
  an explicit, current instruction to do so in the session. The numbers in
  `.env` (1% risk/trade, 25% max position, 3% daily loss, 6 trades/day cap,
  1.5% combined open-risk, 10% max drawdown) are locked decisions (spec
  §4.1–4.3) — treat them as load-bearing, not tunable defaults. **Track B
  guardrail rescaling (spec v32, "Current status") is a separate,
  additive set of Track-B-specific overrides layered alongside these
  global numbers, not a replacement of them** — the global `.env` numbers
  still govern crypto/Track A; `risk_filter.py` will need to branch on
  which track/strategy is active once it's actually implemented, per the
  same never-fork-on-`TRADING_ENV` discipline in "Environment" below
  (branch on the strategy/track, not by duplicating logic).
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
