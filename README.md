# Crypto Day-Trading Bot

Automated BTC/USD + ETH/USD trend-following bot on Alpaca. See
`trading-bot-spec-v6.md` and `session-playbook-v6.md` (project knowledge)
for the full decision record — this repo implements those decisions, it
doesn't redefine them.

## Status

EMA/ATR signal generation, historical data ingestion, and
`scripts/backtest.py` are implemented and tested. Execution, position
management, and the real risk-filter checks are still stubs — see
`CLAUDE.md` for current details.

## Setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your actual Alpaca paper keys + Telegram token/chat ID
pytest tests/ -v                  # confirms .env is wired correctly
```

## Structure

```
src/
  config.py              # single source of env/secrets loading
  halt_state.py           # persisted halt state (restart != resume, spec §2/§4.5)
  data_ingestion.py        # pipeline §3.1 step 1
  signal_generation.py     # pipeline §3.1 step 2 — EMA crossover + volume filter
  risk_filter.py           # pipeline §3.1 step 3 — all of spec §4 guardrails
  execution.py              # pipeline §3.1 step 4 — BLOCKED on bracket-order design fix, see file
  position_management.py    # pipeline §3.1 step 5
  journaling.py             # pipeline §3.2 — daily journal, strategy review
  telegram_bot.py           # human-in-the-loop interface (spec §2, §7)
  promotion/
    criteria.py             # pipeline §3.3 — paper-to-live promotion gate (locked v6)
scripts/
  backtest.py              # NEXT MILESTONE — validates EMA/ATR before anything live
tests/
  test_config.py           # real, runnable — confirms .env setup today
```

## Known open items before further build

- **Crypto bracket-order gap** (see `src/execution.py` docstring) — Alpaca
  doesn't support bracket/OCO orders for crypto pairs, only for stocks.
  Needs a spec correction before `execution.py` is implemented.
- EMA period tuning, ATR multiplier, promotion criteria thresholds — all
  pending the backtest session (`session-playbook-v6.md` §7).

## Environment

Paper vs. live is a config flag (`TRADING_ENV` in `.env`), not a code fork
— see spec §2 "Environment separation & code promotion pipeline (v6)".
All new work happens on the `paper` branch; `main` is only updated via the
Telegram-approved promotion pipeline (spec §3.3).
