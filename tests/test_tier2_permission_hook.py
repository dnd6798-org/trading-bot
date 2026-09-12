"""
scripts/tier2_permission_hook.py — PreToolUse hook replacing the
--allowedTools exact-match design (CLAUDE.md "Session update ...
2026-09-12, spec/playbook v77" and the same-day PreToolUse-hook design
correction, made after a live test proved plain --allowedTools too
fragile to tolerate a harmless cd/echo wrapper around the command).

Covers strip_known_wrappers()/evaluate_command() only — pure functions,
no stdin/stdout I/O exercised here. The empirical "does allow/deny
actually work against the real CLI" question was verified live this
session (see CLAUDE.md), not re-tested here.
"""
import pytest

from scripts import tier2_permission_hook as hook


SIX_EXACT_COMMANDS = (
    "python scripts/droplet_diag.py status",
    "python scripts/droplet_diag.py listener-log",
    "python scripts/droplet_diag.py digest-log",
    "python scripts/droplet_diag.py git-head",
    "python scripts/droplet_diag.py halt-state",
    "python scripts/droplet_diag.py disk",
)


# --- strip_known_wrappers() ---

@pytest.mark.parametrize("command", SIX_EXACT_COMMANDS)
def test_strip_known_wrappers_is_a_noop_on_an_already_exact_command(command):
    assert hook.strip_known_wrappers(command) == command


def test_strip_known_wrappers_strips_the_real_bash_wrapper_from_the_live_incident():
    # The exact command the live test's permission_denials showed.
    command = 'cd "D:/Journal/trade/trading-bot" && python scripts/droplet_diag.py status; echo "EXIT:$?"'
    assert hook.strip_known_wrappers(command) == "python scripts/droplet_diag.py status"


def test_strip_known_wrappers_strips_the_real_powershell_wrapper_from_the_live_incident():
    command = 'cd "D:\\Journal\\trade\\trading-bot"; python scripts/droplet_diag.py status; Write-Output "EXIT:$LASTEXITCODE"'
    assert hook.strip_known_wrappers(command) == "python scripts/droplet_diag.py status"


def test_strip_known_wrappers_strips_leading_only():
    command = 'cd "D:/Journal/trade/trading-bot" && python scripts/droplet_diag.py disk'
    assert hook.strip_known_wrappers(command) == "python scripts/droplet_diag.py disk"


def test_strip_known_wrappers_strips_trailing_only():
    command = 'python scripts/droplet_diag.py git-head; echo "EXIT:$?"'
    assert hook.strip_known_wrappers(command) == "python scripts/droplet_diag.py git-head"


def test_strip_known_wrappers_never_strips_an_unrecognized_wrapper():
    # A DIFFERENT-looking wrapper, not one of the four fixed strings —
    # must be left completely untouched (no partial/fuzzy stripping).
    command = 'cd /some/other/path && python scripts/droplet_diag.py status'
    assert hook.strip_known_wrappers(command) == command


# --- evaluate_command() ---

@pytest.mark.parametrize("command", SIX_EXACT_COMMANDS)
def test_evaluate_command_allows_each_of_the_six_exact_commands(command):
    allowed, reason = hook.evaluate_command(command)
    assert allowed is True
    assert command in reason


def test_evaluate_command_allows_a_wrapped_version_of_an_allowed_command():
    command = 'cd "D:/Journal/trade/trading-bot" && python scripts/droplet_diag.py halt-state; echo "EXIT:$?"'
    allowed, reason = hook.evaluate_command(command)
    assert allowed is True


def test_evaluate_command_denies_an_unrelated_command_with_a_reason():
    allowed, reason = hook.evaluate_command("rm -rf /")
    assert allowed is False
    assert "rm -rf /" in reason


def test_evaluate_command_denies_a_close_but_wrong_action_name():
    # Not one of the six — must not fuzzy-match.
    allowed, reason = hook.evaluate_command("python scripts/droplet_diag.py restart-everything")
    assert allowed is False


def test_evaluate_command_denies_a_command_that_still_doesnt_reduce_after_stripping():
    # Has a recognized leading wrapper, but the payload after it is not
    # one of the six — must still be denied, not accidentally allowed
    # just because a known wrapper was present.
    command = 'cd "D:/Journal/trade/trading-bot" && rm -rf /; echo "EXIT:$?"'
    allowed, reason = hook.evaluate_command(command)
    assert allowed is False
    assert "rm -rf /" in reason


def test_evaluate_command_denies_an_extra_flag_appended_to_an_allowed_command():
    # No partial/prefix matching — an allowed command plus anything
    # extra must be denied outright.
    allowed, reason = hook.evaluate_command("python scripts/droplet_diag.py status --extra-flag")
    assert allowed is False


def test_evaluate_command_denies_empty_string():
    allowed, reason = hook.evaluate_command("")
    assert allowed is False


# --- main(): stdin/stdout wiring ---

def test_main_reads_tool_input_command_and_prints_the_allow_decision(monkeypatch, capsys):
    import io
    payload = '{"tool_name": "Bash", "tool_input": {"command": "python scripts/droplet_diag.py disk"}}'
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    hook.main()

    import json
    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_main_denies_when_tool_input_has_no_command_key(monkeypatch, capsys):
    import io
    payload = '{"tool_name": "Bash", "tool_input": {}}'
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    hook.main()

    import json
    output = json.loads(capsys.readouterr().out)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
