# Outreach — TODO 3 from the office-hours design

The assignment, verbatim from `~/.gstack/projects/zzbyy-clawtodos/zz-main-design-20260428-194413.md`:

> **Within the next 14 days: get a two-agent live coordination demo working — Claude Desktop and Codex CLI both connected to the local clawtodos MCP server, both attempting to claim a task, only one succeeding, the other picking a different task. Record a 60-second screen capture. Send it to three tool builders you respect and ask one question: "what would make you switch your kanban's storage to this?" Don't pitch. Just show and ask.**

The demo is the proof. The three responses are the data that decides whether v3.2 goes toward Approach B (board) or Approach C (kanban backend adapter).

---

## Pick 3 names

You'd know better than I would, but the audience profile is **tool builders shipping AI-agent infrastructure in 2026**. Concrete categories:

- **Multi-agent kanban authors:** the makers of Vibe Kanban (VirtusLab), Cline Kanban, Agent Kanban (saltbo), Routa (phodal), Agent Board. They're the most likely to convert this into a product decision.
- **MCP-server authors you respect:** anyone shipping non-trivial MCP servers with multiple tools.
- **Builders inside the agent runtimes:** people working on Claude Code, Cursor, Continue, Zed who care about cross-tool interop.
- **People in your existing network** who use 2+ AI coding tools daily. They feel the pain.

If you don't have an existing relationship, GitHub issues / Discord / X DMs all work. The asset is the same.

---

## The asset to attach

- **GitHub Release:** https://github.com/zzbyy/clawtodos/releases/tag/v3.1.0
- **Spec:** https://github.com/zzbyy/clawtodos/blob/v3.1.0/SPEC-v3.1.md
- **Self-contained demo (no install needed beyond the CLI):**
  ```bash
  pip install 'git+https://github.com/zzbyy/clawtodos.git@v3.1.0[mcp]'
  curl -O https://raw.githubusercontent.com/zzbyy/clawtodos/main/examples/demo/two_agent_race.sh
  bash two_agent_race.sh
  ```
  30 seconds, no GUI, prints colored output showing the claim race + handoff + audit log.

For a screen-capture you can also do `asciinema rec demo.cast && bash two_agent_race.sh && exit`, then upload the `.cast` to https://asciinema.org or convert with `agg`. Or screen-record live in two terminals: one running clawtodos-mcp + Claude Desktop, the other running Codex CLI, both calling tasks.claim on the same id.

---

## The message — three drafts

Pick the one closest to your voice. The forcing function is the question; everything else is set dressing.

### Draft A — minimal, builder-to-builder

> Hey [name] — I shipped [clawtodos v3.1](https://github.com/zzbyy/clawtodos/releases/tag/v3.1.0). It's a markdown-native task store with a `tasks.claim` MCP tool so agents on the same machine coordinate without colliding. Plain text on disk, git-as-audit, filelock for concurrency. 30-second demo: `bash <(curl -sSL https://raw.githubusercontent.com/zzbyy/clawtodos/main/examples/demo/two_agent_race.sh)` (creates a tmp dir, runs alice vs bob racing for one claim, shows the audit log).
>
> One question: **what would make you switch [your kanban / your tool] to use this as the backing store?**
>
> No pitch. Just want to know what's missing.

### Draft B — with context for someone who hasn't seen the kanban-for-agents space

> Hey [name] — wanted to share something I shipped today and ask one question.
>
> Multi-agent kanban tools have exploded this year (Vibe Kanban, Cline Kanban, Agent Kanban, Routa, etc.) but they all build their own state stores. clawtodos v3.1 ([release](https://github.com/zzbyy/clawtodos/releases/tag/v3.1.0)) is the opposite move: just markdown files in git, with claim/release/handoff primitives via filelock + an append-only event log. Single-machine, zero servers, MCP server for any agent that speaks it.
>
> 30-sec demo (no install if you have Python 3.10+):
> ```
> bash <(curl -sSL https://raw.githubusercontent.com/zzbyy/clawtodos/main/examples/demo/two_agent_race.sh)
> ```
>
> The question: **what would make you switch [your tool's] storage to this — or what's the deal-breaker?**
>
> Genuinely just trying to find out.

### Draft C — short DM / X / Discord

> built [clawtodos v3.1](https://github.com/zzbyy/clawtodos/releases/tag/v3.1.0) — markdown task store + MCP server with claim/handoff so agents coordinate without colliding. 30-sec demo: `bash <(curl -sSL https://raw.githubusercontent.com/zzbyy/clawtodos/main/examples/demo/two_agent_race.sh)`. one question: would you switch [your kanban]'s storage to this? what's missing?

---

## Where to capture answers

When responses come in, paste them verbatim (good and bad) into a new note in `~/.todos/clawtodos/` or somewhere durable. The exact phrasing is what matters — *what they said*, not your interpretation. Three answers is enough signal:

- 3/3 say "yes if it had X" → build X. v3.2 is clear.
- 2/3 say "I want a board too" → revisit Approach B (board UI on top).
- 2/3 say "make it the backend for [my tool]" → revisit Approach C (kanban adapter).
- 0/3 reply / 0/3 care → that's also data; reconsider whether the wedge has demand.

Mark TODO 3 done when you have 3 answers captured.
