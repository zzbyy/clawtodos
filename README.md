# clawtodos

> **Agent-native task manager.** Multiple AI agents propose work. You approve. One central place to look across every project, code repo, and personal program. Repos stay clean. Nothing scattered.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Spec](https://img.shields.io/badge/spec-v3.1-blue)](SPEC-v3.1.md)
[![Python](https://img.shields.io/badge/python-3.9%2B%20(MCP%3A%203.10%2B)-blue)](pyproject.toml)
[![Cross-platform](https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-supported-brightgreen)](#install)

```
┌──────────────────────────────────────────────────────────────────┐
│  Claude Code · Codex CLI · Cursor · OpenClaw · any AI agent      │
│                              │                                   │
│              "add X"         │       "what's on the list?"       │
│              "I shipped X"   │       "what should I work on?"    │
│              "drop X"        │       "anything new?"             │
│                              ▼                                   │
│              ┌──────────────────────────────────┐                │
│              │   ~/.todos/<project>/TODOS.md    │                │
│              │   ONE FILE. Lifecycle in status: │                │
│              │   pending → open → in-progress   │                │
│              │            → done                │                │
│              │     side: → wont (tombstone)     │                │
│              └──────────────────────────────────┘                │
│                                                                  │
│  Repos: read-only sources.        Git: free audit log.           │
└──────────────────────────────────────────────────────────────────┘
```

---

## Why this exists

If you use multiple AI coding agents — Claude Code, Codex, Cursor, Antigravity, OpenClaw, anything else — you have probably noticed that **they all leave todos in different places.** A `TodoWrite` here, an Apple Reminder there, a checkbox in your Obsidian vault, a `.planning/todos/` folder in some repo, a few `TODO:` comments in source files. By the time you sit down for your morning review, you have no single place to look.

`clawtodos` fixes that with three simple rules:

1. **Agents propose. Humans approve.** Agents never write canonical state. They write to a per-project TODOS.md with a `status:` field. Default for explicit asks is `open` (already approved). Autonomous follow-ups go to `pending` for your review.
2. **Repos stay clean.** Nothing in this system writes to your code repos. Personal todo state never pollutes a shared codebase.
3. **One central home.** `~/.todos/` is the only place to look. Code projects, personal programs, side projects — all the same shape, all in one tree.

It's plain Markdown. Plain text. Git-versioned for free audit history. Zero daemons, zero servers, zero lock-in.

---

## How it works

Each registered project gets **one file** at `~/.todos/<slug>/TODOS.md`. Every entry has a `status:` field that encodes its lifecycle:

| `status:` | Meaning | Set by |
|---|---|---|
| `pending` | An agent proposed it autonomously; you haven't reviewed yet | Agent (rare path) |
| `open` | Confirmed work, on the list, not started | You — or an agent after you said yes in conversation |
| `in-progress` | Actively being worked | You / `todos start` |
| `done` | Shipped | You / `todos done` |
| `wont` | Decided not to do (kept as a tombstone so agents don't re-propose) | You / `todos drop` |

**Two ways todos get added:**

- **Interactive (the common case).** You're in conversation with an agent. You say *"add a todo: fix the auth bug"* — the agent appends an entry with `status: open`. You already approved by speaking.
- **Autonomous (the rare case).** Claude Code finishes a coding session and notices a related concern. No human is watching. It appends with `status: pending`. You see it next time you ask *"anything new?"*.

When you talk to your AI normally, it translates your sentences into the right status transitions. *"I shipped X"* → flips to done. *"drop Y, out of scope"* → flips to wont. *"defer Z to next Monday"* → adds `deferred:` field. Each transition produces one git commit in `~/.todos/`. That's your audit log.

---

## What's new in v3.1

> **Multi-agent coordination + MCP server.** Multiple AI agents on the same machine can now coordinate on the same task store without colliding. Plus a stdio MCP server so any MCP-aware agent (Claude Desktop, Cursor, Continue, Zed) speaks the protocol natively. See [SPEC-v3.1.md](SPEC-v3.1.md) for the full spec deltas.

### Try it in 30 seconds

```bash
pip install 'git+https://github.com/zzbyy/clawtodos.git@v3.1.0'
bash <(curl -sSL https://raw.githubusercontent.com/zzbyy/clawtodos/main/examples/demo/two_agent_race.sh)
```

That's a self-contained demo: spawns "alice" and "bob" racing for the same task, shows the collision error, the handoff, and the full audit log. Uses a tmp dir; never touches your real `~/.todos`.

### What you can now do

**As a human at a CLI** — three new verbs round out the v3.1 surface:

```bash
todos claim   <slug> <id> --actor <name> [--lease 3600]   # take a 1h lease (default)
todos release <slug> <id> --actor <name>                  # give it back
todos handoff <slug> <id> --actor <name> --to <Y> [--note ...]  # delegate / re-route
todos render  <slug>                                      # rebuild TODOS.md from EVENTS.ndjson
```

**As an AI agent in conversation** — the new conversational vocabulary (per [SPEC-v3.1.md §8](SPEC-v3.1.md)):

| You say | The agent runs |
|---|---|
| *"claim the auth refactor"* | `todos claim my-app fix-auth-refactor --actor <self>` |
| *"I'll take that"* | (same — agent uses its own slug as `--actor`) |
| *"hand off the migration to codex"* | `todos handoff my-app schema-migration --actor <self> --to codex` |
| *"let claude finish this"* | `todos handoff my-app some-id --actor <self> --to claude-code` |
| *"release my claim"* | `todos release my-app some-id --actor <self>` |
| *"what is codex working on?"* | `todos list --json` then read `claimed_by` fields |
| *"TODOS.md got hand-edited, fix it"* | `todos render my-app` |

### A short walkthrough — alice and bob coordinate on one task

```bash
# Setup (one task, fresh project)
$ todos new my-app "Implement claim semantics" --priority P1 --agent claude-code
added: my-app/implement-claim-semantics (status=open)

# Two terminals racing for the same claim:
# Terminal 1 (alice):
$ todos claim my-app implement-claim-semantics --actor alice
claimed: my-app/implement-claim-semantics by alice until 2026-04-28T16:24:18Z

# Terminal 2 (bob), simultaneously:
$ todos claim my-app implement-claim-semantics --actor bob
error: already_claimed by alice until 2026-04-28T16:24:18Z      # bob picks a different task

# Later, alice realizes bob is better suited:
$ todos handoff my-app implement-claim-semantics --actor alice --to bob --note "your area"
handoff: my-app/implement-claim-semantics -> bob (lease 2026-04-28T17:24:19Z)

# bob ships it:
$ todos done my-app implement-claim-semantics
my-app/implement-claim-semantics: open -> done
```

The full audit log lives at `~/.todos/my-app/EVENTS.ndjson`:

```jsonl
{"v":1,"ts":"...","actor":"claude-code","event":"create","id":"my-app/implement-claim-semantics","fields":{...}}
{"v":1,"ts":"...","actor":"alice","event":"claim","id":"my-app/implement-claim-semantics","lease_until":"..."}
{"v":1,"ts":"...","actor":"alice","event":"handoff","id":"my-app/implement-claim-semantics","to":"bob","lease_until":"..."}
{"v":1,"ts":"...","actor":"bob","event":"done","id":"my-app/implement-claim-semantics"}
```

`TODOS.md` is the human-readable render of the log; the log is the source of truth. Plain text, no DB, no daemon. Hand-editing `TODOS.md` while a mutation is happening is detected and blocked; `todos render` re-derives the file from the log.

### Wiring `clawtodos-mcp` into Claude Desktop

Tools become available in any MCP-aware client. For Claude Desktop, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "clawtodos": { "command": "clawtodos-mcp" }
  }
}
```

Restart Claude Desktop. In the next conversation, ask *"what's on the clawtodos list?"* — Claude calls `tasks.list` over MCP and shows the live state. Try the same against Codex CLI in another terminal — both agents now coordinate through the same `~/.todos/<slug>/` store.

Tools exposed: `projects.list`, `tasks.{list,create,claim,release,handoff,start,done,drop}`. Errors carry stable code strings (`unknown_id`, `already_claimed`, `task_held_by_other_actor`, `not_claimed_by_actor`, `bad_transition`, etc.) so agents can react programmatically rather than parsing prose.

### What v3.1 changes (vs v3.0, the brief version)

- **`pending` is now an optional soft-norm**, not a required gate. Agents may use it when uncertain or write directly to `open` when context is clear. Conversational vocabulary ("approve X") still works on `pending` entries. Behavioral change — see [SPEC-v3.1.md §5](SPEC-v3.1.md).
- **`EVENTS.ndjson` is the new source of truth.** `TODOS.md` becomes a deterministic render. Existing v3.0 stores auto-bootstrap on first v3.1 mutation (idempotent, never destructive, with duplicate-slug auto-disambiguation).
- **Claims are advisory hints**, not enforcement. `start` / `done` / `drop` do not check the claim. Well-behaved agents respect it; the system trusts cooperating agents on one user's machine. Multi-user / signed-actor scenarios are deferred to v4.

Full release notes: [CHANGELOG.md](CHANGELOG.md#310--2026-04-28-compliance-kit). Spec: [SPEC-v3.1.md](SPEC-v3.1.md).

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
5. Append the [agent snippet](snippets/AGENTS_SNIPPET.md) to each chosen instruction file (replacing any old v1 or v2 block automatically).
6. Install the [`clawtodos`](openclaw/clawtodos) skill if you have OpenClaw.
7. Ask which directories on your machine are active projects, register each with `todos add`.
8. Run `todos doctor` and offer to walk you through your first list.

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

After install you have **zero new commands to memorize.** Talk to your agent the way you already do. The agent translates your sentences into the right `todos` action via a fixed conversational vocabulary documented in [SPEC.md §6](SPEC.md). Any clawtodos-conformant agent recognizes these phrases:

| You say | Agent does |
|---|---|
| *"add a todo to `<X>`: …"* / *"remind me to fix `<Y>` in `<X>`"* / *"put `<W>` in the project todos"* | Append entry to that project's TODOS.md, `status: open`, today's date |
| *"what's on the list"* / *"what are the todos"* / *"what's left in `<X>`"* | Show entries with status `open` or `in-progress` |
| *"what's outstanding across everything"* | Cross-project rollup — counts by priority, top P0/P1, stale, done this week |
| *"anything new"* / *"what did the agents propose"* | Show only `status: pending` entries |
| *"what should I work on"* / *"what should I tackle in 2 hours"* | Filter `open`, sort by priority + effort + freshness, recommend top 3 matching the time budget |
| *"I'm doing `<X>`"* / *"start `<X>`"* | Flip target to `in-progress` |
| *"I shipped `<X>`"* / *"`<X>` is done"* | Flip to `done`, set `updated:` to today |
| *"drop `<X>`"* / *"we won't do `<X>`"* / *"out of scope"* | Flip to `wont`, capture reason in `wont_reason` field |
| *"defer `<X>` to `<date>`"* | Add `deferred:` field; hide from default list until date |
| *"approve `<X>`"* / *"yes, add it"* | Flip `pending → open` |
| *"weekly review"* / *"what shipped this week"* | Diff vs last week's snapshot — shipped, created, net delta, stale spotlight |

That's the whole vocabulary. Eleven phrase patterns, five statuses, one file per project. **You never type a `todos` command unless you want to.**

### Adding — what it actually looks like

> **You:** "add a todo to my-app: fix MW API rate-limit silent failure. P1, effort S."
>
> **Agent:** *Detects you're in `my-app`, appends an entry to `~/.todos/my-app/TODOS.md` with `status: open`, `agent: claude-code`, `priority: P1`, `effort: S`, today's date.*
>
> **Agent:** "Added to my-app TODOS as 'Fix MW API rate-limit silent failure' (P1, S). Your repo working tree is unchanged."

### The cross-project rollup — *"what's outstanding?"*

> **You:** "what's outstanding across everything?"
>
> **Agent:** *Runs `todos index` → reads `~/.todos/INDEX.md` → summarizes:*
>
> > 📋 38 active · 4 done this week · 3 pending review · 5 stale (>30d)
> >
> > 🔥 P0/P1 (3):
> > • my-app — Fix MW API rate-limit silent failure (P1, S)
> > • side-project — Magika auto-detect follow-up (P1, M)
> > • personal/health — Annual physical (P1, deadline May 14)
> >
> > Want me to drill into any project, or recommend what to tackle next?

### Smart prioritization — *"what should I tackle in 2 hours?"*

> **You:** "I have 2 hours before pickup. What should I tackle?"
>
> **Agent:** *Reads INDEX, scores by priority + effort + freshness:*
>
> > Based on priority, effort, and freshness:
> > - **my-app — MW API fix** — P1, S effort, ~1 hour. Fastest win.
> > - **side-project — Dead-link cleanup** — P2, XS effort, 10 min while you wait.
> > - skip personal/health — needs physical presence, not desk time.
> >
> > Want me to run `todos start my-app fix-mw-api-rate-limit-silent-failure` and pull up the body?

### Closing finished work

> **You:** "I shipped the MW API fix and the dead-link cleanup."
>
> **Agent:** *Runs `todos done` for both. Summary follows.*

### Weekly review — Sunday evening

> **You:** "weekly review"
>
> **Agent:** *Writes this week's snapshot, diffs vs last week:*
>
> > 📊 Weekly review — 2026-W18 (Apr 22–28)
> > Shipped: 4 · Created: 6 · Net: +2 backlog. Manageable.
> > Stale spotlight: "Cerebro provider integration" hasn't moved in 47 days. Schedule, demote, or drop?

---

## A day in the life

**8:30 AM — OpenClaw**

> **You:** "what's outstanding across everything?"
>
> OpenClaw runs `todos index`, summarizes: *38 active, 3 P1s, 4 done this week, 3 pending review.* You ask to drill into the pending. OpenClaw walks 3 proposals — you approve 2, drop 1 ("out of scope this quarter"). ~3 minutes.

**10:00 AM — Claude Code, working in `~/code/my-app`**

> **You:** "fix the MW API rate-limit issue"
>
> Claude Code reads `~/.todos/my-app/TODOS.md`, sees the approved task, fixes it. Wraps up:
>
> **Claude Code:** "Done. While I was in there I noticed `/auth/refresh` isn't rate-limited — separate concern. Want me to leave a follow-up?"
>
> **You:** "yeah, P2."
>
> Claude Code runs `todos new my-app "Add rate-limiting to /auth/refresh" --priority P2 --agent claude-code`. Your repo's working tree has only the rate-limit fix; no todo state leaked into the commit.

**3:00 PM — Codex on a different repo (`side-project`)**

> **You:** "what's left in side-project?"
>
> Codex runs `todos list --slug side-project` → shows the 5 active items.

**6:00 PM — OpenClaw**

> **You:** "I shipped the MW API fix and the rate-limiting."
>
> **OpenClaw:** *Runs `todos done` for both.* "Marked 2 done. Today: 3 approved, 2 shipped, 1 dropped. 1 new pending (claude-code's rate-limiting follow-up — already approved at 10:14). Solid day."

You wrote zero CLI commands. Three different agents collaborated on the same task tree without colliding. Your repos stayed clean.

---

## CLI escape hatch — when you want direct control

You never *have* to use the CLI. But it's there for scripting, automation, or when you want one fast action without a chat round-trip.

```bash
todos list                                            # active items (open + in-progress)
todos list --state pending                            # what agents proposed
todos approve my-app fix-auth-token-refresh-on-expiry # accept a proposal
todos defer  my-app docs-cleanup --until 2026-05-04   # delay re-review
todos reject my-app rename-everything --reason "..."  # decline
todos done   my-app fix-auth-token-refresh-on-expiry  # mark shipped

todos add /path/to/your/repo                          # register a new project
todos ingest my-app                                   # one-shot import of v1 todos
todos doctor                                          # sanity check
```

Common scripting use: a cron job that runs `todos list --state pending` once a morning and emails you if there are more than 10 unreviewed proposals.

---

## Migrating from todo-contract/v1

If you have repos already using v1 (in-repo `TODOS.md`):

> **You:** "register my-app and import its existing todos"
> **Agent:** *Runs `todos add /path/to/my-app --ingest`.*

The ingest scanner reads `TODOS.md` and `.planning/todos/` in your source repo. Findings land in `~/.todos/<slug>/TODOS.md` with `status: pending`. Tell your agent which ones to approve (`pending → open`) and which to drop (`pending → wont`).

The in-repo `TODOS.md` is **never modified.** You can keep using v1 in that repo, or `git rm` the file once everything you care about is migrated. Your call.

---

## CLI reference

```
todos init                                       # bootstrap ~/.todos/

todos add <path-or-name> [--type code|program]   # register a project
                         [--ingest|--no-ingest]
                         [--slug <name>]

todos list [--slug <slug>]                        # list todos
           [--state pending|open|in-progress|done|wont|active|all]

todos approve <slug> <id>                         # pending -> open
todos drop    <slug> <id> [--reason "<text>"]     # any -> wont (tombstone)
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
├── .git/                          ← git repo, 1 commit per status transition
├── README.md                      ← what this directory is
├── registry.yaml                  ← list of registered projects
├── INDEX.md                       ← cross-project rollup (run `todos index`)
├── snapshots/
│   └── 2026-W18.json              ← weekly snapshot for diff-based reviews
├── my-app/
│   └── TODOS.md                   ← ONE file. All entries, all statuses.
└── personal/
    └── health/
        └── TODOS.md
```

---

## Compatibility

| Agent / Tool                  | Reads TODOS.md    | Writes todos      | Notes                                              |
|-------------------------------|-------------------|-------------------|----------------------------------------------------|
| Claude Code                   | ✓                 | ✓                 | Add snippet to `~/.claude/CLAUDE.md`               |
| Codex CLI                     | ✓                 | ✓                 | Add snippet to `~/.codex/AGENTS.md` or per-repo    |
| Cursor                        | ✓                 | ✓                 | Add snippet to `<repo>/.cursorrules`               |
| OpenClaw                      | ✓                 | ✓                 | + dedicated `clawtodos` skill (handles full conversational vocab) |
| Antigravity                   | ✓                 | ✓                 | Per-repo `AGENTS.md`                               |
| Anything with an instruction file | ✓             | ✓                 | The contract is voluntary social — agents honor it because the snippet tells them to |

The contract is documented in [SPEC.md](SPEC.md) (`todo-contract/v3`). Any tool can read or write the format directly without going through the `todos` CLI.

---

## Spec

The wire format is documented in [SPEC.md](SPEC.md):

- File layout and lifecycle states
- Per-todo block syntax (frontmatter, fields, body, terminators)
- The five lifecycle states and transitions (approve / start / done / drop / defer)
- Agent contract
- Coexistence with todo-contract/v1 and v2
- Versioning policy

Reference implementation: [`src/clawtodos/cli.py`](src/clawtodos/cli.py). Single module, Python stdlib only.

---

## Project status

`v3.0.0` — single-file model. Schema locked at `todo-contract/v3`. Five statuses (`pending` / `open` / `in-progress` / `done` / `wont`) encode the lifecycle. CLI is intentionally minimal; new verbs require a matching spec change.

Roadmap (post-2.0, no commitments):

- **`todos archive`** — sweep old DONE entries into year-stamped files
- **`todos archive`** — sweep old `done` entries into year-stamped files when a project's TODOS.md grows large
- **External capture bridges** — Apple Reminders, Obsidian quick-add (writes `status: pending` entries)
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

`clawtodos` evolved from [`todo-contract/v1`](https://github.com/zzbyy/todo-contract). v1 is per-repo and voluntary; v3 (this repo) is central, single-file-per-project, with the full lifecycle in a `status:` field. v1 is not deprecated — if your needs are met by per-repo todos, stay on v1.

The `clawtodos` skill is named for [OpenClaw](https://openclaw.com), my personal-life AI assistant.

---

## License

[MIT](LICENSE)
