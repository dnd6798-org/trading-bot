"""
scripts/droplet_diag.py — Tier 2 monitoring redesign (CLAUDE.md "Session
update ... 2026-09-12, spec/playbook v77").

Covers argument parsing and command-selection logic only — no real SSH
call is ever made. run_action()'s `runner` is always a fake/mock in
these tests, per the milestone brief's explicit instruction not to run
a live end-to-end test from this session.
"""
from types import SimpleNamespace

import pytest

from scripts import droplet_diag


def _fake_result(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# --- build_ssh_command(): the exact, literal SSH invocation per action ---

@pytest.mark.parametrize("action", droplet_diag.ACTIONS)
def test_build_ssh_command_sends_the_bare_action_name_only(action):
    # No shell command text, no flags, no extra arguments — the droplet-
    # side dispatcher owns translating the action name into a real
    # command. This is the core of the double-enforced read-only
    # boundary the milestone brief requires.
    assert droplet_diag.build_ssh_command(action) == ["ssh", droplet_diag.SSH_ALIAS, action]


def test_build_ssh_command_uses_the_confirmed_alias_not_a_raw_host():
    assert droplet_diag.SSH_ALIAS == "trading-bot-droplet"
    for action in droplet_diag.ACTIONS:
        command = droplet_diag.build_ssh_command(action)
        assert "67.205.164.36" not in command
        assert "tradingbot@" not in " ".join(command)


def test_actions_are_exactly_the_six_locked_actions():
    assert droplet_diag.ACTIONS == (
        "status", "listener-log", "digest-log", "git-head", "halt-state", "disk",
    )


# --- parse_args(): argparse validation ---

@pytest.mark.parametrize("action", droplet_diag.ACTIONS)
def test_parse_args_accepts_each_locked_action(action):
    args = droplet_diag.parse_args([action])
    assert args.action == action


def test_parse_args_rejects_an_unrecognized_action(capsys):
    with pytest.raises(SystemExit) as exc_info:
        droplet_diag.parse_args(["restart-everything"])
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_parse_args_rejects_no_argument():
    with pytest.raises(SystemExit) as exc_info:
        droplet_diag.parse_args([])
    assert exc_info.value.code == 2


def test_parse_args_rejects_extra_arguments():
    # Guards against a future caller accidentally forwarding variable
    # text alongside the action name.
    with pytest.raises(SystemExit) as exc_info:
        droplet_diag.parse_args(["status", "; rm -rf /"])
    assert exc_info.value.code == 2


# --- run_action(): wires the built command through an injected runner ---

def test_run_action_calls_the_runner_with_the_exact_built_command():
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append((command, capture_output, text))
        return _fake_result(stdout="ok\n")

    droplet_diag.run_action("status", runner=fake_runner)

    assert calls == [(["ssh", "trading-bot-droplet", "status"], True, True)]


def test_run_action_prints_stdout_and_returns_the_real_returncode(capsys):
    fake_runner = lambda command, capture_output, text: _fake_result(stdout="hello from droplet\n", returncode=0)

    code = droplet_diag.run_action("disk", runner=fake_runner)

    assert code == 0
    assert capsys.readouterr().out == "hello from droplet\n"


def test_run_action_prints_stderr_and_propagates_a_nonzero_returncode(capsys):
    # systemctl status legitimately returns non-zero when a queried unit
    # is inactive — not an SSH/auth failure, must not be swallowed.
    fake_runner = lambda command, capture_output, text: _fake_result(
        stdout="some output\n", stderr="some warning\n", returncode=3,
    )

    code = droplet_diag.run_action("status", runner=fake_runner)

    assert code == 3
    captured = capsys.readouterr()
    assert captured.out == "some output\n"
    assert captured.err == "some warning\n"


def test_run_action_never_forwards_extra_text_to_the_runner():
    calls = []

    def fake_runner(command, capture_output, text):
        calls.append(command)
        return _fake_result()

    droplet_diag.run_action("git-head", runner=fake_runner)

    assert calls == [["ssh", "trading-bot-droplet", "git-head"]]


# --- main(): wires parse_args() + run_action() together ---

def test_main_parses_and_runs_the_requested_action(monkeypatch):
    recorded = {}

    def fake_run_action(action, runner=None):
        recorded["action"] = action
        return 0

    monkeypatch.setattr(droplet_diag, "run_action", fake_run_action)

    exit_code = droplet_diag.main(["halt-state"])

    assert exit_code == 0
    assert recorded["action"] == "halt-state"


def test_main_returns_2_for_an_invalid_action(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_action must not be called for an invalid action")

    monkeypatch.setattr(droplet_diag, "run_action", fail_if_called)

    with pytest.raises(SystemExit) as exc_info:
        droplet_diag.main(["not-a-real-action"])
    assert exc_info.value.code == 2
