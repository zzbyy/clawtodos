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
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

SCHEMA = "todo-contract/v3"

# All valid states. The order is the lifecycle order: pending → open → in-progress → done,
# with wont as a side-path (tombstone).
ALL_STATES = ("pending", "open", "in-progress", "done", "wont")
ACTIVE_STATES = ("open", "in-progress")

PRIORITY_ALIASES = {
    "urgent": "P0", "critical": "P0",
    "high": "P1",
    "med": "P2", "medium": "P2",
    "low": "P3",
    "p0": "P0", "p1": "P1", "p2": "P2", "p3": "P3",
}
EFFORT_TOKENS = {"XS", "S", "M", "L", "XL"}


def default_root() -> Path:
    return Path(os.environ.get("TODO_CONTRACT_ROOT", str(Path.home() / ".todos"))).expanduser()


# Mutable; set by main() once flags are parsed.
ROOT: Path = default_root()


# --------------------------------------------------------------------------------------
# Tiny YAML reader/writer (registry.yaml is flat; PyYAML used if present, else hand-rolled)
# --------------------------------------------------------------------------------------

def _yaml_loads(text: str) -> dict:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except Exception:
        return _yaml_loads_minimal(text)


def _yaml_dumps(data: dict) -> str:
    try:
        import yaml  # type: ignore
        return yaml.safe_dump(data, sort_keys=False)
    except Exception:
        return _yaml_dumps_minimal(data)


def _yaml_loads_minimal(text: str) -> dict:
    out: dict = {}
    cur_list = None
    cur_item: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^  - (\w+):\s*(.*)$", line)
        if m:
            if cur_list is None:
                continue
            cur_item = {m.group(1): _coerce(m.group(2))}
            cur_list.append(cur_item)
            continue
        m = re.match(r"^    (\w+):\s*(.*)$", line)
        if m and cur_item is not None:
            cur_item[m.group(1)] = _coerce(m.group(2))
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2)
            if val == "":
                cur_list = []
                out[key] = cur_list
                cur_item = None
            else:
                out[key] = _coerce(val)
                cur_list = None
                cur_item = None
    return out


def _coerce(raw: str):
    raw = raw.strip()
    if raw.lower() in ("true", "yes"):
        return True
    if raw.lower() in ("false", "no"):
        return False
    if raw.lower() in ("null", "~", ""):
        return None
    if raw.startswith(('"', "'")) and raw.endswith(raw[0]):
        return raw[1:-1]
    return raw


def _yaml_dumps_minimal(data: dict) -> str:
    lines: list[str] = []
    for k, v in data.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                first = True
                for ik, iv in item.items():
                    prefix = "  - " if first else "    "
                    first = False
                    lines.append(f"{prefix}{ik}: {_emit_scalar(iv)}")
                lines.append("")
        else:
            lines.append(f"{k}: {_emit_scalar(v)}")
    return "\n".join(lines).rstrip() + "\n"


def _emit_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    return str(v)


# --------------------------------------------------------------------------------------
# Markdown parsing — todo-contract/v3 §4 (per-todo block)
# --------------------------------------------------------------------------------------

@dataclass
class Todo:
    title: str
    fields: dict[str, str] = field(default_factory=dict)
    body: str = ""

    @property
    def status(self) -> str:
        s = self.fields.get("status", "open").lower()
        return s if s in ALL_STATES else "open"

    @property
    def priority(self) -> str:
        return self.fields.get("priority", "P2")

    @property
    def slug(self) -> str:
        t = self.title.strip("~* ").lower()
        s = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
        return s[:80] or "untitled"

    def to_md(self) -> str:
        lines = [f"### {self.title}"]
        for k in ("status", "priority", "effort", "agent", "created", "updated", "tags",
                  "deferred", "wont_reason"):
            if k in self.fields:
                lines.append(f"- **{k}:** {self.fields[k]}")
        canonical = {"status", "priority", "effort", "agent", "created", "updated", "tags",
                     "deferred", "wont_reason"}
        for k, v in self.fields.items():
            if k not in canonical:
                lines.append(f"- **{k}:** {v}")
        if self.body.strip():
            lines.append("")
            lines.append(self.body.strip())
        lines.append("")
        lines.append("---")
        lines.append("")
        return "\n".join(lines)


@dataclass
class TodoFile:
    path: Path
    frontmatter: dict[str, str]
    preamble: str
    todos: list[Todo]

    def write(self) -> None:
        out: list[str] = []
        if self.frontmatter:
            out.append("---")
            for k, v in self.frontmatter.items():
                out.append(f"{k}: {v}")
            out.append("---")
            out.append("")
        if self.preamble.strip():
            out.append(self.preamble.rstrip())
            out.append("")
        for t in self.todos:
            out.append(t.to_md())
        self.path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


_FIELD_RE = re.compile(r"^(?:-\s+)?\*\*(\w+):\*\*\s*(.*?)\s*$")


def parse_todo_file(path: Path) -> TodoFile:
    if not path.exists():
        return TodoFile(path=path, frontmatter={}, preamble="", todos=[])

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    fm: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            m = re.match(r"^(\w+):\s*(.*)$", lines[i])
            if m:
                fm[m.group(1)] = m.group(2).strip()
            i += 1
        i += 1

    preamble_lines: list[str] = []
    while i < len(lines):
        if lines[i].startswith("### ") or lines[i].startswith("## "):
            break
        preamble_lines.append(lines[i])
        i += 1
    preamble = "\n".join(preamble_lines).strip("\n")

    todos: list[Todo] = []
    in_done_group = False  # legacy v1 compat: ## Done section auto-marks done
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            in_done_group = (heading == "done")
            i += 1
            continue
        if line.startswith("### "):
            title = line[4:].strip()
            t = Todo(title=title)
            i += 1
            body_lines: list[str] = []
            while i < len(lines):
                ln = lines[i]
                if ln.startswith("### ") or ln.startswith("## "):
                    break
                if ln.strip() == "---":
                    i += 1
                    break
                m = _FIELD_RE.match(ln)
                if m and not body_lines and ln.lstrip().startswith(("-", "*")):
                    t.fields[m.group(1)] = _normalize_field(m.group(1), m.group(2))
                else:
                    body_lines.append(ln)
                i += 1
            while body_lines and not body_lines[-1].strip():
                body_lines.pop()
            t.body = "\n".join(body_lines)
            # legacy v1 compat: ~~strikethrough~~ → done
            if t.title.startswith("~~") and t.title.endswith("~~"):
                t.fields.setdefault("status", "done")
            elif in_done_group:
                t.fields.setdefault("status", "done")
            todos.append(t)
            continue
        i += 1

    return TodoFile(path=path, frontmatter=fm, preamble=preamble, todos=todos)


def _normalize_field(key: str, val: str) -> str:
    v = val.strip()
    if key == "priority":
        return PRIORITY_ALIASES.get(v.lower(), v.upper() if v.lower().startswith("p") else v)
    if key == "effort":
        head = v.split()[0].upper() if v else v
        return head if head in EFFORT_TOKENS else v
    if key == "status":
        return v.lower()
    return v


# --------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------

def load_registry() -> dict:
    p = ROOT / "registry.yaml"
    if not p.exists():
        return {"schema": SCHEMA, "projects": []}
    return _yaml_loads(p.read_text(encoding="utf-8"))


def save_registry(reg: dict) -> None:
    (ROOT / "registry.yaml").write_text(_yaml_dumps(reg), encoding="utf-8")


def find_project(reg: dict, slug: str) -> dict | None:
    for p in reg.get("projects", []):
        if p.get("slug") == slug:
            return p
    return None


# --------------------------------------------------------------------------------------
# Project filesystem
# --------------------------------------------------------------------------------------

def project_dir(slug: str) -> Path:
    return ROOT / slug


def todos_path(slug: str) -> Path:
    """The single canonical TODOS.md for a project."""
    return project_dir(slug) / "TODOS.md"


def ensure_project_dir(slug: str) -> None:
    d = project_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    p = todos_path(slug)
    if not p.exists():
        p.write_text(_blank_file(slug), encoding="utf-8")


def _blank_file(slug: str) -> str:
    return (
        f"---\nschema: {SCHEMA}\nproject: {slug}\n---\n\n"
        f"# TODOS — {slug}\n\n"
        f"Single canonical list. Lifecycle is encoded in each entry's `status:` field:\n"
        f"`pending` (agent proposed) → `open` → `in-progress` → `done`. "
        f"Side path: `wont` (tombstone for declined work).\n"
    )


# --------------------------------------------------------------------------------------
# Git helpers
# --------------------------------------------------------------------------------------

def _git_available() -> bool:
    return shutil.which("git") is not None


def git_commit(message: str, files: Iterable[Path]) -> None:
    if not (ROOT / ".git").exists() or not _git_available():
        return
    paths = [str(p.relative_to(ROOT)) for p in files if p.exists()]
    if not paths:
        return
    try:
        subprocess.run(["git", "-C", str(ROOT), "add", *paths],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ROOT), "commit", "-m", message],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        msg = (e.stdout or b"").decode() + (e.stderr or b"").decode()
        if "nothing to commit" not in msg:
            print(f"warning: git commit failed: {msg.strip()}", file=sys.stderr)


# --------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------

def cmd_init(args) -> int:
    """Bootstrap ROOT: create dir, write registry.yaml + README, git init."""
    ROOT.mkdir(parents=True, exist_ok=True)
    reg_path = ROOT / "registry.yaml"
    if not reg_path.exists():
        save_registry({"schema": SCHEMA, "projects": []})
    readme = ROOT / "README.md"
    if not readme.exists():
        readme.write_text(_root_readme(), encoding="utf-8")
    snap_dir = ROOT / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    if _git_available() and not (ROOT / ".git").exists():
        try:
            subprocess.run(["git", "-C", str(ROOT), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(ROOT), "add", "."], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(ROOT), "commit", "-m", "init: clawtodos root"],
                           check=True, capture_output=True)
        except Exception as e:
            print(f"note: git init skipped ({e})", file=sys.stderr)
    print(f"initialized: {ROOT}")
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


def cmd_add(args) -> int:
    reg = load_registry()
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
    save_registry(reg)

    ensure_project_dir(slug)
    print(f"registered: {slug} (type={type_}, ingest={ingest})")

    if ingest and path is not None:
        do_ingest(slug, path)

    git_commit(f"register: {slug}", [ROOT / "registry.yaml", project_dir(slug)])
    return 0


def cmd_new(args) -> int:
    """Add a new todo with status=open (the explicit-approval path)."""
    return _append_todo(args, default_status="open")


def cmd_propose(args) -> int:
    """Add a new todo with status=pending (the autonomous-agent path)."""
    return _append_todo(args, default_status="pending")


def _append_todo(args, default_status: str) -> int:
    reg = load_registry()
    if not find_project(reg, args.slug):
        print(f"unknown slug: {args.slug}", file=sys.stderr)
        return 1
    ensure_project_dir(args.slug)
    p = todos_path(args.slug)
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

    git_commit(f"{default_status}: {args.slug}/{new.slug}", [p])
    print(f"added: {args.slug}/{new.slug} (status={default_status})")
    return 0


def cmd_list(args) -> int:
    reg = load_registry()
    slugs = [args.slug] if args.slug else [p["slug"] for p in reg.get("projects", [])]

    state_filter = (args.state or "active").lower()
    if state_filter == "active":
        wanted = set(ACTIVE_STATES)
    elif state_filter == "all":
        wanted = set(ALL_STATES)
    else:
        wanted = {state_filter}

    today = dt.date.today().isoformat()
    any_output = False
    for slug in slugs:
        if not find_project(reg, slug):
            print(f"unknown slug: {slug}", file=sys.stderr)
            continue
        tf = parse_todo_file(todos_path(slug))
        rows = []
        for t in tf.todos:
            if t.status not in wanted:
                continue
            # Hide deferred items that are still in the future
            deferred = t.fields.get("deferred")
            if state_filter == "active" and deferred and deferred > today:
                continue
            rows.append(t)
        if not rows:
            continue
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
    return 0


def cmd_set_status(args) -> int:
    """Generic state-flip primitive."""
    return _flip_status(args.slug, args.id, args.to.lower(),
                        reason=getattr(args, "reason", None))


def cmd_approve(args) -> int:
    return _flip_status(args.slug, args.id, "open")


def cmd_start(args) -> int:
    return _flip_status(args.slug, args.id, "in-progress")


def cmd_done(args) -> int:
    return _flip_status(args.slug, args.id, "done")


def cmd_drop(args) -> int:
    return _flip_status(args.slug, args.id, "wont", reason=args.reason)


def _flip_status(slug: str, todo_id: str, target: str, reason: str | None = None) -> int:
    reg = load_registry()
    if not find_project(reg, slug):
        print(f"unknown slug: {slug}", file=sys.stderr)
        return 1
    if target not in ALL_STATES:
        print(f"bad status: {target}. Must be one of {ALL_STATES}", file=sys.stderr)
        return 1

    p = todos_path(slug)
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
    git_commit(f"{target}: {slug}/{todo_id}{suffix}", [p])
    print(f"{slug}/{todo_id}: {prev} -> {target}")
    return 0


def cmd_defer(args) -> int:
    p = todos_path(args.slug)
    tf = parse_todo_file(p)
    todo = next((t for t in tf.todos if t.slug == args.id), None)
    if not todo:
        print(f"not found: {args.slug}/{args.id}", file=sys.stderr)
        return 1
    todo.fields["deferred"] = args.until
    todo.fields["updated"] = dt.date.today().isoformat()
    tf.write()
    git_commit(f"defer: {args.slug}/{args.id} until {args.until}", [p])
    print(f"deferred: {args.slug}/{args.id} until {args.until}")
    return 0


def cmd_ingest(args) -> int:
    reg = load_registry()
    proj = find_project(reg, args.slug)
    if not proj:
        print(f"unknown slug: {args.slug}", file=sys.stderr)
        return 1
    path_str = proj.get("path")
    if not path_str:
        print(f"slug '{args.slug}' has no source path; nothing to ingest", file=sys.stderr)
        return 1
    do_ingest(args.slug, Path(os.path.expanduser(path_str)).resolve())
    return 0


def do_ingest(slug: str, source: Path) -> None:
    """Scan source repo for existing todos. Append as `status: pending` so the
    user can review and approve."""
    found: list[Todo] = []

    # 1) v1 in-repo TODOS.md
    v1 = source / "TODOS.md"
    if v1.exists():
        tf = parse_todo_file(v1)
        for t in tf.todos:
            t.fields.setdefault("agent", "ingest")
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
    p = todos_path(slug)
    project_dir(slug).mkdir(parents=True, exist_ok=True)
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
    git_commit(f"ingest: {slug} ({new_count} new from {source.name})", [p])
    print(f"ingested {new_count} new entries from {source} -> {p}")


def _all_todos() -> list[tuple[str, Todo]]:
    """Return (slug, Todo) pairs across every registered project."""
    reg = load_registry()
    out = []
    for proj in reg.get("projects", []):
        slug = proj["slug"]
        tf = parse_todo_file(todos_path(slug))
        for t in tf.todos:
            out.append((slug, t))
    return out


def cmd_index(_args) -> int:
    today = dt.date.today()
    today_iso = today.isoformat()
    week_ago = (today - dt.timedelta(days=7)).isoformat()

    todos = _all_todos()
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
    reg = load_registry()
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

    (ROOT / "INDEX.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {ROOT / 'INDEX.md'}")
    return 0


def cmd_snapshot(_args) -> int:
    """Write a weekly snapshot to ~/.todos/snapshots/YYYY-Wxx.json."""
    snap_dir = ROOT / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    snap_path = snap_dir / f"{iso_year}-W{iso_week:02d}.json"

    todos = _all_todos()
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
    git_commit(f"snapshot: {iso_year}-W{iso_week:02d}", [snap_path])
    print(f"wrote snapshot: {snap_path} ({payload['counts']['total']} todos)")
    return 0


def cmd_doctor(_args) -> int:
    problems = 0
    if not ROOT.exists():
        print(f"root missing: {ROOT}", file=sys.stderr)
        return 1
    reg = load_registry()
    if reg.get("schema") != SCHEMA:
        print(f"warn: registry schema is {reg.get('schema')!r}, expected {SCHEMA!r}")
        problems += 1
    for proj in reg.get("projects", []):
        slug = proj["slug"]
        p = todos_path(slug)
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
        print(f"ok: root={ROOT}, projects={len(reg.get('projects', []))}, schema={SCHEMA}")
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
    global ROOT
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "root", None):
        ROOT = Path(os.path.expanduser(args.root)).resolve()
    if args.cmd != "init":
        if not ROOT.exists():
            print(f"error: {ROOT} does not exist. Run `todos init` first.", file=sys.stderr)
            return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
