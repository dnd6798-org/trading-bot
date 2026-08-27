# Project Rules — Read This First

**Purpose:** This file governs *how the two surfaces of this project work together*. It is process discipline, not strategy content — strategy decisions live in `trading-bot-spec-vNN.md`. Read this file at the start of every session, on both surfaces, before doing any work.

---

## 1. The two surfaces and their roles

- **claude.ai chat (this interface):** Expert architect and code reviewer. Owns strategy design, system architecture, guardrail numbers, and validation of everything Claude Code reports. Nothing gets implemented until it's been designed and locked here first.
- **Claude Code (local Windows machine):** Implementer. Builds exactly what's specified in a locked brief from claude.ai. Does not make undocumented architecture or strategy decisions on its own — if something is ambiguous or underspecified, it stops and reports back rather than guessing.

Claude Code should read this file (`RULES.md`) at the start of every session, before starting any work, in addition to `CLAUDE.md`.

**File access is asymmetric.** `trading-bot-spec-vNN.md` and `session-playbook-vNN.md` live only in the claude.ai project — Claude Code has no access to them. Claude Code's only persistent in-repo records are `CLAUDE.md` and this file. Every Claude Code message must therefore be fully self-contained — all decisions and requirements inlined, never left for Claude Code to look up. A "spec vNN §X" mention in a Claude Code message is a provenance citation for `CLAUDE.md`'s history, never a pointer Claude Code is expected to fetch or open.

---

## 2. No vagueness, ever

- Every fact stated by either surface — file names, version numbers, commit hashes, variable/function names, line numbers — must be exact and verified, never a placeholder or an approximation.
- If a fact isn't confirmed, say so explicitly and ask, rather than presenting a guess as settled.
- Claude Code should always report commit hashes and exact test pass/fail counts, never "done" or "tests pass" without the number.
- claude.ai should never refer to "the next version" or "vNext" without pinning down the actual number by checking project files first.

## 3. Claude (claude.ai) does not hand decisions back as open questions

Claude is the domain and architecture expert on this project. For technical, architectural, or strategy-design questions, Claude should research (web search, project files, past chats, code inspection via Claude Code) and give a direct, reasoned recommendation — not a menu of options, and not a question back to the user, unless the question is a genuine product-owner call (business priority, risk tolerance, final approval to proceed/spend/go live).

If Claude is uncertain, the fix is more research, not deferring the decision to the user.

## 4. Communication protocol between the two surfaces

- The user manually copies messages between claude.ai and Claude Code — there is no direct connection between them. Every handoff must therefore be self-contained and exact.
- Whenever claude.ai locks a new decision (design, guardrail numbers, architecture), it must, in the same response:
  1. Update the spec/playbook content (or clearly state what changed if not producing new files that turn).
  2. Provide the exact, verbatim, ready-to-paste Claude Code messages needed to act on it — never described vaguely ("tell Claude Code to update CLAUDE.md").
- Claude Code handoffs are always two separate messages, sent in order:
  1. **CLAUDE.md-update message** — sent first, summarizing the session's decisions. Wait for Claude Code to confirm this is done before sending message 2.
  2. **Milestone/task brief** — sent second, only after CLAUDE.md confirmation.
- When Claude Code reports a milestone back, the user pastes that report into claude.ai. Claude.ai's job is to validate it — check it against what was actually briefed, not just accept a summary at face value. If anything doesn't match the brief (wrong content, unexplained claims, mismatched commit history), stop and ask for direct verification (e.g., `git log`) before treating it as accepted.
- **Droplet-side verification must be reported back the same session.** Claude Code has no droplet access of its own — any check performed directly against the droplet (e.g. manual SSH, guided live by claude.ai) is invisible to Claude Code until it's explicitly reported. Report the exact result (what was checked, what happened, pass/fail) back to Claude Code the same session it happens, so CLAUDE.md never drifts from what's actually true. A milestone with a droplet-verification component is not closed, on either surface, until Claude Code has recorded that confirmation itself. (Added 2026-08-22, after the four systemd-units Step 5 checks ran and passed live on the droplet but sat unreported to Claude Code for a full session afterward.)
- "Pushed to origin/paper" and "deployed on the droplet" are different facts and neither may be asserted without checking the other — verify the droplet's own `git log -1` against origin/paper before marking any droplet-side milestone complete.
- Don't run git commands as root on the droplet; use `sudo -u tradingbot` for anything touching the repo, to avoid leaving `.git` internals root-owned.
- **Claude Code confirming "CLAUDE.md updated" is not the same fact as that update being committed to the repo, and neither may be asserted without checking the other.** A working-tree edit and a git commit are different states — always run `git status` (and `git diff` if anything looks unexpected) before reporting a CLAUDE.md update as done, and report the actual commit hash once committed, not just "updated." (Added 2026-08-27, after the v45 and v46 CLAUDE.md updates were each confirmed as done in-session but sat uncommitted in the working tree for two full sessions, discovered only when the v47 session ran `git status` before committing and found `CLAUDE.md` still showing as modified from two sessions back.)

## 5. Proactive clarity

Both surfaces should surface relevant risks, inconsistencies, or implications the user hasn't explicitly asked about, rather than answering only the literal question. Err toward more context, not less — especially when a design choice has a non-obvious consequence elsewhere in the system.

## 6. Process discipline (carried from the playbook)

- One major topic per session — design work and implementation validation shouldn't be crammed into the same session as a new design.
- No guardrail, architecture, or strategy decision is briefed to Claude Code until it's fully locked in claude.ai first.
- Every milestone that changes tested behavior gets tests proving it, not just a claim.
- Anti-overfitting and pre-committed-bar discipline (see spec) apply to all strategy work; this file governs process, the spec governs strategy content.

---

## 7. Keeping this file current

Update `RULES.md` whenever the process itself changes (not strategy decisions — those go in the spec). Commit it alongside spec/playbook version bumps when relevant.
