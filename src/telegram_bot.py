"""
Telegram integration — the human-in-the-loop control interface (spec §2, §7).

Two directions of traffic:
- Outbound: daily journal, promotion-approval requests, halt notifications
- Inbound: approve/reject commands (promotion pipeline, spec §3.3), manual
  kill switch (§4.3), resume-after-halt approval (§7)

Inbound commands need either polling (getUpdates) or a webhook — decide
during the build session; polling is simpler to run on a single droplet.
"""
import logging

import requests

from .config import get_telegram_config

log = logging.getLogger(__name__)


def send_message(text: str, requests_module=requests) -> bool:
    """Fire-and-forget send via Telegram's Bot API. Best-effort only,
    deliberately: NEVER raises — a Telegram/network failure must never
    crash a caller that's mid-alert about something else (this is the
    actual fix for the 2026-08-28 cascading-crash finding, where a
    raising send_message() called from inside error-handling code turned
    one failure into two). Returns True if the send succeeded, False
    (logged) otherwise.

    Plain synchronous requests.post(), NOT the python-telegram-bot
    library (which is async and would hit the same "cannot nest
    asyncio.run()" constraint fill_listener.py already documents for
    TradingStream.run(), since this is called synchronously from inside
    that module's running event loop). Matches the exact best-effort
    pattern of execution.send_daily_heartbeat() /
    fill_listener.send_listener_heartbeat()."""
    try:
        cfg = get_telegram_config()
        url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
        requests_module.post(url, json={"chat_id": cfg.chat_id, "text": text}, timeout=10)
        return True
    except Exception as exc:  # noqa: BLE001 — must never crash the caller, matches send_daily_heartbeat()'s convention
        log.warning(f"telegram_bot.send_message: send failed ({exc}) — caller unaffected.")
        return False


def send_approval_request(summary: str, request_id: str) -> None:
    """
    Sends a summary with inline approve/reject buttons (or a text command
    prompt) for promotion-pipeline approvals (spec §3.3) or capital-increase
    suggestions (§3.2 step 4). Never auto-resolves — always waits for the
    explicit human response.
    """
    raise NotImplementedError


def poll_for_commands():
    """
    Long-poll for inbound commands: /approve, /reject, /kill, /status.
    Design the exact command syntax during the build session
    (playbook v6 §7 open item).
    """
    raise NotImplementedError
