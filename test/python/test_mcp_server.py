"""
End-to-end MCP server tests.

Spawns `clawtodos-mcp` as a subprocess via the official mcp client SDK,
exercises every tool, and asserts on the documented JSON shapes and error
codes.

Skipped if the `mcp` package is not installed (Python < 3.10).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

mcp = pytest.importorskip("mcp")

import asyncio  # noqa: E402
import sys  # noqa: E402

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402


def _find_clawtodos_mcp() -> str:
    """Find a clawtodos-mcp script whose shebang points at THIS Python.

    PATH may have a script for a different Python (e.g., 3.9) ahead of the
    one for the current interpreter. We need the script that imports `mcp`
    successfully, which means a script using sys.executable (or compatible).
    """
    # Try sys.executable's adjacent bin first.
    candidates = [Path(sys.executable).parent / "clawtodos-mcp"]
    # Try common user-site script dirs for this Python version.
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates.extend([
        Path.home() / "Library" / "Python" / py / "bin" / "clawtodos-mcp",
        Path.home() / ".local" / "bin" / "clawtodos-mcp",
    ])
    for cand in candidates:
        if not cand.exists():
            continue
        # Check the shebang matches our interpreter
        shebang = cand.read_text().splitlines()[0] if cand.is_file() else ""
        if str(sys.executable) in shebang or "python" + py in shebang:
            return str(cand)
    # Fallback to PATH lookup (may pick wrong Python; tests will fail loudly)
    return shutil.which("clawtodos-mcp") or "clawtodos-mcp"


CLAWTODOS_MCP_BIN = _find_clawtodos_mcp()
TODOS_BIN = (
    shutil.which("todos") or os.path.expanduser("~/Library/Python/3.9/bin/todos")
)


def _todos(*args, root: Path) -> subprocess.CompletedProcess:
    """Run the regular `todos` CLI to set up fixtures."""
    cmd = [TODOS_BIN, "--root", str(root), *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"setup failed: {r.stderr}"
    return r


@pytest.fixture
def root(tmp_path: Path) -> Path:
    todos_root = tmp_path / "todos"
    _todos("init", root=todos_root)
    return todos_root


@pytest.fixture
def project(root: Path, tmp_path: Path) -> tuple[Path, str]:
    """Registered project with one open task."""
    fake_repo = tmp_path / "myapp"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    _todos("add", str(fake_repo), "--no-ingest", root=root)
    _todos("new", "myapp", "Task one", "--priority", "P1",
           "--agent", "claude-code", root=root)
    return root, "myapp"


async def _call_tool(root: Path, name: str, args: dict) -> dict:
    """Spawn clawtodos-mcp, call one tool, return parsed JSON response."""
    server_params = StdioServerParameters(
        command=CLAWTODOS_MCP_BIN,
        env={**os.environ, "TODO_CONTRACT_ROOT": str(root)},
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, args)
            assert result.content, "no content in response"
            text = result.content[0].text
            return json.loads(text)


def call_tool(root: Path, name: str, args: dict) -> dict:
    """Synchronous wrapper for use in pytest tests."""
    return asyncio.run(_call_tool(root, name, args))


# --------------------------------------------------------------------------------------
# Smoke
# --------------------------------------------------------------------------------------

def test_clawtodos_mcp_help_or_version_doesnt_crash():
    """Cheapest possible smoke: the binary at least imports without error."""
    # The MCP server doesn't have --help/--version; just ensure it doesn't fail
    # to import on this Python. We exec it briefly and kill it.
    proc = subprocess.Popen(
        [CLAWTODOS_MCP_BIN],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    proc.stdin.close()
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    # Should NOT have written anything to stdout before EOF
    # (per Issue 1 stdout-discipline).
    assert out == b"", f"server wrote to stdout pre-handshake: {out!r}"


# --------------------------------------------------------------------------------------
# projects.list
# --------------------------------------------------------------------------------------

def test_projects_list(project):
    root, slug = project
    result = call_tool(root, "projects.list", {})
    slugs = [p["slug"] for p in result["projects"]]
    assert slug in slugs


# --------------------------------------------------------------------------------------
# tasks.list / create
# --------------------------------------------------------------------------------------

def test_tasks_list_returns_active_default(project):
    root, slug = project
    result = call_tool(root, "tasks.list", {"slug": slug})
    titles = [t["title"] for t in result["tasks"]]
    assert "Task one" in titles
    assert result["counts"]["open"] >= 1


def test_tasks_create_via_mcp(project):
    root, slug = project
    result = call_tool(root, "tasks.create", {
        "slug": slug, "title": "Created via MCP", "priority": "P1",
    })
    assert "id" in result
    assert result["todo"]["title"] == "Created via MCP"


# --------------------------------------------------------------------------------------
# claim / release / handoff with the post-Codex semantics
# --------------------------------------------------------------------------------------

def test_tasks_claim_happy_path(project):
    root, slug = project
    result = call_tool(root, "tasks.claim", {
        "slug": slug, "id": "task-one", "actor": "alice",
    })
    assert result["claimed_by"] == "alice"
    assert "lease_until" in result


def test_tasks_claim_collision_returns_already_claimed(project):
    root, slug = project
    call_tool(root, "tasks.claim", {"slug": slug, "id": "task-one", "actor": "alice"})
    result = call_tool(root, "tasks.claim",
                       {"slug": slug, "id": "task-one", "actor": "bob"})
    assert "error" in result
    assert result["error"]["code"] == "already_claimed"
    assert result["error"]["details"]["claimed_by"] == "alice"


def test_tasks_handoff_unclaimed_delegation(project):
    """Issue 4 amendment: handoff with no holder = delegation. Should succeed via MCP."""
    root, slug = project
    result = call_tool(root, "tasks.handoff", {
        "slug": slug, "id": "task-one", "actor": "orchestrator", "to": "codex",
    })
    assert "error" not in result
    assert result["claimed_by"] == "codex"


def test_tasks_handoff_third_party_blocked(project):
    """Issue 4 amendment: handoff by non-holder when another holds = error."""
    root, slug = project
    call_tool(root, "tasks.claim", {"slug": slug, "id": "task-one", "actor": "alice"})
    result = call_tool(root, "tasks.handoff", {
        "slug": slug, "id": "task-one", "actor": "orchestrator", "to": "bob",
    })
    assert result["error"]["code"] == "task_held_by_other_actor"
    assert result["error"]["details"]["claimed_by"] == "alice"


def test_tasks_release_non_holder_returns_error(project):
    root, slug = project
    call_tool(root, "tasks.claim", {"slug": slug, "id": "task-one", "actor": "alice"})
    result = call_tool(root, "tasks.release",
                       {"slug": slug, "id": "task-one", "actor": "bob"})
    assert result["error"]["code"] == "not_claimed_by_actor"


# --------------------------------------------------------------------------------------
# State transitions
# --------------------------------------------------------------------------------------

def test_tasks_done(project):
    root, slug = project
    result = call_tool(root, "tasks.done", {"slug": slug, "id": "task-one"})
    assert result["status"] == "done"


def test_tasks_drop_with_reason(project):
    root, slug = project
    result = call_tool(root, "tasks.drop", {
        "slug": slug, "id": "task-one", "reason": "out of scope",
    })
    assert result["status"] == "wont"
    assert result["wont_reason"] == "out of scope"


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------

def test_tasks_list_unknown_slug(root):
    result = call_tool(root, "tasks.list", {"slug": "nope"})
    assert result["error"]["code"] == "unknown_slug"


def test_tasks_create_duplicate_id(project):
    root, slug = project
    # task-one already exists from the fixture
    result = call_tool(root, "tasks.create", {
        "slug": slug, "title": "Task one", "priority": "P1",
    })
    assert result["error"]["code"] == "duplicate_id"
