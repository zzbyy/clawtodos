"""
Real CLI lifecycle smoke test for clawtodos.

Run: pytest test/python/

Uses tmp_path for full isolation from the user's ~/.todos store.
Exercises the packaged `todos` CLI as a subprocess. Asserts on JSON output
where possible (more stable than text rendering).

This is the regression net the v3.1 refactor leans on. Until v3.1 is built,
it also documents what today's CLI does behaviorally.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


TODOS_BIN = shutil.which("todos") or os.path.expanduser("~/Library/Python/3.9/bin/todos")


def run(*args, root: Path, expect_code: int | None = 0) -> subprocess.CompletedProcess:
    """Run `todos --root <root> <args>`. --root MUST come before the subcommand."""
    cmd = [TODOS_BIN, "--root", str(root), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if expect_code is not None:
        assert result.returncode == expect_code, (
            f"expected exit {expect_code}, got {result.returncode}\n"
            f"cmd: {' '.join(cmd)}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Initialize a fresh ~/.todos root in tmp_path."""
    todos_root = tmp_path / "todos"
    run("init", root=todos_root)
    assert (todos_root / "registry.yaml").exists()
    return todos_root


@pytest.fixture
def project(root: Path, tmp_path: Path) -> Path:
    """Register a project pointing at a fake repo."""
    fake_repo = tmp_path / "fake-repo"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    run("add", str(fake_repo), "--no-ingest", root=root)
    return fake_repo


# ---------- init ----------

def test_init_creates_registry_and_readme(tmp_path: Path):
    todos_root = tmp_path / "todos"
    r = run("init", root=todos_root)
    assert "initialized" in r.stdout
    assert (todos_root / "registry.yaml").exists()
    assert (todos_root / "README.md").exists()
    assert (todos_root / "snapshots").is_dir()


def test_init_is_idempotent(tmp_path: Path):
    todos_root = tmp_path / "todos"
    run("init", root=todos_root)
    # Running init twice should not error
    run("init", root=todos_root)


# ---------- add (register project) ----------

def test_add_registers_project(root: Path, tmp_path: Path):
    fake_repo = tmp_path / "myapp"
    fake_repo.mkdir()
    (fake_repo / ".git").mkdir()
    r = run("add", str(fake_repo), "--no-ingest", root=root)
    assert "registered" in r.stdout
    assert (root / "myapp" / "TODOS.md").exists()


def test_add_pseudo_project(root: Path):
    r = run("add", "personal/health", "--type", "program", "--no-ingest", root=root)
    assert "registered" in r.stdout


def test_add_duplicate_slug_errors(root: Path, project: Path):
    slug = project.name
    fake_repo2 = project.parent / "another"
    fake_repo2.mkdir()
    (fake_repo2 / ".git").mkdir()
    # Same slug (default = dirname) — but different path
    r = run("add", str(fake_repo2), "--slug", slug, root=root, expect_code=1)
    assert "already registered" in r.stderr


# ---------- new (open todo) ----------

def test_new_creates_open_todo(root: Path, project: Path):
    slug = project.name
    r = run("new", slug, "Fix auth bug", "--priority", "P1", "--effort", "S",
            "--agent", "claude-code", root=root)
    assert "added" in r.stdout
    assert "status=open" in r.stdout

    # Verify via JSON
    r2 = run("list", "--slug", slug, "--json", root=root)
    data = json.loads(r2.stdout)
    todos = data["projects"][0]["todos"]
    assert len(todos) == 1
    assert todos[0]["title"] == "Fix auth bug"
    assert todos[0]["status"] == "open"
    assert todos[0]["priority"] == "P1"
    assert todos[0]["agent"] == "claude-code"


def test_new_with_body(root: Path, project: Path):
    slug = project.name
    run("new", slug, "Refactor login", "--body", "Long-form context here", root=root)
    r = run("list", "--slug", slug, "--json", root=root)
    data = json.loads(r.stdout)
    assert "Long-form context" in data["projects"][0]["todos"][0]["body"]


# ---------- propose (pending todo, autonomous path) ----------

def test_propose_creates_pending_todo(root: Path, project: Path):
    slug = project.name
    r = run("propose", slug, "Maybe do this", "--agent", "codex", root=root)
    assert "status=pending" in r.stdout

    # Active list should NOT show pending
    r2 = run("list", "--slug", slug, "--json", root=root)
    data = json.loads(r2.stdout)
    assert data["projects"][0]["todos"] == []
    # Pending count should be 1
    assert data["projects"][0]["counts"]["pending"] == 1


# ---------- list filters ----------

def test_list_default_shows_active(root: Path, project: Path):
    slug = project.name
    run("new", slug, "Active task", root=root)
    run("propose", slug, "Pending task", "--agent", "codex", root=root)

    r = run("list", "--slug", slug, "--json", root=root)
    data = json.loads(r.stdout)
    titles = [t["title"] for t in data["projects"][0]["todos"]]
    assert "Active task" in titles
    assert "Pending task" not in titles


def test_list_state_pending(root: Path, project: Path):
    slug = project.name
    run("propose", slug, "Pending task", "--agent", "codex", root=root)

    r = run("list", "--slug", slug, "--state", "pending", "--json", root=root)
    data = json.loads(r.stdout)
    titles = [t["title"] for t in data["projects"][0]["todos"]]
    assert "Pending task" in titles


def test_list_empty_with_pending_emits_nudge(root: Path, project: Path):
    slug = project.name
    run("propose", slug, "Pending only", "--agent", "codex", root=root)

    r = run("list", "--slug", slug, root=root)
    # Active is empty → output mentions empty + nudges about pending
    assert "(empty)" in r.stdout
    assert "pending" in r.stdout.lower()


def test_list_json_schema(root: Path, project: Path):
    r = run("list", "--json", root=root)
    data = json.loads(r.stdout)
    assert data["schema"] == "todo-contract/v3"
    assert "counts" in data
    assert isinstance(data["projects"], list)


# ---------- state transitions ----------

def test_approve_pending_to_open(root: Path, project: Path):
    slug = project.name
    run("propose", slug, "Maybe do this", "--agent", "codex", root=root)

    # Get the id from JSON
    r = run("list", "--slug", slug, "--state", "pending", "--json", root=root)
    todo_id = json.loads(r.stdout)["projects"][0]["todos"][0]["slug"]

    r2 = run("approve", slug, todo_id, root=root)
    assert "pending -> open" in r2.stdout


def test_start_open_to_in_progress(root: Path, project: Path):
    slug = project.name
    run("new", slug, "Active task", root=root)
    r = run("list", "--slug", slug, "--json", root=root)
    todo_id = json.loads(r.stdout)["projects"][0]["todos"][0]["slug"]

    run("start", slug, todo_id, root=root)
    r2 = run("list", "--slug", slug, "--json", root=root)
    assert json.loads(r2.stdout)["projects"][0]["todos"][0]["status"] == "in-progress"


def test_done(root: Path, project: Path):
    slug = project.name
    run("new", slug, "Active task", root=root)
    todo_id = json.loads(run("list", "--slug", slug, "--json", root=root).stdout)[
        "projects"][0]["todos"][0]["slug"]

    run("done", slug, todo_id, root=root)
    r = run("list", "--slug", slug, "--state", "done", "--json", root=root)
    assert json.loads(r.stdout)["projects"][0]["todos"][0]["status"] == "done"


def test_drop_with_reason(root: Path, project: Path):
    slug = project.name
    run("new", slug, "Bad idea", root=root)
    todo_id = json.loads(run("list", "--slug", slug, "--json", root=root).stdout)[
        "projects"][0]["todos"][0]["slug"]

    run("drop", slug, todo_id, "--reason", "out of scope", root=root)
    r = run("list", "--slug", slug, "--state", "wont", "--json", root=root)
    todo = json.loads(r.stdout)["projects"][0]["todos"][0]
    assert todo["status"] == "wont"
    assert todo["wont_reason"] == "out of scope"


def test_defer_hides_from_active_until_date(root: Path, project: Path):
    slug = project.name
    run("new", slug, "Future task", root=root)
    todo_id = json.loads(run("list", "--slug", slug, "--json", root=root).stdout)[
        "projects"][0]["todos"][0]["slug"]

    # Defer to far future
    run("defer", slug, todo_id, "--until", "2099-12-31", root=root)

    # Should be hidden from active
    r = run("list", "--slug", slug, "--json", root=root)
    assert json.loads(r.stdout)["projects"][0]["todos"] == []


# ---------- snapshot, index, doctor ----------

def test_snapshot_writes_iso_week_file(root: Path, project: Path):
    run("new", project.name, "Some task", root=root)
    r = run("snapshot", root=root)
    assert "wrote snapshot" in r.stdout
    snaps = list((root / "snapshots").glob("*.json"))
    assert len(snaps) == 1
    payload = json.loads(snaps[0].read_text())
    assert payload["schema"] == "todo-contract/v3"
    assert payload["counts"]["total"] >= 1


def test_index_writes_index_md(root: Path, project: Path):
    run("new", project.name, "Some task", "--priority", "P1", root=root)
    r = run("index", root=root)
    assert "wrote" in r.stdout
    idx = (root / "INDEX.md").read_text()
    assert "INDEX" in idx
    assert "P1" in idx


def test_doctor_clean_root(root: Path, project: Path):
    r = run("doctor", root=root)
    assert "ok" in r.stdout
