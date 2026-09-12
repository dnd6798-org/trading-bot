"""
Tier 2 monitoring redesign (CLAUDE.md "Session update ... 2026-09-12,
spec/playbook v77" + the same-day PreToolUse-hook design correction) —
PreToolUse permission hook for the headless Tier 2 diagnostic run.

REPLACES the original plain --allowedTools exact-match design, which a
real live test proved fragile: the model naturally wraps a Bash/
PowerShell invocation in a `cd ... &&`/`; echo "EXIT:$?"` (or the
PowerShell equivalents) even when told to run one exact command, and an
--allowedTools exact-string rule has no tolerance for that — both
attempts were denied on the very first live run, and the diagnostic
never ran at all (see CLAUDE.md for the full incident).

This hook is judged empirically, not from docs alone (verified live
against Claude Code 2.1.220 before this file was written): a PreToolUse
hook's "allow" decision DOES override --permission-mode dontAsk with no
matching --allowedTools entry — a real Bash call was allowed through
and executed with zero entries in `permission_denials`. Its "deny"
decision DOES block a call that would otherwise run — the command never
executed, and Claude's own final answer explicitly reported it was
"blocked by a hook."

Mechanism, still STRICT exact-match, no wildcards anywhere — this hook
only tolerates two FIXED, ENUMERATED wrapper patterns around the six
locked droplet_diag.py commands, nothing else:
  - a known leading `cd <repo root> &&`/`;` (bash/PowerShell forms)
  - a known trailing `; echo "EXIT:$?"`/`; Write-Output
    "EXIT:$LASTEXITCODE"` (bash/PowerShell forms)
After stripping AT MOST one leading and one trailing wrapper, what
remains must be an EXACT match to one of the six locked commands or the
call is denied, with a reason string, including any command that still
doesn't reduce to one of the six after stripping. This does not
introduce a new privilege boundary beyond the six droplet_diag.py
actions — it only tolerates two specific, harmless textual wrappers
around them.

Registered ONLY in scripts/tier2_settings.json (a dedicated settings
file passed via `claude -p --settings ...` from
scripts/run_tier2_diag.ps1) — NOT in .claude/settings.local.json, so
this hook has no effect on interactive Claude Code sessions.
"""
import json
import sys

ALLOWED_COMMANDS = frozenset({
    "python scripts/droplet_diag.py status",
    "python scripts/droplet_diag.py listener-log",
    "python scripts/droplet_diag.py digest-log",
    "python scripts/droplet_diag.py git-head",
    "python scripts/droplet_diag.py halt-state",
    "python scripts/droplet_diag.py disk",
})

# Fixed, enumerated wrapper text only — no regex, no wildcards. Each is
# a literal string observed in the real live-test failure (bash) or its
# direct PowerShell equivalent.
LEADING_WRAPPERS = (
    'cd "D:/Journal/trade/trading-bot" && ',
    'cd "D:\\Journal\\trade\\trading-bot"; ',
)
TRAILING_WRAPPERS = (
    '; echo "EXIT:$?"',
    '; Write-Output "EXIT:$LASTEXITCODE"',
)


def strip_known_wrappers(command: str) -> str:
    """Strips AT MOST one known leading wrapper and AT MOST one known
    trailing wrapper, in that order. A command with neither wrapper
    (already an exact match) passes through unchanged."""
    stripped = command
    for leading in LEADING_WRAPPERS:
        if stripped.startswith(leading):
            stripped = stripped[len(leading):]
            break
    for trailing in TRAILING_WRAPPERS:
        if stripped.endswith(trailing):
            stripped = stripped[:-len(trailing)]
            break
    return stripped


def evaluate_command(command: str) -> tuple[bool, str]:
    """Returns (allowed, reason). `reason` is always populated — used
    as the denial message when not allowed, informational otherwise."""
    stripped = strip_known_wrappers(command)
    if stripped in ALLOWED_COMMANDS:
        return True, f"matches an allowed droplet_diag.py action: {stripped!r}"
    return False, (
        f"command {command!r} does not reduce to one of the six locked "
        f"droplet_diag.py actions after stripping known wrappers "
        f"(reduced to {stripped!r})"
    )


def main() -> None:
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")
    allowed, reason = evaluate_command(command)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if allowed else "deny",
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
