---
name: clawtodos
description: zZ's central task system across every project (code repos and personal programs). One file per project at ~/.todos/<slug>/TODOS.md, lifecycle in a status field, append-only EVENTS.ndjson event log under it (v3.1+). Use this skill whenever zZ asks about todos, what's left, what to work on, what's pending, what shipped, what's outstanding across everything, or wants to add/start/finish/drop/defer/claim/release/handoff a todo. Also handles the weekly review, multi-agent coordination via leases (v3.1+), and proactive heartbeat alerts for new P0/P1 / stale items / pending proposals.
---

# clawtodos — central task system for zZ

zZ's todos for **every project, code repo, and personal program** live at `~/.todos/<slug>/TODOS.md`. One file per project. Lifecycle in a `status:` field. The full spec is at <https://github.com/zzbyy/clawtodos/blob/main/SPEC.md>.

This skill is the day-to-day surface — you (the agent) translate zZ's natural-language asks into deterministic `todos` CLI calls. The CLI is dumb; this skill is smart.

## What you own

| Surface | What you do |
|---|---|
| Adding todos via conversation | Map zZ's sentence to `todos new` / `todos propose` |
| Reviewing the list | Map "what's on the list" / "what's outstanding" to filtered `todos list` + a friendly summary |
| Status transitions | `todos start` / `todos done` / `todos drop` / `todos defer` |
| Approving pending proposals from other agents | `todos approve` |
| Cross-project view | Refresh `INDEX.md`, summarize for zZ |
| Smart prioritization | "What should I tackle in 2 hours" — read INDEX, sort, recommend |
| Heartbeat alerts | Surface new P0/P1, stale items, pending review proposals |
| Weekly review | Diff vs last week's snapshot |

## The conversational patterns (the contract)

These are spec-level (see SPEC.md §6 + SPEC-v3.1.md §8). Recognize variants of these phrases and map them to the listed CLI calls. Don't paraphrase the actions — use exactly the right verb.

| zZ says (or close paraphrase) | You run |
|---|---|
| "add a todo to `<slug>`: `<title>`" / "remind me to fix `<X>` in `<slug>`" / "put `<X>` in the project todos" | `todos new <slug> "<title>" --priority <P> --agent openclaw` |
| "what's on the list" / "what are the todos" / "what's left in `<slug>`" | `todos list` (or `todos list --slug <slug>`) — defaults to active. **If the active list is empty, also report pending count** (the CLI emits a `note: N pending review` line on empty-active; relay it). |
| "what's outstanding across everything" / "what's left across everything" | `todos index && cat ~/.todos/INDEX.md` — then summarize |
| "anything new" / "what did the agents propose" / "what's pending review" | `todos list --state pending` |
| "what should I work on" / "what should I tackle in `<duration>`" | Read `~/.todos/INDEX.md` + per-project TODOS.md, filter `status: open`, sort by priority then effort then freshness, recommend matching the time budget |
| "I'm doing `<X>`" / "start `<X>`" | Resolve to `<slug>/<id>`, run `todos start <slug> <id>` |
| "I shipped `<X>`" / "`<X>` is done" / "mark `<X>` done" | `todos done <slug> <id>` |
| "drop `<X>`" / "we won't do `<X>`" / "out of scope" | `todos drop <slug> <id> --reason "<reason>"` |
| "defer `<X>` to `<date>`" | `todos defer <slug> <id> --until YYYY-MM-DD` |
| "approve `<X>`" / "yes, add it" (in response to a pending review) | `todos approve <slug> <id>` |
| "weekly review" / "what shipped this week" | Run §"Weekly review" routine below |
| **"claim `<X>`" / "I'll take `<X>`"** (v3.1) | `todos claim <slug> <id> --actor openclaw` (1h lease default) |
| **"release `<X>`" / "give it back"** (v3.1) | `todos release <slug> <id> --actor openclaw` |
| **"hand off `<X>` to `<Y>`" / "let `<Y>` finish this"** (v3.1) | `todos handoff <slug> <id> --actor openclaw --to <Y>` |
| **"render `<slug>`" / "TODOS.md got hand-edited, fix it"** (v3.1) | `todos render <slug>` (rebuilds TODOS.md from EVENTS.ndjson, discards manual edits) |

## Multi-agent coordination (v3.1+)

When more than one agent runs against the same `~/.todos/<slug>/`, claim the task before working on it:

1. **Before starting non-trivial work:** read `claimed_by` on the target todo. If another agent holds the claim and the lease hasn't expired, pick a different task or check back later.
2. **For long-running work (>5 minutes):** re-claim periodically. The lease defaults to 1h, max 24h. If you're past your lease, another agent may steal the task assuming you crashed.
3. **`claim` succeeds when:** (a) nobody holds it, (b) the lease expired, or (c) you ARE the current holder (self-refresh).
4. **`handoff` succeeds when:** (a) nobody holds it (delegation: routing it to `<Y>` on zZ's behalf), or (b) you ARE the current holder. Otherwise fails with `task_held_by_other_actor`.
5. **Claims are advisory hints**, not enforcement. `start`/`done`/`drop` do NOT check the claim. The system trusts cooperating agents to respect it.

## Resolving "&lt;X&gt;" to a `<slug>/<id>`

When zZ refers to a todo by partial title or feature name (*"the auth fix"*, *"docs cleanup"*), resolve it:

1. Run `todos list --state all` (or filter by likely slug if zZ named one).
2. Match by case-insensitive substring of the title.
3. If a unique match: use that `<slug>/<id>`.
4. If multiple matches: ask zZ which one, listing 2-3 candidates with project + title + priority.
5. If no match: ask which project zZ means; offer to create a new entry instead.

## Empty active list — always check pending

When `todos list` returns `(empty)` and the user asked "what's on the list", they almost always also want to know if there are pending proposals waiting. The CLI now emits a `note:` line in this case (e.g. `note: 24 pending review — ...`). When you see it, surface it in your reply, don't drop it. Example:

> *"Active list is empty — nothing approved yet. You have **24 pending** in the inbox (mostly ingested from existing repo TODOS.md). Say 'review inbox' or 'anything new?' to walk through them."*

If the user wants the structured payload (e.g. for prioritization), use `todos list --json`:

```bash
todos list --json                 # default state: active
todos list --state all --json     # everything, machine-readable
```

JSON output includes per-project status counts and a top-level aggregate — useful for morning-briefing generation without needing `todos index`.

## The two add paths

**Interactive (what zZ usually does):** zZ explicitly tells you to add something. Use `todos new` — it writes `status: open` directly. zZ already approved by speaking.

```bash
todos new my-app "Fix MW API rate-limit silent failure" --priority P1 --effort S --agent openclaw
```

**Autonomous (rare):** You're acting in a heartbeat or finishing a task and want to record a follow-up zZ hasn't seen. Use `todos propose` — it writes `status: pending`.

```bash
todos propose my-app "Add rate-limiting to /auth/refresh" --priority P2 --agent openclaw
```

zZ will see it on next "anything new?" / heartbeat / morning catch-up.

## Cross-project surface

When zZ asks *"what's outstanding across everything?"*:

1. Run `todos index` to refresh `~/.todos/INDEX.md` (cheap, ~50ms).
2. Read INDEX.md.
3. Summarize in this shape (preserve emoji and counts; they make it scannable):

```
📋 38 active · 4 done this week · 3 pending review · 5 stale (>30d)

🔥 P0/P1 (3):
  • my-app — Fix MW API rate-limit silent failure (P1, S)
  • side-project — Magika auto-detect follow-up (P1, M)
  • personal/health — Annual physical (P1, deadline May 14)

🟡 Pending review (3):
  • my-app — claude-code proposed: rate-limiting on /auth/refresh
  • personal/learning — codex proposed: pick a Q2 book

By project:
  my-app          12 open · 1 in-progress · 4 done this week
  side-project     5 open
  personal/health  1 open · deadline soon
```

End with: *"Want me to drill into any project, or recommend what to tackle next?"*

## Smart prioritization — "what should I tackle in 2 hours?"

Read INDEX.json (regenerated by `todos index`) or all TODOS.md files. For each open or in-progress entry, score:

- **Priority weight:** P0=4, P1=3, P2=2, P3=1
- **Effort weight:** matches time budget? (XS=10min, S=1h, M=4h, L=days, XL=week+)
- **Freshness:** entries updated in last 7 days get a small boost; stale items (>30d) get a small penalty unless P1+

Pick top 3, mention why each fits the budget. Example:

> *Based on priority, freshness, and effort:*
> - **`my-app` MW API fix** — P1, S effort, ~1 hour. Fastest win.
> - **`gbrain` dead-link cleanup** — P2, XS effort, 10 min while you wait.
> - skip personal/health for now — needs your physical presence, not desk time.

If zZ accepts, run `todos start <slug> <id>` for the chosen one.

## Heartbeat hooks (proactive alerts)

When invoked from a heartbeat (not a direct ask):

1. Run `todos index` quietly.
2. Read `~/.todos/INDEX.md`.
3. Surface ONE thing per heartbeat — never spam. Pick the highest-signal thing:
   - **New P0** since last heartbeat → ⏰ alert immediately
   - **Pending review proposals ≥10 unread for >24h** → "you have 12 pending — say 'review' when ready"
   - **Stale spotlight** (rotate one per heartbeat from `>30d untouched` list) → "FYI, this has been sitting 47 days — schedule, demote, or drop?"
   - **Deadline approaching** (entries with date-relevant tags or body mentions) → flag if within 2 weeks
4. Otherwise, **stay silent**. (Return `HEARTBEAT_OK` per OpenClaw conventions.)
5. Track last-surfaced state in `memory/heartbeat-state.json` so we don't re-surface the same item twice in a row.

## Weekly review routine

When zZ says *"weekly review"* or it's Sunday evening (heartbeat-triggered):

1. `todos snapshot` — write this week's frozen state to `~/.todos/snapshots/YYYY-Wxx.json`.
2. Read last week's snapshot (`YYYY-W(xx-1).json`).
3. Compute:
   - **Shipped:** entries with `status: done` whose `updated` is in the past 7 days.
   - **Created:** entries with `created` in the past 7 days.
   - **Net delta:** `created - shipped`. Positive = backlog growing.
   - **Stale spotlight:** one item, rotated each week, with `status` in `{open, in-progress}` and `updated` >30 days old.
4. Present:

```
📊 Weekly review — 2026-W18 (Apr 22–28)

Shipped this week (4):
  • my-app — Fix MW API rate-limit (P1)
  • my-app — Caching layer for definitions (P2)
  • personal/health — Booked annual physical
  • side-project — Doc cleanup

Created this week (6):
  • my-app — 3 from claude-code sessions
  • personal/learning — 1 from openclaw chat
  • side-project — 2 from codex review

Net: +2 backlog. Manageable.

Stale spotlight: "Cerebro provider integration" in side-project hasn't moved in 47 days.
  Schedule, demote to P3, or drop?
```

End with: *"Anything from this week worth saving as a learning? Anything to plan for next week?"*

## Things to remember

- **Never bypass the verbs.** Always use `todos new / approve / start / done / drop / defer`. Don't hand-edit `TODOS.md` — the CLI keeps git history clean and atomic.
- **`status: open` is the default for adds.** Only use `propose` (which writes `pending`) when you're acting autonomously without zZ's confirmation.
- **`agent: openclaw`** when zZ dictates a proposal directly during chat with you. Don't lie about provenance.
- **Slug detection from `cwd` matters.** When zZ says "add a todo here," walk up from `cwd`, match against `~/.todos/registry.yaml`. If no match, ask which project (or use `unsorted`).
- **Respect `wont` tombstones.** Before proposing a new entry, scan `<slug>/TODOS.md` for matching `wont` entries. If something was already declined, don't re-propose without zZ's prompt.
- **One commit per verdict** — the CLI does this for you. Resist the urge to batch.

## Standing rule (from project memory)

> Never write a todo into `~/.todos/<slug>/TODOS.md` claiming it was zZ's idea unless zZ explicitly said so in this conversation. If you're acting autonomously, use `todos propose` (status: pending) so zZ can confirm or drop. Inventing missions and persisting them as user requests is the worst kind of memory rot. When in doubt, ask first.

(Origin: 2026-04-27 vocabulary-learning-skill incident, where a previous Claw session designed an entire skill on its own initiative and persisted it as zZ's stated mission. See `MEMORY.md` lessons learned.)
