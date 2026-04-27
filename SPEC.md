# clawtodos / todo-contract/v2 — Specification

**Status:** Stable (v2.0.0)
**Version:** 2.0.0
**Schema identifier:** `todo-contract/v2`

This document defines the format, parsing rules, and agent contract for `clawtodos`, the v2 of `todo-contract`. v2 keeps the v1 per-todo schema unchanged but moves the *location* of contract files from each repo to a single central directory and adds a human-approval staging layer.

If you only need per-repo todos with no approval gate, [todo-contract/v1](https://github.com/zzbyy/todo-contract) is still supported and recommended.

---

## 1. Goals

A portable persistent-todo format with these properties:

- **G1.** Any AI agent can propose todos to a central system without modifying the repos it works in.
- **G2.** Humans approve all proposals before they become canonical. Agents never write canonical state directly.
- **G3.** Code projects and personal-life programs share one schema and one home.
- **G4.** Plain Markdown — readable, diffable, editable in any tool.
- **G5.** Reuses the v1 per-todo block format unchanged. v1 parsers can read v2 files.

The motivating problem v2 solves: with multiple AI agents (Claude Code, Codex, Cursor, Antigravity, OpenClaw, etc.) writing todos into many places (repos, Obsidian, Apple Reminders, private skill dirs), state scatters and humans lose the thread. v2 says: one central home, agents propose, humans approve, repos stay clean.

---

## 2. Central Layout

A v2-conforming installation has a single root directory, by default `~/.todos/`. Set `$TODO_CONTRACT_ROOT` to override.

```
$TODO_CONTRACT_ROOT/
├── registry.yaml                 # registered projects (see §3)
├── INDEX.md                      # generated rollup across all projects
├── <project-slug>/
│   ├── INBOX.md                  # proposed todos (agents APPEND here)
│   ├── TODOS.md                  # approved canonical todos (humans promote here)
│   ├── DONE.md                   # archived completions (audit trail)
│   ├── REJECTED.md               # rejected proposals (audit trail)
│   └── ingested.md               # read-only mirror of source todos found in the repo (optional)
└── personal/
    └── <program-slug>/
        ├── INBOX.md
        ├── TODOS.md
        ├── DONE.md
        └── REJECTED.md
```

### 2.1 Repo isolation

A v2 system MUST NOT modify any registered project's working tree. The registered repo path is read-only from this contract's perspective. Any "ingestion" of existing in-repo todos produces a mirror at `<slug>/ingested.md` and never writes back.

### 2.2 Project slugs

Slugs are lowercase, hyphenated, and globally unique within `registry.yaml`. Personal/non-repo programs MAY use a `personal/<name>` form; the slash is permitted in slugs only for the `personal/` prefix.

### 2.3 Root as a git repo

`$TODO_CONTRACT_ROOT` SHOULD be a git repository. Approval and rejection actions SHOULD produce one commit each, providing a free audit log. Tools MUST function correctly when the root is not a git repo (commits become no-ops).

---

## 3. registry.yaml

The registry declares what projects are known to the system.

```yaml
schema: todo-contract/v2
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
    path: ~/notes/health           # optional: source folder for ingestion
    ingest: false
```

| Key | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | Unique project identifier. Becomes the directory name under root. |
| `type` | `code` \| `program` | yes | `code` = a git repo. `program` = a non-code domain (health, self-dev, errands). |
| `path` | string | no | Filesystem path to the source. Tilde-expansion required. Optional for `program` types. |
| `ingest` | bool | no, default `false` | If true, ingestion scans `path` for existing todos. |

Additional keys are RESERVED. v2 parsers MUST ignore unknown keys.

---

## 4. Per-Todo Block

The per-todo block format is **identical to v1 §4**, with one new field.

### 4.1 The `agent:` field (NEW in v2, REQUIRED in INBOX.md)

Every entry in `INBOX.md` MUST carry an `agent:` field naming the agent that proposed it. Recommended values: `claude-code`, `codex`, `cursor`, `antigravity`, `openclaw`, `human` (when a human writes a proposal directly), `ingest` (when populated by the ingestion scanner).

```markdown
### Fix auth token refresh on expiry
- **status:** open
- **priority:** P1
- **effort:** S
- **agent:** claude-code
- **created:** 2026-04-27

Token refresh fails when expiry is exactly at request time. Repro: ...

---
```

`agent:` is OPTIONAL in `TODOS.md`, `DONE.md`, and `REJECTED.md`, but parsers MUST preserve it on promotion (approve / done / reject).

### 4.2 The `deferred:` field (NEW in v2, OPTIONAL)

A proposal MAY carry `deferred: YYYY-MM-DD`. Reviewers SHOULD hide deferred entries until that date.

### 4.3 The `rejected_at:` and `rejected_reason:` fields (NEW in v2, OPTIONAL)

When a proposal is rejected, it moves to `REJECTED.md` with these fields appended:

```markdown
- **rejected_at:** 2026-04-27
- **rejected_reason:** Out of scope for current sprint
```

All other v1 fields (`status`, `priority`, `effort`, `created`, `updated`, `tags`) work identically.

---

## 5. The Three Flows

### 5.1 Register

```
todos add /path/to/your/repo        # auto-detects code repo, slug = dirname
todos add personal/health           # creates pseudo-project
```

`todos add` writes a new entry to `registry.yaml` and creates `<slug>/INBOX.md` and `<slug>/TODOS.md`. If `--ingest` is passed (or the project type is `code` and ingestion is the default), it scans `path` for existing todos and writes them to `<slug>/ingested.md`.

### 5.2 Propose (agent → INBOX)

An agent working in a registered project:

1. Detects its project slug by walking upward from `cwd` and matching against `registry.yaml`'s `path` entries. If no match, the agent SHOULD ask the human or write to a default `unsorted` slug.
2. Appends a todo block to `$TODO_CONTRACT_ROOT/<slug>/INBOX.md` with the v1 schema plus a required `agent:` field.
3. MUST NOT modify `<slug>/TODOS.md`, `<slug>/DONE.md`, or `<slug>/REJECTED.md`.
4. MUST NOT modify any in-repo `TODOS.md` in the source repo.

### 5.3 Approve (human, agent-mediated)

A reviewer (human, optionally driven by an agent like OpenClaw) walks pending entries one at a time and chooses:

- **Approve** — entry moves from `INBOX.md` to `TODOS.md`. Recommended commit: `approve: <slug>/<title>`.
- **Edit** — entry is opened in `$EDITOR`, then approved.
- **Defer** — entry stays in `INBOX.md` with a `deferred:` field. Hidden from review until that date.
- **Reject** — entry moves to `REJECTED.md` with `rejected_at:` and optional `rejected_reason:`. Agents reading `REJECTED.md` SHOULD avoid re-proposing the same title.

A v2 implementation MUST provide these four primitives. The UI may be conversational (an agent walks the human through), CLI (`todos move`), or any other surface.

### 5.4 Complete

When work on an approved todo finishes, change its `status:` to `done` and `updated:` to today's date. The entry MAY be moved from `TODOS.md` to `DONE.md`; both are valid. Implementations SHOULD prefer keeping recent `done` entries in `TODOS.md` for context and only archiving on a manual `todos archive` action.

---

## 6. Ingestion

If a registered project has `ingest: true`, an ingestion pass scans the source path and produces `<slug>/ingested.md`. Suggested sources:

- An in-repo `TODOS.md` (v1) at `<path>/TODOS.md`
- `.planning/todos/{pending,closed,done}/*.md`
- Source-code `TODO:`, `FIXME:`, `XXX:` comments
- README-level checklists

`ingested.md` is **read-only output**. It is not part of the approval flow directly. A v2 implementation SHOULD treat each ingested entry as a candidate proposal — i.e., the reviewer can promote ingested entries into `INBOX.md` (and from there approve into `TODOS.md`) but they do not auto-promote.

Ingestion MUST NOT modify the source path.

---

## 7. Agent Contract

The `AGENTS_SNIPPET-v2.md` distributed with this spec is the canonical agent-facing instruction. It MUST be included in each agent's global or repo-level instruction file (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`, OpenClaw global rules, etc.).

Agents conforming to v2 MUST:

1. **Read** `$TODO_CONTRACT_ROOT/<slug>/{INBOX.md, TODOS.md, REJECTED.md}` before starting non-trivial work, to know what's outstanding and avoid duplicate proposals.
2. **Append** new persistent todos to `$TODO_CONTRACT_ROOT/<slug>/INBOX.md`, NOT to any in-repo file.
3. **Include `agent:`** on every INBOX entry they write.
4. **Never modify** `TODOS.md`, `DONE.md`, or `REJECTED.md`. Promotion is a human action.
5. **Detect slug** by matching `cwd` against `registry.yaml` paths. If no match, ask the human or use `unsorted`.

Agents MAY drive the approval flow (acting on the human's behalf via the four verbs in §5.3) but MUST NOT auto-approve their own proposals.

---

## 8. Coexistence with v1

v2 is additive at the file-format level (per-todo blocks are unchanged) but architecturally different (location moves out of the repo).

- A repo MAY use v1 (in-repo `TODOS.md`) and v2 (registered in central system) simultaneously. Ingestion can read the v1 file as a one-way mirror.
- A v2-only repo SHOULD have no in-repo `TODOS.md`. The system SHOULD provide a `todos doctor` check that detects accidental in-repo writes by misbehaving agents.
- A v1-only repo is unaffected by v2 entirely. It works exactly as documented in [SPEC.md](./SPEC.md).

A reference parser SHOULD support both versions behind a single API: pass it either a repo root (v1 mode) or `$TODO_CONTRACT_ROOT` (v2 mode).

---

## 9. Non-Goals

Same as v1 §12, plus:

- **Not a real-time sync system.** Git push/pull on `$TODO_CONTRACT_ROOT` is the multi-device strategy. No daemon, no socket protocol, no watchers required.
- **Not a UI.** v2 specifies file formats and the four verbs. UIs (CLI, TUI, web, conversational) are implementation choices.
- **Not an agent runtime.** v2 does not specify how an agent decides what to propose — only how it writes the proposal.

---

## 10. Versioning

- **Patch (v2.0.x):** clarifications, parser-behavior fixes.
- **Minor (v2.x):** additive fields and verbs. v2.0 parsers MUST tolerate unknown fields.
- **Major (v3):** breaking changes (e.g., adding required external-capture bridges, new schema string `todo-contract/v3`).

---

## 11. Reference Implementation

The reference implementation lives in two places:

- The `todos` CLI in this repo at [`src/clawtodos/cli.py`](./src/clawtodos/cli.py) — single-module, stdlib-only, implements §2-§6.
- The `clawtodos-review` skill in OpenClaw — implements the conversational approval surface for §5.3.
