"""
Tier 2 monitoring redesign (CLAUDE.md "Session update ... 2026-09-12,
spec/playbook v77") — droplet read-only diagnostic actions, invoked by a
headless `claude -p` run (scripts/run_tier2_diag.ps1) under a hard
read-only --allowedTools boundary.

Each of the six actions below sends exactly one fixed, literal action
name as the SSH remote command to the `trading-bot-droplet` alias
(~/.ssh/config on this machine, a dedicated tier2-only ed25519 keypair)
— never a full shell command string, and never any variable/user-
supplied text. The droplet's own scripts/droplet_diag_dispatch.sh
(droplet-side, forced via `command=` in tradingbot's authorized_keys —
see CLAUDE.md's v77 record) is what actually maps each literal action
name to its real, fixed, read-only shell command; this script only ever
transmits one of the six recognized action names, verbatim, as the SSH
remote command. Connects as tradingbot (never root), per the standing
droplet deployment convention.

This double-enforces the read-only boundary: even if a future
--allowedTools rule were ever misconfigured client-side, the droplet's
own forced-command dispatcher independently refuses anything outside
these six actions.
"""
import argparse
import subprocess
import sys

SSH_ALIAS = "trading-bot-droplet"

ACTIONS = (
    "status",
    "listener-log",
    "digest-log",
    "git-head",
    "halt-state",
    "disk",
)


def build_ssh_command(action: str) -> list[str]:
    """The exact argv for the SSH call for `action` — the bare action
    name is sent as the remote command; droplet_diag_dispatch.sh (on the
    droplet) owns translating it into the real, fixed read-only shell
    command. No other text is ever included."""
    return ["ssh", SSH_ALIAS, action]


def run_action(action: str, runner=subprocess.run) -> int:
    result = runner(build_ssh_command(action), capture_output=True, text=True)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=ACTIONS)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    return run_action(args.action)


if __name__ == "__main__":
    sys.exit(main())
