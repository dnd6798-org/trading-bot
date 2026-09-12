"""
Tier 2 monitoring redesign (CLAUDE.md "Session update ... 2026-09-12,
spec/playbook v77") — thin CLI shim so scripts/run_tier2_diag.ps1 (a
PowerShell script) can call src.telegram_bot.send_message() unchanged,
without reimplementing the Telegram send logic in PowerShell.

Reads the full message text from stdin (avoids fragile PowerShell/argv
quoting for a large, JSON-derived diagnostic summary) and sends it via
the SAME best-effort, never-raising send_message() Tier 1 already uses
(scripts/service_alert.py) — no new alerting mechanism.

Same sys.path-insert import convention as scripts/service_alert.py
(scripts/ has no __init__.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.telegram_bot import send_message


def main() -> None:
    text = sys.stdin.read()
    send_message(text)


if __name__ == "__main__":
    main()
