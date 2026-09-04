"""
Daily automated Telegram digest (Tier 1 monitoring redesign — CLAUDE.md
"Session update ... 2026-09-04, spec/playbook v76"). systemd ExecStart
target for trading-bot-digest.service, fired by trading-bot-digest.timer
30 minutes after Track B/Track C's shared post-close slot so both daily
jobs have already run.

Pure reporting — this module never builds a TradingClient and never
submits/touches an order. Position data comes from the SAME source
Track B/Track C's own daily self-heal already trusts as ground truth
(src/track_positions.py's ledger, kept in sync with Alpaca by
execution.heal_track_b_ownership_ledger() / track_positions.
heal_track_c_ownership_ledger(), both of which already run once per
weekday as part of the daily/track-c jobs before this digest's own
17:30 America/New_York slot) — reused directly via track_positions.get_track_qty(),
per the milestone brief, rather than reimplementing position lookups
against Alpaca from scratch.

THREE SECTIONS ARE FLAGGED "NOT YET AVAILABLE", NOT FABRICATED, per the
milestone brief's explicit instruction — each has no real persisted data
source to read from as of this milestone:
  - Today's fills: src/journaling.py (spec §3.2) is still 100%
    NotImplementedError — aggregate_day()/format_journal_message() have
    never been built. There is no persisted fill record anywhere in this
    repo for this section to read.
  - Today's errors: run_daily_execution_job() (execution.py) and
    run_track_c_execution_job() (track_c_execution.py) both return a
    plain run_log dict with an "errors" list — but neither module
    persists that dict anywhere; each job's own main() only logs it to
    journald (spec §3.2 journaling is explicitly a separate, not-yet-
    built milestone — see execution.run_daily_execution_job()'s own
    docstring: "the caller is responsible for persisting it"). This
    digest job runs as its own separate systemd invocation with no
    access to another process's journald output or in-memory run_log,
    so there is nothing real to report here yet.
  - Listener restart count today: Part A of this same milestone
    (scripts/service_alert.py) sends a Telegram alert on every listener
    start/stop, but does not persist a count anywhere — there is no
    running tally this digest could read.

None of the three above should be read as "zero" — reporting a
fabricated zero would misrepresent an unmeasured quantity as a measured
one. Each renders literally as "not yet available" in both the returned
dict and the Telegram message.
"""
import logging
from datetime import datetime, timezone

from . import execution
from . import halt_state
from . import telegram_bot
from . import track_c_execution
from . import track_positions
from .config import get_log_level

log = logging.getLogger(__name__)

NOT_YET_AVAILABLE = "not yet available"


def _open_positions(track: str, universe) -> dict:
    """Ledger-only lookup via track_positions.get_track_qty() per symbol
    over `universe` — reuses the existing helper directly, no
    reimplementation of position lookups (per the milestone brief).
    Only symbols with a real (> 0) ledger qty are included."""
    positions = {}
    for symbol in universe:
        qty = track_positions.get_track_qty(track, symbol)
        if qty > 0:
            positions[symbol] = qty
    return positions


def build_digest(now_fn=lambda: datetime.now(timezone.utc)) -> dict:
    """
    Gathers today's digest content. No trading client, no network calls
    beyond what track_positions/halt_state's own file reads need — pure
    reporting over already-persisted local state.
    """
    today = now_fn().date().isoformat()

    halt = halt_state.load_halt_state()
    track_c_halt = halt_state.load_track_c_halt()

    return {
        "date": today,
        "track_b_positions": _open_positions("track_b", execution.TRACK_B_UNIVERSE),
        "track_c_positions": _open_positions("track_c", track_c_execution.HEAL_UNIVERSE),
        "halted": halt.halted,
        "halt_reason": halt.reason,
        "track_c_halted": track_c_halt.halted,
        "track_c_halt_reason": track_c_halt.reason,
        "todays_fills": NOT_YET_AVAILABLE,
        "todays_errors": NOT_YET_AVAILABLE,
        "listener_restart_count_today": NOT_YET_AVAILABLE,
    }


def _format_positions(positions: dict) -> str:
    if not positions:
        return "  none"
    return "\n".join(f"  {symbol}: {qty}" for symbol, qty in sorted(positions.items()))


def _format_halt(halted: bool, reason: str | None) -> str:
    if not halted:
        return "OK (not halted)"
    return f"HALTED — {reason}"


def format_digest_message(digest: dict) -> str:
    lines = [
        f"Daily Digest — {digest['date']}",
        "",
        "Track B positions:",
        _format_positions(digest["track_b_positions"]),
        "",
        "Track C positions:",
        _format_positions(digest["track_c_positions"]),
        "",
        f"Track B halt: {_format_halt(digest['halted'], digest['halt_reason'])}",
        f"Track C halt: {_format_halt(digest['track_c_halted'], digest['track_c_halt_reason'])}",
        "",
        f"Today's fills: {digest['todays_fills']}",
        f"Today's errors: {digest['todays_errors']}",
        f"Listener restarts today: {digest['listener_restart_count_today']}",
    ]
    return "\n".join(lines)


def run_daily_digest_job(send_fn=None) -> dict:
    """
    Builds the digest, formats it, sends it via Telegram, and returns a
    plain dict log — same "return a plain dict log" convention as
    run_daily_execution_job()/run_track_c_execution_job(). send_fn
    defaults to telegram_bot.send_message (itself already best-effort,
    never-raising); the try/except here guards build_digest()/
    format_digest_message() instead, so an unexpected local failure
    (e.g. a corrupt ledger/halt-state file) is logged and reported in
    run_log["errors"] rather than crashing the scheduled job.
    """
    if send_fn is None:
        send_fn = telegram_bot.send_message

    run_log = {"date": None, "digest": None, "sent": False, "errors": []}
    try:
        digest = build_digest()
        run_log["date"] = digest["date"]
        run_log["digest"] = digest
        message = format_digest_message(digest)
        run_log["sent"] = send_fn(message)
    except Exception as exc:  # noqa: BLE001 — a digest failure must not crash the scheduled job
        run_log["errors"].append({"step": "build_or_send", "error": str(exc)})
    return run_log


def main() -> None:
    """
    systemd ExecStart target for trading-bot-digest.service. Same shape
    as execution.main()/track_c_execution.main(): configure logging from
    LOG_LEVEL, run the job, log the result dict. No heartbeat ping for
    this job — it has no dedicated Healthchecks.io monitor as of this
    milestone (not requested in the brief; the three existing monitors
    cover the daily job, the listener, and the Track C rebalance job).
    """
    logging.basicConfig(level=get_log_level(), format="%(asctime)s %(levelname)s %(message)s")
    run_log = run_daily_digest_job()
    log.info("run_daily_digest_job() result: %s", run_log)


if __name__ == "__main__":
    main()
