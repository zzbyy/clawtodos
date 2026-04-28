"""
clawtodos core — schema constants, parser, registry, FS layout.

Stdlib only. Pure functions where possible; functions that touch the filesystem
take an explicit `Context` so the same code runs from the CLI, the MCP server,
and pytest fixtures without module-global state.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------------------
# Schema constants
# --------------------------------------------------------------------------------------

SCHEMA = "todo-contract/v3"

# Lifecycle order: pending -> open -> in-progress -> done; wont = side-path tombstone.
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
    """Resolve ~/.todos (or $TODO_CONTRACT_ROOT) without applying it as a global."""
    return Path(os.environ.get("TODO_CONTRACT_ROOT", str(Path.home() / ".todos"))).expanduser()


# --------------------------------------------------------------------------------------
# Context — the explicit alternative to module-global state.
# --------------------------------------------------------------------------------------

@dataclass
class Context:
    """Per-invocation state. Pass to every function that touches the filesystem.

    Build one in cli.py main() from --root or env. Build one in mcp_server.py from
    env. Build one per-test in pytest fixtures pointing at tmp_path. No globals.
    """
    root: Path

    @classmethod
    def from_default(cls) -> "Context":
        return cls(root=default_root())


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
    """Hand-rolled minimal YAML reader (used when PyYAML isn't installed).

    Supports the two flat forms PyYAML's safe_dump emits for our use case:
      - List items at column 0:    `- slug: x\\n  type: y`
      - List items indented by 2:  `  - slug: x\\n    type: y`

    The list-item indent is detected from the first list item encountered
    after a `key:` line and used as the field-indent boundary for that list.
    """
    out: dict = {}
    cur_list = None
    cur_item: dict | None = None
    list_item_indent = -1  # number of leading spaces on the `- ` line (set on first item)
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue

        # List item start: `<indent>- key: val`
        m = re.match(r"^(\s*)-\s+(\w+):\s*(.*)$", line)
        if m and cur_list is not None:
            indent = len(m.group(1))
            if list_item_indent < 0 or indent == list_item_indent:
                list_item_indent = indent
                cur_item = {m.group(2): _coerce(m.group(3))}
                cur_list.append(cur_item)
                continue
            # else fall through (different indent → not a list item for this list)

        # List item field: `<list_item_indent + 2>key: val`
        if cur_item is not None and list_item_indent >= 0:
            field_indent = list_item_indent + 2
            stripped = line[field_indent:] if line.startswith(" " * field_indent) else None
            if stripped is not None and stripped and not stripped.startswith(" "):
                m = re.match(r"^(\w+):\s*(.*)$", stripped)
                if m:
                    cur_item[m.group(1)] = _coerce(m.group(2))
                    continue

        # Top-level key
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2)
            if val == "":
                # Block sequence on next line: `key:\n- item\n` or `key:\n  - item\n`
                cur_list = []
                out[key] = cur_list
                cur_item = None
                list_item_indent = -1
            elif val.strip() == "[]":
                # Inline empty sequence (PyYAML safe_dump emits this for `[]`)
                out[key] = []
                cur_list = None
                cur_item = None
                list_item_indent = -1
            elif val.strip() == "{}":
                out[key] = {}
                cur_list = None
                cur_item = None
                list_item_indent = -1
            else:
                out[key] = _coerce(val)
                cur_list = None
                cur_item = None
                list_item_indent = -1
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
# Registry — read/write the projects index at <root>/registry.yaml
# --------------------------------------------------------------------------------------

def load_registry(ctx: Context) -> dict:
    p = ctx.root / "registry.yaml"
    if not p.exists():
        return {"schema": SCHEMA, "projects": []}
    return _yaml_loads(p.read_text(encoding="utf-8"))


def save_registry(ctx: Context, reg: dict) -> None:
    (ctx.root / "registry.yaml").write_text(_yaml_dumps(reg), encoding="utf-8")


def find_project(reg: dict, slug: str) -> dict | None:
    for p in reg.get("projects", []):
        if p.get("slug") == slug:
            return p
    return None


# --------------------------------------------------------------------------------------
# Project filesystem layout
# --------------------------------------------------------------------------------------

def project_dir(ctx: Context, slug: str) -> Path:
    return ctx.root / slug


def todos_path(ctx: Context, slug: str) -> Path:
    """The single canonical TODOS.md for a project."""
    return project_dir(ctx, slug) / "TODOS.md"


def ensure_project_dir(ctx: Context, slug: str) -> None:
    d = project_dir(ctx, slug)
    d.mkdir(parents=True, exist_ok=True)
    p = todos_path(ctx, slug)
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
