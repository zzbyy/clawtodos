# clawtodos / todo-contract/v3 — Specification

**Status:** Stable (v3.0.0)
**Version:** 3.0.0
**Schema identifier:** `todo-contract/v3`

This document defines the format, parsing rules, agent contract, and conversational vocabulary for `clawtodos`. v3 keeps the v1 per-todo block format unchanged but consolidates the v2 four-file lifecycle (INBOX/TODOS/DONE/REJECTED) into a single `TODOS.md` per project, with the lifecycle encoded in each entry's `status:` field.

> **Why v3 over v2:** four files for what's fundamentally a five-state lifecycle was overengineered. `INBOX.md` collided with email semantics. `DONE.md` and `REJECTED.md` were graveyard files. v3 keeps the approval gate (it's now conversational, between you and the agent, before anything gets written) but eliminates the file sprawl.

---

## 1. Goals

- **G1.** One file per project. The state of every entry — proposed by an agent, on your list, in progress, shipped, or declined — lives in a single `status:` field on a single file.
- **G2.** Agent-native. Any AI agent that reads instruction files (Claude Code, Codex, Cursor, OpenClaw, …) can read and write the format consistently.
- **G3.** Repos stay clean. Nothing in this system writes to your code repos. Repos are read-only sources for ingestion.
- **G4.** Plain Markdown. Diffable in git, readable in any editor, parseable by any tool.
- **G5.** Conversational vocabulary is part of the spec, not just docs. Any compliant agent maps a fixed set of natural-language phrases to deterministic actions.

---

## 2. Central Layout

A v3-conforming installation has a single root directory, by default `~/.todos/`. Set `$TODO_CONTRACT_ROOT` to override.

```
$TODO_CONTRACT_ROOT/
├── registry.yaml               # registered projects (see §3)
├── INDEX.md                    # generated cross-project rollup
├── snapshots/
│   └── YYYY-Wxx.json           # weekly snapshots for diff-based reviews
├── <project-slug>/
│   └── TODOS.md                # ONE canonical file per project
└── personal/
    └── <program-slug>/
        └── TODOS.md
```

### 2.1 Repo isolation

A v3 system MUST NOT modify any registered project's working tree. Any "ingestion" of existing in-repo todos appends entries to `<slug>/TODOS.md` with `status: pending` and never writes back to the source repo.

### 2.2 Project slugs

Slugs are lowercase, hyphenated, and globally unique within `registry.yaml`. Personal/non-repo programs MAY use a `personal/<name>` form; the slash is permitted in slugs only for the `personal/` prefix.

### 2.3 Root as a git repo

`$TODO_CONTRACT_ROOT` SHOULD be a git repository. Every status transition (approve, start, done, drop, defer) SHOULD produce one commit, providing a free audit log. Tools MUST function correctly when the root is not a git repo (commits become no-ops).

---

## 3. registry.yaml

The registry declares what projects are known to the system.

```yaml
schema: todo-contract/v3
projects:
  - slug: my-app
    type: code
    path: /home/alice/code/my-app
    ingest: true

  - slug: side-project
    type: code
    path: /home/alice/code/side-project
    ingest: true

  - slug: personal/health
    type: program
    ingest: false
```

| Key | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | Unique project identifier. Becomes the directory name under root. |
| `type` | `code` \| `program` | yes | `code` = a git repo. `program` = a non-code domain (health, learning, errands). |
| `path` | string | no | Filesystem path to the source. Tilde-expansion required. Optional for `program` types. |
| `ingest` | bool | no, default `false` | If true, ingestion scans `path` for existing todos. |

Additional keys are RESERVED. v3 parsers MUST ignore unknown keys.

---

## 4. Per-Todo Block

Each todo is one Markdown `###` heading followed by an optional field list and an optional body, terminated by the next `###`, the next `##`, a horizontal rule (`---`) on its own line, or end of file.

```markdown
### Fix auth token refresh on expiry
- **status:** open
- **priority:** P1
- **effort:** S
- **agent:** claude-code
- **created:** 2026-04-28
- **updated:** 2026-04-28
- **tags:** auth, security

Body — what / why / context, free-form Markdown.

---
```

### 4.1 Recognized fields

| Field | Allowed values | Default | Notes |
|---|---|---|---|
| `status` | `pending`, `open`, `in-progress`, `done`, `wont` | `open` | The lifecycle. See §5. |
| `priority` | `P0`, `P1`, `P2`, `P3` | `P2` | Lower number = higher priority. P0 = drop everything. |
| `effort` | `XS`, `S`, `M`, `L`, `XL` | _none_ | Rough time estimate. |
| `agent` | string slug naming the agent | _none_ | REQUIRED on entries with `status: pending`. Optional otherwise. Example values: `claude-code`, `codex`, `cursor`, `openclaw`, `human`, `ingest`. |
| `created` | `YYYY-MM-DD` | _none_ | Creation date. |
| `updated` | `YYYY-MM-DD` | _none_ | Last meaningful update — set automatically on every status transition. |
| `tags` | comma-separated list | _none_ | Free-form tags for filtering and grouping. |
| `deferred` | `YYYY-MM-DD` | _none_ | If set and in the future, the entry is hidden from the default `active` list until the date is reached. |
| `wont_reason` | string | _none_ | Set when an entry transitions to `status: wont`, capturing why. |

Field VALUES are case-insensitive on parse; parsers SHOULD canonicalize on emit (`p1` → `P1`, `m` → `M`, `OPEN` → `open`).

### 4.2 Backward-compatibility (v1/v2 conventions)

Parsers MUST honor these freeform conventions to avoid forcing a migration:

- Strikethrough title (`~~text~~`) → `status: done`.
- A `## Done` group heading → every `###` until the next `##` or EOF is treated as `status: done`.
- Priority aliases: `urgent`/`critical` → `P0`; `high` → `P1`; `med`/`medium` → `P2`; `low` → `P3`.

---

## 5. The Five Statuses (Lifecycle)

| Status | Meaning | Set by |
|---|---|---|
| `pending` | An agent autonomously proposed this. The user hasn't reviewed it yet. | Agent acting without immediate user confirmation. |
| `open` | Confirmed work, on the list, not started. | User (directly or after agent asks "should I add this?"). |
| `in-progress` | Actively being worked. | User or `todos start`. |
| `done` | Shipped. | User or `todos done`. |
| `wont` | Decided not to do. Kept as a tombstone so agents see it and don't re-propose. | User or `todos drop`. |

### 5.1 The two write paths

**Interactive (the common case).** The user is in conversation with an agent. The agent suggests, asks, the user agrees, the agent writes the entry with `status: open` directly. Example: *"add 'fix auth bug' to the my-app todos"* → entry written, status `open`.

**Autonomous (the minority case).** The agent is finishing work and notices a follow-up worth recording. The user isn't in the conversation. The agent writes the entry with `status: pending`. The user reviews next time they ask *"anything new?"* and either approves (`pending → open`) or drops (`pending → wont`).

### 5.2 State transitions

```
pending ──approve──→ open
                      │
                   start
                      │
                      ▼
                in-progress ──done──→ done
                      │
                      └──── (any state) ──drop──→ wont
```

Allowed transitions:
- `pending → open` (approve) | `pending → wont` (drop) | `pending → done` (rare; treat as approve+ship)
- `open → in-progress` (start) | `open → done` (skip the in-progress step) | `open → wont` (drop)
- `in-progress → done` | `in-progress → open` (paused) | `in-progress → wont`
- `done → open` (re-open if you find a regression)
- `wont → open` (resurrect if scope changes)

### 5.3 Deferral

`deferred: YYYY-MM-DD` on a `pending` or `open` entry hides it from the default `active` list until the date is reached. Used to push a low-priority item out of sight without dropping it.

---

## 6. Conversational Vocabulary (the agent contract)

A v3-conforming agent MUST recognize the following natural-language patterns and map them to the listed actions. These are not just suggestions — they're part of the spec, so any agent reading the snippet behaves the same way.

| User says | Agent does |
|---|---|
| *"add a todo to `<X>`: …"* / *"remind me to fix `<Y>` in `<Z>`"* / *"put `<W>` in the project todos"* | Append entry to `~/.todos/<slug>/TODOS.md` with `status: open`, `agent: <self>`, today's date, default `priority: P2`. |
| *"what's on the list"* / *"what are the todos"* / *"what's left in `<X>`"* | Show entries with `status: open` or `status: in-progress`. NOT pending. NOT wont. |
| *"what's outstanding across everything"* / *"what's left across everything"* | Cross-project rollup from `~/.todos/INDEX.md`: counts by priority, top P0/P1, stale items, done this week. |
| *"anything new"* / *"what did the agents propose"* / *"what's pending review"* | Show only `status: pending` entries. |
| *"what should I work on"* / *"what's next"* / *"what should I tackle in `<duration>`"* | Filter `status: open`, sort by priority then effort then freshness; recommend top N matching the time budget. |
| *"I'm doing `<X>`"* / *"start `<X>`"* | Flip target entry's status to `in-progress`. |
| *"I shipped `<X>`"* / *"`<X>` is done"* / *"mark `<X>` done"* | Flip to `done`, set `updated` to today. |
| *"drop `<X>`"* / *"we won't do `<X>`"* / *"out of scope"* | Flip to `wont`, capture reason in `wont_reason` field and commit message. |
| *"defer `<X>` to `<date>`"* | Add `deferred:` field. Hide from default `active` until date. |
| *"approve `<X>`"* / *"yes, add it"* (in response to a pending review) | Flip `pending → open`. |
| *"weekly review"* / *"what shipped this week"* | Diff vs last week's snapshot in `~/.todos/snapshots/`: shipped count, created count, net delta, stale spotlight. |

Agents MAY recognize additional phrases as aliases. Agents MUST NOT use these phrases for actions other than those listed.

---

## 7. Snapshots and Weekly Review

To support *"what shipped this week"* and *"net backlog delta"* queries, v3 implementations SHOULD write a weekly snapshot.

### 7.1 Format

```
~/.todos/snapshots/YYYY-Wxx.json
```

ISO week number. The current week's snapshot is overwritten on each `todos snapshot` call; prior weeks are frozen. Snapshot contents:

```json
{
  "schema": "todo-contract/v3",
  "snapshot_date": "2026-04-28",
  "iso_week": "2026-W18",
  "counts": { "total": N, "pending": N, "open": N, "in-progress": N, "done": N, "wont": N },
  "todos": [
    {
      "id": "<slug>/<todo-slug>",
      "project": "<slug>",
      "title": "...",
      "status": "...",
      "priority": "...",
      "effort": "...",
      "agent": "...",
      "created": "YYYY-MM-DD",
      "updated": "YYYY-MM-DD",
      "deferred": null,
      "tags": [...]
    }
  ]
}
```

### 7.2 Weekly review computation

Given snapshot `S0` (last week) and the current state `S1`:

- **Shipped this week:** entries with `status: done` in `S1` whose `updated` is between `S0.snapshot_date` and `S1.snapshot_date`.
- **Created this week:** entries in `S1` with `created` in that range.
- **Net delta:** `created - shipped`. Positive = backlog growing.
- **Stale:** entries with `status` in `{open, in-progress}` and `updated` (or `created` if no updated) older than 30 days.

---

## 8. Agent Contract

The `snippets/AGENTS_SNIPPET.md` distributed with this spec is the canonical agent-facing instruction. It MUST be included in each agent's global or repo-level instruction file (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, OpenClaw global rules, etc.).

Agents conforming to v3 MUST:

1. **Read** `~/.todos/<slug>/TODOS.md` before starting non-trivial work to know what's pending and avoid duplicates.
2. **Detect slug** by walking up from `cwd` and matching against `~/.todos/registry.yaml`. If no match, ask the user or use the slug `unsorted`.
3. **Respect the conversational vocabulary in §6.** When the user says one of the listed phrases, the agent maps it to the listed action.
4. **Default to `status: open` on user-explicit adds.** When the user says *"add this"*, write `status: open` (the user is the implicit approval).
5. **Use `status: pending` only when acting autonomously.** When no human is in the conversation and the agent decides to record a follow-up.
6. **Respect `wont` tombstones.** Before proposing a new entry, check `<slug>/TODOS.md` for matching `wont` entries; do not re-propose without the user's prompt.

---

## 9. Coexistence with v1 and v2

- **v1 (`todo-contract/v1`):** per-repo `TODOS.md`, voluntary, no approval gate. Still supported as-is at <https://github.com/zzbyy/todo-contract>. v3 ingestion can pull v1 in-repo files.
- **v2 (`todo-contract/v2`, never widely deployed):** four-file central architecture. Superseded by v3.
- **v3 → v1 reading:** v1 parsers can read v3 files because the per-todo block format is unchanged. Unknown statuses (`pending`, `wont`) and unknown fields (`agent`, `wont_reason`, `deferred`) are tolerated by v1's "unknown values" rule.

---

## 10. Non-Goals

- **Not a real-time sync system.** Git push/pull on `~/.todos/` is the multi-device strategy. No daemon, no socket protocol, no watchers.
- **Not a UI.** v3 specifies file formats, statuses, and conversational vocabulary. UIs (CLI, TUI, web, conversational) are implementation choices.
- **Not an agent runtime.** v3 does not specify how an agent decides what to propose — only how it writes the proposal.
- **Not project management.** No epics, sprints, milestones, dependencies, assignees, attachments. Use `tags` for groupings; for richer needs, use Linear / Things / Jira.

---

## 11. Versioning

- **Patch (v3.0.x):** clarifications, parser-behavior fixes.
- **Minor (v3.x):** additive fields, new conversational phrases, new statuses (rare). v3.0 parsers MUST tolerate unknown fields and statuses.
- **Major (v4):** breaking changes (e.g., new schema string `todo-contract/v4`).

---

## 12. Reference Implementation

The reference implementation lives in two places:

- The `todos` CLI in this repo at [`src/clawtodos/cli.py`](./src/clawtodos/cli.py) — single-module, Python 3.9+, stdlib only.
- The `clawtodos` skill in [`openclaw/clawtodos/`](./openclaw/clawtodos/) — implements the §6 conversational vocabulary and the §7 weekly review for OpenClaw.
