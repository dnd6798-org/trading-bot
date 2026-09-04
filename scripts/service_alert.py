"""
Telegram alert on trading-bot-listener.service start/stop (Tier 1
monitoring redesign — CLAUDE.md "Session update ... 2026-09-04, spec/
playbook v76"). Invoked by systemd itself via ExecStartPost/ExecStopPost
hooks on deploy/systemd/trading-bot-listener.service — not meant to be
run manually, though it can be (see Usage below).

Import convention deliberately mirrors scripts/dry_run_execution_track_b.py
exactly: scripts/ has no __init__.py, so this cannot be invoked as
`-m scripts.service_alert` from the systemd unit — a plain sys.path
insert + direct import instead.

Reuses src.telegram_bot.send_message() unchanged — no new alerting
mechanism. send_message() itself already never raises (best-effort,
logs and returns False on failure), but this script wraps the whole
body in its own try/except anyway: the ExecStartPost/ExecStopPost
lifecycle step must never be blocked or fail the service transition
because of an alerting problem, regardless of where in this script that
problem originates (argument composition, env var reads, etc.), not
just inside send_message() itself.

On --event=stopped, systemd is documented to populate SERVICE_RESULT,
EXIT_CODE, and EXIT_STATUS for ExecStopPost= — but does NOT reliably set
all three on every failure path (a known upstream edge case,
systemd/systemd issue #4770). Each is read via os.environ.get() and
defaults to "unknown" if unset OR present-but-empty, rather than
assuming systemd always populates them.

Usage (normally invoked by systemd, shown here for manual testing):
    python scripts/service_alert.py --event=starting
    python scripts/service_alert.py --event=stopped
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telegram_bot import send_message
from src.config import get_log_level

log = logging.getLogger(__name__)

SERVICE_NAME = "trading-bot-listener.service"


def compose_starting_message() -> str:
    return f"{SERVICE_NAME}: started."


def compose_stopped_message(service_result: str, exit_code: str, exit_status: str) -> str:
    return (
        f"{SERVICE_NAME}: stopped. "
        f"result={service_result} exit_code={exit_code} exit_status={exit_status}"
    )


def _env_or_unknown(name: str) -> str:
    """os.environ.get(name, "unknown") is not enough on its own — systemd
    can set a var to an EMPTY string rather than leaving it unset (the
    #4770 edge case referenced in the module docstring). `or` treats
    both None and "" as missing."""
    return os.environ.get(name) or "unknown"


def main(argv=None) -> None:
    logging.basicConfig(level=get_log_level(), format="%(asctime)s %(levelname)s %(message)s")
    try:
        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("--event", required=True, choices=["starting", "stopped"])
        args = parser.parse_args(argv)

        if args.event == "starting":
            text = compose_starting_message()
        else:
            text = compose_stopped_message(
                _env_or_unknown("SERVICE_RESULT"),
                _env_or_unknown("EXIT_CODE"),
                _env_or_unknown("EXIT_STATUS"),
            )
        send_message(text)
    except Exception as exc:  # noqa: BLE001 — must never block or fail the ExecStartPost/ExecStopPost lifecycle step
        log.warning(f"service_alert: failed to send alert ({exc}).")


if __name__ == "__main__":
    main()
