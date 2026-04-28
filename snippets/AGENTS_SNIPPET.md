<!--
This is the snippet to drop into each agent's global or repo-level
instruction file (CLAUDE.md, AGENTS.md, .cursorrules, OpenClaw global rules).

It tells any AI agent how to handle persistent todos under clawtodos /
todo-contract/v3: https://github.com/zzbyy/clawtodos

Copy everything between the BEGIN and END markers.
-->

<!-- BEGIN: clawtodos / todo-contract/v3 -->
## Persistent todos — clawtodos (todo-contract/v3)

This system uses a **central** todo store at `~/.todos/` (or `$TODO_CONTRACT_ROOT`). One file per project: `~/.todos/<slug>/TODOS.md`. The lifecycle of every entry is encoded in a `status:` field — there are no separate INBOX / DONE / REJECTED files.

### When you start non-trivial work

1. Detect the project slug: walk up from `cwd` and find the first directory whose path matches an entry in `~/.todos/registry.yaml`. The matching `slug:` is your project. If nothing matches, ask the user or use the slug `unsorted`.
2. Read `~/.todos/<slug>/TODOS.md` to know what's pending and what's already been declined (so you don't re-propose a `wont` entry).

### The five statuses

| Status | Meaning |
|---|---|
| `pending` | An agent proposed this autonomously; awaits user confirmation. |
| `open` | Confirmed by the user, on the list, not started. |
| `in-progress` | Actively being worked. |
| `done` | Shipped. |
| `wont` | Decided not to do (kept as tombstone — agents see it and don't re-propose). |

### When you want to add a todo — two paths

**Interactive path (the common case).** The user explicitly told you to add it ("add a todo: ..." / "remind me to ..."). The user already approved by speaking. Append the entry with `status: open`.

**Autonomous path (the rare case).** You're finishing work and want to record a follow-up; the user isn't in the conversation. Append with `status: pending`. The user reviews next time they ask "anything new?".

Either way, append a block to `~/.todos/<slug>/TODOS.md` in this format:

```markdown
### <Short, action-oriented title>
- **status:** open
- **priority:** P2
- **effort:** M
- **agent:** <your-agent-name>
- **created:** YYYY-MM-DD

Body — what / why / context, free-form markdown.

---
```

`<your-agent-name>` is one of: `claude-code`, `codex`, `cursor`, `antigravity`, `openclaw`, or another short slug naming you. The `agent:` field is **required** on `status: pending` entries; recommended otherwise.

### Conversational vocabulary (recognize these phrases — they're spec)

| User says | You do |
|---|---|
| "add a todo to X: ..." / "remind me to fix Y in X" | Append with `status: open`, `agent: <self>` |
| "what's on the list" / "what are the todos" / "what's left in X" | Show entries with `status: open` or `in-progress` (NOT pending, NOT wont). **If the active list is empty AND `pending` is non-empty, also surface the pending count in the same reply** (e.g. *"Active list is empty. You have 12 pending review — say 'anything new?' to see them."*). The CLI's `todos list` prints a `note:` line for this case; honor it when relaying to the user. |
| "what's outstanding across everything" | Cross-project rollup from `~/.todos/INDEX.md` |
| "anything new" / "what did the agents propose" | Show only `status: pending` |
| "what should I work on" / "what should I tackle in N hours" | Filter `open`, sort by priority + effort + freshness; recommend top N |
| "I'm doing X" / "start X" | Flip target to `in-progress` |
| "I shipped X" / "X is done" | Flip to `done`, set `updated` to today |
| "drop X" / "we won't do X" | Flip to `wont`, capture reason in `wont_reason` field and commit |
| "defer X to `<date>`" | Add `deferred:` field; hide from default list until date |
| "approve X" / "yes, add it" | Flip `pending → open` |
| "weekly review" / "what shipped this week" | Diff vs last week's snapshot in `~/.todos/snapshots/` |

### What you MUST NOT do

- **Do not modify any in-repo `TODOS.md`** in the source repo. Repos are read-only from this system. Leave any in-repo legacy file alone.
- **Do not auto-approve your own proposals** — `propose` writes `pending`; only the user (or an explicit user instruction) flips to `open`.
- **Do not re-propose `wont` entries.** If a matching title appears with `status: wont`, the user already declined it. Don't bring it up again unless the user prompts.

### CLI primitives

The `todos` CLI is on PATH after install (`pip install --user git+https://github.com/zzbyy/clawtodos.git`). Available verbs:

```
todos add <path-or-name>            # register a project
todos new <slug> "<title>"           # add an open todo (interactive path)
todos propose <slug> "<title>"       # add a pending todo (autonomous path)
todos list [--state ...] [--json]    # default: active (open + in-progress)
todos approve <slug> <id>            # pending -> open
todos start   <slug> <id>            # open    -> in-progress
todos done    <slug> <id>            # any     -> done
todos drop    <slug> <id> [--reason] # any     -> wont
todos defer   <slug> <id> --until YYYY-MM-DD
todos ingest  <slug>                 # scan source repo for existing todos
todos index                          # regenerate ~/.todos/INDEX.md
todos snapshot                       # write weekly snapshot
todos doctor
```

### Multi-agent coordination (v3.1+)

When multiple AI agents work on the same task store on the same machine, they coordinate via lease-based claims. Conversational vocabulary:

| User says | You do |
|---|---|
| *"claim X"* / *"I'll take X"* | `todos claim <slug> <id> --actor <self>` (default 1h lease, max 24h) |
| *"release X"* / *"give it back"* | `todos release <slug> <id> --actor <self>` |
| *"hand off X to <Y>"* / *"let <Y> finish this"* | `todos handoff <slug> <id> --actor <self> --to <Y>` |
| *"what is <Y> working on"* | `todos list --json` then read `claimed_by` fields |

Behavior contract:
- Before starting non-trivial work on a task, **check `claimed_by`**. If another agent holds the claim and the lease hasn't expired, pick a different task.
- For long-running work (>5 minutes), **re-claim periodically** to refresh the lease. Otherwise another agent may steal the task assuming you crashed.
- `claim` succeeds when (a) nobody holds the task, (b) the lease has expired, or (c) you ARE the current holder (self-refresh).
- `handoff` succeeds when (a) nobody holds the task (delegation: you're routing it to <Y> on the user's behalf), or (b) you ARE the current holder. Otherwise fails with `task_held_by_other_actor`.
- Claims are **advisory hints**, not enforcement. `start`/`done`/`drop` do not check the claim. Other well-behaved agents respect it; misbehaving agents can ignore it. This is acceptable for v3.1's "cooperating agents on one user's machine" scope.

### MCP server

`pip install clawtodos[mcp]` installs `clawtodos-mcp`, an MCP stdio server. Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (or any other MCP client config):

```json
{
  "mcpServers": {
    "clawtodos": { "command": "clawtodos-mcp" }
  }
}
```

Tools exposed: `projects.list`, `tasks.{list,create,claim,release,handoff,start,done,drop}`. Errors carry stable `code` strings (`unknown_id`, `already_claimed`, `task_held_by_other_actor`, etc.) so agents can react programmatically rather than parsing prose.

Full spec: <https://github.com/zzbyy/clawtodos/blob/main/SPEC.md> (v3.0) and <https://github.com/zzbyy/clawtodos/blob/main/SPEC-v3.1.md> (v3.1 deltas).
<!-- END: clawtodos / todo-contract/v3 -->
