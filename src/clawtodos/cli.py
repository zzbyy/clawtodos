#!/usr/bin/env python3
"""
todos — reference CLI for clawtodos / todo-contract/v3.

Single-module, Python stdlib only. Cross-platform (macOS, Linux, Windows).

  todos init                                 # bootstrap ~/.todos/, git init
  todos add <path-or-name> [--type code|program] [--ingest|--no-ingest]
  todos list [--slug <slug>] [--state pending|open|in-progress|done|wont|active|all]
  todos new <slug> "<title>" [--priority P2] [--effort M] [--agent <name>]
  todos propose <slug> "<title>" [--priority P2] [--effort M] [--agent <name>]
  todos approve <slug> <id>                  # pending -> open
  todos start   <slug> <id>                  # open    -> in-progress
  todos done    <slug> <id>                  # any     -> done
  todos drop    <slug> <id> [--reason <text>] # any    -> wont
  todos defer   <slug> <id> --until YYYY-MM-DD
  todos ingest  <slug>                        # one-shot scan of source repo
  todos index                                 # regenerate ~/.todos/INDEX.md
  todos snapshot                              # write weekly snapshot
  todos doctor

The <id> is the slugified title (lowercased, non-alnum -> -) within a project.
Use `todos list --slug <slug>` to see ids.

Default `todos list` (no --state) shows only "active" entries (open + in-progress).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from .core import (
    ACTIVE_STATES,
    ALL_STATES,
    Context,
    SCHEMA,
    Todo,
    default_root,
    ensure_project_dir,
    find_project,
    load_registry,
    parse_todo_file,
    project_dir,
    save_registry,
    todos_path,
    _blank_file,
)


# --------------------------------------------------------------------------------------
# Git helpers — commit on every mutation when ROOT is itself a git repo.
# --------------------------------------------------------------------------------------

def _git_available() -> bool:
    return shutil.which("git") is not None


def git_commit(ctx: Context, message: str, files: Iterable[Path]) -> None:
    if not (ctx.root / ".git").exists() or not _git_available():
        return
    paths = [str(p.relative_to(ctx.root)) for p in files if p.exists()]
    if not paths:
        return
    try:
        subprocess.run(["git", "-C", str(ctx.root), "add", *paths],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ctx.root), "commit", "-m", message],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        msg = (e.stdout or b"").decode() + (e.stderr or b"").decode()
        if "nothing to commit" not in msg:
            print(f"warning: git commit failed: {msg.strip()}", file=sys.stderr)


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------

def cmd_init(ctx: Context, args) -> int:
    """Bootstrap ROOT: create dir, write registry.yaml + README, git init."""
    ctx.root.mkdir(parents=True, exist_ok=True)
    reg_path = ctx.root / "registry.yaml"
    if not reg_path.exists():
        save_registry(ctx, {"schema": SCHEMA, "projects": []})
    readme = ctx.root / "README.md"
    if not readme.exists():
        readme.write_text(_root_readme(), encoding="utf-8")
    snap_dir = ctx.root / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    if _git_available() and not (ctx.root / ".git").exists():
        try:
            subprocess.run(["git", "-C", str(ctx.root), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(ctx.root), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(ctx.root), "commit", "-m", "init: clawtodos root"],
                           check=True, capture_output=True)
        except Exception as e:
            print(f"note: git init skipped ({e})", file=sys.stderr)
    print(f"initialized: {ctx.root}")
    print()
    print("Next steps:")
    print(f"  1. Register a project:   todos add /path/to/your/repo")
    print(f"  2. Wire your AI agents:  see https://github.com/zzbyy/clawtodos#wire-up-agents")
    print(f"  3. Use your AI normally; review with `todos list` (or just say 'what's on the list?').")
    return 0


def _root_readme() -> str:
    return (
        "# ~/.todos\n\n"
        "Central home for [clawtodos](https://github.com/zzbyy/clawtodos) — "
        "agent-native task manager.\n\n"
        "- `registry.yaml` — registered projects and personal programs\n"
        "- `<slug>/TODOS.md` — per-project task list (one file, lifecycle in `status:` field)\n"
        "- `INDEX.md` — generated cross-project rollup\n"
        "- `snapshots/YYYY-Wxx.json` — weekly snapshots for diff-based weekly reviews\n\n"
        "This directory is itself a git repo. Every meaningful action commits.\n"
    )


def cmd_add(ctx: Context, args) -> int:
    reg = load_registry(ctx)
    target = args.target

    if Path(target).exists():
        path = Path(target).resolve()
        slug = args.slug or path.name
        type_ = args.type or ("code" if (path / ".git").exists() else "program")
        ingest = True if args.ingest is None else args.ingest
    else:
        slug = args.slug or target
        path = None
        type_ = args.type or "program"
        ingest = False if args.ingest is None else args.ingest

    if find_project(reg, slug):
        print(f"error: slug '{slug}' is already registered", file=sys.stderr)
        return 1

    entry = {"slug": slug, "type": type_}
    if path is not None:
        entry["path"] = str(path)
    entry["ingest"] = bool(ingest)
    reg.setdefault("projects", []).append(entry)
    reg["schema"] = SCHEMA
    save_registry(ctx, reg)

    ensure_project_dir(ctx, slug)
    print(f"registered: {slug} (type={type_}, ingest={ingest})")

    if ingest and path is not None:
        do_ingest(ctx, slug, path)

    git_commit(ctx, f"register: {slug}", [ctx.root / "registry.yaml", project_dir(ctx, slug)])
    return 0


def cmd_new(ctx: Context, args) -> int:
    """Add a new todo with status=open (the explicit-approval path)."""
    return _append_todo(ctx, args, default_status="open")


def cmd_propose(ctx: Context, args) -> int:
    """Add a new todo with status=pending (the autonomous-agent path)."""
    return _append_todo(ctx, args, default_status="pending")


def _append_todo(ctx: Context, args, default_status: str) -> int:
    reg = load_registry(ctx)
    if not find_project(reg, args.slug):
        print(f"unknown slug: {args.slug}", file=sys.stderr)
        return 1
    ensure_project_dir(ctx, args.slug)
    p = todos_path(ctx, args.slug)
    tf = parse_todo_file(p)

    today = dt.date.today().isoformat()
    fields = {
        "status": default_status,
        "priority": (args.priority or "P2").upper(),
        "created": today,
    }
    if args.effort:
        fields["effort"] = args.effort.upper()
    if args.agent:
        fields["agent"] = args.agent
    if args.tags:
        fields["tags"] = args.tags

    new = Todo(title=args.title, fields=fields, body=(args.body or ""))
    if any(t.slug == new.slug and t.status not in ("done", "wont") for t in tf.todos):
        print(f"warning: a todo with id '{new.slug}' already exists in {args.slug}",
              file=sys.stderr)
    tf.todos.append(new)
    tf.write()

    git_commit(ctx, f"{default_status}: {args.slug}/{new.slug}", [p])
    print(f"added: {args.slug}/{new.slug} (status={default_status})")
    return 0


def cmd_list(ctx: Context, args) -> int:
    reg = load_registry(ctx)
    slugs = [args.slug] if args.slug else [p["slug"] for p in reg.get("projects", [])]

    state_filter = (args.state or "active").lower()
    if state_filter == "active":
        wanted = set(ACTIVE_STATES)
    elif state_filter == "all":
        wanted = set(ALL_STATES)
    else:
        wanted = {state_filter}

    today = dt.date.today().isoformat()
    json_out = getattr(args, "json", False)

    # Collect rows per slug, plus per-slug status counts (used for the
    # "empty active but pending exists" nudge and for --json output).
    per_slug_rows: list[tuple[str, list[Todo]]] = []
    per_slug_counts: dict[str, dict[str, int]] = {}
    for slug in slugs:
        if not find_project(reg, slug):
            if not json_out:
                print(f"unknown slug: {slug}", file=sys.stderr)
            continue
        tf = parse_todo_file(todos_path(ctx, slug))
        counts = {s: 0 for s in ALL_STATES}
        rows: list[Todo] = []
        for t in tf.todos:
            counts[t.status] = counts.get(t.status, 0) + 1
            if t.status not in wanted:
                continue
            # Hide deferred items that are still in the future
            deferred = t.fields.get("deferred")
            if state_filter == "active" and deferred and deferred > today:
                continue
            rows.append(t)
        per_slug_counts[slug] = counts
        if rows:
            per_slug_rows.append((slug, rows))

    # JSON output: structured payload, easy for agents to consume.
    if json_out:
        payload = {
            "schema": SCHEMA,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "state_filter": state_filter,
            "projects": [],
        }
        included = {s for s, _ in per_slug_rows}
        ordered = [s for s, _ in per_slug_rows] + [
            s for s in per_slug_counts if s not in included
        ]
        for slug in ordered:
            rows = next((r for s, r in per_slug_rows if s == slug), [])
            payload["projects"].append({
                "slug": slug,
                "counts": per_slug_counts.get(slug, {}),
                "todos": [_todo_to_dict(slug, t) for t in rows],
            })
        agg = {s: 0 for s in ALL_STATES}
        for c in per_slug_counts.values():
            for s, n in c.items():
                agg[s] = agg.get(s, 0) + n
        payload["counts"] = agg
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    # Human output
    any_output = False
    for slug, rows in per_slug_rows:
        any_output = True
        print(f"\n=== {slug} ({len(rows)}) ===")
        for t in rows:
            pri = t.priority
            eff = t.fields.get("effort", "")
            agent = t.fields.get("agent", "")
            stat = t.status
            stat_tag = f"[{stat}]" if state_filter in ("all", "active") and stat != "open" else ""
            meta = " ".join(filter(None, [pri, eff, f"@{agent}" if agent else "", stat_tag]))
            print(f"  [{t.slug}] {t.title}  {meta}".rstrip())
    if not any_output:
        print("(empty)")
        # Nudge: when the default 'active' filter found nothing, surface other
        # states that DO have entries — most commonly, pending review proposals
        # from agents. Avoids the silent-empty-list trap where a user thinks
        # they have no work but actually has 24 ingested proposals waiting.
        if state_filter == "active":
            other_counts = {s: 0 for s in ALL_STATES if s not in wanted}
            for c in per_slug_counts.values():
                for s, n in c.items():
                    if s in other_counts:
                        other_counts[s] += n
            hints = []
            if other_counts.get("pending", 0):
                hints.append(
                    f"{other_counts['pending']} pending review — "
                    f"`todos list --state pending` (or say 'anything new?')"
                )
            if other_counts.get("done", 0):
                hints.append(
                    f"{other_counts['done']} done — `todos list --state done`"
                )
            for hint in hints:
                print(f"note: {hint}")
    return 0


def _todo_to_dict(slug: str, t: Todo) -> dict:
    """Serialize a Todo for JSON output."""
    return {
        "id": f"{slug}/{t.slug}",
        "slug": t.slug,
        "project": slug,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "effort": t.fields.get("effort"),
        "agent": t.fields.get("agent"),
        "created": t.fields.get("created"),
        "updated": t.fields.get("updated"),
        "deferred": t.fields.get("deferred"),
        "tags": [s.strip() for s in t.fields.get("tags", "").split(",") if s.strip()],
        "wont_reason": t.fields.get("wont_reason"),
        "body": t.body,
    }


def cmd_set_status(ctx: Context, args) -> int:
    """Generic state-flip primitive."""
    return _flip_status(ctx, args.slug, args.id, args.to.lower(),
                        reason=getattr(args, "reason", None))


def cmd_approve(ctx: Context, args) -> int:
    return _flip_status(ctx, args.slug, args.id, "open")


def cmd_start(ctx: Context, args) -> int:
    return _flip_status(ctx, args.slug, args.id, "in-progress")


def cmd_done(ctx: Context, args) -> int:
    return _flip_status(ctx, args.slug, args.id, "done")


def cmd_drop(ctx: Context, args) -> int:
    return _flip_status(ctx, args.slug, args.id, "wont", reason=args.reason)


def _flip_status(ctx: Context, slug: str, todo_id: str, target: str,
                 reason: str | None = None) -> int:
    reg = load_registry(ctx)
    if not find_project(reg, slug):
        print(f"unknown slug: {slug}", file=sys.stderr)
        return 1
    if target not in ALL_STATES:
        print(f"bad status: {target}. Must be one of {ALL_STATES}", file=sys.stderr)
        return 1

    p = todos_path(ctx, slug)
    tf = parse_todo_file(p)
    todo = next((t for t in tf.todos if t.slug == todo_id), None)
    if not todo:
        print(f"not found: {slug}/{todo_id}", file=sys.stderr)
        return 1

    prev = todo.status
    if prev == target:
        print(f"already {target}: {slug}/{todo_id}")
        return 0

    today = dt.date.today().isoformat()
    todo.fields["status"] = target
    todo.fields["updated"] = today
    if target != "pending":
        todo.fields.pop("deferred", None)
    if target == "wont" and reason:
        todo.fields["wont_reason"] = reason

    tf.write()
    suffix = f" ({reason})" if reason else ""
    git_commit(ctx, f"{target}: {slug}/{todo_id}{suffix}", [p])
    print(f"{slug}/{todo_id}: {prev} -> {target}")
    return 0


def cmd_defer(ctx: Context, args) -> int:
    p = todos_path(ctx, args.slug)
    tf = parse_todo_file(p)
    todo = next((t for t in tf.todos if t.slug == args.id), None)
    if not todo:
        print(f"not found: {args.slug}/{args.id}", file=sys.stderr)
        return 1
    todo.fields["deferred"] = args.until
    todo.fields["updated"] = dt.date.today().isoformat()
    tf.write()
    git_commit(ctx, f"defer: {args.slug}/{args.id} until {args.until}", [p])
    print(f"deferred: {args.slug}/{args.id} until {args.until}")
    return 0


def cmd_ingest(ctx: Context, args) -> int:
    reg = load_registry(ctx)
    proj = find_project(reg, args.slug)
    if not proj:
        print(f"unknown slug: {args.slug}", file=sys.stderr)
        return 1
    path_str = proj.get("path")
    if not path_str:
        print(f"slug '{args.slug}' has no source path; nothing to ingest", file=sys.stderr)
        return 1
    do_ingest(ctx, args.slug, Path(os.path.expanduser(path_str)).resolve())
    return 0


def do_ingest(ctx: Context, slug: str, source: Path) -> None:
    """Scan source repo for existing todos. Append as `status: pending` so the
    user can review and approve."""
    found: list[Todo] = []

    # 1) v1 in-repo TODOS.md
    v1 = source / "TODOS.md"
    if v1.exists():
        tf = parse_todo_file(v1)
        for t in tf.todos:
            t.fields.setdefault("agent", "ingest")
            # Preserve terminal states (done/wont) instead of forcing them
            # back into the review queue. v1 conventions like `## Done`
            # group headings or `~~strikethrough~~` titles surface as
            # status=done at parse time; respect that. Only items that
            # were genuinely active in the source repo go to pending.
            if t.status not in ("done", "wont"):
                t.fields["status"] = "pending"
            found.append(t)

    # 2) .planning/todos/{pending,done,closed}/*.md (gsd-style)
    for sub, status in (("pending", "pending"), ("done", "done"), ("closed", "wont")):
        d = source / ".planning" / "todos" / sub
        if d.exists():
            for f in sorted(d.glob("*.md")):
                title = f.stem.replace("-", " ").capitalize()
                body_text = f.read_text(encoding="utf-8")
                t = Todo(title=title)
                t.fields["status"] = status
                t.fields["agent"] = "ingest"
                t.body = body_text
                found.append(t)

    if not found:
        print(f"ingested 0 entries from {source}")
        return

    # Append into the project's TODOS.md (don't overwrite existing entries by id)
    p = todos_path(ctx, slug)
    project_dir(ctx, slug).mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(_blank_file(slug), encoding="utf-8")
    tf = parse_todo_file(p)
    existing_slugs = {t.slug for t in tf.todos}
    new_count = 0
    for t in found:
        if t.slug in existing_slugs:
            continue
        tf.todos.append(t)
        new_count += 1
    tf.write()
    git_commit(ctx, f"ingest: {slug} ({new_count} new from {source.name})", [p])
    print(f"ingested {new_count} new entries from {source} -> {p}")


def _all_todos(ctx: Context) -> list[tuple[str, Todo]]:
    """Return (slug, Todo) pairs across every registered project."""
    reg = load_registry(ctx)
    out = []
    for proj in reg.get("projects", []):
        slug = proj["slug"]
        tf = parse_todo_file(todos_path(ctx, slug))
        for t in tf.todos:
            out.append((slug, t))
    return out


def cmd_index(ctx: Context, _args) -> int:
    today = dt.date.today()
    today_iso = today.isoformat()
    week_ago = (today - dt.timedelta(days=7)).isoformat()

    todos = _all_todos(ctx)
    visible_pending = [(s, t) for s, t in todos
                       if t.status == "pending"
                       and (not t.fields.get("deferred") or t.fields["deferred"] <= today_iso)]
    active = [(s, t) for s, t in todos if t.status in ACTIVE_STATES
              and (not t.fields.get("deferred") or t.fields["deferred"] <= today_iso)]
    in_prog = [(s, t) for s, t in todos if t.status == "in-progress"]
    open_ = [(s, t) for s, t in todos if t.status == "open"]
    done_recent = [(s, t) for s, t in todos
                   if t.status == "done"
                   and t.fields.get("updated", "") >= week_ago]
    stale = [(s, t) for s, t in todos
             if t.status in ACTIVE_STATES
             and (t.fields.get("updated") or t.fields.get("created", "9999")) <
             (today - dt.timedelta(days=30)).isoformat()]

    p_counts = {p: sum(1 for _, t in active if t.priority == p) for p in ("P0", "P1", "P2", "P3")}
    by_proj_active: dict[str, list[Todo]] = {}
    for s, t in active:
        by_proj_active.setdefault(s, []).append(t)

    lines = [
        "# clawtodos — INDEX",
        "",
        f"_generated {dt.datetime.now().isoformat(timespec='seconds')}_",
        "",
        f"📋 **{len(active)} active** ({len(in_prog)} in-progress, {len(open_)} open) "
        f"· **{len(visible_pending)} pending review** "
        f"· **{len(done_recent)} done this week** "
        f"· **{len(stale)} stale (>30d)**",
        "",
        f"**By priority (active):**  P0={p_counts['P0']} · P1={p_counts['P1']} · "
        f"P2={p_counts['P2']} · P3={p_counts['P3']}",
        "",
    ]

    # Pending review block
    if visible_pending:
        lines.append(f"## 🟡 Pending review ({len(visible_pending)})")
        lines.append("")
        for s, t in sorted(visible_pending, key=lambda x: (x[1].priority, x[0], x[1].title)):
            agent = f" @{t.fields.get('agent', '?')}"
            lines.append(f"- **[{t.priority}]** `{s}` — {t.title}{agent}")
        lines.append("")

    # Top of mind: P0 / P1 active
    hot = [(s, t) for s, t in active if t.priority in ("P0", "P1")]
    if hot:
        lines.append(f"## 🔥 Top of mind ({len(hot)} P0/P1)")
        lines.append("")
        for s, t in sorted(hot, key=lambda x: (x[1].priority, x[0])):
            lines.append(f"- **[{t.priority}]** `{s}` — {t.title}")
        lines.append("")

    # By project
    lines.append("## By project")
    lines.append("")
    reg = load_registry(ctx)
    for proj in reg.get("projects", []):
        slug = proj["slug"]
        recs = by_proj_active.get(slug, [])
        all_for_proj = [t for s, t in todos if s == slug]
        if not all_for_proj:
            lines.append(f"### `{slug}` — _no todos yet_")
            lines.append("")
            continue
        ip = sum(1 for t in all_for_proj if t.status == "in-progress")
        op = sum(1 for t in all_for_proj if t.status == "open")
        dn = sum(1 for t in all_for_proj if t.status == "done")
        wn = sum(1 for t in all_for_proj if t.status == "wont")
        lines.append(f"### `{slug}` — {op} open · {ip} in-progress · {dn} done · {wn} wont")
        lines.append("")
        if not recs:
            continue
        for t in sorted(recs, key=lambda x: (x.priority, x.title)):
            eff = t.fields.get("effort", "")
            tag = f"[{t.status}]" if t.status != "open" else ""
            lines.append(f"- **[{t.priority}{(' · ' + eff) if eff else ''}]** {t.title} {tag}".rstrip())
        lines.append("")

    # Stale spotlight
    if stale:
        lines.append(f"## ⏳ Stale (>30 days, top {min(5, len(stale))})")
        lines.append("")
        for s, t in sorted(stale,
                           key=lambda x: x[1].fields.get("updated") or x[1].fields.get("created", ""))[:5]:
            updated = t.fields.get("updated") or t.fields.get("created", "?")
            lines.append(f"- `{s}` — {t.title} _(last touched {updated})_")
        lines.append("")

    (ctx.root / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {ctx.root / 'INDEX.md'}")
    return 0


def cmd_snapshot(ctx: Context, _args) -> int:
    """Write a weekly snapshot to ~/.todos/snapshots/YYYY-Wxx.json."""
    snap_dir = ctx.root / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    snap_path = snap_dir / f"{iso_year}-W{iso_week:02d}.json"

    todos = _all_todos(ctx)
    payload = {
        "schema": SCHEMA,
        "snapshot_date": today.isoformat(),
        "iso_week": f"{iso_year}-W{iso_week:02d}",
        "counts": {
            "total": len(todos),
            **{state: sum(1 for _, t in todos if t.status == state) for state in ALL_STATES},
        },
        "todos": [
            {
                "id": f"{slug}/{t.slug}",
                "project": slug,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "effort": t.fields.get("effort"),
                "agent": t.fields.get("agent"),
                "created": t.fields.get("created"),
                "updated": t.fields.get("updated"),
                "deferred": t.fields.get("deferred"),
                "tags": [x.strip() for x in t.fields.get("tags", "").split(",") if x.strip()],
            }
            for slug, t in todos
        ],
    }
    snap_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    git_commit(ctx, f"snapshot: {iso_year}-W{iso_week:02d}", [snap_path])
    print(f"wrote snapshot: {snap_path} ({payload['counts']['total']} todos)")
    return 0


def cmd_doctor(ctx: Context, _args) -> int:
    problems = 0
    if not ctx.root.exists():
        print(f"root missing: {ctx.root}", file=sys.stderr)
        return 1
    reg = load_registry(ctx)
    if reg.get("schema") != SCHEMA:
        print(f"warn: registry schema is {reg.get('schema')!r}, expected {SCHEMA!r}")
        problems += 1
    for proj in reg.get("projects", []):
        slug = proj["slug"]
        p = todos_path(ctx, slug)
        if not p.exists():
            print(f"warn: missing {p}")
            problems += 1
        path_str = proj.get("path")
        if path_str:
            in_repo = Path(os.path.expanduser(path_str)) / "TODOS.md"
            if in_repo.exists():
                print(f"info: {slug} has a v1-style in-repo TODOS.md at {in_repo}")
                print(f"      consider: todos ingest {slug} (one-shot import as pending)")
    if problems == 0:
        print(f"ok: root={ctx.root}, projects={len(reg.get('projects', []))}, schema={SCHEMA}")
    return 0 if problems == 0 else 2


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="todos",
        description="clawtodos / todo-contract/v3 reference CLI",
    )
    p.add_argument("--root", help="override TODO_CONTRACT_ROOT (default ~/.todos)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init", help="bootstrap ~/.todos/ (create dir, registry, git)")
    a.set_defaults(func=cmd_init)

    a = sub.add_parser("add", help="register a project or pseudo-project")
    a.add_argument("target", help="filesystem path OR pseudo-slug like personal/health")
    a.add_argument("--slug", help="override slug (default: dirname or target)")
    a.add_argument("--type", choices=("code", "program"))
    a.add_argument("--ingest", dest="ingest", action="store_true", default=None)
    a.add_argument("--no-ingest", dest="ingest", action="store_false")
    a.set_defaults(func=cmd_add)

    a = sub.add_parser("new", help="create a new todo (status: open — explicit-approval path)")
    a.add_argument("slug")
    a.add_argument("title")
    a.add_argument("--priority", default="P2")
    a.add_argument("--effort")
    a.add_argument("--agent", help="who's proposing it (default: not set)")
    a.add_argument("--tags", help="comma-separated tags")
    a.add_argument("--body", help="optional free-form body text")
    a.set_defaults(func=cmd_new)

    a = sub.add_parser("propose", help="propose a todo (status: pending — autonomous-agent path)")
    a.add_argument("slug")
    a.add_argument("title")
    a.add_argument("--priority", default="P2")
    a.add_argument("--effort")
    a.add_argument("--agent", help="who's proposing it")
    a.add_argument("--tags")
    a.add_argument("--body")
    a.set_defaults(func=cmd_propose)

    a = sub.add_parser("list", help="list todos (default: only active)")
    a.add_argument("--slug")
    a.add_argument(
        "--state",
        choices=("active", "pending", "open", "in-progress", "done", "wont", "all"),
        help="default: active (open + in-progress)",
    )
    a.add_argument(
        "--json",
        action="store_true",
        help="emit JSON for agent consumption (includes per-project counts)",
    )
    a.set_defaults(func=cmd_list)

    a = sub.add_parser("approve", help="pending → open")
    a.add_argument("slug"); a.add_argument("id")
    a.set_defaults(func=cmd_approve)

    a = sub.add_parser("start", help="open → in-progress")
    a.add_argument("slug"); a.add_argument("id")
    a.set_defaults(func=cmd_start)

    a = sub.add_parser("done", help="any → done")
    a.add_argument("slug"); a.add_argument("id")
    a.set_defaults(func=cmd_done)

    a = sub.add_parser("drop", help="any → wont (tombstone)")
    a.add_argument("slug"); a.add_argument("id")
    a.add_argument("--reason")
    a.set_defaults(func=cmd_drop)

    a = sub.add_parser("set-status", help="generic state-flip primitive")
    a.add_argument("slug"); a.add_argument("id")
    a.add_argument("--to", required=True,
                   choices=ALL_STATES)
    a.add_argument("--reason")
    a.set_defaults(func=cmd_set_status)

    a = sub.add_parser("defer", help="add deferred:<date> field; hide from active list until then")
    a.add_argument("slug"); a.add_argument("id")
    a.add_argument("--until", required=True, help="YYYY-MM-DD")
    a.set_defaults(func=cmd_defer)

    a = sub.add_parser("ingest", help="scan a registered project's source for existing todos")
    a.add_argument("slug")
    a.set_defaults(func=cmd_ingest)

    a = sub.add_parser("index", help="regenerate ~/.todos/INDEX.md")
    a.set_defaults(func=cmd_index)

    a = sub.add_parser("snapshot", help="write weekly snapshot to ~/.todos/snapshots/YYYY-Wxx.json")
    a.set_defaults(func=cmd_snapshot)

    a = sub.add_parser("doctor", help="sanity check the central tree")
    a.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "root", None):
        ctx = Context(root=Path(os.path.expanduser(args.root)).resolve())
    else:
        ctx = Context.from_default()
    if args.cmd != "init":
        if not ctx.root.exists():
            print(f"error: {ctx.root} does not exist. Run `todos init` first.", file=sys.stderr)
            return 1
    return args.func(ctx, args)


if __name__ == "__main__":
    sys.exit(main())
