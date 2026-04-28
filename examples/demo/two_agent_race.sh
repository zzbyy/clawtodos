#!/usr/bin/env bash
# two_agent_race.sh — the v3.1 wedge in 30 seconds.
#
# Spawns two pretend "agents" (alice and bob) that race to claim the same
# todo. Shows the lease semantics, the handoff flow, and the final state.
# No GUI tools, no MCP setup needed — just the `todos` CLI.
#
# Run:
#   bash examples/demo/two_agent_race.sh
#
# Cleanup happens automatically on exit (uses a tmp dir; never touches your
# real ~/.todos).

set -euo pipefail

ROOT=$(mktemp -d -t clawtodos-demo-XXXXXX)
trap 'rm -rf "$ROOT"' EXIT

TODOS=(todos --root "$ROOT")

cyan() { printf "\033[36m%s\033[0m\n" "$*"; }
gray() { printf "\033[90m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

cyan "=== clawtodos v3.1 — two-agent coordination demo ==="
gray "tmp store: $ROOT"
echo

cyan "[1/6] Set up store + register one project + create one task"
"${TODOS[@]}" init >/dev/null
mkdir -p "$ROOT/fake-app/.git"
"${TODOS[@]}" add "$ROOT/fake-app" --no-ingest >/dev/null
"${TODOS[@]}" new fake-app "Implement v3.1 claim semantics" --priority P1 --agent claude-code >/dev/null
gray "  ✓ task: fake-app/implement-v3-1-claim-semantics"
echo

cyan "[2/6] Both agents try to claim the same task at the same instant"
gray "  alice and bob race; only one wins."
ALICE_OUT=$("${TODOS[@]}" claim fake-app implement-v3-1-claim-semantics --actor alice 2>&1) || true
BOB_OUT=$("${TODOS[@]}" claim fake-app implement-v3-1-claim-semantics --actor bob 2>&1) || true
green "  alice: $ALICE_OUT"
yellow "  bob:   $BOB_OUT"
echo

cyan "[3/6] bob's tasks.list shows the lease and skips this task"
gray "  (he sees claimed_by=alice with a future lease_until)"
"${TODOS[@]}" list --slug fake-app --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
todos = data['projects'][0]['todos']
for t in todos:
    title = t['title']
    print(f\"  {title}\")
    print(f\"    claimed_by: {t.get('claimed_by') or '(unclaimed)'}\")
    print(f\"    lease_until: {t.get('lease_until') or '-'}\")
"
echo

cyan "[4/6] alice realizes bob is better suited; hands off"
HANDOFF=$("${TODOS[@]}" handoff fake-app implement-v3-1-claim-semantics --actor alice --to bob --note "your area of expertise" 2>&1)
green "  $HANDOFF"
echo

cyan "[5/6] bob marks it done; lease + claim auto-release"
DONE=$("${TODOS[@]}" done fake-app implement-v3-1-claim-semantics 2>&1)
green "  $DONE"
echo

cyan "[6/6] Inspect the audit log — every transition recorded"
gray "  ~/.todos/fake-app/EVENTS.ndjson:"
python3 - << PY
import json, pathlib, sys
events_path = pathlib.Path("$ROOT/fake-app/EVENTS.ndjson")
for i, line in enumerate(events_path.read_text().splitlines(), 1):
    if not line.strip():
        continue
    e = json.loads(line)
    extras = []
    if "to" in e: extras.append(f"to={e['to']}")
    if "lease_until" in e: extras.append(f"lease={e['lease_until']}")
    if "hash" in e: extras.append(f"hash={e['hash'][:8]}")
    extra = " " + " ".join(extras) if extras else ""
    eid = e.get("id", "(project-scoped)")
    print(f"  {i:2d}. {e['ts']}  {e['actor']:13s}  {e['event']:8s}  {eid}{extra}")
PY
echo

cyan "=== Final TODOS.md (the human view, derived from the log) ==="
cat "$ROOT/fake-app/TODOS.md"

echo
green "wedge: ✓ two agents coordinated on one task store via plain text + filelock"
green "no SaaS, no DB, no orchestrator — open spec, git-native audit log"
gray "(spec: https://github.com/zzbyy/clawtodos/blob/v3.1.0/SPEC-v3.1.md)"
