---
schema: todo-contract/v2
project: my-app
file: INBOX
---

# INBOX — my-app

Proposed todos waiting for human review.
Agents append here; humans approve via `todos approve <slug> <id>`.

### Fix auth token refresh on expiry
- **status:** open
- **priority:** P1
- **effort:** S
- **agent:** claude-code
- **created:** 2026-04-27

Token refresh fails when expiry is exactly at request time. Repro:

1. Set token TTL to 60s.
2. Wait 60s.
3. Call any authenticated endpoint.
4. Observe 401 instead of refresh.

Likely fix: change strict `<` to `<=` in `auth.refreshIfExpired()`.

---

### Document the new event-stream API in README
- **status:** open
- **priority:** P3
- **effort:** S
- **agent:** codex
- **created:** 2026-04-27
- **deferred:** 2026-05-15

Wait until the API is stable for a week before documenting. Otherwise the docs
will go stale immediately.

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
