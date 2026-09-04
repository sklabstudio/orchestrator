"""Task normalization, deterministic classification, capability mapping."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sklab_orchestrator.models import Classification, Confidence, TaskCategory, TaskSpec

_CATEGORY_PATTERNS: list[tuple[TaskCategory, list[str]]] = [
    (TaskCategory.SECURITY_REVIEW, ["secur", "vulnerab", "cve", "xss", "injection", "auth bypass", "exploit"]),
    (TaskCategory.SMART_CONTRACT, ["solidity", "smart contract", "vyper", "hardhat", "foundry", "erc-20", "erc20"]),
    (TaskCategory.CI, ["ci ", "ci/", "github action", "pipeline", "workflow fail", "build fail"]),
    (TaskCategory.BUG_FIX, ["fix", "bug", "error", "exception", "fail", "broken", "timeout", "crash", "regression", "incorrect"]),
    (TaskCategory.TESTING, ["test", "coverage", "pytest", "jest", "regression"]),
    (TaskCategory.DEPENDENCY, ["dependenc", "upgrade package", "bump", "requirements", "package.json", "cargo update"]),
    (TaskCategory.DOCUMENTATION, ["doc", "readme", "changelog", "comment", "sphinx", "mkdocs"]),
    (TaskCategory.PERFORMANCE, ["perform", "profil", "latency", "slow", "optimiz", "benchmark"]),
    (TaskCategory.MIGRATION, ["migrat", "upgrade python", "port ", "migrate"]),
    (TaskCategory.REFACTOR, ["refactor", "cleanup", "restructure", "extract function"]),
    (TaskCategory.API, ["api ", "endpoint", "rest ", "openapi", "fastapi", "graphql"]),
    (TaskCategory.FRONTEND, ["frontend", "react", "vue", "css", "html", "ui ", "component"]),
    (TaskCategory.BACKEND, ["backend", "django", "flask", "database", "sql", "server"]),
    (TaskCategory.FULLSTACK, ["fullstack", "full-stack", "end-to-end", "e2e"]),
    (TaskCategory.FEATURE, ["add", "implement", "create", "build", "feature", "support"]),
]


def normalize_task(
    instruction: str,
    repo: str = "",
    source: str = "inline",
    task_file: str | None = None,
    bench: str | None = None,
    constraints: dict | None = None,
    required_checks: list[str] | None = None,
) -> TaskSpec:
    instruction = (instruction or "").strip()
    if task_file:
        p = Path(task_file)
        if p.exists():
            instruction = p.read_text(encoding="utf-8").strip() or instruction
            source = "file"
    if bench:
        source = "benchsuite"
    tid = hashlib.sha256(instruction.encode("utf-8")).hexdigest()[:12]
    return TaskSpec(
        id=f"task-{tid}",
        instruction=instruction,
        source=source,
        repository=repo,
        bench_task=bench,
        constraints=constraints or {},
        required_checks=required_checks or [],
        metadata={"bench": bench} if bench else {},
    )


def classify_task(instruction: str, repo_signals: list[str] | None = None) -> Classification:
    text = (instruction or "").lower()
    signals = [s.lower() for s in (repo_signals or [])]
    joined = text + " " + " ".join(signals)
    for cat, keywords in _CATEGORY_PATTERNS:
        for kw in keywords:
            if kw in joined:
                # confidence: HIGH when keyword in instruction itself with strong verbs
                conf = Confidence.HIGH if kw in text and len(text) < 500 else Confidence.MEDIUM
                return Classification(
                    category=cat, confidence=conf, reasons=[f"matched keyword '{kw}'"]
                )
    return Classification(
        category=TaskCategory.UNKNOWN, confidence=Confidence.LOW, reasons=["no keyword matched"]
    )


# Capability requirements per category
CAPABILITY_MAP: dict[TaskCategory, list[str]] = {
    TaskCategory.BUG_FIX: ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"],
    TaskCategory.FEATURE: ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"],
    TaskCategory.REFACTOR: ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"],
    TaskCategory.TESTING: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.CI: ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"],
    TaskCategory.DEPENDENCY: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.DOCUMENTATION: ["FILES_READ", "FILES_WRITE", "NON_INTERACTIVE"],
    TaskCategory.SECURITY_REVIEW: ["FILES_READ", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.PERFORMANCE: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.MIGRATION: ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"],
    TaskCategory.API: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.FRONTEND: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.BACKEND: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.FULLSTACK: ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"],
    TaskCategory.SMART_CONTRACT: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
    TaskCategory.UNKNOWN: ["FILES_READ", "FILES_WRITE", "SHELL", "NON_INTERACTIVE"],
}


def required_capabilities(category: TaskCategory) -> list[str]:
    return list(CAPABILITY_MAP.get(category, CAPABILITY_MAP[TaskCategory.UNKNOWN]))


def repo_signals(repo_path: str) -> list[str]:
    """Cheap static signals from repo file names (no LLM)."""
    sigs: list[str] = []
    try:
        p = Path(repo_path)
        if not p.exists():
            return sigs
        names = [f.name.lower() for f in list(p.iterdir())[:50]]
        joined = " ".join(names)
        if "contract" in joined or ".sol" in joined:
            sigs.append("solidity smart contract")
        if "pytest.ini" in joined or "test_" in joined:
            sigs.append("pytest tests")
        if "package.json" in joined:
            sigs.append("npm frontend")
        if "requirements" in joined or "pyproject.toml" in joined:
            sigs.append("python backend")
        if ".github" in joined:
            sigs.append("github action ci")
    except OSError:
        pass
    # also scan instruction-adjacent? keep simple
    _ = re.compile(r".*")
    return sigs
