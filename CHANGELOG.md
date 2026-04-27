# Changelog

All notable changes to `clawtodos` will be documented in this file. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/).

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
