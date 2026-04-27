#!/usr/bin/env python3
"""
todos — reference CLI for clawtodos / todo-contract/v2.

Single-module, Python stdlib only. Cross-platform (macOS, Linux, Windows).

  todos init                                 # bootstrap ~/.todos/, git init
  todos add <path-or-name> [--type code|program] [--ingest|--no-ingest]
  todos list [--slug <slug>] [--state inbox|todos|done|rejected|all]
  todos move <slug> <id> --to inbox|todos|done|rejected [--reason <text>]
  todos approve <slug> <id>
  todos reject  <slug> <id> [--reason <text>]
  todos defer   <slug> <id> --until YYYY-MM-DD
  todos done    <slug> <id>
  todos ingest  <slug>
  todos index
  todos doctor

The <id> is the slugified title (lowercased, non-alnum -> -) within a project.
Use `todos list --slug <slug>` to see ids.
"""

from __future__ import annotations

import argparse
import datetime as dt
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

SCHEMA = "todo-contract/v2"
STATES = ("INBOX", "TODOS", "DONE", "REJECTED")
STATE_FILES = {s: f"{s}.md" for s in STATES}

PRIORITY_ALIASES = {
    "urgent": "P0", "critical": "P0",
    "high": "P1",
    "med": "P2", "medium": "P2",
    "low": "P3",
    "p0": "P0", "p1": "P1", "p2": "P2", "p3": "P3",
}
EFFORT_TOKENS = {"XS", "S", "M", "L", "XL"}
STATUS_VALUES = {"open", "in-progress", "done", "wont"}


def default_root() -> Path:
    return Path(os.environ.get("TODO_CONTRACT_ROOT", str(Path.home() / ".todos"))).expanduser()


# Mutable, set by main() once flags are parsed.
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
# Markdown parsing — matches SPEC §4
# --------------------------------------------------------------------------------------

@dataclass
class Todo:
    title: str
    fields: dict[str, str] = field(default_factory=dict)
    body: str = ""
    in_done_group: bool = False

    @property
    def status(self) -> str:
        if self.in_done_group:
            return "done"
        if self.title.startswith("~~") and self.title.endswith("~~"):
            return "done"
        return self.fields.get("status", "open")

    @property
    def slug(self) -> str:
        t = self.title.strip("~* ").lower()
        s = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
        return s[:80] or "untitled"

    def to_md(self) -> str:
        lines = [f"### {self.title}"]
        for k in ("status", "priority", "effort", "agent", "created", "updated", "tags",
                  "deferred", "rejected_at", "rejected_reason"):
            if k in self.fields:
                lines.append(f"- **{k}:** {self.fields[k]}")
        canonical = {"status", "priority", "effort", "agent", "created", "updated", "tags",
                     "deferred", "rejected_at", "rejected_reason"}
        for k, v in self.fields.items():
            if k not in canonical:
                lines.append(f"- **{k}:** {v}")
        if self.body.strip():
            lines.append("")
            lines.append(self.body.rstrip())
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
    in_done_group = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            in_done_group = (heading == "done")
            i += 1
            continue
        if line.startswith("### "):
            title = line[4:].strip()
            t = Todo(title=title, in_done_group=in_done_group)
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


def state_path(slug: str, state: str) -> Path:
    return project_dir(slug) / STATE_FILES[state]


def ensure_project_dir(slug: str) -> None:
    d = project_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    for state in ("INBOX", "TODOS"):
        p = state_path(slug, state)
        if not p.exists():
            p.write_text(_blank_file(slug, state), encoding="utf-8")


def _blank_file(slug: str, state: str) -> str:
    return (
        f"---\nschema: {SCHEMA}\nproject: {slug}\nfile: {state}\n---\n\n"
        f"# {state} — {slug}\n"
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
    print(f"  2. Paste the snippet at  https://github.com/zzbyy/clawtodos#agent-instructions")
    print(f"     into your CLAUDE.md / AGENTS.md / .cursorrules.")
    print(f"  3. Use your AI normally. Review the inbox once a day:  todos list --state inbox")
    return 0


def _root_readme() -> str:
    return (
        "# ~/.todos\n\n"
        "Central home for [clawtodos](https://github.com/zzbyy/clawtodos) — "
        "agent-native task manager.\n\n"
        "- `registry.yaml` — registered projects and personal programs\n"
        "- `<slug>/INBOX.md` — proposed todos (agents append here)\n"
        "- `<slug>/TODOS.md` — approved canonical todos\n"
        "- `<slug>/DONE.md` — archived completions\n"
        "- `<slug>/REJECTED.md` — rejected proposals (audit trail)\n"
        "- `INDEX.md` — generated cross-project rollup\n\n"
        "This directory is itself a git repo. Every approve/reject/defer commits.\n"
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


def cmd_list(args) -> int:
    reg = load_registry()
    slugs = [args.slug] if args.slug else [p["slug"] for p in reg.get("projects", [])]
    states = [args.state.upper()] if args.state and args.state != "all" else ["INBOX", "TODOS"]
    if args.state == "all":
        states = list(STATES)

    any_output = False
    for slug in slugs:
        if not find_project(reg, slug):
            print(f"unknown slug: {slug}", file=sys.stderr)
            continue
        for state in states:
            tf = parse_todo_file(state_path(slug, state))
            if not tf.todos:
                continue
            any_output = True
            print(f"\n=== {slug} / {state} ===")
            for t in tf.todos:
                pri = t.fields.get("priority", "")
                eff = t.fields.get("effort", "")
                agent = t.fields.get("agent", "")
                meta = " ".join(filter(None, [pri, eff, f"@{agent}" if agent else ""]))
                print(f"  [{t.slug}] {t.title}  {meta}".rstrip())
    if not any_output:
        print("(empty)")
    return 0


def cmd_move(args) -> int:
    return _do_move(args.slug, args.id, args.to.upper(),
                    reason=getattr(args, "reason", None))


def cmd_approve(args) -> int:
    return _do_move(args.slug, args.id, "TODOS")


def cmd_reject(args) -> int:
    return _do_move(args.slug, args.id, "REJECTED", reason=args.reason)


def cmd_done(args) -> int:
    return _do_move(args.slug, args.id, "DONE")


def cmd_defer(args) -> int:
    src_path = state_path(args.slug, "INBOX")
    src = parse_todo_file(src_path)
    todo = next((t for t in src.todos if t.slug == args.id), None)
    if not todo:
        print(f"not found: {args.slug}/{args.id} in INBOX", file=sys.stderr)
        return 1
    todo.fields["deferred"] = args.until
    todo.fields["updated"] = dt.date.today().isoformat()
    src.write()
    git_commit(f"defer: {args.slug}/{args.id} until {args.until}", [src_path])
    print(f"deferred: {args.slug}/{args.id} until {args.until}")
    return 0


def _do_move(slug: str, todo_id: str, dest_state: str,
             reason: str | None = None) -> int:
    reg = load_registry()
    if not find_project(reg, slug):
        print(f"unknown slug: {slug}", file=sys.stderr)
        return 1
    if dest_state not in STATES:
        print(f"bad destination: {dest_state}", file=sys.stderr)
        return 1

    src_state = None
    src_tf: TodoFile | None = None
    todo: Todo | None = None
    for s in STATES:
        tf = parse_todo_file(state_path(slug, s))
        match = next((t for t in tf.todos if t.slug == todo_id), None)
        if match:
            src_state, src_tf, todo = s, tf, match
            break
    if not todo or src_tf is None or src_state is None:
        print(f"not found: {slug}/{todo_id}", file=sys.stderr)
        return 1
    if src_state == dest_state:
        print(f"already in {dest_state}: {slug}/{todo_id}")
        return 0

    today = dt.date.today().isoformat()
    todo.fields["updated"] = today
    if dest_state == "TODOS":
        todo.fields.setdefault("status", "open")
        todo.fields.pop("deferred", None)
    elif dest_state == "DONE":
        todo.fields["status"] = "done"
    elif dest_state == "REJECTED":
        todo.fields["rejected_at"] = today
        if reason:
            todo.fields["rejected_reason"] = reason
        todo.fields.pop("deferred", None)

    src_tf.todos = [t for t in src_tf.todos if t.slug != todo_id]
    dest_path = state_path(slug, dest_state)
    if not dest_path.exists():
        dest_path.write_text(_blank_file(slug, dest_state), encoding="utf-8")
    dest_tf = parse_todo_file(dest_path)
    dest_tf.todos.append(todo)
    src_tf.write()
    dest_tf.write()

    git_commit(
        f"{dest_state.lower()}: {slug}/{todo_id}" + (f" ({reason})" if reason else ""),
        [src_tf.path, dest_tf.path],
    )
    print(f"moved {slug}/{todo_id}: {src_state} -> {dest_state}")
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
    found: list[Todo] = []
    v1 = source / "TODOS.md"
    if v1.exists():
        tf = parse_todo_file(v1)
        for t in tf.todos:
            t.fields.setdefault("agent", "ingest")
            found.append(t)
    for sub, status in (("pending", "open"), ("done", "done"), ("closed", "wont")):
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

    out = project_dir(slug) / "ingested.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = [
        "---",
        f"schema: {SCHEMA}",
        f"project: {slug}",
        "file: ingested",
        "---",
        "",
        f"# INGESTED — {slug}",
        "",
        f"Read-only mirror of todos discovered in {source}.",
        f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for t in found:
        body.append(t.to_md())
    out.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    print(f"ingested {len(found)} entries from {source} -> {out}")


def cmd_index(_args) -> int:
    reg = load_registry()
    rows: list[tuple[str, str, str, str, str]] = []
    for proj in reg.get("projects", []):
        slug = proj["slug"]
        for state in ("INBOX", "TODOS"):
            tf = parse_todo_file(state_path(slug, state))
            for t in tf.todos:
                rows.append((
                    slug, state, t.fields.get("priority", "P2"),
                    t.fields.get("agent", ""), t.title,
                ))

    rows.sort(key=lambda r: (r[1], r[2], r[0], r[4]))
    out = ["# INDEX", "", f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}", ""]
    out.append("| State | Priority | Project | Agent | Title |")
    out.append("|---|---|---|---|---|")
    for slug, state, pri, agent, title in rows:
        out.append(f"| {state} | {pri} | {slug} | {agent} | {title} |")
    if not rows:
        out.append("| _no entries yet_ | | | | |")
    (ROOT / "INDEX.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {ROOT / 'INDEX.md'} ({len(rows)} entries)")
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
        for s in ("INBOX", "TODOS"):
            p = state_path(slug, s)
            if not p.exists():
                print(f"warn: missing {p}")
                problems += 1
        path_str = proj.get("path")
        if path_str:
            in_repo = Path(os.path.expanduser(path_str)) / "TODOS.md"
            if in_repo.exists():
                print(f"info: {slug} has a v1-style in-repo TODOS.md at {in_repo}")
                print(f"      consider: todos ingest {slug} (one-shot import as proposals)")
    if problems == 0:
        print(f"ok: root={ROOT}, projects={len(reg.get('projects', []))}")
    return 0 if problems == 0 else 2


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="todos",
                                description="clawtodos / todo-contract/v2 reference CLI")
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

    a = sub.add_parser("list", help="list todos")
    a.add_argument("--slug")
    a.add_argument("--state", choices=("inbox", "todos", "done", "rejected", "all"))
    a.set_defaults(func=cmd_list)

    a = sub.add_parser("move", help="move a todo between INBOX/TODOS/DONE/REJECTED")
    a.add_argument("slug")
    a.add_argument("id")
    a.add_argument("--to", required=True, choices=("inbox", "todos", "done", "rejected"))
    a.add_argument("--reason", help="reason (used for rejection)")
    a.set_defaults(func=cmd_move)

    a = sub.add_parser("approve", help="promote INBOX entry to TODOS")
    a.add_argument("slug"); a.add_argument("id")
    a.set_defaults(func=cmd_approve)

    a = sub.add_parser("reject", help="reject an INBOX entry")
    a.add_argument("slug"); a.add_argument("id")
    a.add_argument("--reason")
    a.set_defaults(func=cmd_reject)

    a = sub.add_parser("done", help="mark a TODOS entry done (move to DONE)")
    a.add_argument("slug"); a.add_argument("id")
    a.set_defaults(func=cmd_done)

    a = sub.add_parser("defer", help="keep entry in INBOX with deferred:<date>")
    a.add_argument("slug"); a.add_argument("id")
    a.add_argument("--until", required=True, help="YYYY-MM-DD")
    a.set_defaults(func=cmd_defer)

    a = sub.add_parser("ingest", help="scan registered project's source for existing todos")
    a.add_argument("slug")
    a.set_defaults(func=cmd_ingest)

    a = sub.add_parser("index", help="generate $TODO_CONTRACT_ROOT/INDEX.md")
    a.set_defaults(func=cmd_index)

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
