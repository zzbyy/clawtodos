---
schema: todo-contract/v3
project: my-app
---

# TODOS — my-app

Single canonical list. Lifecycle is encoded in each entry's `status:` field:
`pending` (agent proposed) → `open` → `in-progress` → `done`. Side path: `wont` (tombstone for declined work).

### Fix auth token refresh on expiry
- **status:** in-progress
- **priority:** P1
- **effort:** S
- **agent:** human
- **created:** 2026-04-26
- **updated:** 2026-04-28

Token refresh fails when expiry is exactly at request time. Repro:

1. Set token TTL to 60s.
2. Wait 60s.
3. Call any authenticated endpoint.
4. Observe 401 instead of refresh.

Likely fix: change strict `<` to `<=` in `auth.refreshIfExpired()`.

---

### Add a CLI subcommand to export user data
- **status:** open
- **priority:** P2
- **effort:** L
- **agent:** human
- **created:** 2026-04-27
- **tags:** privacy, gdpr

Compliance ask. Should output a single JSON file per user with all profile,
preferences, and activity data. Needs a confirmation prompt because it can
take minutes for active users.

---

### Add rate-limiting to /auth/refresh
- **status:** pending
- **priority:** P2
- **effort:** S
- **agent:** claude-code
- **created:** 2026-04-28

The fix to refreshIfExpired removes the bug, but the endpoint is still
unprotected. A botnet could DoS it cheaply. Suggest 5 req/min/IP.

(claude-code proposed this autonomously after fixing the auth bug. Awaiting
human review.)

---

### Document the new event-stream API in README
- **status:** open
- **priority:** P3
- **effort:** S
- **agent:** codex
- **created:** 2026-04-25
- **updated:** 2026-04-28
- **deferred:** 2026-05-15

Wait until the API is stable for a week before documenting. Otherwise the docs
will go stale immediately. Hidden from default list until 2026-05-15.

---

### Migrate to event-sourced auth
- **status:** wont
- **priority:** P3
- **agent:** human
- **created:** 2026-03-15
- **updated:** 2026-04-10
- **wont_reason:** scope creep — current session-based auth is fine for the next 12 months

Tombstone. Agents see this and don't re-propose.

---

### Pick the new logo color palette
- **status:** done
- **priority:** P2
- **effort:** XS
- **agent:** human
- **created:** 2026-04-20
- **updated:** 2026-04-25

Done items stay in this file with `status: done`. Optional `todos archive`
sweep can move old done entries to year-stamped files later.

---
