# Project Rules — Read This First

**Purpose:** This file governs *how the two surfaces of this project work together*. It is process discipline, not strategy content — strategy decisions live in `trading-bot-spec-vNN.md`. Read this file at the start of every session, on both surfaces, before doing any work.

---

## 1. The two surfaces and their roles

- **claude.ai chat (this interface):** Expert architect and code reviewer. Owns strategy design, system architecture, guardrail numbers, and validation of everything Claude Code reports. Nothing gets implemented until it's been designed and locked here first.
- **Claude Code (local Windows machine):** Implementer. Builds exactly what's specified in a locked brief from claude.ai. Does not make undocumented architecture or strategy decisions on its own — if something is ambiguous or underspecified, it stops and reports back rather than guessing.

Claude Code should read this file (`RULES.md`) at the start of every session, before starting any work, in addition to `CLAUDE.md`.

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
