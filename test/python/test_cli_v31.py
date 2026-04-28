"""
End-to-end CLI tests for v3.1 surface (claim/release/handoff/render + bootstrap).

Exercises the packaged `todos` binary as a subprocess. Uses tmp_path for
isolation. These tests document and lock in the v3.1 behavior amendments
from plan-eng-review (Issue 4 handoff semantics, Issue 2 crash recovery,
Codex T2 disambiguation, Codex F2 lock-through-commit).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


TODOS_BIN = shutil.which("todos") or os.path.expanduser("~/Library/Python/3.9/bin/todos")


def run(*args, root: Path, expect_code: int | None = 0,
        env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run `todos --root <root> <args>`."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    cmd = [TODOS_BIN, "--root", str(root), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if expect_code is not None:
        assert result.returncode == expect_code, (
            f"expected exit {expect_code}, got {result.returncode}\n"
            f"cmd: {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


@pytest.fixture
def root(tmp_path: Path) -> Path:
    todos_root = tmp_path / "todos"
    run("init", root=todos_root)
    return todos_root


@pytest.fixture
def project_with_task(root: Path, tmp_path: Path) -> tuple[Path, str, str]:
    """Registered project with one open task. Returns (root, slug, todo_id)."""
    fake_repo = tmp_path / "myapp"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    run("add", str(fake_repo), "--no-ingest", root=root)
    run("new", "myapp", "Task one", "--priority", "P1", "--agent", "claude-code",
        root=root)
    return root, "myapp", "task-one"


# --------------------------------------------------------------------------------------
# Bootstrap on first mutation
# --------------------------------------------------------------------------------------

def test_first_mutation_auto_bootstraps(root: Path, tmp_path: Path):
    fake_repo = tmp_path / "myapp"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    run("add", str(fake_repo), "--no-ingest", root=root)
    # No EVENTS.ndjson yet
    events_file = root / "myapp" / "EVENTS.ndjson"
    assert not events_file.exists()
    # First mutation triggers bootstrap
    run("new", "myapp", "First task", root=root)
    assert events_file.exists()
    # Should have at least the create event + render event
    lines = events_file.read_text().strip().split("\n")
    assert len(lines) >= 2
    events = [json.loads(l) for l in lines]
    assert events[-1]["event"] == "render"
    assert any(e["event"] == "create" for e in events)


# --------------------------------------------------------------------------------------
# claim / release / handoff CLI
# --------------------------------------------------------------------------------------

def test_cli_claim_happy_path(project_with_task):
    root, slug, todo_id = project_with_task
    r = run("claim", slug, todo_id, "--actor", "alice", root=root)
    assert "claimed" in r.stdout
    assert "alice" in r.stdout

    # Verify via list --json
    r2 = run("list", "--slug", slug, "--json", root=root)
    todo = json.loads(r2.stdout)["projects"][0]["todos"][0]
    # claimed_by appears in the rendered Todo's body via to_md, but list --json
    # surfaces fields through _todo_to_dict — check the markdown directly.
    todos_md = (root / slug / "TODOS.md").read_text()
    assert "**claimed_by:** alice" in todos_md
    assert "**lease_until:**" in todos_md


def test_cli_claim_collision_returns_error(project_with_task):
    root, slug, todo_id = project_with_task
    run("claim", slug, todo_id, "--actor", "alice", root=root)
    r = run("claim", slug, todo_id, "--actor", "bob", root=root, expect_code=1)
    assert "already_claimed" in r.stderr
    assert "alice" in r.stderr


def test_cli_release_by_holder(project_with_task):
    root, slug, todo_id = project_with_task
    run("claim", slug, todo_id, "--actor", "alice", root=root)
    run("release", slug, todo_id, "--actor", "alice", root=root)
    md = (root / slug / "TODOS.md").read_text()
    assert "**claimed_by:**" not in md


def test_cli_release_by_non_holder_errors(project_with_task):
    root, slug, todo_id = project_with_task
    run("claim", slug, todo_id, "--actor", "alice", root=root)
    r = run("release", slug, todo_id, "--actor", "bob", root=root, expect_code=1)
    assert "not_claimed_by_actor" in r.stderr


def test_cli_handoff_unclaimed_delegation(project_with_task):
    """Issue 4 amendment: handoff with no current holder = delegation, succeeds."""
    root, slug, todo_id = project_with_task
    r = run("handoff", slug, todo_id, "--actor", "orchestrator", "--to", "codex",
            root=root)
    assert "handoff" in r.stdout
    assert "codex" in r.stdout
    md = (root / slug / "TODOS.md").read_text()
    assert "**claimed_by:** codex" in md
    assert "**handoff_to:** codex" in md


def test_cli_handoff_third_party_blocked(project_with_task):
    """Issue 4 amendment: handoff by non-holder when another holds = error."""
    root, slug, todo_id = project_with_task
    run("claim", slug, todo_id, "--actor", "alice", root=root)
    r = run("handoff", slug, todo_id, "--actor", "orchestrator", "--to", "bob",
            root=root, expect_code=1)
    assert "task_held_by_other_actor" in r.stderr


def test_cli_handoff_from_holder(project_with_task):
    root, slug, todo_id = project_with_task
    run("claim", slug, todo_id, "--actor", "alice", root=root)
    run("handoff", slug, todo_id, "--actor", "alice", "--to", "bob", root=root)
    md = (root / slug / "TODOS.md").read_text()
    assert "**claimed_by:** bob" in md


# --------------------------------------------------------------------------------------
# render command + hand-edit detect-and-block
# --------------------------------------------------------------------------------------

def test_cli_render_recovers_from_hand_edit(project_with_task):
    root, slug, todo_id = project_with_task
    md_path = root / slug / "TODOS.md"
    original = md_path.read_text()

    # Hand-edit
    md_path.write_text(original + "\n# stray edit\n")

    # Next mutation should error with hand-edit collision
    r = run("done", slug, todo_id, root=root, expect_code=1)
    assert "TODOS.md has unrecorded edits" in r.stderr or "HandEditCollision" in r.stderr

    # `todos render` discards the edit and re-syncs
    run("render", slug, "--actor", "human", root=root)
    md_after = md_path.read_text()
    assert "stray edit" not in md_after

    # Now the mutation succeeds
    run("done", slug, todo_id, root=root)


# --------------------------------------------------------------------------------------
# Done + drop preserve their existing CLI surface (regression)
# --------------------------------------------------------------------------------------

def test_legacy_done_routes_through_events(project_with_task):
    """Done still produces 'task-id: open -> done' on stdout AND writes a `done` event."""
    root, slug, todo_id = project_with_task
    r = run("done", slug, todo_id, root=root)
    assert "open -> done" in r.stdout
    # Verify event log
    lines = (root / slug / "EVENTS.ndjson").read_text().strip().split("\n")
    events = [json.loads(l) for l in lines]
    assert any(e["event"] == "done" for e in events)


def test_legacy_drop_records_reason(project_with_task):
    root, slug, todo_id = project_with_task
    run("drop", slug, todo_id, "--reason", "out of scope", root=root)
    md = (root / slug / "TODOS.md").read_text()
    assert "**status:** wont" in md
    assert "**wont_reason:** out of scope" in md
