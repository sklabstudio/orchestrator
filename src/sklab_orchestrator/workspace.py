"""Isolated workspace: temp clone/worktree; never mutate original repo by default."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path


def snapshot_repo_state(repo: str) -> dict[str, str | None]:
    """Capture branch/HEAD/dirty-state of original repo for safety assertions."""
    snap: dict[str, str | None] = {"branch": None, "head": None, "dirty": None, "untracked": None}
    try:
        p = Path(repo)
        if not (p.exists() and (p / ".git").exists()):
            return snap
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(p),
                             capture_output=True, text=True, timeout=10)
        snap["head"] = out.stdout.strip() if out.returncode == 0 else None
        out = subprocess.run(["git", "branch", "--show-current"], cwd=str(p),
                             capture_output=True, text=True, timeout=10)
        snap["branch"] = out.stdout.strip() if out.returncode == 0 else None
        out = subprocess.run(["git", "status", "--porcelain"], cwd=str(p),
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            lines = out.stdout.splitlines()
            snap["dirty"] = "\n".join(sorted(
                line for line in lines if line and not line.startswith("??")))
            snap["untracked"] = "\n".join(sorted(
                line for line in lines if line.startswith("??")))
    except Exception:
        pass
    return snap


def verify_repo_untouched(repo: str, before: dict) -> list[str]:
    after = snapshot_repo_state(repo)
    problems = []
    for key in ("branch", "head", "dirty", "untracked"):
        if before.get(key) != after.get(key):
            problems.append(f"original repo changed: {key}")
    return problems


def create_workspace(repo: str, run_id: str) -> Path:
    """Create isolated workspace as a filesystem copy (compatible with ReproBox/CodeTrials)."""
    dest = Path(tempfile.gettempdir()) / f"sklab-{run_id}"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(repo) if repo else None
    try:
        if src is not None and src.exists():
            if (src / ".git").exists():
                # Prefer git worktree-like clone: copy tracked + untracked content cheaply.
                # Copy project content without the source metadata, then create a
                # private baseline repository so adapter patch capture can diff it.
                shutil.copytree(src, dest / "work", ignore=shutil.ignore_patterns(".git"),
                                dirs_exist_ok=True)
                _initialize_workspace_repo(dest / "work")
            else:
                shutil.copytree(src, dest / "work", dirs_exist_ok=True)
        else:
            (dest / "work").mkdir(exist_ok=True)
    except Exception:
        (dest / "work").mkdir(exist_ok=True)
    return dest / "work"


def _initialize_workspace_repo(workspace: Path) -> None:
    """Create a disposable Git baseline without touching the source repository."""
    try:
        commands = [
            ["git", "init", "--quiet"],
            ["git", "add", "--all"],
            ["git", "-c", "user.name=SKLab", "-c", "user.email=sklab@localhost",
             "commit", "--quiet", "--allow-empty", "-m", "SKLab baseline"],
        ]
        for argv in commands:
            result = subprocess.run(
                argv, cwd=str(workspace), capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                shutil.rmtree(workspace / ".git", ignore_errors=True)
                return
    except (OSError, subprocess.TimeoutExpired):
        shutil.rmtree(workspace / ".git", ignore_errors=True)


def cleanup_workspace(workspace: str | Path) -> None:
    try:
        ws = Path(workspace)
        # Only clean project-owned temp dirs: parent name must start with sklab-
        parent = ws.parent if ws.name == "work" else ws
        if parent.name.startswith("sklab-") and str(parent).startswith(tempfile.gettempdir()):
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass


def workspace_fingerprint(workspace: str) -> str:
    return hashlib.sha256(f"workspace|{workspace}".encode()).hexdigest()[:16]
