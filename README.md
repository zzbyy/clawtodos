# clawtodos

> **Agent-native task manager.** Multiple AI agents propose work. You approve. One central place to look across every project, code repo, and personal program. Repos stay clean. Nothing scattered.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Spec](https://img.shields.io/badge/spec-todo--contract%2Fv2-blue)](SPEC.md)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![Cross-platform](https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-supported-brightgreen)](install.py)

```
┌──────────────────────────────────────────────────────────────────┐
│   Claude Code   Codex CLI   Cursor   OpenClaw   ...any agent     │
│        │           │           │         │                       │
│        └───────────┴───────────┴─────────┘                       │
│                          │                                       │
│                          ▼  proposes                             │
│            ┌─────────────────────────────┐                       │
│            │   ~/.todos/<project>/       │                       │
│            │      INBOX.md  ←  agents    │                       │
│            └──────────────┬──────────────┘                       │
│                           │                                      │
│                  approve / edit / defer / reject  ← YOU          │
│                           │                                      │
│                           ▼                                      │
│            ┌─────────────────────────────┐                       │
│            │      TODOS.md               │   ← canonical work    │
│            │      DONE.md, REJECTED.md   │   ← audit trail       │
│            └─────────────────────────────┘                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## Why this exists

If you use multiple AI coding agents — Claude Code, Codex, Cursor, Antigravity, OpenClaw, anything else — you have probably noticed that **they all leave todos in different places.** A `TodoWrite` here, an Apple Reminder there, a checkbox in your Obsidian vault, a `.planning/todos/` folder in some repo, a few `TODO:` comments in source files. By the time you sit down for your morning review, you have no single place to look.

`clawtodos` fixes that with three simple rules:

1. **Agents propose. Humans approve.** Agents never write canonical state. They drop proposals into a per-project inbox; you decide what's real.
2. **Repos stay clean.** Nothing in this system writes to your code repos. Personal todo state never pollutes a shared codebase.
3. **One central home.** `~/.todos/` is the only place to look. Code projects, personal programs, side projects — all the same shape, all in one tree.

It's plain Markdown. Plain text. Git-versioned for free audit history. Zero daemons, zero servers, zero lock-in.

---

## How it works

Each registered project gets a small directory at `~/.todos/<slug>/` with four files:

| File          | Who writes  | What's in it                                |
|---------------|-------------|---------------------------------------------|
| `INBOX.md`    | AI agents   | Proposals waiting for your approval         |
| `TODOS.md`    | You         | Canonical, approved work to do              |
| `DONE.md`     | You         | Finished work (the audit trail)             |
| `REJECTED.md` | You         | Declined proposals (so agents don't re-ask) |

When an AI agent — Claude Code, Codex, Cursor, OpenClaw — finishes a session and wants to leave a follow-up, it appends a markdown block to that project's `INBOX.md` with an `agent:` field naming itself. Your repo is untouched.

When you're ready to review, you run `todos list --state inbox` (or, if you're an OpenClaw user, just say *"review my inbox"* and the conversational skill walks you through). Four verbs, nothing else: **approve**, **edit**, **defer**, **reject**. Each one produces a single git commit in `~/.todos/`. That's your audit log.

---

## Install

### Option 1 — pip (cross-platform, recommended)

```bash
pip install --user git+https://github.com/zzbyy/clawtodos.git
todos init
```

That's it. `todos` is now on your PATH; `~/.todos/` is bootstrapped and version-controlled.

### Option 2 — clone + installer (no pip needed)

```bash
git clone https://github.com/zzbyy/clawtodos.git
cd clawtodos
python3 install.py        # macOS / Linux
python  install.py        # Windows
```

The installer copies a small `todos` wrapper to `~/.local/bin/todos` (Unix) or `%LOCALAPPDATA%\clawtodos\bin\todos.cmd` (Windows), then runs `todos init`. If the bin dir isn't on your `PATH`, the installer tells you exactly what line to add.

### Option 3 — local dev install

```bash
git clone https://github.com/zzbyy/clawtodos.git
cd clawtodos
pip install --user -e .
```

Edits to `src/clawtodos/cli.py` are picked up immediately.

---

## Quick start

```bash
# 1. Bootstrap. Creates ~/.todos/, registers it as a git repo, writes registry.yaml.
todos init

# 2. Register a project. Auto-detects code repos vs personal programs.
todos add /path/to/your/repo
todos add personal/health           # pseudo-project for non-code domains

# 3. (One-time) Tell your AI agents about clawtodos. See "Wire up agents" below.

# 4. Use your AI normally. When it leaves a follow-up, it lands in INBOX.md.

# 5. Review the inbox once a day.
todos list --state inbox
todos approve my-app fix-auth-token-refresh-on-expiry
todos defer  my-app document-event-stream-api --until 2026-05-15
todos reject my-app rename-everything --reason "out of scope"
```

That's the loop.

---

## Wire up agents

Tell each AI agent about clawtodos by pasting [`snippets/AGENTS_SNIPPET.md`](snippets/AGENTS_SNIPPET.md) into its instruction file. Once. The snippet is short — 50 lines of "here's where to write proposals, here's what NOT to do."

| Agent                      | Where to paste the snippet                              |
|----------------------------|---------------------------------------------------------|
| Claude Code                | `~/.claude/CLAUDE.md` (global)                          |
| Codex CLI                  | `~/.codex/AGENTS.md` (global), or per-repo `AGENTS.md`  |
| Cursor                     | `<repo>/.cursorrules` (per-repo)                        |
| OpenClaw                   | `~/.openclaw/workspace/AGENTS.md`                       |
| Antigravity                | per-repo `AGENTS.md`                                    |
| Anything else with an instruction file | wherever it reads on startup            |

OpenClaw users — also install the dedicated review skill:

```bash
# macOS / Linux
cp -r openclaw/clawtodos-review ~/.openclaw/workspace/skills/

# Windows
xcopy /E /I "openclaw\clawtodos-review" "%USERPROFILE%\.openclaw\workspace\skills\clawtodos-review"
```

Then say *"review my inbox"* in any OpenClaw chat. The skill walks pending proposals one at a time and applies your verdict via the `todos` CLI. Every approve/reject/defer commits.

---

## How to use it

A real day looks like this.

### Morning — clear the inbox

You sit down with coffee. Your AI agents have been proposing work overnight (or while you were focused on something else).

```bash
$ todos list --state inbox

=== my-app / INBOX ===
  [fix-auth-token-refresh-on-expiry]   Fix auth token refresh on expiry      P1 S @claude-code
  [document-event-stream-api]          Document the new event-stream API     P3 S @codex
  [add-cli-subcommand-export-user-data] Add a CLI subcommand to export user data  P2 L @human

=== personal/health / INBOX ===
  [book-annual-physical]               Book annual physical                  P2 XS @openclaw
```

You walk them. (Or, in OpenClaw: *"review my inbox"* — same flow, conversational.)

```bash
$ todos approve my-app fix-auth-token-refresh-on-expiry
moved my-app/fix-auth-token-refresh-on-expiry: INBOX -> TODOS

$ todos defer my-app document-event-stream-api --until 2026-05-15
deferred: my-app/document-event-stream-api until 2026-05-15

$ todos approve my-app add-cli-subcommand-export-user-data
$ todos approve personal/health book-annual-physical
```

Inbox empty. Your `~/.todos/` git log now has four atomic commits — one per verdict — and `TODOS.md` in each project has the work that's actually queued.

### Mid-day — agent leaves a follow-up

You're pairing with Claude Code on `my-app`. You finish the auth fix. Claude Code recognizes there's a related concern (rate-limiting on the refresh endpoint) and instead of trying to do it now, it appends a proposal to `~/.todos/my-app/INBOX.md`:

```markdown
### Add rate-limiting to /auth/refresh
- **status:** open
- **priority:** P2
- **effort:** S
- **agent:** claude-code
- **created:** 2026-04-27

The fix to refreshIfExpired removes the bug, but the endpoint is still
unprotected. A botnet could DoS it cheaply. Suggest 5 req/min/IP.

---
```

Your repo's working tree is unchanged. The proposal will be there for you tomorrow morning.

### End of day — close out finished work

```bash
$ todos done my-app fix-auth-token-refresh-on-expiry
moved my-app/fix-auth-token-refresh-on-expiry: TODOS -> DONE
```

`DONE.md` accumulates your finished work. Combined with the git log, you have a perfect history of what got done and when.

### Migrating from todo-contract/v1

If you have repos already using v1 (in-repo `TODOS.md`):

```bash
todos add /path/to/v1-repo --ingest
```

The ingest scanner reads `TODOS.md`, `.planning/todos/`, and `TODO:` source comments. Findings land in `~/.todos/<slug>/ingested.md`. Promote whichever ones you still care about into the inbox, leave the rest as historical.

The in-repo `TODOS.md` is **never modified**. You can keep using v1 in that repo, or `git rm` the file once everything you care about is migrated. Your call.

---

## CLI reference

```
todos init                                       # bootstrap ~/.todos/

todos add <path-or-name> [--type code|program]   # register a project
                         [--ingest|--no-ingest]
                         [--slug <name>]

todos list [--slug <slug>]                        # list todos
           [--state inbox|todos|done|rejected|all]

todos approve <slug> <id>                         # INBOX -> TODOS
todos reject  <slug> <id> [--reason "<text>"]     # INBOX -> REJECTED
todos defer   <slug> <id> --until YYYY-MM-DD      # delay re-review
todos done    <slug> <id>                         # TODOS -> DONE
todos move    <slug> <id> --to <state>            # generic move

todos ingest  <slug>                              # one-shot scan of source repo
todos index                                       # regenerate INDEX.md
todos doctor                                      # sanity check

todos --root /custom/path <command>               # override $TODO_CONTRACT_ROOT
```

`<id>` is the slugified title (lowercased, non-alphanumeric → `-`). Run `todos list --slug <slug>` to see ids.

---

## File layout

After `todos init` and a couple of `todos add` calls:

```
~/.todos/
├── .git/                          ← git repo, 1 commit per verdict
├── README.md                      ← what this directory is
├── registry.yaml                  ← list of registered projects
├── INDEX.md                       ← cross-project rollup (run `todos index`)
├── my-app/
│   ├── INBOX.md                   ← agents append here
│   ├── TODOS.md                   ← humans approve into here
│   ├── DONE.md                    ← finished work
│   ├── REJECTED.md                ← declined proposals (audit trail)
│   └── ingested.md                ← read-only mirror of v1 todos (if any)
└── personal/
    └── health/
        ├── INBOX.md
        └── TODOS.md
```

---

## Compatibility

| Agent / Tool                  | Reads INBOX/TODOS | Writes proposals  | Notes                                              |
|-------------------------------|-------------------|-------------------|----------------------------------------------------|
| Claude Code                   | ✓                 | ✓                 | Add snippet to `~/.claude/CLAUDE.md`               |
| Codex CLI                     | ✓                 | ✓                 | Add snippet to `~/.codex/AGENTS.md` or per-repo    |
| Cursor                        | ✓                 | ✓                 | Add snippet to `<repo>/.cursorrules`               |
| OpenClaw                      | ✓                 | ✓                 | + dedicated `clawtodos-review` skill               |
| Antigravity                   | ✓                 | ✓                 | Per-repo `AGENTS.md`                               |
| Anything with an instruction file | ✓             | ✓                 | The contract is voluntary social — agents honor it because the snippet tells them to |

The contract is documented in [SPEC.md](SPEC.md) (`todo-contract/v2`). Any tool can read or write the format directly without going through the `todos` CLI.

---

## Spec

The wire format is documented in [SPEC.md](SPEC.md):

- File layout and lifecycle states
- Per-todo block syntax (frontmatter, fields, body, terminators)
- The four verbs (approve / edit / defer / reject)
- Agent contract
- Coexistence with todo-contract/v1
- Versioning policy

Reference implementation: [`src/clawtodos/cli.py`](src/clawtodos/cli.py). Single module, Python stdlib only.

---

## Project status

`v2.0.0` — first stable release. Schema is locked at `todo-contract/v2`. The CLI is intentionally minimal; new verbs require a matching spec change.

Roadmap (post-2.0, no commitments):

- **`todos archive`** — sweep old DONE entries into year-stamped files
- **External capture bridges** — Apple Reminders, Obsidian quick-add (writes into appropriate INBOX)
- **TUI dashboard** — keyboard-driven review for users who want a non-conversational UI
- **`todos doctor --fix`** — auto-correct common drift (in-repo TODOS.md created by misbehaving agents)

---

## Contributing

Issues and PRs welcome. The spec is intentionally small; if you want to add a field or verb, open an issue first to discuss whether it belongs in the spec, in the CLI, or as a separate tool.

Run the test loop locally:

```bash
git clone https://github.com/zzbyy/clawtodos.git
cd clawtodos
pip install -e .
todos --root /tmp/cltest init
todos --root /tmp/cltest add personal/test --type program
todos --root /tmp/cltest doctor
```

---

## Credits

`clawtodos` is the v2 of [`todo-contract`](https://github.com/zzbyy/todo-contract), which I shipped earlier. v1 is per-repo and voluntary; v2 is central and approval-gated. v1 is not deprecated — if your needs are met by per-repo todos, stay on v1.

The conversational `clawtodos-review` skill is named for [OpenClaw](https://openclaw.com), my personal-life AI assistant.

---

## License

[MIT](LICENSE)
