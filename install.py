#!/usr/bin/env python3
"""
clawtodos — cross-platform installer.

Run this once after cloning the repo. It will:

  1. Install the `todos` CLI to a stable location on PATH:
     - macOS / Linux:  ~/.local/bin/todos          (Bash/Zsh PATH)
     - Windows:        %LOCALAPPDATA%\\clawtodos\\bin\\todos.cmd  (you may need to add this to PATH)
  2. Run `todos init` to bootstrap ~/.todos/ (or $TODO_CONTRACT_ROOT).
  3. Print next steps (snippet to paste, optional OpenClaw skill install).

Requirements: Python 3.9+, git (recommended). No third-party deps.

For pip users, you can skip this and just run:
    pip install --user .

That sets up `todos` on PATH automatically via the entry point in pyproject.toml.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SRC = REPO / "src"
SNIPPET = REPO / "snippets" / "AGENTS_SNIPPET.md"
OPENCLAW_SKILL = REPO / "openclaw" / "clawtodos-review"


def info(msg: str) -> None:
    print(f"  {msg}")


def step(msg: str) -> None:
    print(f"\n→ {msg}")


def find_python() -> str:
    """Return the absolute path to the current Python interpreter."""
    return sys.executable


def install_unix() -> Path:
    """Install a 'todos' wrapper to ~/.local/bin and return its path."""
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "todos"

    py = find_python()
    wrapper = (
        "#!/usr/bin/env bash\n"
        f"export PYTHONPATH=\"{SRC}:${{PYTHONPATH:-}}\"\n"
        f"exec \"{py}\" -m clawtodos \"$@\"\n"
    )
    target.write_text(wrapper, encoding="utf-8")
    target.chmod(0o755)
    return target


def install_windows() -> Path:
    """Install a 'todos.cmd' wrapper to %LOCALAPPDATA%\\clawtodos\\bin and return its path."""
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    bin_dir = base / "clawtodos" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "todos.cmd"

    py = find_python()
    # Quote paths for cmd.exe; %* forwards all args.
    wrapper = (
        "@echo off\r\n"
        f"set PYTHONPATH={SRC};%PYTHONPATH%\r\n"
        f"\"{py}\" -m clawtodos %*\r\n"
    )
    target.write_text(wrapper, encoding="utf-8")
    return target


def on_path(directory: Path) -> bool:
    parts = (os.environ.get("PATH") or "").split(os.pathsep)
    return any(Path(p).resolve() == directory.resolve() for p in parts if p)


def main() -> int:
    print("clawtodos installer")
    print("===================")
    info(f"repo:       {REPO}")
    info(f"python:     {sys.executable}")
    info(f"platform:   {platform.system()} ({platform.machine()})")

    if shutil.which("git") is None:
        info("warning: git not found on PATH. clawtodos works without it,")
        info("         but you'll lose the per-action audit log.")

    step("Installing `todos` command…")
    try:
        if platform.system() == "Windows":
            target = install_windows()
        else:
            target = install_unix()
    except Exception as e:
        print(f"\nERROR: failed to install wrapper: {e}", file=sys.stderr)
        return 1
    info(f"installed:  {target}")

    if not on_path(target.parent):
        info("")
        info(f"⚠  {target.parent} is NOT on your PATH.")
        if platform.system() == "Windows":
            info("   Add it via System Properties → Environment Variables → User PATH,")
            info("   or open a new PowerShell and run:")
            info(f"     [Environment]::SetEnvironmentVariable('Path', \"$env:Path;{target.parent}\", 'User')")
        else:
            shell = os.environ.get("SHELL", "")
            rc = "~/.zshrc" if shell.endswith("zsh") else "~/.bashrc"
            info(f"   Add this line to {rc} (or your shell rc) and restart the shell:")
            info(f"     export PATH=\"$HOME/.local/bin:$PATH\"")

    step("Bootstrapping ~/.todos/ via `todos init`…")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC}{os.pathsep}{env.get('PYTHONPATH', '')}"
    rc = subprocess.run(
        [sys.executable, "-m", "clawtodos", "init"],
        env=env,
    ).returncode
    if rc != 0:
        return rc

    step("All set. Next steps:")
    info("1. Tell your AI agents about clawtodos.")
    info(f"   Copy the contents of {SNIPPET}")
    info("   into your agent's instruction file:")
    info("     • Claude Code:   ~/.claude/CLAUDE.md")
    info("     • Codex CLI:     ~/.codex/AGENTS.md")
    info("     • Cursor:        <repo>/.cursorrules  (per-repo)")
    info("     • Generic:       AGENTS.md  (per-repo)")
    info("")
    if OPENCLAW_SKILL.exists():
        info("2. (Optional) OpenClaw users — install the conversational review skill:")
        if platform.system() == "Windows":
            info(f"   xcopy /E /I \"{OPENCLAW_SKILL}\" \"%USERPROFILE%\\.openclaw\\workspace\\skills\\clawtodos-review\"")
        else:
            info(f"   cp -r {OPENCLAW_SKILL} ~/.openclaw/workspace/skills/")
        info("")
    info("3. Register your first project:")
    info("     todos add /path/to/your/repo")
    info("")
    info("4. Use your AI normally. Review the inbox once a day:")
    info("     todos list --state inbox")
    info("     todos approve <slug> <id>")
    info("")
    info("Full docs: https://github.com/zzbyy/clawtodos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
