---
name: clawtodos-review
description: Walk the user through pending todo proposals (clawtodos / todo-contract/v2 INBOX entries) one at a time. Use whenever the user says "review my inbox", "review todos", "what's pending approval", "what did the agents leave for me", or starts a daily/weekly review session. The agents propose; the user decides; this skill mediates.
---

# clawtodos-review — conversational approval for clawtodos

Pending todo proposals live in `~/.todos/<slug>/INBOX.md` (one file per project, written by Claude Code, Codex, Cursor, OpenClaw, or any clawtodos-conforming agent).

This skill walks the user through pending proposals one at a time and applies their verdict.

**Verbs:** approve / edit / defer / reject. That's it.
**Source of truth:** `~/.todos/` is a git repo. Every action commits.
**CLI:** `todos` (installed by clawtodos — assume on PATH).

## When to use this skill

| User says… | Do this |
| --- | --- |
| "review my inbox" / "review todos" / "what's pending?" | Run the full review flow (below) |
| "approve all P0 in <project>" | Filter pending, run approve on each |
| "reject the auth proposal in <project>" | Map title → id, run `todos reject` |
| "defer the docs cleanup until next week" | Compute date, run `todos defer --until` |
| "what did Claude Code propose today?" | Filter by agent + created date |

## Core paths

- **Root:** `~/.todos/` (override with `$TODO_CONTRACT_ROOT`)
- **CLI:** `todos` (run `todos --help` for verbs)
- **Spec:** [SPEC.md](https://github.com/zzbyy/clawtodos/blob/main/SPEC.md)

## The full review flow

When the user says "review my inbox" or equivalent:

### 1. List pending entries

```bash
todos list --state inbox
```

Each line is `[<id>] <title>  <priority> <effort> @<agent>`.

If empty, tell the user "Inbox is clean — nothing to review" and stop.

### 2. Announce the queue

> "You have **N** proposals pending across **M** projects. Walking them now. Say 'stop' anytime to pause."

If N is large (>20), offer to filter first: "That's a lot. Want to focus on P0/P1 only? Or one project at a time?"

### 3. Walk one at a time

For each entry, read the relevant section of `~/.todos/<slug>/INBOX.md` and present:

> **`<project>` — proposed by `<agent>`** _(<created>)_
> ### <title>
> Priority: **<P>** · Effort: **<E>**
>
> <body — first 4 lines max, then "…" if truncated>
>
> **Approve / Edit / Defer / Reject?** (a/e/d/r, or `s` to skip-don't-touch, or `stop`)

Wait for the user's verdict. Map shortcuts:

| Verdict | Action | CLI |
|---|---|---|
| `a` / approve | Move to TODOS.md | `todos approve <slug> <id>` |
| `e` / edit | Open in $EDITOR, then approve | (see "Editing" below) |
| `d` / defer | Ask "until when?", then defer | `todos defer <slug> <id> --until <date>` |
| `r` / reject | Ask "reason? (optional)", then reject | `todos reject <slug> <id> --reason "<text>"` |
| `s` / skip | Leave in inbox, don't ask again this session | (no-op) |
| `stop` | Halt the loop | (break) |

Each action commits to `~/.todos/`'s git repo. Show the resulting commit hash inline.

### 4. Closing

When the loop ends:

> "Reviewed **N**: ✅ `<a_count>` approved · ⏸ `<d_count>` deferred · ❌ `<r_count>` rejected · ↪ `<s_count>` skipped."

If `<a_count> > 0`: "Now run the actual work — `todos list` shows what's queued."

## Editing an entry

When the user chooses `edit`:

1. Open `~/.todos/<slug>/INBOX.md` in `$EDITOR` (fall back to `notepad` on Windows, `nano` on Unix).
2. Wait for save+exit.
3. Re-parse and confirm: "OK, here's the edited version. Approve now?" (a/d/r/skip)
4. If approve, run `todos approve <slug> <id>`.

## Direct verb shortcuts (when user skips the walk)

If the user says "approve <something>" without walking:

1. Resolve the target by slug+id, slug+title-fragment, or title-only.
2. If ambiguous, list candidates and ask which.
3. Run the appropriate CLI command.
4. Confirm with the resulting commit hash.

Examples:

```bash
todos approve gbrain fix-auth-token-refresh-on-expiry
todos defer  personal/health pick-a-doctor --until 2026-05-04
todos reject some-repo rename-everything --reason "out of scope"
```

## Filters and bulk operations

The user may scope the review:

- "review only `<project>`" → `todos list --slug <project> --state inbox`
- "review P0/P1 only" → filter the list output by priority field
- "review proposals from Claude Code only" → filter by `@claude-code`
- "review what arrived today" → filter by `created == today`

## Things to remember

- **Never bypass the verbs.** Always use `todos approve/reject/defer` (or the bare `todos move`). Don't hand-edit `INBOX.md`/`TODOS.md` directly — the CLI keeps git history clean.
- **One commit per verdict.** This is the audit log. Resist the urge to batch.
- **`agent: openclaw`** when the user dictates a proposal directly during a chat with you.
- **Slug detection from `cwd`.** When the user says "add a todo here," walk up from `cwd`, match against `~/.todos/registry.yaml`. If no match, ask which project (or `unsorted`).

## Heartbeat behavior (OpenClaw-specific)

When invoked from a heartbeat:

1. Run `todos list --state inbox` quietly.
2. Count entries.
3. If count crossed a threshold the user cares about (default: ≥10) since last heartbeat, surface a single line: *"You have 12 pending proposals — say 'review my inbox' when ready."*
4. Don't auto-walk during a heartbeat. The user initiates.
