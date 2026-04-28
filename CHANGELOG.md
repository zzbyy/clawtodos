# Changelog

All notable changes to `clawtodos` will be documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Fixed

- **`todos ingest` no longer overwrites `done`/`wont` items.** Previously, ingesting a v1 in-repo `TODOS.md` forced **every** parsed entry to `status: pending`, including items that the v1 source already marked done (via `## Done` group heading) or killed (via `~~strikethrough~~` titles). The user then had to wade through completed work in the review queue. Ingest now preserves terminal states (`done`, `wont`); only genuinely active source entries become `pending`.

### Changed

- **`todos list` empty-active output now nudges the user toward pending.** When the default `active` filter returns no results but pending (or done) entries exist, the CLI prints a `note:` line so users don't think "nothing on the list" when really 24 ingested proposals are waiting for review. Example:
  ```
  $ todos list
  (empty)
  note: 24 pending review — `todos list --state pending` (or say 'anything new?')
  ```
  The agent snippet (`snippets/AGENTS_SNIPPET.md`) and OpenClaw skill are updated to surface this `note:` to users instead of just relaying "empty".

### Added

- **`todos list --json`.** Emits structured output for agent consumption: per-project todos plus per-project status counts plus top-level aggregate counts. Lets agents do morning-briefing generation and smart prioritization without parsing human-readable text. Example:
  ```bash
  todos list --json | jq '.counts'
  todos list --state all --json | jq '.projects[] | select(.counts.pending > 0)'
  ```

## [3.0.0] — 2026-04-28

Schema redesign. Major rewrite of the file model and conversational vocabulary based on feedback that the v2 4-file split (`INBOX.md` / `TODOS.md` / `DONE.md` / `REJECTED.md`) was overengineered, and that `INBOX` collided with email semantics for users with Gmail-integrated agents.

### Changed (BREAKING)

- **Schema string:** `todo-contract/v2` → `todo-contract/v3`.
- **One file per project.** All entries for a project live in `~/.todos/<slug>/TODOS.md`. No more `INBOX.md`, `DONE.md`, `REJECTED.md`.
- **Lifecycle is now a `status:` field**, not a file location:
  - `pending` — agent proposed autonomously, awaits user confirmation
  - `open` — confirmed work, on the list, not started
  - `in-progress` — actively being worked
  - `done` — shipped (stays in TODOS.md)
  - `wont` — declined / out of scope (kept as a tombstone so agents don't re-propose)
- **Agents writing on the explicit-approval path use `status: open` directly.** When the user says *"add this"*, they already approved by speaking. The `pending` state exists for the rare autonomous case.
- **Rejection is now `status: wont` with optional `wont_reason`,** not a separate file. Visible to agents so they don't re-propose. Git history captures the transition.
- **CLI verbs renamed and added:**
  - new: `todos new <slug> "<title>"` — adds an open todo (interactive path)
  - new: `todos propose <slug> "<title>"` — adds a pending todo (autonomous path)
  - new: `todos start <slug> <id>` — open → in-progress
  - new: `todos drop <slug> <id> [--reason]` — replaces `todos reject`; flips to wont
  - new: `todos snapshot` — write weekly snapshot for diff-based reviews
  - removed: `todos move`, `todos reject`
  - `todos approve` now flips pending → open (was: move INBOX → TODOS)
  - `todos done` now flips status → done (was: move TODOS → DONE)

### Added

- **Conversational vocabulary as part of the spec (SPEC.md §6).** 11 phrase patterns mapped to deterministic agent actions. Any clawtodos-conformant agent recognizes these phrases. Examples:
  - *"what's on the list"* / *"what are the todos"* → show open + in-progress
  - *"what's outstanding across everything"* → cross-project rollup
  - *"anything new"* / *"what did the agents propose"* → show pending
  - *"what should I tackle in 2 hours"* → smart prioritization by priority + effort + freshness
  - *"weekly review"* → diff vs last week's snapshot
- **Cross-project `INDEX.md`** with morning-briefing format: counts by priority, top P0/P1, stale items (>30d), done this week, pending review, by-project breakdown.
- **Weekly snapshots** at `~/.todos/snapshots/YYYY-Wxx.json` for shipped/created/net-delta computation.
- **OpenClaw skill renamed and expanded** from `clawtodos-review` to just `clawtodos`. Now ~400 lines covering all 11 conversational patterns, smart prioritization, heartbeat alerts (P0/P1, stale spotlight), and weekly review template.

### Migration from v2

If you ran v2 (briefly): `~/.todos/<slug>/INBOX.md` entries should be appended to `<slug>/TODOS.md` with `status: pending`. `DONE.md` entries become `<slug>/TODOS.md` entries with `status: done`. `REJECTED.md` entries become `status: wont` with `wont_reason` set. A migration helper isn't included because v2 had a tiny user base; manual `cat` + edit is faster.

If you ran v1 (per-repo `TODOS.md`): no breaking change for v1 itself — `todo-contract/v1` repos keep working untouched. `todos add /path --ingest` reads v1 in-repo files and writes them to your central TODOS.md as `status: pending`.

## [2.2.0] — 2026-04-27

### Removed

- **`install.py`** — deleted. It was redundant with `pip install` (both put `todos` on PATH and bootstrap `~/.todos/`), and confusing to users trying to understand which install path to use. The agent-native flow (`BOOTSTRAP.md`) and the manual fallback (`pip install`) both now use `pip` exclusively. One install path, no ambiguity.

### Changed

- README "Manual install" section trimmed to one option: `pip install --user git+https://github.com/zzbyy/clawtodos.git`. Dev install for contributors stays.
- Snippet (`snippets/AGENTS_SNIPPET.md`) updated to reference only the pip command.

### Migration

If you ran the old `install.py`, no action needed — it produced exactly the same end state as `pip install`. The `todos` command on your PATH is unchanged.

## [2.1.1] — 2026-04-27

### Changed

- **README rewritten around the conversational UX.** Replaced the CLI-first "Quick start" / "Wire up agents" / "How to use it" sections with three new ones: **First conversation — per agent** (concrete table of where to paste the install line in OpenClaw / Claude Code / Codex / Cursor), **Daily use — just talk to your agent** (natural-language dialogue examples for adding, reviewing, approving, deferring, rejecting, closing), and **A day in the life** (end-to-end narrative across three agents collaborating on the same task tree).
- The CLI is still documented but moved to an "escape hatch" section after the agent-native flow. Reinforces that users don't need to memorize commands — talking to the agent is the primary UX.

## [2.1.0] — 2026-04-27

### Added

- **`BOOTSTRAP.md`** — agent-native install procedure. Paste one line into any AI agent (OpenClaw, Claude Code, Codex, Cursor) and it walks the user through full setup: detect environment, pip install, init `~/.todos/`, discover other AI agents on the machine, wire each one with the snippet (auto-replacing legacy v1 blocks), install the OpenClaw review skill, register active projects, run doctor, queue first review. About 2 minutes, fully conversational.
- **README** now leads with the agent-native install. pip / install.py / dev install moved to a "Manual install" subsection for users who don't yet have an agent set up.

### Changed

- Manual install paths (pip / install.py) are unchanged and still supported. The agent-native flow is layered on top, not a replacement.

## [2.0.0] — 2026-04-27

Initial release of `clawtodos`.

This is the v2 of the [todo-contract](https://github.com/zzbyy/todo-contract) project. v1 is per-repo and voluntary; v2 (clawtodos) is central and approval-gated. Both are independently maintained — v1 is not deprecated.

### Added

- **Central architecture.** All canonical state lives in `~/.todos/` (or `$TODO_CONTRACT_ROOT`). Repos are read-only sources.
- **Approval staging.** Each project has `INBOX.md` (proposed by agents) and `TODOS.md` (approved by humans), plus `DONE.md` and `REJECTED.md` for audit.
- **`agent:` field.** Required on every INBOX entry. Identifies the agent that proposed it (`claude-code`, `codex`, `cursor`, `openclaw`, `human`, `ingest`, ...).
- **`deferred:` field.** Optional ISO-date that hides an inbox entry from review until that date.
- **`rejected_at:` and `rejected_reason:` fields.** Captured automatically when a proposal is rejected.
- **`todos` CLI.** Zero-deps Python (3.9+). Verbs: `init`, `add`, `list`, `move`, `approve`, `reject`, `defer`, `done`, `ingest`, `index`, `doctor`.
- **Cross-platform installer.** `python install.py` works on macOS, Linux, and Windows. pip install also supported.
- **OpenClaw skill `clawtodos-review`.** Conversational walker that drives the four verbs one entry at a time.
- **Per-action git audit log.** Every approve / reject / defer / done is one commit in `~/.todos/`.

### Compatibility with v1

- v1 markdown per-todo block format is unchanged. v1 parsers can read v2 files (unknown fields are ignored, per v1 §10).
- `todos ingest <slug>` reads a v1 in-repo `TODOS.md` (or `.planning/todos/`) and writes the entries to `<slug>/ingested.md` for one-shot import as proposals. The source repo is never modified.
