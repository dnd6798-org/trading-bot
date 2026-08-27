"""
Persisted halt state — checked on every process boot.

Spec §2/§4.5/§7 (locked v5): a systemd restart brings the *process* back,
never the trading state. If the bot was halted (daily loss limit, drawdown
breach, manual kill switch) before a crash/restart, it must come back up
still halted. Resuming is always a manual, human decision — never automatic.

This is intentionally the simplest possible mechanism (a JSON file) so it's
easy to audit by hand. Swap the backing store later if needed, but keep the
interface the same.
"""
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

_STATE_PATH = os.environ.get("HALT_STATE_PATH", "halt_state.json")

# Track-C-specific halt (spec v55 §10.25, Milestone 2 — position-ownership
# ledger). Deliberately a SEPARATE file from the global/Track-B halt
# above: the position-reconciliation integrity check
# (track_positions.reconcile_symbol()) must be able to halt Track C's
# autonomous trading WITHOUT touching Track B — the two halts are
# independent by design. Same persisted-JSON / survives-restart /
# human-clears-only semantics as the global halt (spec §2/§4.5/§7),
# reusing the same HaltState shape — only the backing file differs, which
# is why this lives here in the halt module rather than in
# track_positions.py (halting semantics are a distinct concern from
# position bookkeeping and stay centralized here regardless of which
# track is halted). Nothing READS this halt yet — Track C has no
# execution code until Milestone 3; this milestone only records it.
_TRACK_C_STATE_PATH = os.environ.get("TRACK_C_HALT_STATE_PATH", "track_c_halt_state.json")


@dataclass
class HaltState:
    halted: bool
    reason: str | None = None
    halted_at: str | None = None


def load_halt_state() -> HaltState:
    if not os.path.exists(_STATE_PATH):
        # No file yet = never halted. Default is NOT trading-enabled by
        # itself — this only reports halt status; the trade loop still
        # needs an explicit human "go" the very first time it runs.
        return HaltState(halted=False)
    with open(_STATE_PATH) as f:
        return HaltState(**json.load(f))


def set_halt(reason: str) -> None:
    state = HaltState(
        halted=True,
        reason=reason,
        halted_at=datetime.now(timezone.utc).isoformat(),
    )
    with open(_STATE_PATH, "w") as f:
        json.dump(asdict(state), f, indent=2)


def clear_halt() -> None:
    """
    Only ever called after explicit human approval (Telegram command).
    Never called automatically on boot — see spec §7 human-in-the-loop table.
    """
    state = HaltState(halted=False)
    with open(_STATE_PATH, "w") as f:
        json.dump(asdict(state), f, indent=2)


# --- Track-C halt (spec v55 §10.25) — same mechanism, separate file -------
# Independent of the global/Track-B halt above: set_track_c_halt() must
# never affect load_halt_state(), and vice versa.


def load_track_c_halt() -> HaltState:
    if not os.path.exists(_TRACK_C_STATE_PATH):
        return HaltState(halted=False)
    with open(_TRACK_C_STATE_PATH) as f:
        return HaltState(**json.load(f))


def set_track_c_halt(reason: str) -> None:
    state = HaltState(
        halted=True,
        reason=reason,
        halted_at=datetime.now(timezone.utc).isoformat(),
    )
    with open(_TRACK_C_STATE_PATH, "w") as f:
        json.dump(asdict(state), f, indent=2)


def clear_track_c_halt() -> None:
    """Human-only, same convention as clear_halt() — never called automatically on boot."""
    state = HaltState(halted=False)
    with open(_TRACK_C_STATE_PATH, "w") as f:
        json.dump(asdict(state), f, indent=2)
