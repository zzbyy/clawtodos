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

clawtodos is **agent-native** — the whole product is "your AI does work for you." Installation works the same way. Paste one line into any AI agent you already use and it walks you through everything: install the CLI, bootstrap the central system, wire up your other agents, register your projects, queue your first review.

### One-liner — paste this into any AI agent

```text
Install clawtodos for me. Follow the bootstrap procedure at:
https://raw.githubusercontent.com/zzbyy/clawtodos/main/BOOTSTRAP.md
```

Works in **OpenClaw**, **Claude Code**, **Codex CLI**, **Cursor**, or any agent that can fetch URLs and run shell commands. The agent will:

1. Detect your Python / pip / git environment.
2. Run `pip install --user git+https://github.com/zzbyy/clawtodos.git`.
3. Run `todos init` — creates `~/.todos/`, makes it a git repo.
4. Discover which other AI agents you have (Claude Code, Codex, Cursor, OpenClaw) and ask which to wire up.
5. Append the [agent snippet](snippets/AGENTS_SNIPPET.md) to each chosen instruction file (replacing any old v1 block automatically).
6. Install the [`clawtodos-review`](openclaw/clawtodos-review) skill if you have OpenClaw.
7. Ask which directories on your machine are active projects, register each with `todos add`.
8. Run `todos doctor` and offer to walk you through your first inbox.

About 2 minutes start to finish. Each step asks before doing anything that writes outside `~/.todos/`.

If you don't yet have an AI agent set up, or you prefer scripts, see [Manual install](#manual-install) below.

### Manual install

<details>
<summary><b>pip</b> — cross-platform, no agent needed</summary>

```bash
pip install --user git+https://github.com/zzbyy/clawtodos.git
todos init
```

Then paste [`snippets/AGENTS_SNIPPET.md`](snippets/AGENTS_SNIPPET.md) into your agent instruction files yourself. See the table in [Wire up agents](#wire-up-agents) for which file goes where.
</details>

<details>
<summary><b>clone + python install.py</b> — Python only, no pip</summary>

```bash
git clone https://github.com/zzbyy/clawtodos.git
cd clawtodos
python3 install.py        # macOS / Linux
python  install.py        # Windows
```

Drops a `todos` wrapper into `~/.local/bin/` (Unix) or `%LOCALAPPDATA%\clawtodos\bin\` (Windows) and runs `todos init`. You still need to copy the snippet into your agent files yourself.
</details>

<details>
<summary><b>local dev install</b> — for hacking on clawtodos itself</summary>

```bash
git clone https://github.com/zzbyy/clawtodos.git
cd clawtodos
pip install --user -e .
```

Edits to `src/clawtodos/cli.py` are picked up immediately.
</details>

---

## First conversation — per agent

You only do this once per machine. Open the agent you already use. Paste the install line. Answer 5 questions. You're done.

| Agent | How you open it | What you paste / say |
|---|---|---|
| **OpenClaw** | Open the OpenClaw chat (web or app) | `Install clawtodos. Follow https://raw.githubusercontent.com/zzbyy/clawtodos/main/BOOTSTRAP.md` |
| **Claude Code** | `claude` in any terminal | Same line as above |
| **Codex CLI** | `codex` in any terminal | Same line as above (Codex will request file-write permission once) |
| **Cursor** | Cmd-L (or Ctrl-L) opens the chat panel inside your repo | Same line as above (Cursor wires the snippet into per-repo `.cursorrules` rather than a global file) |
| **Antigravity / other** | However you normally chat with it | Same line — any agent with shell + URL access can run the bootstrap |

The agent reads `BOOTSTRAP.md`, runs the 8 phases, and asks you maybe 5 questions along the way (which other agents to wire, which directories are your active projects). End state: `todos` is on PATH, `~/.todos/` exists, every agent you chose to wire knows about clawtodos, and your projects are registered. Total time: ~2 minutes.

> **Tip — if you only have one agent on this machine.** That's fine. Run the bootstrap there. When you install another agent later, run the bootstrap again from inside *that* one — it's idempotent and will just wire the new agent and skip everything already done.

---

## Daily use — just talk to your agent

After install you have **zero new commands to memorize.** Talk to your agent the way you already do. The agent translates your sentences into the right `todos` action.

### Adding a follow-up — *describe the work, don't write commands*

> **You:** "leave a follow-up about the rate-limiting concern. P2."
>
> **Agent:** *Detects you're in `my-app`, appends a properly-formatted entry to `~/.todos/my-app/INBOX.md` with `agent: claude-code` and today's date.*
>
> **Agent:** "Added to my-app inbox as 'Add rate-limiting to /auth/refresh' (P2). Your repo working tree is unchanged."

### Reviewing the inbox — *the daily ritual*

In **OpenClaw** (using the dedicated `clawtodos-review` skill the bootstrap installed):

> **You:** "review my inbox"
>
> **OpenClaw:** "You have 4 proposals across 3 projects. Walking now.
>
> **(1/4) my-app** — proposed by claude-code _(2026-04-27)_
> ### Fix auth token refresh on expiry
> Priority: **P1** · Effort: **S**
> Token refresh fails when expiry is exactly at request time. Repro…
>
> **Approve / Edit / Defer / Reject?**"
>
> **You:** "approve"
>
> **OpenClaw:** "✅ Moved to TODOS. Commit `3406585`. (2/4) …"

In **Claude Code / Codex / Cursor** (no dedicated skill — same flow, slightly less polished):

> **You:** "review my inbox"
>
> **Agent:** *Runs `todos list --state inbox`, presents each entry, asks for your verdict, calls the right CLI verb. Identical end result.*

### One-shot verbs — *when you already know what you want*

> **You:** "approve the auth fix in my-app"
> **Agent:** *Runs `todos approve my-app fix-auth-token-refresh-on-expiry`.*

> **You:** "defer the docs cleanup until next Monday"
> **Agent:** *Computes date → runs `todos defer my-app document-event-stream-api --until 2026-05-04`.*

> **You:** "reject the rename proposal — it's out of scope"
> **Agent:** *Runs `todos reject my-app rename-everything --reason "out of scope"`.*

### Closing finished work

> **You:** "I shipped the auth fix and the rate-limiting"
> **Agent:** *Runs `todos done` for both, summarizes.*

That's the entire daily UX. **You never type a `todos` command unless you want to.**

---

## A day in the life

**8:30 AM — OpenClaw on your phone or laptop**

> **You:** "review my inbox"
>
> OpenClaw walks 4 proposals from yesterday. You approve 2, defer 1 to next week, reject 1 ("out of scope, won't ship this quarter"). Inbox empty. ~3 minutes.

**10:00 AM — Claude Code, working in `~/code/my-app`**

> **You:** "fix the auth refresh bug"
>
> Claude Code reads `~/.todos/my-app/TODOS.md`, sees the approved task, fixes it. As it wraps up:
>
> **Claude Code:** "Done. While I was in there I noticed `/auth/refresh` isn't rate-limited — that's a separate concern. Want me to leave a follow-up?"
>
> **You:** "yeah, P2."
>
> Claude Code appends a proposal to `~/.todos/my-app/INBOX.md`. The auth fix is committed to your repo cleanly; no todo state leaked into the diff.

**3:00 PM — Codex on a different repo (`side-project`)**

> **You:** "what's left to do here?"
>
> Codex runs `todos list --slug side-project --state todos` → shows the 3 queued items for that project only.

**6:00 PM — OpenClaw again**

> **You:** "I shipped the auth fix and the rate-limiting"
>
> **OpenClaw:** "Marked 2 done. Today: 3 approved, 2 shipped, 1 deferred, 1 rejected. Inbox: 1 new (claude-code added the rate-limiting follow-up at 10:14 — already approved by you at 10:15). Solid day."

You wrote zero CLI commands. Three different agents collaborated on the same task tree without colliding. Your repos stayed clean.

---

## CLI escape hatch — when you want direct control

You never *have* to use the CLI. But it's there for scripting, automation, or when you want one fast action without a chat round-trip.

```bash
todos list --state inbox                              # see what's pending
todos approve my-app fix-auth-token-refresh-on-expiry # accept a proposal
todos defer  my-app docs-cleanup --until 2026-05-04   # delay re-review
todos reject my-app rename-everything --reason "..."  # decline
todos done   my-app fix-auth-token-refresh-on-expiry  # mark shipped

todos add /path/to/your/repo                          # register a new project
todos ingest my-app                                   # one-shot import of v1 todos
todos doctor                                          # sanity check
```

Common scripting use: a cron job that runs `todos list --state inbox` once a morning and emails you if the inbox has more than 10 entries.

---

## Migrating from todo-contract/v1

If you have repos already using v1 (in-repo `TODOS.md`):

> **You:** "register my-app and import its existing todos"
> **Agent:** *Runs `todos add /path/to/my-app --ingest`.*

The ingest scanner reads `TODOS.md`, `.planning/todos/`, and `TODO:` source comments. Findings land in `~/.todos/<slug>/ingested.md` as candidates. Tell your agent which ones to promote into the inbox and which to drop.

The in-repo `TODOS.md` is **never modified.** You can keep using v1 in that repo, or `git rm` the file once everything you care about is migrated. Your call.

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
