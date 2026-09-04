# systemd units — Track B daily job + fill-protection listener + Track C rebalance job + daily digest

spec v34 §10.6 (Track B daily job + listener), spec v59 §10.29 (Track C
rebalance job), and the Tier 1 monitoring redesign (CLAUDE.md "Session
update ... 2026-09-04, spec/playbook v76" — the digest job + the
listener's ExecStartPost/ExecStopPost alert hooks). These files are the
deployment artifacts; nothing in this directory runs on its own until
installed on the droplet.

`trading-bot-track-c.service` / `.timer` (spec v59 §10.29) run
`python -m src.track_c_execution` — the DMSR monthly sector-rotation
rebalance. The timer fires every weekday at the same 17:00
America/New_York as the Track B daily timer; the job self-gates via
`dmsr_signal.is_rebalance_day()` and is a no-op on every day except the
first trading day after a month-end. See the `.timer` file's header for
a flagged (unresolved) same-17:00 race concern with the Track B daily
job over the shared AGG ledger. All `.service` files' `User=`,
`WorkingDirectory=`, and `EnvironmentFile=` must match exactly.

`trading-bot-listener.service` gained `ExecStartPost=`/`ExecStopPost=`
hooks (Tier 1 monitoring redesign) that call `scripts/service_alert.py`
to send a Telegram alert on every listener start/stop/restart (a restart
is a stop followed by a start, so both hooks fire — no separate restart
case needed). `trading-bot-digest.service` / `.timer` (also Tier 1) run
`python -m src.daily_digest` — a read-only reporting job (current
positions per track, halt status, and three sections explicitly flagged
"not yet available": today's fills, today's errors, listener restart
count — see `src/daily_digest.py`'s module docstring for why each has no
real data source yet). The timer fires a literal `21:30:00 UTC`,
weekdays only — see the `.timer` file's own header for a flagged DST-drift
caveat versus the other two timers' `America/New_York`-anchored schedule.
Neither the digest job's units nor the listener's new alert hooks have
been installed/enabled on the droplet as of this milestone — see
"Install" below.

## Before installing — verify, don't assume

Three facts these unit files currently assume (chosen conventions, not
confirmed against the real droplet — no droplet access from the
Windows-local Claude Code session that authored them; see CLAUDE.md
"Current status", systemd-units milestone, for the full record):

1. **Deployment path.** Assumed `/opt/trading-bot` with venv at
   `/opt/trading-bot/venv`. If the real deployment lives elsewhere,
   either move it to `/opt/trading-bot` or edit `WorkingDirectory=`,
   `EnvironmentFile=`, and `ExecStart=` in all three files consistently
   — the two `.service` files' `WorkingDirectory=` must match each
   other exactly (see `trading-bot-listener.service`'s header comment:
   `halt_state.py` resolves its state file relative to CWD).
2. **`.env` location.** Assumed `/opt/trading-bot/.env`, alongside the
   code. Confirm this is really where manual runs load `.env` from
   today before trusting `EnvironmentFile=`.
3. **systemd version.** `trading-bot-daily.timer`'s `OnCalendar=` uses a
   per-line timezone suffix, which needs systemd >= 239. Run
   `systemctl --version` on the droplet before enabling the timer; on
   an older systemd, set the box's system timezone to
   `America/New_York` instead and drop the trailing timezone from
   `OnCalendar=`.

## Step 4 — create the service user

No login shell, not in sudoers:

```
sudo useradd --system --no-create-home --shell /usr/sbin/nologin tradingbot
sudo chown -R tradingbot:tradingbot /opt/trading-bot
```

(Adjust the path if item 1 above resolved differently.)

## Install

```
sudo cp trading-bot-daily.service trading-bot-daily.timer trading-bot-listener.service \
        trading-bot-track-c.service trading-bot-track-c.timer \
        trading-bot-digest.service trading-bot-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-bot-daily.timer
sudo systemctl enable --now trading-bot-listener.service
sudo systemctl enable --now trading-bot-track-c.timer
sudo systemctl enable --now trading-bot-digest.timer
```

Also copy `scripts/service_alert.py` to `/opt/trading-bot/scripts/` if it
isn't already present via `git pull` — `trading-bot-listener.service`'s
new `ExecStartPost=`/`ExecStopPost=` hooks call it by absolute path.

Per the Milestone 4 brief, actually enabling/starting `trading-bot-track-c`
on the droplet is a later deployment step, not part of the build
milestone — the unit files are committed here but were NOT installed or
started anywhere by that milestone. The same is true of
`trading-bot-digest.service`/`.timer` and `trading-bot-listener.service`'s
new alert hooks (Tier 1 monitoring redesign) — committed, not yet
installed/enabled on the droplet.

## Step 5 — droplet-only verification (not performable from Windows/local dev)

- **Restart-safety, through systemd itself:**
  ```
  sudo systemctl status trading-bot-listener.service   # note the PID
  sudo kill -9 <PID>
  sleep 15
  sudo systemctl status trading-bot-listener.service   # should be active again, new PID, within RestartSec=10
  ```
- **Manual daily-job trigger:**
  ```
  sudo systemctl start trading-bot-daily.service
  sudo systemctl status trading-bot-daily.service       # should show inactive (dead) / exit code 0 once the oneshot completes
  sudo journalctl -u trading-bot-daily.service -n 50
  ```
- **Reboot survival + halt-state check:**
  ```
  sudo systemctl is-enabled trading-bot-daily.timer trading-bot-listener.service   # both should print "enabled"
  sudo reboot
  # after reboot:
  sudo systemctl status trading-bot-daily.timer trading-bot-listener.service   # both active, no manual start needed
  cat /opt/trading-bot/halt_state.json   # if halted before reboot, must still read halted=true after
  ```
  If the bot was halted before the reboot, `run_daily_execution_job()`
  gates new entries on `halt_state.load_halt_state()` (see
  `src/execution.py`) — confirm the post-reboot daily-job log shows
  `"halted": true` and no new entries, per the repo's standing "never
  auto-resume trading after a crash/restart" rule.

These four checks were NOT run this session — they require the actual
droplet and a real systemd instance, neither of which this session had
access to. What WAS verified locally (Windows, no systemd): `python -m
src.execution` runs to completion and exits 0 against the real paper
account, and `python -m src.fill_listener` starts and blocks cleanly
with no startup error against the real paper account's WebSocket. See
CLAUDE.md for the exact output of both.
