"""
Unit tests for clawtodos.events — the v3.1 event log + mutation pipeline.

Covers:
- append_event / read_events round-trip
- render_to_markdown determinism + canonical field order
- mutate() pipeline: full happy path, hand-edit detection, crash recovery
- bootstrap_from_v30: idempotency, duplicate-slug disambiguation
- claim / release / handoff: all the post-Codex-amendment semantics
- Schema validation: corrupt JSON, unknown v, missing required keys
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pytest

from clawtodos.core import Context, Todo, parse_todo_file, todos_path
from clawtodos.events import (
    AlreadyClaimed,
    CorruptEventLog,
    DEFAULT_LEASE_SECONDS,
    HandEditCollision,
    NotClaimedByActor,
    SchemaVersionUnsupported,
    TaskHeldByOtherActor,
    UnknownTodo,
    append_event,
    bootstrap_from_v30,
    claim,
    events_path,
    fold_events,
    handoff,
    is_bootstrapped,
    mutate,
    read_events,
    release,
    render_hash,
    render_state_to_markdown,
    render_to_markdown,
)


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------

@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    """A Context pointing at a fresh tmp dir. No git init; commits no-op."""
    root = tmp_path / "todos"
    root.mkdir()
    # Minimal registry so other tests can use slugs if they want
    (root / "registry.yaml").write_text(
        "schema: todo-contract/v3\nprojects:\n", encoding="utf-8"
    )
    return Context(root=root)


def _create_evt(slug: str, todo_slug: str, title: str, **fields) -> dict:
    full_id = f"{slug}/{todo_slug}"
    base = {
        "v": 1,
        "ts": "2026-04-28T20:00:00Z",
        "actor": "test",
        "event": "create",
        "id": full_id,
        "fields": {"title": title, **fields},
    }
    return base


# --------------------------------------------------------------------------------------
# Append / read
# --------------------------------------------------------------------------------------

def test_read_events_empty_log_returns_empty(ctx: Context):
    assert read_events(ctx, "myproj") == []


def test_append_then_read_round_trip(ctx: Context):
    (ctx.root / "myproj").mkdir()
    evt = _create_evt("myproj", "first", "First task", priority="P1", status="open")
    append_event(ctx, "myproj", evt)
    events = read_events(ctx, "myproj")
    assert len(events) == 1
    assert events[0]["event"] == "create"
    assert events[0]["fields"]["title"] == "First task"


def test_append_is_monotonic(ctx: Context):
    (ctx.root / "myproj").mkdir()
    e1 = _create_evt("myproj", "a", "A")
    e2 = _create_evt("myproj", "b", "B")
    append_event(ctx, "myproj", e1)
    size1 = events_path(ctx, "myproj").stat().st_size
    append_event(ctx, "myproj", e2)
    size2 = events_path(ctx, "myproj").stat().st_size
    assert size2 > size1


# --------------------------------------------------------------------------------------
# Schema validation
# --------------------------------------------------------------------------------------

def test_corrupt_json_line_fails_closed(ctx: Context):
    (ctx.root / "myproj").mkdir()
    p = events_path(ctx, "myproj")
    p.write_text('{"v":1,"ts":"x","actor":"a","event":"create","id":"x/y"}\nNOT JSON\n',
                 encoding="utf-8")
    with pytest.raises(CorruptEventLog) as exc:
        read_events(ctx, "myproj")
    assert "line 2" in str(exc.value)


def test_unknown_v_fails_closed(ctx: Context):
    (ctx.root / "myproj").mkdir()
    p = events_path(ctx, "myproj")
    p.write_text('{"v":99,"ts":"x","actor":"a","event":"create","id":"x/y"}\n',
                 encoding="utf-8")
    with pytest.raises(SchemaVersionUnsupported):
        read_events(ctx, "myproj")


def test_missing_required_key_fails_closed(ctx: Context):
    (ctx.root / "myproj").mkdir()
    p = events_path(ctx, "myproj")
    # Missing 'actor'
    p.write_text('{"v":1,"ts":"x","event":"create","id":"x/y"}\n', encoding="utf-8")
    with pytest.raises(CorruptEventLog) as exc:
        read_events(ctx, "myproj")
    assert "actor" in str(exc.value)


def test_unknown_event_type_warns_but_does_not_crash(ctx: Context, capsys):
    """Per spec: unknown event types are no-ops with a warning."""
    (ctx.root / "myproj").mkdir()
    p = events_path(ctx, "myproj")
    p.write_text('{"v":1,"ts":"x","actor":"a","event":"future_thing","id":"x/y"}\n',
                 encoding="utf-8")
    events = read_events(ctx, "myproj")
    state = fold_events(events)
    err = capsys.readouterr().err
    assert "future_thing" in err
    # No state added
    assert state == {}


# --------------------------------------------------------------------------------------
# Render — folding events into Todo state
# --------------------------------------------------------------------------------------

def test_render_empty_log_produces_frontmatter_only(ctx: Context):
    (ctx.root / "myproj").mkdir()
    text = render_to_markdown(ctx, "myproj")
    assert "schema: todo-contract/v3" in text
    assert "project: myproj" in text
    assert "###" not in text  # no todos


def test_render_create_then_done(ctx: Context):
    (ctx.root / "myproj").mkdir()
    create = _create_evt("myproj", "fix-bug", "Fix bug", priority="P1", status="open")
    done = {
        "v": 1, "ts": "2026-04-28T21:00:00Z", "actor": "test", "event": "done",
        "id": "myproj/fix-bug",
    }
    append_event(ctx, "myproj", create)
    append_event(ctx, "myproj", done)
    text = render_to_markdown(ctx, "myproj")
    assert "### Fix bug" in text
    assert "**status:** done" in text


def test_render_is_deterministic(ctx: Context):
    """Rendering the same log twice produces byte-identical output."""
    (ctx.root / "myproj").mkdir()
    append_event(ctx, "myproj", _create_evt("myproj", "a", "A", priority="P1"))
    append_event(ctx, "myproj", _create_evt("myproj", "b", "B", priority="P2"))
    t1 = render_to_markdown(ctx, "myproj")
    t2 = render_to_markdown(ctx, "myproj")
    assert t1 == t2


def test_render_canonical_field_order_includes_v31_fields(ctx: Context):
    """claimed_by, lease_until, handoff_to land in canonical position."""
    state = {
        "p/x": Todo(
            title="X",
            fields={
                "wont_reason": "z",  # would land last in v3.0 unknown-fields fallback
                "claimed_by": "alice",  # v3.1 field
                "status": "in-progress",
                "priority": "P1",
                "lease_until": "2099-01-01T00:00:00Z",
            },
        ),
    }
    text = render_state_to_markdown("p", state)
    # Canonical order: status, priority, ..., agent, claimed_by, lease_until, handoff_to,
    # created, updated, tags, deferred, wont_reason
    status_pos = text.index("**status:**")
    claimed_pos = text.index("**claimed_by:**")
    lease_pos = text.index("**lease_until:**")
    wont_pos = text.index("**wont_reason:**")
    assert status_pos < claimed_pos < lease_pos < wont_pos


# --------------------------------------------------------------------------------------
# mutate() pipeline
# --------------------------------------------------------------------------------------

def test_mutate_writes_event_and_renders_and_records_hash(ctx: Context):
    (ctx.root / "myproj").mkdir()
    create = _create_evt("myproj", "task-a", "Task A", priority="P1", status="open")
    mutate(ctx, "myproj", [create])
    events = read_events(ctx, "myproj")
    # Two events: the create + the trailing render
    assert len(events) == 2
    assert events[-1]["event"] == "render"
    # The render hash should match the file on disk
    on_disk = todos_path(ctx, "myproj").read_text(encoding="utf-8")
    assert events[-1]["hash"] == render_hash(on_disk)


def test_mutate_detects_hand_edit_collision(ctx: Context):
    (ctx.root / "myproj").mkdir()
    mutate(ctx, "myproj", [_create_evt("myproj", "a", "A", status="open")])
    # Hand-edit TODOS.md
    p = todos_path(ctx, "myproj")
    text = p.read_text() + "\n# malicious edit\n"
    p.write_text(text)
    # Next mutation should raise
    with pytest.raises(HandEditCollision):
        mutate(ctx, "myproj", [_create_evt("myproj", "b", "B", status="open")])


def test_mutate_recovers_from_interrupted_previous_run(ctx: Context):
    """Issue 2: if last event is NOT a render event, treat as crash and re-render."""
    (ctx.root / "myproj").mkdir()
    mutate(ctx, "myproj", [_create_evt("myproj", "a", "A", status="open")])
    # Simulate crash: append a `done` event manually but no render event
    crash_evt = {
        "v": 1, "ts": "2026-04-28T22:00:00Z", "actor": "crashed",
        "event": "done", "id": "myproj/a",
    }
    append_event(ctx, "myproj", crash_evt)
    # Now TODOS.md is stale (still shows status=open) and last event is NOT render.
    # Next mutate() should auto-recover, not raise.
    mutate(ctx, "myproj", [_create_evt("myproj", "b", "B", status="open")])
    # Verify state is consistent
    text = todos_path(ctx, "myproj").read_text()
    assert "**status:** done" in text  # the crash-event got picked up
    assert "### B" in text


# --------------------------------------------------------------------------------------
# Bootstrap migration (v3.0 -> v3.1)
# --------------------------------------------------------------------------------------

def test_bootstrap_no_todos_md_no_events_yields_empty(ctx: Context):
    (ctx.root / "myproj").mkdir()
    report = bootstrap_from_v30(ctx, "myproj")
    assert report == {"created": 0, "disambiguated": []}
    assert is_bootstrapped(ctx, "myproj")


def test_bootstrap_idempotent(ctx: Context):
    (ctx.root / "myproj").mkdir()
    todos_path(ctx, "myproj").write_text(
        "---\nschema: todo-contract/v3\nproject: myproj\n---\n\n"
        "### One thing\n- **status:** open\n- **priority:** P1\n\n---\n"
    )
    r1 = bootstrap_from_v30(ctx, "myproj")
    assert r1["created"] == 1
    # Second call is a no-op
    r2 = bootstrap_from_v30(ctx, "myproj")
    assert r2["created"] == 0


def test_bootstrap_creates_events_for_existing_todos(ctx: Context):
    (ctx.root / "myproj").mkdir()
    todos_path(ctx, "myproj").write_text(
        "---\nschema: todo-contract/v3\nproject: myproj\n---\n\n"
        "### First\n- **status:** open\n- **priority:** P1\n\n---\n\n"
        "### Second\n- **status:** in-progress\n- **priority:** P2\n\n---\n"
    )
    report = bootstrap_from_v30(ctx, "myproj")
    assert report["created"] == 2
    events = read_events(ctx, "myproj")
    create_events = [e for e in events if e["event"] == "create"]
    assert len(create_events) == 2
    assert create_events[0]["actor"] == "ingest"
    assert create_events[0]["fields"]["title"] in ("First", "Second")


def test_bootstrap_disambiguates_duplicate_slugs(ctx: Context):
    """Codex T2 fix: two todos with same title get auto-disambiguated."""
    (ctx.root / "myproj").mkdir()
    todos_path(ctx, "myproj").write_text(
        "---\nschema: todo-contract/v3\nproject: myproj\n---\n\n"
        "### Fix auth\n- **status:** open\n\n---\n\n"
        "### Fix auth\n- **status:** open\n\n---\n"
    )
    report = bootstrap_from_v30(ctx, "myproj")
    assert report["created"] == 2
    assert ("fix-auth", "fix-auth-2") in report["disambiguated"]
    events = read_events(ctx, "myproj")
    ids = [e["id"] for e in events if e["event"] == "create"]
    assert "myproj/fix-auth" in ids
    assert "myproj/fix-auth-2" in ids


# --------------------------------------------------------------------------------------
# Claim / release / handoff
# --------------------------------------------------------------------------------------

@pytest.fixture
def slug_with_task(ctx: Context) -> tuple[Context, str, str]:
    """A bootstrapped project with one open task."""
    slug = "coord"
    (ctx.root / slug).mkdir()
    mutate(ctx, slug, [_create_evt(slug, "task-1", "Task one", status="open", priority="P1")])
    return ctx, slug, "task-1"


def test_claim_happy_path(slug_with_task):
    ctx, slug, todo_slug = slug_with_task
    result = claim(ctx, slug, todo_slug, actor="alice")
    assert result["claimed_by"] == "alice"
    assert "lease_until" in result
    # State reflects the claim
    state = fold_events(read_events(ctx, slug))
    assert state[f"{slug}/{todo_slug}"].fields["claimed_by"] == "alice"


def test_claim_already_claimed_by_other_raises(slug_with_task):
    ctx, slug, todo_slug = slug_with_task
    claim(ctx, slug, todo_slug, actor="alice")
    with pytest.raises(AlreadyClaimed) as exc:
        claim(ctx, slug, todo_slug, actor="bob")
    assert exc.value.claimed_by == "alice"


def test_claim_self_refresh_succeeds(slug_with_task):
    """Conformance #22 (Issue 8): actor claims a task it already holds → succeeds."""
    ctx, slug, todo_slug = slug_with_task
    r1 = claim(ctx, slug, todo_slug, actor="alice", lease_seconds=60)
    time.sleep(0.05)  # ensure timestamp differs
    r2 = claim(ctx, slug, todo_slug, actor="alice", lease_seconds=120)
    assert r2["claimed_by"] == "alice"
    assert r2["lease_until"] >= r1["lease_until"]


def test_claim_after_lease_expired_succeeds(slug_with_task):
    ctx, slug, todo_slug = slug_with_task
    # Issue a claim that's already expired (lease ts in the past)
    full_id = f"{slug}/{todo_slug}"
    expired_evt = {
        "v": 1, "ts": "2020-01-01T00:00:00Z", "actor": "alice",
        "event": "claim", "id": full_id,
        "lease_until": "2020-01-01T01:00:00Z",  # in the past
    }
    mutate(ctx, slug, [expired_evt])
    # bob can now re-claim
    result = claim(ctx, slug, todo_slug, actor="bob")
    assert result["claimed_by"] == "bob"


def test_release_by_holder(slug_with_task):
    ctx, slug, todo_slug = slug_with_task
    claim(ctx, slug, todo_slug, actor="alice")
    release(ctx, slug, todo_slug, actor="alice")
    state = fold_events(read_events(ctx, slug))
    assert "claimed_by" not in state[f"{slug}/{todo_slug}"].fields


def test_release_by_non_holder_raises(slug_with_task):
    ctx, slug, todo_slug = slug_with_task
    claim(ctx, slug, todo_slug, actor="alice")
    with pytest.raises(NotClaimedByActor):
        release(ctx, slug, todo_slug, actor="bob")


def test_handoff_from_holder(slug_with_task):
    ctx, slug, todo_slug = slug_with_task
    claim(ctx, slug, todo_slug, actor="alice")
    result = handoff(ctx, slug, todo_slug, actor="alice", to="bob")
    assert result["claimed_by"] == "bob"
    state = fold_events(read_events(ctx, slug))
    assert state[f"{slug}/{todo_slug}"].fields["claimed_by"] == "bob"
    assert state[f"{slug}/{todo_slug}"].fields["handoff_to"] == "bob"


def test_handoff_unclaimed_succeeds(slug_with_task):
    """Issue 4: handoff with no current holder = delegation. Should succeed."""
    ctx, slug, todo_slug = slug_with_task
    result = handoff(ctx, slug, todo_slug, actor="orchestrator", to="codex")
    assert result["claimed_by"] == "codex"


def test_handoff_while_other_holds_raises(slug_with_task):
    """Issue 4: handoff by non-holder when another holds = TaskHeldByOtherActor."""
    ctx, slug, todo_slug = slug_with_task
    claim(ctx, slug, todo_slug, actor="alice")
    with pytest.raises(TaskHeldByOtherActor) as exc:
        handoff(ctx, slug, todo_slug, actor="orchestrator", to="bob")
    assert exc.value.claimed_by == "alice"


def test_unknown_todo_raises(ctx: Context):
    (ctx.root / "myproj").mkdir()
    with pytest.raises(UnknownTodo):
        claim(ctx, "myproj", "nonexistent", actor="alice")
    with pytest.raises(UnknownTodo):
        release(ctx, "myproj", "nonexistent", actor="alice")
    with pytest.raises(UnknownTodo):
        handoff(ctx, "myproj", "nonexistent", actor="alice", to="bob")
