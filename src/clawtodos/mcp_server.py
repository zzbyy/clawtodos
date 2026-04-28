"""
clawtodos-mcp — stdio MCP server for clawtodos / todo-contract/v3.1.

Exposes the v3.1 wedge tools (projects.list, tasks.{list,create,claim,
release,handoff,start,done,drop}) over the Model Context Protocol's stdio
transport. Drop-in for Claude Desktop, Cursor, Continue, Zed, or any MCP
client.

Install: pip install clawtodos[mcp]
Run:     clawtodos-mcp
Wire:    add to ~/Library/Application Support/Claude/claude_desktop_config.json:
         { "mcpServers": { "clawtodos": { "command": "clawtodos-mcp" } } }

STDIO discipline (per SPEC-v3.1.md §9.2): stdout is reserved for JSON-RPC
protocol messages. This module captures a reference to the real stdout at
startup, then replaces sys.stdout with sys.stderr so any application-level
print() goes safely to stderr. The MCP SDK is then handed the captured
real stdout explicitly (see _run below). One stray print() in a dep can no
longer corrupt the protocol stream.
"""
from __future__ import annotations

import sys

# Stdout safety: capture the REAL stdout before anything else runs, then
# redirect sys.stdout to sys.stderr. The captured _real_stdout is handed
# back to stdio_server() in _run() so the MCP SDK still talks on FD 1.
# Per SPEC-v3.1.md §9.2 and plan-eng-review Issue 1.
_real_stdout = sys.stdout
sys.stdout = sys.stderr

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

try:
    from mcp.server import Server  # type: ignore
    from mcp.server.stdio import stdio_server  # type: ignore
    from mcp import types  # type: ignore
except ImportError as e:
    print(
        "ERROR: clawtodos-mcp requires the `mcp` SDK (Python 3.10+).\n"
        "Install with: pip install 'clawtodos[mcp]'\n"
        f"(import failed: {e})",
        file=sys.stderr,
    )
    raise SystemExit(1)

from . import events  # noqa: E402
from .core import (  # noqa: E402
    ACTIVE_STATES,
    ALL_STATES,
    Context,
    default_root,
    find_project,
    load_registry,
    todos_path,
)


# --------------------------------------------------------------------------------------
# Context construction (no CLI flags — pull from env)
# --------------------------------------------------------------------------------------

def _build_context() -> Context:
    return Context(root=default_root())


# --------------------------------------------------------------------------------------
# Error model — wrap exceptions into the documented JSON envelope.
# --------------------------------------------------------------------------------------

def _err(code: str, message: str, **details: Any) -> dict:
    payload: dict = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return payload


def _resolve_actor(args: dict) -> str:
    return args.get("actor") or os.environ.get("USER", "human")


# --------------------------------------------------------------------------------------
# Tool implementations — pure, sync, return dict (then wrapped to TextContent).
# --------------------------------------------------------------------------------------

def _tool_projects_list(ctx: Context, args: dict) -> dict:
    reg = load_registry(ctx)
    return {
        "projects": [
            {
                "slug": p["slug"],
                "type": p.get("type", "code"),
                "path": p.get("path"),
            }
            for p in reg.get("projects", [])
        ]
    }


def _todo_to_dict(slug: str, todo) -> dict:
    return {
        "id": f"{slug}/{todo.slug}",
        "slug": todo.slug,
        "project": slug,
        "title": todo.title,
        "status": todo.status,
        "priority": todo.priority,
        "effort": todo.fields.get("effort"),
        "agent": todo.fields.get("agent"),
        "claimed_by": todo.fields.get("claimed_by"),
        "lease_until": todo.fields.get("lease_until"),
        "handoff_to": todo.fields.get("handoff_to"),
        "created": todo.fields.get("created"),
        "updated": todo.fields.get("updated"),
        "deferred": todo.fields.get("deferred"),
        "tags": [
            s.strip() for s in todo.fields.get("tags", "").split(",") if s.strip()
        ],
        "wont_reason": todo.fields.get("wont_reason"),
        "body": todo.body,
    }


def _tool_tasks_list(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    state_filter = (args.get("state") or "active").lower()
    if state_filter == "active":
        wanted = set(ACTIVE_STATES)
    elif state_filter == "all":
        wanted = set(ALL_STATES)
    else:
        wanted = {state_filter}

    reg = load_registry(ctx)
    if not find_project(reg, slug):
        return _err("unknown_slug", f"unknown slug: {slug}")

    if events.is_bootstrapped(ctx, slug):
        state = events.fold_events(events.read_events(ctx, slug))
        all_todos = list(state.values())
    else:
        from .core import parse_todo_file
        tf = parse_todo_file(todos_path(ctx, slug))
        all_todos = tf.todos

    counts = {s: 0 for s in ALL_STATES}
    for t in all_todos:
        counts[t.status] = counts.get(t.status, 0) + 1
    visible = [t for t in all_todos if t.status in wanted]
    return {
        "tasks": [_todo_to_dict(slug, t) for t in visible],
        "counts": counts,
    }


def _tool_tasks_create(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    title = args["title"]
    reg = load_registry(ctx)
    if not find_project(reg, slug):
        return _err("unknown_slug", f"unknown slug: {slug}")

    # Auto-bootstrap if needed
    if not events.is_bootstrapped(ctx, slug):
        events.bootstrap_from_v30(ctx, slug)

    from .core import Todo
    placeholder = Todo(title=title)
    todo_slug = placeholder.slug
    full_id = f"{slug}/{todo_slug}"

    state = events.fold_events(events.read_events(ctx, slug))
    if full_id in state and state[full_id].fields.get("status") not in ("done", "wont"):
        return _err("duplicate_id", f"todo already exists: {full_id}", id=full_id)

    actor = _resolve_actor(args)
    fields: dict = {
        "title": title,
        "status": (args.get("status") or "open").lower(),
        "priority": (args.get("priority") or "P2").upper(),
    }
    if args.get("effort"):
        fields["effort"] = args["effort"].upper()
    if args.get("agent"):
        fields["agent"] = args["agent"]
    if args.get("tags"):
        fields["tags"] = args["tags"]

    import datetime as dt
    evt = {
        "v": events.EVENT_SCHEMA_VERSION,
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": actor,
        "event": "create",
        "id": full_id,
        "fields": fields,
    }
    if args.get("body"):
        evt["body"] = args["body"]
    events.mutate(ctx, slug, [evt], commit_message=f"create: {full_id}")

    new_state = events.fold_events(events.read_events(ctx, slug))
    return {"id": full_id, "todo": _todo_to_dict(slug, new_state[full_id])}


def _tool_tasks_claim(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    todo_slug = args["id"].split("/", 1)[-1] if "/" in args["id"] else args["id"]
    actor = _resolve_actor(args)
    lease_sec = args.get("lease_sec") or events.DEFAULT_LEASE_SECONDS
    if not events.is_bootstrapped(ctx, slug):
        events.bootstrap_from_v30(ctx, slug)
    try:
        return events.claim(ctx, slug, todo_slug, actor=actor,
                            lease_seconds=lease_sec)
    except events.UnknownTodo as e:
        return _err("unknown_id", str(e))
    except events.AlreadyClaimed as e:
        return _err("already_claimed", str(e),
                    claimed_by=e.claimed_by, lease_until=e.lease_until)


def _tool_tasks_release(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    todo_slug = args["id"].split("/", 1)[-1] if "/" in args["id"] else args["id"]
    actor = _resolve_actor(args)
    if not events.is_bootstrapped(ctx, slug):
        events.bootstrap_from_v30(ctx, slug)
    try:
        return events.release(ctx, slug, todo_slug, actor=actor)
    except events.UnknownTodo as e:
        return _err("unknown_id", str(e))
    except events.NotClaimedByActor as e:
        return _err("not_claimed_by_actor", str(e))


def _tool_tasks_handoff(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    todo_slug = args["id"].split("/", 1)[-1] if "/" in args["id"] else args["id"]
    actor = _resolve_actor(args)
    to = args["to"]
    note = args.get("note")
    lease_sec = args.get("lease_sec") or events.DEFAULT_LEASE_SECONDS
    if not events.is_bootstrapped(ctx, slug):
        events.bootstrap_from_v30(ctx, slug)
    try:
        return events.handoff(ctx, slug, todo_slug, actor=actor, to=to, note=note,
                              lease_seconds=lease_sec)
    except events.UnknownTodo as e:
        return _err("unknown_id", str(e))
    except events.TaskHeldByOtherActor as e:
        return _err("task_held_by_other_actor", str(e),
                    claimed_by=e.claimed_by, lease_until=e.lease_until)


def _tool_state_flip(ctx: Context, slug: str, todo_slug: str, target: str,
                     actor: str, reason: str | None = None) -> dict:
    if not events.is_bootstrapped(ctx, slug):
        events.bootstrap_from_v30(ctx, slug)
    full_id = f"{slug}/{todo_slug}"
    state = events.fold_events(events.read_events(ctx, slug))
    if full_id not in state:
        return _err("unknown_id", f"unknown todo: {full_id}")
    prev = state[full_id].fields.get("status", "open")
    if prev == target:
        return {"id": full_id, "status": target, "noop": True}

    import datetime as dt
    event_type_map = {"in-progress": "start", "done": "done", "wont": "drop"}
    event_type = event_type_map.get(target, "update")
    evt: dict = {
        "v": events.EVENT_SCHEMA_VERSION,
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": actor,
        "event": event_type,
        "id": full_id,
    }
    if event_type == "drop" and reason:
        evt["reason"] = reason
    elif event_type == "update":
        evt["fields"] = {"status": target, "updated": dt.date.today().isoformat()}
    events.mutate(ctx, slug, [evt], commit_message=f"{target}: {full_id}")
    out: dict = {"id": full_id, "status": target}
    if event_type == "drop" and reason:
        out["wont_reason"] = reason
    return out


def _tool_tasks_start(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    todo_slug = args["id"].split("/", 1)[-1] if "/" in args["id"] else args["id"]
    return _tool_state_flip(ctx, slug, todo_slug, "in-progress", _resolve_actor(args))


def _tool_tasks_done(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    todo_slug = args["id"].split("/", 1)[-1] if "/" in args["id"] else args["id"]
    return _tool_state_flip(ctx, slug, todo_slug, "done", _resolve_actor(args))


def _tool_tasks_drop(ctx: Context, args: dict) -> dict:
    slug = args["slug"]
    todo_slug = args["id"].split("/", 1)[-1] if "/" in args["id"] else args["id"]
    return _tool_state_flip(ctx, slug, todo_slug, "wont", _resolve_actor(args),
                            reason=args.get("reason"))


# --------------------------------------------------------------------------------------
# Tool registry: name -> (description, input_schema, handler)
# --------------------------------------------------------------------------------------

_STATE_ENUM = ["active", "pending", "open", "in-progress", "done", "wont", "all"]

TOOLS: dict[str, dict] = {
    "projects.list": {
        "description": "List all registered projects in the clawtodos store.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": _tool_projects_list,
    },
    "tasks.list": {
        "description": "List todos for a project. Default state filter is 'active' "
                       "(open + in-progress). Returns counts by state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Project slug."},
                "state": {
                    "type": "string", "enum": _STATE_ENUM,
                    "description": "State filter. Default: active.",
                },
            },
            "required": ["slug"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_list,
    },
    "tasks.create": {
        "description": "Create a new todo. Default status is 'open'. Use 'pending' "
                       "for the autonomous-agent (uncertain) path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string", "enum": ["open", "pending"]},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                "effort": {"type": "string", "enum": ["XS", "S", "M", "L", "XL"]},
                "agent": {"type": "string"},
                "tags": {"type": "string", "description": "Comma-separated."},
                "body": {"type": "string"},
                "actor": {"type": "string", "description": "Defaults to $USER."},
            },
            "required": ["slug", "title"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_create,
    },
    "tasks.claim": {
        "description": "Claim a task with a time-bounded lease. Succeeds if the task "
                       "is unclaimed, the lease expired, or the actor IS the current "
                       "holder (self-refresh). Errors with 'already_claimed' if "
                       "another actor holds the claim.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "id": {"type": "string", "description": "Todo id (slug or slug/todo-slug)."},
                "actor": {"type": "string"},
                "lease_sec": {"type": "integer", "minimum": 1, "maximum": 86400},
            },
            "required": ["slug", "id"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_claim,
    },
    "tasks.release": {
        "description": "Release a claim. Holder-only. Errors with "
                       "'not_claimed_by_actor' if you don't hold the claim.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "id": {"type": "string"},
                "actor": {"type": "string"},
            },
            "required": ["slug", "id"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_release,
    },
    "tasks.handoff": {
        "description": "Hand off a task to another actor. Succeeds if the task is "
                       "unclaimed (delegation) OR the calling actor IS the current "
                       "holder. Errors with 'task_held_by_other_actor' if a different "
                       "actor holds the claim.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "id": {"type": "string"},
                "to": {"type": "string", "description": "Recipient agent slug."},
                "actor": {"type": "string"},
                "note": {"type": "string"},
                "lease_sec": {"type": "integer", "minimum": 1, "maximum": 86400},
            },
            "required": ["slug", "id", "to"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_handoff,
    },
    "tasks.start": {
        "description": "Mark a todo as in-progress. Idempotent.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "id": {"type": "string"},
                           "actor": {"type": "string"}},
            "required": ["slug", "id"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_start,
    },
    "tasks.done": {
        "description": "Mark a todo as done. Releases any held claim.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "id": {"type": "string"},
                           "actor": {"type": "string"}},
            "required": ["slug", "id"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_done,
    },
    "tasks.drop": {
        "description": "Mark a todo as wont. Optionally captures a reason.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "id": {"type": "string"},
                           "reason": {"type": "string"}, "actor": {"type": "string"}},
            "required": ["slug", "id"],
            "additionalProperties": False,
        },
        "handler": _tool_tasks_drop,
    },
}


# --------------------------------------------------------------------------------------
# Server wiring
# --------------------------------------------------------------------------------------

def _build_server() -> "Server":
    server = Server("clawtodos", version="3.1.0")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=spec["description"],
                inputSchema=spec["input_schema"],
            )
            for name, spec in TOOLS.items()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name not in TOOLS:
            payload = _err("unknown_tool", f"no such tool: {name}")
        else:
            handler = TOOLS[name]["handler"]
            ctx = _build_context()
            try:
                result = handler(ctx, arguments or {})
                payload = result
            except Exception as e:  # belt-and-suspenders catch
                payload = _err("internal_error", f"{type(e).__name__}: {e}")
        return [types.TextContent(
            type="text",
            text=json.dumps(payload, indent=2, ensure_ascii=False),
        )]

    return server


async def _run() -> None:
    """Spin up the server. We hand the SDK the REAL stdout we captured at
    module load time so it can write protocol messages on FD 1, even though
    sys.stdout is now pointing at stderr to catch stray prints."""
    import anyio
    server = _build_server()
    # Wrap the captured real stdout into the AsyncFile the SDK expects.
    real_stdout_async = anyio.wrap_file(_real_stdout)
    async with stdio_server(stdout=real_stdout_async) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
