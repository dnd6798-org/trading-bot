"""
Telegram integration — the human-in-the-loop control interface (spec §2, §7).

Two directions of traffic:
- Outbound: daily journal, promotion-approval requests, halt notifications
- Inbound: approve/reject commands (promotion pipeline, spec §3.3), manual
  kill switch (§4.3), resume-after-halt approval (§7)

Inbound commands need either polling (getUpdates) or a webhook — decide
during the build session; polling is simpler to run on a single droplet.
"""
from .config import get_telegram_config


def send_message(text: str) -> None:
    """Fire-and-forget send. Used for journals, alerts, halt notices."""
    raise NotImplementedError("Build session — python-telegram-bot, sendMessage")


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
