# Bootstrap clawtodos — instructions for AI agents

> **You are an AI agent (OpenClaw, Claude Code, Codex, Cursor, or similar).** A human just asked you to install or set up `clawtodos`. This file is written *for you*, not for them. Follow it top to bottom. Ask the human one question at a time. Confirm before any action that writes outside `~/.todos/` or `~/.clawtodos/`.

If you cannot run shell commands, edit files outside the current repo, or read URLs — stop and say so. Direct the human to <https://github.com/zzbyy/clawtodos#install> for a manual install.

---

## What clawtodos is (so you set expectations correctly)

A central, agent-proposes / human-approves task system. Canonical state lives at `~/.todos/` (or `$TODO_CONTRACT_ROOT`). Multiple AI agents drop proposed todos into per-project `INBOX.md` files; the human approves into `TODOS.md`. Repos are read-only sources. The full spec is at <https://github.com/zzbyy/clawtodos/blob/main/SPEC.md>.

You will be installing both the `todos` CLI and the per-agent instruction snippet.

---

## Phase 0 — Verify you can do this

Before saying anything to the human, run these checks silently:

```bash
python3 --version         # need 3.9+
pip --version || python3 -m pip --version
git --version             # recommended; clawtodos works without it but loses audit log
which todos               # if non-empty, clawtodos may already be installed
```

Decide:
- **If `which todos` returns a path AND `todos doctor` succeeds:** clawtodos is already installed. Skip to Phase 4 (wire agents, register projects).
- **If Python is missing:** stop and tell the human "I need Python 3.9+ to install this. On macOS, run `brew install python`. On Windows, install from python.org." Don't proceed.
- **Otherwise:** continue.

Then greet the human:

> "I'll set up clawtodos for you. This will: (1) install the `todos` CLI, (2) create `~/.todos/` as your central task home, (3) wire up your AI agents to use it, and (4) register your active projects. About 2 minutes. Ready?"

Wait for confirmation.

---

## Phase 1 — Install the CLI

Install via pip in user mode. This avoids needing sudo and puts `todos` on the user's PATH:

```bash
python3 -m pip install --user --upgrade git+https://github.com/zzbyy/clawtodos.git
```

After it finishes, verify:

```bash
which todos
todos --help
```

**If `which todos` returns nothing**, the user-bin dir is not on PATH. Detect and fix:

- macOS / Linux: PATH should include `~/.local/bin` (Linux) or `~/Library/Python/3.X/bin` (macOS). Tell the human exactly what to add to their shell rc:
    ```bash
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # or ~/.bashrc
    ```
- Windows: tell them to add `%APPDATA%\Python\Python3X\Scripts` to their User PATH via System Properties → Environment Variables.

Tell the human to open a new shell (or source the rc), then re-run `which todos` to confirm. Don't proceed until it returns a path.

---

## Phase 2 — Initialize `~/.todos/`

```bash
todos init
```

This creates the directory, writes `registry.yaml` and `README.md`, and runs `git init` for the audit log. It is idempotent — safe to run if it's already initialized.

Confirm with the human:

> "Created `~/.todos/`. This is now the only place we'll store todo state. Your code repos won't be touched."

---

## Phase 3 — Discover the human's AI agents

Detect which agent instruction files exist on this machine. Run silently:

```bash
ls -d ~/.claude 2>/dev/null && echo HAS_CLAUDE_CODE
ls -d ~/.codex 2>/dev/null && echo HAS_CODEX
ls -d ~/.openclaw/workspace 2>/dev/null && echo HAS_OPENCLAW
# Cursor and Antigravity are per-repo via .cursorrules / AGENTS.md — check later, per project.
```

Also look at the standard global instruction files:

- Claude Code: `~/.claude/CLAUDE.md`
- Codex CLI: `~/.codex/AGENTS.md`
- OpenClaw: `~/.openclaw/workspace/AGENTS.md`

Read each one (silently). For each, note whether it already contains `<!-- BEGIN: clawtodos / todo-contract/v2 -->` (already wired) or `<!-- BEGIN: todo-contract/v1 -->` (legacy v1 — needs upgrade).

Then ask the human:

> "I found these AI agents on your machine: **[list them]**. Should I add the clawtodos snippet to each one so they all use the same central system? (yes / no / pick specific ones)"

Wait for the answer. If they say specific ones, narrow the list.

---

## Phase 4 — Wire each agent

Fetch the snippet content from the public repo:

```bash
curl -fsSL https://raw.githubusercontent.com/zzbyy/clawtodos/main/snippets/AGENTS_SNIPPET.md
```

(Or read from the cloned repo if you've cloned it.)

For each chosen agent's instruction file:

1. **If the file already contains `<!-- BEGIN: clawtodos / todo-contract/v2 -->`:** skip; already wired. Move on.
2. **If the file contains `<!-- BEGIN: todo-contract/v1 -->`:** the human is migrating from v1. Tell them: *"Your `<file>` has the v1 todo-contract snippet. clawtodos v2 supersedes it. I'll replace the v1 block with the v2 block. OK?"* On yes, delete from the v1 BEGIN to v1 END line and append the v2 snippet to the end.
3. **Else:** append the snippet to the end of the file. Preceded by a blank line.

After modifying, show the human a 3-line preview of the change with the file path. Don't dump the whole snippet to chat — they can read the file later.

Repeat for each chosen agent.

---

## Phase 5 — Install the OpenClaw conversational skill (only if applicable)

If the human has OpenClaw (`~/.openclaw/workspace/skills/`), install the `clawtodos-review` skill so they can say *"review my inbox"* in OpenClaw and get a guided walk-through.

```bash
SKILL_DIR=~/.openclaw/workspace/skills/clawtodos-review
mkdir -p "$SKILL_DIR"
curl -fsSL https://raw.githubusercontent.com/zzbyy/clawtodos/main/openclaw/clawtodos-review/SKILL.md -o "$SKILL_DIR/SKILL.md"
```

Tell the human:

> "Installed the `clawtodos-review` skill in OpenClaw. From now on, just say *'review my inbox'* and I'll walk you through pending proposals one at a time."

Skip this phase if OpenClaw is not present.

---

## Phase 6 — Register the human's active projects

Suggest likely projects by listing top-level dirs under common roots:

```bash
ls -d ~/code/*/ ~/projects/*/ ~/repos/*/ ~/work/*/ 2>/dev/null | head -20
```

Filter to dirs that have `.git/`. Ask the human:

> "Here are some directories that look like git repos: **[list]**. Which of these are your active projects to register? You can also name personal programs (like 'health' or 'self-dev'). Reply with a comma-separated list, or 'skip' to register projects later yourself."

For each project they name:

```bash
todos add /full/path/to/project
# or for personal programs (no path):
todos add personal/<name> --type program
```

Each `todos add` produces a git commit in `~/.todos/`. Show progress to the human:

> "Registered `my-app` (code repo, ingested 3 existing TODO comments → INBOX). Registered `personal/health` (program). Done — 2 projects."

If `--ingest` was triggered (default for code repos), tell them about the ingested entries — those are now their first batch of proposals to review.

---

## Phase 7 — Verify and queue first review

Run the doctor and a quick listing:

```bash
todos doctor
todos list --state inbox
```

If `doctor` returns ok, summarize:

> "✅ clawtodos is installed.
>  • CLI:          `todos` is on PATH
>  • Central root: `~/.todos/` (git-versioned)
>  • Agents wired: [list]
>  • OpenClaw skill installed: [yes/no]
>  • Projects registered: [N]
>  • Pending in inbox: [M]
>
>  Want to review your first inbox now?"

If yes, walk them through it (use the `clawtodos-review` skill if you're OpenClaw, otherwise manually: present each entry with title/priority/agent/body and ask a/e/d/r).

If no, tell them:

> "Whenever you're ready, say *'review my inbox'* (in OpenClaw) or run `todos list --state inbox` to see what's queued."

---

## Phase 8 — Hand-off

Final message to the human:

> "All set. Your AI agents will now propose follow-ups into `~/.todos/<project>/INBOX.md` instead of cluttering your repos. Approve them once a day with `todos approve` (or just say 'review my inbox')."

Done.

---

## Error handling — what to do when something goes wrong

| Symptom | What it means | What to do |
|---|---|---|
| `pip install` fails with permission error | User's pip wants sudo | Always pass `--user`. If still fails, ask user to install Python via Homebrew (Mac) or python.org (Windows) which sets up user-mode pip cleanly. |
| `which todos` empty after install | PATH not set | Tell user the exact line to add to their shell rc, then have them open a new shell. Don't proceed. |
| `todos init` says "already initialized" | Re-running the bootstrap | Fine, this is idempotent. Continue. |
| `git` not found | Old or minimal system | clawtodos works without git; just no audit log. Continue, but warn the user. |
| Agent instruction file not found at expected path | Agent isn't installed, or installed in non-standard location | Ask the user where their `CLAUDE.md` / `AGENTS.md` actually lives and use that path. |
| Snippet already present in file | Already wired (good) or duplicate (bad) | Check for the BEGIN/END markers. If present, skip. If a partial duplicate, ask user before overwriting. |
| `curl` not available (Windows) | Older systems | Use `Invoke-WebRequest` (PowerShell) or `python3 -c "import urllib.request; ..."` as fallback. |

---

## Non-goals for this bootstrap

- **Don't `pip install --upgrade pip`** without asking. That's the user's environment.
- **Don't add `~/.todos/` to any global shell startup.** It's a directory, not something to source.
- **Don't auto-register every git repo on the machine.** Only what the user explicitly names.
- **Don't auto-approve any inbox entries.** The whole point is the human does that. Even ingested ones — those go to `ingested.md` and the human promotes manually.
- **Don't modify any registered repo's working tree.** Ever. Read-only.

---

## A note on idempotency

This bootstrap is safe to run multiple times. Re-running:
- `pip install --user --upgrade` upgrades or no-ops.
- `todos init` no-ops if already initialized.
- Wiring agents detects existing snippet markers and skips.
- Registering projects errors cleanly if the slug already exists (CLI says "already registered"); skip and continue.

If the human is re-running because they hit a snag, ask what failed and resume from that step rather than restarting from Phase 0.
