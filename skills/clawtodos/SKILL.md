---
name: clawtodos
version: 3.1.0
description: Central cross-project todo aggregator for AI agents (clawtodos / todo-contract/v3.1). Manage todos across all projects from one central index, with v3.1 multi-agent coordination (claim/release/handoff with leases) so agents on the same machine don't step on each other. Use when zZ asks about todos, what's left, what's pending, what to work on, or wants to add/approve/drop/defer/claim/release/handoff a todo.
triggers:
  - "what's on my todo list"
  - "what's on my list"
  - "what did agents propose"
  - "pending todos"
  - "anything new"
  - "add a todo"
  - "approve"
  - "drop"
  - "mark done"
  - "start"
  - "inbox review"
  - "clawtodos"
  - "what's left across everything"
  - "what should I work on"
  - "weekly review"
  - "claim"
  - "release"
  - "hand off"
  - "handoff"
  - "give it back"
  - "let claude finish"
  - "let codex finish"
---

# clawtodos — central task system for zZ

zZ's todos for **every project, code repo, and personal program** live at `~/.todos/<slug>/TODOS.md`. One file per project. Lifecycle in a `status:` field. The full spec is at <https://github.com/zzbyy/clawtodos/blob/main/SPEC.md>.

## The rule

This skill is the **agent-facing surface** for clawtodos. It translates natural-language requests into deterministic `todos` CLI calls. The CLI owns persistence, git history, and schema validation. The skill owns conversational routing and response formatting.

**SKILLIFY_STUB** — replaced with operational logic.

## How to use

Run the skill script with a subcommand:

```bash
# List active (default — shows open + in-progress)
bun skills/clawtodos/scripts/clawtodos.mjs list

# List pending (what agents proposed)
bun skills/clawtodos/scripts/clawtodos.mjs list --state pending

# JSON output (for agent processing)
bun skills/clawtodos/scripts/clawtodos.mjs list --json

# Approve a pending item
bun skills/clawtodos/scripts/clawtodos.mjs approve <slug> <id>

# Mark done
bun skills/clawtodos/scripts/clawtodos.mjs done <slug> <id>

# Drop (wont)
bun skills/clawtodos/scripts/clawtodos.mjs drop <slug> <id> --reason <text>

# Defer
bun skills/clawtodos/scripts/clawtodos.mjs defer <slug> <id> --until YYYY-MM-DD

# Add a new open todo
bun skills/clawtodos/scripts/clawtodos.mjs new <slug> "<title>" [--priority P0-P3] [--effort XS-XL]

# Cross-project index (for "what's outstanding across everything")
bun skills/clawtodos/scripts/clawtodos.mjs index

# Weekly review snapshot
bun skills/clawtodos/scripts/clawtodos.mjs snapshot

# v3.1 multi-agent coordination
bun skills/clawtodos/scripts/clawtodos.mjs claim   <slug> <id> --actor <name> [--lease 3600]
bun skills/clawtodos/scripts/clawtodos.mjs release <slug> <id> --actor <name>
bun skills/clawtodos/scripts/clawtodos.mjs handoff <slug> <id> --actor <name> --to <Y>
bun skills/clawtodos/scripts/clawtodos.mjs render  <slug>   # rebuild TODOS.md from EVENTS.ndjson
```

The `todos` CLI must be on PATH (`~/Library/Python/3.9/bin`). If not found, the script falls back to `python3 -m clawtodos`.

## Conversational patterns

| zZ says | Script call |
|---|---|
| "what's on the list" | `list` (active) |
| "what's outstanding across everything" | `index` |
| "anything new" / "what did agents propose" | `list --state pending` |
| "what should I work on" | `list --json` + score by priority/effort |
| "approve X" | `approve <slug> <id>` |
| "drop X" / "out of scope" | `drop <slug> <id> --reason ...` |
| "defer X to date" | `defer <slug> <id> --until YYYY-MM-DD` |
| "weekly review" | `snapshot` + diff vs last week |
| **"claim X" / "I'll take X"** (v3.1) | `claim <slug> <id> --actor <self>` |
| **"release X"** (v3.1) | `release <slug> <id> --actor <self>` |
| **"hand off X to Y"** (v3.1) | `handoff <slug> <id> --actor <self> --to <Y>` |

## Multi-agent coordination (v3.1)

When more than one agent runs against the same `~/.todos/<slug>/`, claim the task before working on it. Before starting non-trivial work, check `claimed_by` on the target todo (read it from `list --json`); if another agent holds the claim and the lease hasn't expired, pick a different task. `claim` succeeds when nobody holds it, the lease expired, OR you ARE the current holder (self-refresh). `handoff` succeeds when nobody holds it (delegation) OR you ARE the holder. Otherwise both error with a stable code (`already_claimed`, `task_held_by_other_actor`). Claims are advisory hints, not enforcement — `start`/`done`/`drop` do not check the claim. See [SPEC-v3.1.md §8](https://github.com/zzbyy/clawtodos/blob/main/SPEC-v3.1.md).

For MCP-aware clients (Claude Desktop, Cursor, Continue, Zed), `pip install 'clawtodos[mcp]'` installs `clawtodos-mcp` — the same surface, exposed as MCP tools.

## Idempotency

All `todos` CLI calls are idempotent. Running the same command twice is safe.

## Privacy

clawtodos stores only project-agnostic todo metadata (titles, priorities, effort estimates). It does not read or write source code, git commits, or any user data beyond the todo entries themselves.
