"""
clawtodos.events — append-only EVENTS.ndjson + the mutation pipeline.

Layout per project at <root>/<slug>/:
    TODOS.md       — derived view (humans read this)
    EVENTS.ndjson  — append-only event log (the source of truth)
    .lock          — file lock (filelock-backed; ignored in git)

Pipeline (per todo-contract/v3.1):
    acquire lock
    -> check render hash (with crash recovery from interrupted previous mutation)
    -> append event(s) to EVENTS.ndjson
    -> re-render TODOS.md from the event log
    -> append `render` event with new hash
    -> commit (with retry on .git/index.lock contention)
    -> release lock

Defined event types (v=1):
    create, update, claim, release, handoff, start, done, drop, defer, render

Errors are surfaced as exceptions (UnknownProject, UnknownTodo, AlreadyClaimed,
NotClaimedByActor, TaskHeldByOtherActor, BadTransition, HandEditCollision,
SchemaVersionUnsupported, CorruptEventLog).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from filelock import FileLock, Timeout

from .core import (
    ACTIVE_STATES,
    ALL_STATES,
    Context,
    SCHEMA,
    Todo,
    TodoFile,
    _blank_file,
    parse_todo_file,
    project_dir,
    todos_path,
)

# --------------------------------------------------------------------------------------
# Schema constants
# --------------------------------------------------------------------------------------

EVENT_SCHEMA_VERSION = 1
DEFINED_EVENT_TYPES = frozenset({
    "create", "update", "claim", "release", "handoff",
    "start", "done", "drop", "defer", "render",
})

# Canonical field order for to_md() in v3.1. Includes claimed_by/lease_until/handoff_to
# in their semantically grouped position (after agent, before created).
CANONICAL_FIELD_ORDER_V31 = (
    "status", "priority", "effort", "agent",
    "claimed_by", "lease_until", "handoff_to",
    "created", "updated", "tags", "deferred", "wont_reason",
)

DEFAULT_LEASE_SECONDS = 3600       # 1 hour
MAX_LEASE_SECONDS = 86400          # 24 hours
LOCK_TIMEOUT_SECONDS = 10          # how long to wait for the project lock
GIT_COMMIT_RETRY_COUNT = 3
GIT_COMMIT_RETRY_BACKOFF_S = 0.1


# --------------------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------------------

class EventLogError(Exception):
    """Base for events.py errors."""


class UnknownProject(EventLogError):
    pass


class UnknownTodo(EventLogError):
    pass


class AlreadyClaimed(EventLogError):
    """Raised when trying to claim a task that another actor holds with a valid lease."""
    def __init__(self, message: str, claimed_by: str, lease_until: str):
        super().__init__(message)
        self.claimed_by = claimed_by
        self.lease_until = lease_until


class NotClaimedByActor(EventLogError):
    """Raised when an actor tries to release a claim it doesn't hold."""


class TaskHeldByOtherActor(EventLogError):
    """Raised when handoff is attempted while another actor holds the claim
    (and the calling actor is not that holder)."""
    def __init__(self, message: str, claimed_by: str, lease_until: str):
        super().__init__(message)
        self.claimed_by = claimed_by
        self.lease_until = lease_until


class BadTransition(EventLogError):
    """Raised when a state transition is not allowed (e.g., done -> in-progress)."""


class HandEditCollision(EventLogError):
    """Raised when TODOS.md was edited by hand between mutations.

    Distinguished from interrupted-mutation by checking that the last event in
    the log IS a `render` event AND its hash differs from the file on disk.
    """


class SchemaVersionUnsupported(EventLogError):
    """Raised when an event has an unknown `v` value (fail closed per spec)."""


class CorruptEventLog(EventLogError):
    """Raised when EVENTS.ndjson contains a line that does not parse as JSON
    or is missing required keys (fail closed per spec)."""


# --------------------------------------------------------------------------------------
# File layout
# --------------------------------------------------------------------------------------

def events_path(ctx: Context, slug: str) -> Path:
    return project_dir(ctx, slug) / "EVENTS.ndjson"


def lock_path(ctx: Context, slug: str) -> Path:
    return project_dir(ctx, slug) / ".lock"


@contextmanager
def project_lock(ctx: Context, slug: str, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Per-project filelock context manager. Times out cleanly."""
    project_dir(ctx, slug).mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path(ctx, slug)), timeout=timeout)
    with lock:
        yield


# --------------------------------------------------------------------------------------
# Event read / write
# --------------------------------------------------------------------------------------

def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_event_schema(line_no: int, raw: str, evt: dict) -> None:
    """Validate one parsed event against the v3.1 schema rules.

    Raises CorruptEventLog for missing required keys; raises SchemaVersionUnsupported
    for unknown `v` values (fail closed per SPEC).
    """
    for key in ("v", "ts", "actor", "event"):
        if key not in evt:
            raise CorruptEventLog(f"event log line {line_no}: missing required key '{key}'")
    if evt["v"] != EVENT_SCHEMA_VERSION:
        raise SchemaVersionUnsupported(
            f"event log line {line_no}: unsupported schema version v={evt['v']!r}; "
            f"this build understands v={EVENT_SCHEMA_VERSION}"
        )
    # `id` is required for every event type EXCEPT `render` (which is project-scoped).
    if evt["event"] != "render" and "id" not in evt:
        raise CorruptEventLog(
            f"event log line {line_no}: event {evt['event']!r} missing required 'id'"
        )


def read_events(ctx: Context, slug: str) -> list[dict]:
    """Read all events from EVENTS.ndjson. Fail-closed on corrupt JSON or unknown v.

    Returns [] if the log file does not exist.
    """
    p = events_path(ctx, slug)
    if not p.exists():
        return []
    out: list[dict] = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            evt = json.loads(line)
        except json.JSONDecodeError as e:
            raise CorruptEventLog(
                f"event log line {i}: not valid JSON ({e.msg})"
            ) from e
        _validate_event_schema(i, line, evt)
        out.append(evt)
    return out


def append_event(ctx: Context, slug: str, event: dict) -> None:
    """Append one event line to EVENTS.ndjson. Caller MUST hold the project lock."""
    p = events_path(ctx, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


# --------------------------------------------------------------------------------------
# Render — fold events into a Todo state map, write TODOS.md
# --------------------------------------------------------------------------------------

def _ensure_state(state: dict[str, Todo], todo_id: str) -> Todo:
    if todo_id not in state:
        # Create a placeholder; the title isn't known from non-create events.
        state[todo_id] = Todo(title=todo_id.split("/", 1)[-1], fields={}, body="")
    return state[todo_id]


def _apply_event(state: dict[str, Todo], evt: dict) -> None:
    """Apply one event to the state map. `render` events are no-ops (they only
    record metadata). Unknown event types are no-ops with a warning printed."""
    et = evt["event"]
    if et == "render":
        return
    if et not in DEFINED_EVENT_TYPES:
        # Unknown but tolerated per spec: warn, don't crash.
        import sys
        print(f"warning: unknown event type {et!r} in event log; treating as no-op",
              file=sys.stderr)
        return

    todo_id = evt["id"]
    if et == "create":
        # Title is in fields (caller put it there). Pull it out to be the title.
        fields = dict(evt.get("fields", {}))
        title = fields.pop("title", todo_id.split("/", 1)[-1])
        body = evt.get("body", "")
        state[todo_id] = Todo(title=title, fields=fields, body=body)
        return
    if et == "update":
        t = _ensure_state(state, todo_id)
        for k, v in evt.get("fields", {}).items():
            if v is None:
                t.fields.pop(k, None)
            else:
                t.fields[k] = v
        if "body" in evt:
            t.body = evt["body"]
        return
    if et == "claim":
        t = _ensure_state(state, todo_id)
        t.fields["claimed_by"] = evt["actor"]
        t.fields["lease_until"] = evt["lease_until"]
        return
    if et == "release":
        t = _ensure_state(state, todo_id)
        t.fields.pop("claimed_by", None)
        t.fields.pop("lease_until", None)
        return
    if et == "handoff":
        t = _ensure_state(state, todo_id)
        t.fields["handoff_to"] = evt["to"]
        t.fields["claimed_by"] = evt["to"]
        t.fields["lease_until"] = evt["lease_until"]
        return
    if et == "start":
        t = _ensure_state(state, todo_id)
        t.fields["status"] = "in-progress"
        t.fields["updated"] = evt["ts"][:10]
        return
    if et == "done":
        t = _ensure_state(state, todo_id)
        t.fields["status"] = "done"
        t.fields["updated"] = evt["ts"][:10]
        # done releases the claim implicitly
        t.fields.pop("claimed_by", None)
        t.fields.pop("lease_until", None)
        return
    if et == "drop":
        t = _ensure_state(state, todo_id)
        t.fields["status"] = "wont"
        t.fields["updated"] = evt["ts"][:10]
        if "reason" in evt and evt["reason"]:
            t.fields["wont_reason"] = evt["reason"]
        return
    if et == "defer":
        t = _ensure_state(state, todo_id)
        t.fields["deferred"] = evt["until"]
        t.fields["updated"] = evt["ts"][:10]
        return


def fold_events(events: Iterable[dict]) -> dict[str, Todo]:
    """Fold an event stream into the current state map keyed by canonical id."""
    state: dict[str, Todo] = {}
    for evt in events:
        _apply_event(state, evt)
    return state


def _to_md_v31(t: Todo) -> str:
    """Like Todo.to_md() but uses the v3.1 canonical field order."""
    lines = [f"### {t.title}"]
    canonical = set(CANONICAL_FIELD_ORDER_V31)
    for k in CANONICAL_FIELD_ORDER_V31:
        if k in t.fields:
            lines.append(f"- **{k}:** {t.fields[k]}")
    for k, v in t.fields.items():
        if k not in canonical:
            lines.append(f"- **{k}:** {v}")
    if t.body.strip():
        lines.append("")
        lines.append(t.body.strip())
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def render_state_to_markdown(slug: str, state: dict[str, Todo]) -> str:
    """Pure function: serialize a state map to canonical TODOS.md text."""
    out = ["---", f"schema: {SCHEMA}", f"project: {slug}", "---", ""]
    for todo_id in sorted(state.keys()):
        out.append(_to_md_v31(state[todo_id]))
    return "\n".join(out).rstrip() + "\n"


def render_to_markdown(ctx: Context, slug: str) -> str:
    """Read the event log, fold to state, write canonical TODOS.md, return its bytes."""
    state = fold_events(read_events(ctx, slug))
    text = render_state_to_markdown(slug, state)
    todos_path(ctx, slug).write_text(text, encoding="utf-8")
    return text


def render_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Mutate — the 8-step pipeline (post-Codex F2: lock held through commit)
# --------------------------------------------------------------------------------------

def _last_event(events: list[dict]) -> dict | None:
    return events[-1] if events else None


def _hand_edit_check(ctx: Context, slug: str, events: list[dict]) -> None:
    """Detect-and-block per design + Issue 2 (crash recovery).

    Resolution rules:
    - If the on-disk TODOS.md doesn't exist or the log is empty, nothing to check.
    - If the LAST event is `render` and its hash matches the on-disk file, OK.
    - If the LAST event is `render` and the hash differs, raise HandEditCollision.
    - If the LAST event is NOT `render`, the previous mutation crashed mid-pipeline
      (Issue 2). Silently re-render and proceed.
    """
    p = todos_path(ctx, slug)
    last = _last_event(events)
    if not p.exists() or last is None:
        return
    if last.get("event") == "render":
        on_disk = p.read_text(encoding="utf-8")
        if render_hash(on_disk) != last.get("hash"):
            raise HandEditCollision(
                f"TODOS.md has unrecorded edits since the last render. "
                f"Re-render with `todos render` to discard them, or use "
                f"`todos import` to capture them as events. (slug={slug})"
            )
    else:
        # Crash recovery: previous mutation appended events but never wrote a
        # render event. Re-render now from the log to bring TODOS.md back in
        # sync. Subsequent mutate() will write a fresh render event.
        text = render_state_to_markdown(slug, fold_events(events))
        p.write_text(text, encoding="utf-8")


def _git_commit_with_retry(ctx: Context, message: str, *paths: Path) -> None:
    """git add + commit with retry on .git/index.lock contention (Issue 9).

    Best-effort: if all retries fail, prints a warning and continues. The mutation
    has already succeeded on disk; git history is the audit log, but losing one
    commit is not a correctness violation.
    """
    import shutil
    import subprocess
    import sys
    if not (ctx.root / ".git").exists() or not shutil.which("git"):
        return
    rels = [str(p.relative_to(ctx.root)) for p in paths if p.exists()]
    if not rels:
        return
    last_err: str = ""
    for attempt in range(GIT_COMMIT_RETRY_COUNT):
        try:
            subprocess.run(["git", "-C", str(ctx.root), "add", *rels],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(ctx.root), "commit", "-m", message],
                           check=True, capture_output=True)
            return
        except subprocess.CalledProcessError as e:
            err = (e.stdout or b"").decode() + (e.stderr or b"").decode()
            if "nothing to commit" in err:
                return
            last_err = err
            if "index.lock" in err and attempt + 1 < GIT_COMMIT_RETRY_COUNT:
                time.sleep(GIT_COMMIT_RETRY_BACKOFF_S)
                continue
            break
    print(f"warning: git commit failed after {GIT_COMMIT_RETRY_COUNT} attempts: "
          f"{last_err.strip()}", file=sys.stderr)


def mutate(
    ctx: Context,
    slug: str,
    events_to_append: list[dict],
    commit_message: str | None = None,
) -> None:
    """The single mutation pipeline. All 8 steps, atomic with respect to the
    per-project lock.

    Caller constructs the events (with v, ts, actor, event, id, plus event-specific
    fields). This function timestamps `render` events itself.
    """
    if not events_to_append:
        return
    project_dir(ctx, slug).mkdir(parents=True, exist_ok=True)
    todos_md = todos_path(ctx, slug)

    # If TODOS.md doesn't exist yet, write the blank template so hand-edit-check
    # has something to compare against on subsequent calls.
    if not todos_md.exists():
        todos_md.write_text(_blank_file(slug), encoding="utf-8")

    with project_lock(ctx, slug):
        # Step 1: read current log
        events = read_events(ctx, slug)
        # Step 2: hand-edit check (with crash recovery from interrupted run)
        _hand_edit_check(ctx, slug, events)
        # Step 3: append the user's events
        for evt in events_to_append:
            append_event(ctx, slug, evt)
        # Step 4: re-render TODOS.md
        new_text = render_to_markdown(ctx, slug)
        # Step 5: append a render event recording the new hash
        render_evt = {
            "v": EVENT_SCHEMA_VERSION,
            "ts": _now_iso(),
            "actor": events_to_append[-1].get("actor", "system"),
            "event": "render",
            "hash": render_hash(new_text),
        }
        append_event(ctx, slug, render_evt)
        # Step 6: git commit (still inside the lock per Codex F2)
        msg = commit_message or _default_commit_message(slug, events_to_append)
        _git_commit_with_retry(ctx, msg, events_path(ctx, slug), todos_md)


def _default_commit_message(slug: str, events: list[dict]) -> str:
    if len(events) == 1:
        e = events[0]
        return f"{e['event']}: {e.get('id', slug)}"
    return f"batch ({len(events)} events): {slug}"


# --------------------------------------------------------------------------------------
# Bootstrap migration — v3.0 TODOS.md -> v3.1 EVENTS.ndjson
# --------------------------------------------------------------------------------------

def is_bootstrapped(ctx: Context, slug: str) -> bool:
    return events_path(ctx, slug).exists()


def bootstrap_from_v30(ctx: Context, slug: str) -> dict:
    """One-shot migration: read existing TODOS.md, synthesize a `create` event per
    todo (with `actor:"ingest"`), append a `render` event, and re-render.

    Returns a report dict: {created: N, disambiguated: [(orig_slug, new_slug), ...]}.

    Idempotent: if EVENTS.ndjson already exists, returns {created: 0, disambiguated: []}.
    Per Codex T2: duplicate slugs are auto-disambiguated by appending -2, -3, ...
    """
    p = todos_path(ctx, slug)
    report = {"created": 0, "disambiguated": []}
    if is_bootstrapped(ctx, slug):
        return report
    if not p.exists():
        # Nothing to migrate. Touch an empty events file so we don't re-run.
        events_path(ctx, slug).touch()
        return report

    tf = parse_todo_file(p)
    file_mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    seen_slugs: dict[str, int] = {}
    events_to_write: list[dict] = []

    for t in tf.todos:
        base_slug = t.slug
        if base_slug in seen_slugs:
            seen_slugs[base_slug] += 1
            new_slug = f"{base_slug}-{seen_slugs[base_slug]}"
            report["disambiguated"].append((base_slug, new_slug))
            todo_slug = new_slug
        else:
            seen_slugs[base_slug] = 1
            todo_slug = base_slug

        full_id = f"{slug}/{todo_slug}"
        fields = dict(t.fields)
        fields["title"] = t.title  # bootstrap preserves the title via fields["title"]
        events_to_write.append({
            "v": EVENT_SCHEMA_VERSION,
            "ts": file_mtime,
            "actor": "ingest",
            "event": "create",
            "id": full_id,
            "fields": fields,
            "body": t.body,
        })
        report["created"] += 1

    project_dir(ctx, slug).mkdir(parents=True, exist_ok=True)
    with project_lock(ctx, slug):
        for evt in events_to_write:
            append_event(ctx, slug, evt)
        new_text = render_to_markdown(ctx, slug)
        render_evt = {
            "v": EVENT_SCHEMA_VERSION,
            "ts": _now_iso(),
            "actor": "ingest",
            "event": "render",
            "hash": render_hash(new_text),
        }
        append_event(ctx, slug, render_evt)
        _git_commit_with_retry(
            ctx,
            f"chore: migrate {slug} to v3.1 event log ({report['created']} todos)",
            events_path(ctx, slug),
            p,
        )
    return report


# --------------------------------------------------------------------------------------
# Claim / release / handoff — high-level helpers built on mutate()
# --------------------------------------------------------------------------------------

def _current_state(ctx: Context, slug: str) -> dict[str, Todo]:
    return fold_events(read_events(ctx, slug))


def _lease_active(t: Todo, now: dt.datetime) -> bool:
    lease = t.fields.get("lease_until")
    if not lease:
        return False
    try:
        # Tolerant parser for the trailing-Z form we emit.
        lease_dt = dt.datetime.strptime(lease, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except ValueError:
        return False
    return lease_dt > now


def claim(
    ctx: Context, slug: str, todo_slug: str, actor: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, str]:
    """Claim a task. Succeeds if unclaimed, lease expired, or actor IS the holder
    (self-refresh). Raises AlreadyClaimed if a different actor holds a valid lease.
    """
    if lease_seconds <= 0 or lease_seconds > MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds out of range (0, {MAX_LEASE_SECONDS}]")
    full_id = f"{slug}/{todo_slug}"
    state = _current_state(ctx, slug)
    if full_id not in state:
        raise UnknownTodo(f"unknown todo: {full_id}")
    t = state[full_id]
    now = dt.datetime.now(dt.timezone.utc)
    if _lease_active(t, now):
        holder = t.fields.get("claimed_by", "?")
        if holder != actor:
            raise AlreadyClaimed(
                f"{full_id} is claimed by {holder} until {t.fields['lease_until']}",
                claimed_by=holder,
                lease_until=t.fields["lease_until"],
            )
        # Else: self-refresh. Fall through.
    lease_until = (now + dt.timedelta(seconds=lease_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    evt = {
        "v": EVENT_SCHEMA_VERSION,
        "ts": _now_iso(),
        "actor": actor,
        "event": "claim",
        "id": full_id,
        "lease_until": lease_until,
    }
    mutate(ctx, slug, [evt])
    return {"id": full_id, "claimed_by": actor, "lease_until": lease_until}


def release(ctx: Context, slug: str, todo_slug: str, actor: str) -> dict[str, str]:
    """Release a claim. Holder-only. Raises NotClaimedByActor otherwise."""
    full_id = f"{slug}/{todo_slug}"
    state = _current_state(ctx, slug)
    if full_id not in state:
        raise UnknownTodo(f"unknown todo: {full_id}")
    t = state[full_id]
    holder = t.fields.get("claimed_by")
    if holder != actor:
        raise NotClaimedByActor(
            f"{full_id} is not claimed by {actor!r} (holder: {holder!r})"
        )
    evt = {
        "v": EVENT_SCHEMA_VERSION,
        "ts": _now_iso(),
        "actor": actor,
        "event": "release",
        "id": full_id,
    }
    mutate(ctx, slug, [evt])
    return {"id": full_id}


def handoff(
    ctx: Context, slug: str, todo_slug: str, actor: str, to: str,
    note: str | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, str]:
    """Hand off a task to another actor.

    Per Issue 4 + Codex review: succeeds if the task is unclaimed OR the calling
    actor IS the current holder. Raises TaskHeldByOtherActor if a different actor
    currently holds the claim with a valid lease.

    Recipient gets an implicit claim with a fresh `lease_seconds` lease.
    """
    if lease_seconds <= 0 or lease_seconds > MAX_LEASE_SECONDS:
        raise ValueError(f"lease_seconds out of range (0, {MAX_LEASE_SECONDS}]")
    full_id = f"{slug}/{todo_slug}"
    state = _current_state(ctx, slug)
    if full_id not in state:
        raise UnknownTodo(f"unknown todo: {full_id}")
    t = state[full_id]
    now = dt.datetime.now(dt.timezone.utc)
    if _lease_active(t, now):
        holder = t.fields.get("claimed_by", "?")
        if holder != actor:
            raise TaskHeldByOtherActor(
                f"{full_id} is held by {holder} until {t.fields['lease_until']}; "
                f"{actor!r} cannot hand off",
                claimed_by=holder,
                lease_until=t.fields["lease_until"],
            )
    lease_until = (now + dt.timedelta(seconds=lease_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    evt = {
        "v": EVENT_SCHEMA_VERSION,
        "ts": _now_iso(),
        "actor": actor,
        "event": "handoff",
        "id": full_id,
        "to": to,
        "lease_until": lease_until,
    }
    if note:
        evt["note"] = note
    mutate(ctx, slug, [evt])
    return {"id": full_id, "handoff_to": to, "claimed_by": to, "lease_until": lease_until}
