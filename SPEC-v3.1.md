# clawtodos / todo-contract/v3.1 — Specification

**Status:** Draft (additive over v3.0)
**Version:** 3.1.0
**Schema identifier:** `todo-contract/v3` (unchanged — v3.1 is a minor extension)
**Reference impl:** [`src/clawtodos/`](./src/clawtodos/) — same package, version 3.1.x

This document is **additive over [SPEC.md](./SPEC.md) (v3.0)**. Read v3.0 first; this file specifies only the deltas. Where a section here conflicts with v3.0, v3.1 wins.

> **What v3.1 adds:** an append-only event log alongside `TODOS.md`, concurrency-safe `claim` / `release` / `handoff` primitives so multiple AI agents on one machine can coordinate on the same task store without colliding, and a stdio MCP server so any MCP-aware agent (Claude Desktop, Cursor, Continue, Zed, …) can speak the protocol natively.
>
> **What v3.1 changes (not strictly additive):** the `pending` status is now an *optional soft-norm* rather than a required approval gate. See §5.

---

## 1. Goals (in addition to v3.0)

- **G6.** Multiple agents on the same machine SHOULD be able to coordinate on the same project's task store without race conditions, without an orchestrator, and without an external service.
- **G7.** Every mutation SHOULD be recorded as an event in an append-only log so the full history is recoverable, auditable, and replayable.
- **G8.** Existing v3.0 stores SHOULD migrate to v3.1 automatically on first mutation, with no data loss and no destructive transformation.

---

## 2. Filesystem additions

For each project at `<root>/<slug>/`:

```
TODOS.md       # human-readable; DERIVED from EVENTS.ndjson in v3.1
EVENTS.ndjson  # NEW in v3.1: append-only event log; the source of truth
.lock          # NEW in v3.1: filelock sidecar; should be in .gitignore
```

**Source-of-truth direction (the load-bearing decision):**

In v3.1, `EVENTS.ndjson` is the source of truth. `TODOS.md` is a deterministic render of the event log. Manual hand-edits to `TODOS.md` are **not** propagated back into the log automatically; they are detected and blocked. See §6.

---

## 3. New / extended fields on the per-todo block

All optional. v3.0 parsers tolerate them per §11 of v3.0.

| Field | Type | Notes |
|---|---|---|
| `claimed_by` | agent slug | The agent currently working on this task. |
| `lease_until` | ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) | When the claim expires. Other agents MAY claim after this time. |
| `handoff_to` | agent slug | Set by the `handoff` event. Records the recipient identity for audit; the recipient ALSO becomes `claimed_by` with a fresh lease. |

**Cut from v3.1, deferred to v3.2:** `depends_on`, `blocked_by`. The v3.1 wedge is collision-prevention; dependencies are a separate feature.

**Canonical field order for v3.1 emit (per `to_md()` in [`events.py`](./src/clawtodos/events.py)):**

```
status, priority, effort, agent,
claimed_by, lease_until, handoff_to,
created, updated, tags, deferred, wont_reason
```

Any unknown fields are emitted in dict-insertion order after the canonical ones.

---

## 4. EVENTS.ndjson format

Append-only. One JSON object per line. Encoded as UTF-8.

Required keys on every event:

| Key | Type | Notes |
|---|---|---|
| `v` | int | Schema version. v3.1 emits `1`. Readers MUST fail closed on unknown `v`. |
| `ts` | string | ISO 8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`). |
| `actor` | string | Agent identity (self-asserted; no auth in v3.1 — see §10). |
| `event` | string | One of the defined event types in §4.1. |
| `id` | string | Canonical `<slug>/<todo-slug>`. REQUIRED on every event type EXCEPT `render` (which is project-scoped, not todo-scoped). |

Event-type-specific keys are documented in §4.1.

### 4.1 Defined event types

| Event | Required extra keys | Effect on state |
|---|---|---|
| `create` | `fields` (dict; MUST contain `title`), optional `body` (string) | New todo with the given fields. `fields["title"]` becomes the title; remaining keys become the todo's fields. |
| `update` | `fields` (dict; values can be `null` to clear), optional `body` | Patch existing todo. `null` values clear that field. Body, if present, replaces. |
| `claim` | `lease_until` (ISO 8601 UTC) | Sets `claimed_by` (= the event's `actor`) and `lease_until`. |
| `release` | — | Clears `claimed_by` and `lease_until`. |
| `handoff` | `to` (agent slug), `lease_until` (ISO 8601 UTC), optional `note` (string) | Sets `handoff_to`, `claimed_by` (= `to`), `lease_until`. |
| `start` | — | `status → in-progress`, `updated = ts[:10]`, clears `deferred`. |
| `done` | — | `status → done`, `updated = ts[:10]`, clears `deferred`, `claimed_by`, `lease_until`. |
| `drop` | optional `reason` (string) | `status → wont`, `updated = ts[:10]`, clears `deferred`, sets `wont_reason` if `reason` provided. |
| `defer` | `until` (ISO 8601 date `YYYY-MM-DD`) | Sets `deferred = until`, `updated = ts[:10]`. |
| `render` | `hash` (hex SHA-256 of TODOS.md after this render) | NO state change. Records the rendered file's hash for hand-edit detection. The only event type with no `id`. |

### 4.2 Schema evolution rules

- **Unknown event types:** readers MUST treat as a no-op AND emit a parse warning to stderr. Do not crash. This lets v3.1 readers tolerate v3.2-and-later additions.
- **Unknown `v` values:** readers MUST fail closed. Refuse to render; require an upgraded reader.
- **Missing required keys:** readers MUST fail closed with a clear error pointing at the line number.

---

## 5. The `pending` status is now soft

| | v3.0 | v3.1 |
|---|---|---|
| `pending` semantics | Autonomous proposal awaiting human approval. **Required gate.** | Optional soft-norm. Agents MAY use it when uncertain about user intent; agents MAY skip it when context is clear. |
| `propose` CLI verb | Writes `pending`. Human MUST `approve` to start. | Writes `pending`. Conversational vocabulary ("approve X") still resolves to `pending → open`, but is no longer required. |
| Direct creation as `open` or `in-progress` | Allowed only when the user explicitly says so ("add this"). | Always allowed. |

**Mixed v3.0 / v3.1 agents:** the `pending` revision is a *behavioral* change, not just a surface change. Agent files (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`) loaded under v3.0 instructions will still treat `pending` as a hard gate; agents loaded under v3.1 will not. This is acceptable because the v3.1 agent contract is opt-in. Update the snippet to v3.1 language where you want the soft-norm behavior.

---

## 6. The mutation pipeline

Every mutating CLI verb and every mutating MCP tool call MUST follow this exact sequence:

```
acquire per-project lock
  ↓
read EVENTS.ndjson
  ↓
hand-edit detect-and-block:
  if last event is `render`:
    if hash(TODOS.md) ≠ render.hash → raise HandEditCollision
  else:
    # previous mutation was interrupted; auto-recover
    re-render TODOS.md from the log silently
  ↓
append the new event(s) to EVENTS.ndjson
  ↓
re-render TODOS.md from the full log
  ↓
append a `render` event with the SHA-256 of the new TODOS.md
  ↓
git commit (best-effort, with retry on .git/index.lock — see §6.2)
  ↓
release lock
```

### 6.1 Locking

Implementations MUST serialize concurrent mutations within a project. The reference implementation uses [`filelock`](https://py-filelock.readthedocs.io/) on a `.lock` sidecar file in the project directory. Other implementations MAY use any equivalent (POSIX `flock`, Windows `LockFileEx`, etc.) so long as exclusive serialization is preserved.

The lock MUST be held through the entire pipeline above, including the git commit. Releasing before the commit allows another writer to mutate, then the original writer's commit stages both mutations — violating the "one transition, one commit" property the audit log relies on.

### 6.2 Git commit retry

The reference implementation retries `git commit` up to 3 times with 100ms backoff specifically on `.git/index.lock: File exists` errors (which happen when the user's IDE or another git tool contends with our commit). Other errors are not retried. If all retries fail, a warning is printed to stderr and the mutation succeeds on disk; the audit log gap is acknowledged but does not block.

---

## 7. Bootstrap migration (v3.0 → v3.1)

The first time any v3.1 mutating operation touches a slug that has a `TODOS.md` but no `EVENTS.ndjson`:

1. Parse the existing `TODOS.md` with the v3.0 parser.
2. Synthesize one `create` event per todo with `actor: "ingest"`, `ts: <file mtime>` (UTC). The event's `fields` includes `"title"` (so the renderer can recover the title).
3. **Duplicate-slug auto-disambiguation:** if two todos have the same canonical slug, the second and onward are renamed to `<base>-2`, `<base>-3`, etc. The disambiguation is logged to stderr.
4. Append a `render` event with the SHA-256 of the (newly normalized) `TODOS.md`.
5. Commit: `chore: migrate <slug> to v3.1 event log (<N> todos)`.

Bootstrap is **one-shot** (only runs when `EVENTS.ndjson` doesn't exist) and **idempotent** (a second run is a no-op). Field order is normalized to v3.1 canonical on bootstrap. Whitespace within todo blocks is normalized by the parser/serializer; the rendered file may differ byte-for-byte from the original v3.0 file, but is structurally equivalent.

---

## 8. Coordination semantics: claim / release / handoff

### 8.1 Claim

`claim(id, actor, lease_seconds)` — claim a task with a time-bounded lease.

| Precondition | Outcome |
|---|---|
| Todo doesn't exist | Error: `unknown_id` |
| Unclaimed (no `claimed_by`, or `lease_until` ≤ now) | Success. Sets `claimed_by = actor`, `lease_until = now + lease_seconds`. |
| Currently held by `actor` (self) | Success — refresh. New `lease_until = now + lease_seconds`. |
| Currently held by another actor with valid lease | Error: `already_claimed`. Returns `claimed_by` and `lease_until` of the holder. |

`lease_seconds` is bounded `(0, MAX_LEASE_SECONDS]` (24h in the reference impl). Default is 1h.

### 8.2 Release

`release(id, actor)` — release a held claim.

| Precondition | Outcome |
|---|---|
| Todo doesn't exist | Error: `unknown_id` |
| `claimed_by ≠ actor` | Error: `not_claimed_by_actor` |
| `claimed_by == actor` | Success. Clears `claimed_by` and `lease_until`. |

### 8.3 Handoff

`handoff(id, actor, to, note?, lease_seconds?)` — re-route a task to another actor.

Per the v3.1 amendment (and the Codex review of plan-eng-review): handoff supports both **delegation** (actor doesn't currently hold) and **re-routing** (actor IS the holder).

| Precondition | Outcome |
|---|---|
| Todo doesn't exist | Error: `unknown_id` |
| Unclaimed | Success — delegation. Sets `handoff_to = to`, `claimed_by = to`, `lease_until = now + lease_seconds`. |
| `claimed_by == actor` | Success — re-route. Same effect as delegation; recipient gets the implicit claim. |
| `claimed_by ≠ actor` AND lease still valid | Error: `task_held_by_other_actor`. Returns the current `claimed_by` and `lease_until`. |

### 8.4 Claims are advisory hints

`tasks.start`, `tasks.done`, `tasks.drop`, and `tasks.defer` do NOT require holding the claim. The claim system is an **advisory hint** for cooperating agents to avoid collisions; it is not enforcement against adversarial agents.

Well-behaved agents SHOULD check `claimed_by` before starting work on a task. The v3.1 reference snippet documents heartbeat re-claim every 5 minutes for long-running work, but enforcement is not specified.

This is consistent with the §10 non-goal: actor identity is self-asserted.

---

## 9. MCP server (stdio)

A reference MCP server is shipped as `clawtodos-mcp` (installed via `pip install clawtodos[mcp]`). It exposes the v3.1 wedge tools over stdio.

| Tool | Purpose |
|---|---|
| `projects.list` | List registered project slugs |
| `tasks.list` | List todos for a project, filterable by state |
| `tasks.create` | Create a new todo |
| `tasks.claim` | Claim a task with a lease |
| `tasks.release` | Release a held claim |
| `tasks.handoff` | Hand off a task (delegation or re-route) |
| `tasks.start` | `→ in-progress` |
| `tasks.done` | `→ done` |
| `tasks.drop` | `→ wont` (with optional reason) |

**Cut for v3.1, deferred to v3.2:** `tasks.defer`, `tasks.watch`, `weekly_review`, `projects.add` (registry mutation is intentionally CLI-only — agents should not be able to register or unregister projects).

### 9.1 Error model

```json
{ "error": { "code": "<snake_case>", "message": "<human readable>", "details": { ... } } }
```

Stable codes used in v3.1: `unknown_slug`, `unknown_id`, `duplicate_id`, `already_claimed`, `not_claimed_by_actor`, `task_held_by_other_actor`, `bad_transition`, `hand_edit_collision`, `schema_version_unsupported`, `corrupt_event_log`. Future v3.x versions MAY add codes; readers SHOULD tolerate unknown codes.

### 9.2 Stdio safety

STDIO transport reserves stdout for the JSON-RPC protocol stream. Server implementations MUST redirect non-protocol output (logs, warnings, accidental prints) to stderr. The reference impl includes a `sys.stdout = sys.stderr` redirect at server startup as a guardrail.

---

## 10. Non-goals (v3.1)

- **Multi-user / multi-tenant.** v3.1 is single-user, single-machine. Multi-device is git push/pull (today's story).
- **Actor authentication.** The `actor` field on every event is self-asserted. Agents can lie. Acceptable for v3.1's "cooperating agents on one user's machine" scope. Multi-user / untrusted-agent scenarios would need v4 with signed events.
- **Encryption at rest.** Plain text on the user's filesystem.
- **Real-time push / streaming.** `tasks.watch` is deferred to v3.2.
- **Dependencies / blocked_by.** Deferred to v3.2.
- **Web UI / kanban board.** Out of scope; that's a downstream consumer of the substrate. See [Approach B / Approach C in the design doc](./README.md).
- **Lease enforcement on `start`/`done`/`drop`.** Claims are advisory hints (see §8.4).

---

## 11. Conformance

The reference implementation ships a pytest conformance suite at `test/python/test_cli_v31.py` and `test/python/test_events.py`. Implementations claiming v3.1 compliance SHOULD pass at least 20 of the 22 conformance scenarios documented in the [test plan](./README.md#conformance).

Run against the reference: `pytest test/python/`.

---

## 12. Versioning

- **v3.1.x patch:** clarifications, parser-behavior fixes, additive event-handler tolerance.
- **v3.2:** additive — `tasks.watch`, `tasks.defer`, `weekly_review` MCP tools, `depends_on` field, log compaction.
- **v4:** breaking — new schema string `todo-contract/v4`. Likely candidates: signed events, agent capability manifests, multi-user.
