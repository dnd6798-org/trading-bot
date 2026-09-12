<#
Tier 2 monitoring redesign (CLAUDE.md "Session update ... 2026-09-12,
spec/playbook v77" + the same-day PreToolUse-hook design correction) —
headless droplet diagnostic run.

Runs a headless `claude -p` diagnosis scoped to droplet_diag.py's six
read-only actions via scripts/tier2_settings.json's PreToolUse hook
(scripts/tier2_permission_hook.py) — NOT a plain --allowedTools
exact-match string. A live test proved --allowedTools alone too
fragile: the model naturally wraps the Bash/PowerShell invocation in a
harmless `cd ... &&`/`; echo "EXIT:$?"` even when told to run one exact
command, and an exact-match --allowedTools rule has zero tolerance for
that — the diagnostic never ran at all on the first live attempt (see
CLAUDE.md for the full incident). The hook tolerates exactly two FIXED,
enumerated wrapper patterns around the same six locked commands, still
denying anything that doesn't reduce to one of them — no wildcards
anywhere in the matching logic, same security property as before, just
robust to that one real failure mode. --permission-mode dontAsk is
unchanged: it still auto-denies any unlisted tool call with no prompt
(correct for an unattended run with no human present), and the hook
only ever grants the same six actions --allowedTools used to name
directly. Empirically verified against the real CLI (2.1.220) before
being relied on here: a PreToolUse hook's "allow" decision does
override dontAsk with no matching --allowedTools entry, and "deny"
does block a call that would otherwise run — see CLAUDE.md.

scripts/tier2_settings.json is a DEDICATED settings file, registered
only for this headless invocation via --settings — never merged into
.claude/settings.local.json, so this hook has zero effect on
interactive Claude Code sessions.

Parses the JSON `result` field and forwards it to Telegram via
src.telegram_bot.send_message() (reused unchanged, through the
scripts/send_tier2_alert.py shim) — same mechanism Tier 1 already uses,
prefixed distinctly as a Tier 2 diagnostic so it's never confused with
Tier 1's operational alerts.

Diagnosis only — the prompt itself instructs no fix/restart/modify
action, and every action the hook can ever allow is read-only by
construction regardless of what the prompt says.

NOT yet wired to Windows Task Scheduler for unattended firing as of
this commit — see CLAUDE.md v77 for why (first live run must happen
session-live, together, before any unattended trigger is enabled).
#>

$ErrorActionPreference = "Stop"

$repoRoot = "D:\Journal\trade\trading-bot"
Set-Location $repoRoot

$logsDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logsDir "tier2-diag-$timestamp.json"

$prompt = @"
Run the droplet diagnostic check: execute each of the six droplet_diag.py actions and summarize findings in plain language. Flag any anomaly: a service not active, an unexpected restart count, disk usage over 80%, halt state set when it shouldn't be, or git HEAD not matching the last known origin/paper commit. This is diagnosis only — do not attempt to fix, restart, or modify anything.
"@

$tier2Settings = Join-Path $repoRoot "scripts\tier2_settings.json"

claude -p $prompt --settings $tier2Settings --permission-mode dontAsk --output-format json |
    Out-File -FilePath $logFile -Encoding utf8

if (-not (Test-Path $logFile)) {
    Write-Error "Tier 2 diagnostic run produced no log file at $logFile"
    exit 1
}

$raw = Get-Content -Path $logFile -Raw
if ([string]::IsNullOrWhiteSpace($raw)) {
    Write-Error "Tier 2 diagnostic log file at $logFile is empty."
    exit 1
}

try {
    $parsed = $raw | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse Tier 2 diagnostic JSON output at $logFile : $_"
    exit 1
}

$result = $parsed.result
if ([string]::IsNullOrWhiteSpace($result)) {
    Write-Error "Tier 2 diagnostic JSON output at $logFile had no 'result' field."
    exit 1
}

$message = "[TIER 2 DIAGNOSTIC -- $timestamp]`n`n$result"

$message | python scripts\send_tier2_alert.py
