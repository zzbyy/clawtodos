---
name: clawtodos
version: 1.0.0
description: Central cross-project todo aggregator for AI agents (clawtodos / todo-contract/v3). Manage todos across all projects from one central index. Use when zZ asks about todos, what's left, what's pending, what to work on, or wants to add/approve/drop/defer a todo.
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

## Idempotency

All `todos` CLI calls are idempotent. Running the same command twice is safe.

## Privacy

clawtodos stores only project-agnostic todo metadata (titles, priorities, effort estimates). It does not read or write source code, git commits, or any user data beyond the todo entries themselves.
