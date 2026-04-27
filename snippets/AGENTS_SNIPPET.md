<!--
This is the snippet to drop into each agent's global or repo-level
instruction file (CLAUDE.md, AGENTS.md, .cursorrules, OpenClaw global rules).

It tells any AI agent how to handle persistent todos under the central
clawtodos / todo-contract/v2 system: https://github.com/zzbyy/clawtodos

Copy everything between the BEGIN and END markers.
-->

<!-- BEGIN: clawtodos / todo-contract/v2 -->
## Persistent todos — clawtodos (todo-contract/v2)

This system uses a **central** todo store at `~/.todos/` (or `$TODO_CONTRACT_ROOT`). You propose; the user approves. You **never** write to canonical state, and **never** modify the repo you're working in for todo purposes.

### When you start non-trivial work

1. Detect the project slug: walk up from `cwd` and find the first directory whose path matches an entry in `~/.todos/registry.yaml`. The matching `slug:` is your project. If nothing matches, ask the user or use the slug `unsorted`.
2. Read these files for context (skip silently if missing):
   - `~/.todos/<slug>/INBOX.md` — proposals waiting for human review
   - `~/.todos/<slug>/TODOS.md` — approved canonical todos
   - `~/.todos/<slug>/REJECTED.md` — proposals already declined; do **not** re-propose

### When you want to leave a follow-up todo

APPEND a block to `~/.todos/<slug>/INBOX.md` in this format:

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

`<your-agent-name>` is one of: `claude-code`, `codex`, `cursor`, `antigravity`, `openclaw`, or another short slug naming you. The `agent:` field is **required** in INBOX.

Recognized fields: `status` (open|in-progress|done|wont), `priority` (P0|P1|P2|P3), `effort` (XS|S|M|L|XL), `agent`, `created`, `updated`, `tags` (comma-separated), `deferred` (YYYY-MM-DD).

### What you MUST NOT do

- **Do not modify `TODOS.md`, `DONE.md`, or `REJECTED.md`.** Those are canonical/audit state. Only the user (or a human-approved review tool) writes there.
- **Do not modify any in-repo `TODOS.md`.** Repos are read-only from this system. If you see an in-repo `TODOS.md` (legacy todo-contract/v1), leave it alone.
- **Do not auto-approve your own proposals.** Always write to INBOX, never to TODOS.

### CLI primitives

The `todos` CLI is on PATH after install (`pip install clawtodos` or run `python install.py`). Available verbs:

```
todos add <path-or-name>           # register a project
todos list [--state inbox|todos|done|rejected|all]
todos approve <slug> <id>          # promote INBOX -> TODOS  (human action)
todos reject  <slug> <id> [--reason]
todos defer   <slug> <id> --until YYYY-MM-DD
todos done    <slug> <id>          # TODOS -> DONE
todos ingest  <slug>               # one-shot scan of source repo for existing todos
todos index                        # regenerate INDEX.md
todos doctor
```

### When the user asks you to "review my inbox"

If your skill set includes the `clawtodos-review` flow (OpenClaw users — see <https://github.com/zzbyy/clawtodos/tree/main/openclaw/clawtodos-review>), walk pending INBOX entries one at a time and ask the user to approve / edit / defer / reject each one. Otherwise, run `todos list --state inbox` and walk the user through the entries manually.

Full spec: <https://github.com/zzbyy/clawtodos/blob/main/SPEC.md>.
<!-- END: clawtodos / todo-contract/v2 -->
