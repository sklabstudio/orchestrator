"""Skills: lightweight resolver with built-in core skills (no Skill Hub auto-install)."""

from __future__ import annotations

from sklab_orchestrator.models import SkillRef

_BUILTIN: dict[str, dict] = {
    "repo-understand": {
        "category": "understand",
        "required_capabilities": ["FILES_READ", "SHELL"],
        "risk": "low",
        "instructions": "Survey repository layout, entry points, tests. Summarize before changing code.",
    },
    "bug-fix": {
        "category": "bug_fix",
        "required_capabilities": ["FILES_READ", "FILES_WRITE", "SHELL", "GIT"],
        "risk": "medium",
        "instructions": "Reproduce the bug, make a minimal fix, add regression coverage, run relevant checks.",
    },
    "feature-build": {
        "category": "feature",
        "required_capabilities": ["FILES_READ", "FILES_WRITE", "SHELL", "GIT"],
        "risk": "medium",
        "instructions": "Implement the feature with tests. Keep the diff minimal and documented.",
    },
    "test-first": {
        "category": "testing",
        "required_capabilities": ["FILES_READ", "FILES_WRITE", "SHELL"],
        "risk": "low",
        "instructions": "Write failing tests first, then implement until green.",
    },
    "debug-test-failure": {
        "category": "testing",
        "required_capabilities": ["FILES_READ", "SHELL"],
        "risk": "low",
        "instructions": "Given trusted failure output, fix only the failing checks without unrelated changes.",
    },
    "code-review": {
        "category": "review",
        "required_capabilities": ["FILES_READ", "SHELL"],
        "risk": "low",
        "instructions": "Review the diff for correctness, regressions, and scope violations. Do not rewrite.",
    },
    "refactor-safe": {
        "category": "refactor",
        "required_capabilities": ["FILES_READ", "FILES_WRITE", "SHELL", "GIT"],
        "risk": "medium",
        "instructions": "Refactor preserving behavior. Run tests before and after.",
    },
    "ci-fix": {
        "category": "ci",
        "required_capabilities": ["FILES_READ", "FILES_WRITE", "SHELL", "GIT"],
        "risk": "medium",
        "instructions": "Fix the failing CI workflow using the exact CI logs. Verify with the same command.",
    },
    "release-check": {
        "category": "release",
        "required_capabilities": ["FILES_READ", "SHELL", "GIT"],
        "risk": "low",
        "instructions": "Verify version, changelog, build, and smoke checks before release.",
    },
}

# category -> preferred skill
_CATEGORY_SKILL = {
    "BUG_FIX": "bug-fix",
    "FEATURE": "feature-build",
    "REFACTOR": "refactor-safe",
    "TESTING": "test-first",
    "CI": "ci-fix",
    "DOCUMENTATION": "repo-understand",
    "SECURITY_REVIEW": "code-review",
    "PERFORMANCE": "refactor-safe",
    "MIGRATION": "feature-build",
    "API": "feature-build",
    "FRONTEND": "feature-build",
    "BACKEND": "feature-build",
    "FULLSTACK": "feature-build",
    "SMART_CONTRACT": "code-review",
    "UNKNOWN": "repo-understand",
}

# skill -> permission set
_SKILL_PERMS: dict[str, dict[str, bool]] = {
    "repo-understand": {"files_read": True, "files_write": False, "shell": True, "git": False,
                        "network": False, "docker": False, "secrets": False},
    "bug-fix": {"files_read": True, "files_write": True, "shell": True, "git": True,
                "network": False, "docker": False, "secrets": False},
    "feature-build": {"files_read": True, "files_write": True, "shell": True, "git": True,
                      "network": False, "docker": False, "secrets": False},
    "test-first": {"files_read": True, "files_write": True, "shell": True, "git": False,
                   "network": False, "docker": False, "secrets": False},
    "debug-test-failure": {"files_read": True, "files_write": True, "shell": True, "git": False,
                           "network": False, "docker": False, "secrets": False},
    "code-review": {"files_read": True, "files_write": False, "shell": True, "git": False,
                    "network": False, "docker": False, "secrets": False},
    "refactor-safe": {"files_read": True, "files_write": True, "shell": True, "git": True,
                      "network": False, "docker": False, "secrets": False},
    "ci-fix": {"files_read": True, "files_write": True, "shell": True, "git": True,
               "network": False, "docker": False, "secrets": False},
    "release-check": {"files_read": True, "files_write": False, "shell": True, "git": True,
                      "network": False, "docker": False, "secrets": False},
}


class SkillResolver:
    """Resolve skills from builtin set (+ future coding-lab / local dirs)."""

    def __init__(self, enable_builtin: bool = True):
        self.enable_builtin = enable_builtin

    def list_builtin(self) -> list[SkillRef]:
        return [self.get(sid) for sid in sorted(_BUILTIN)] if self.enable_builtin else []

    def get(self, skill_id: str) -> SkillRef:
        spec = _BUILTIN.get(skill_id)
        if spec is None:
            raise KeyError(f"unknown skill: {skill_id}")
        return SkillRef(
            id=skill_id, version="0.1.0",
            category=spec["category"],
            required_capabilities=list(spec["required_capabilities"]),
            risk=spec["risk"], instructions=spec["instructions"], source="builtin",
        )

    def resolve(self, category: str, requested: str | None = None) -> SkillRef:
        if requested:
            if requested not in _BUILTIN:
                raise ValueError(f"unknown skill '{requested}'")
            return self.get(requested)
        sid = _CATEGORY_SKILL.get(category, "repo-understand")
        return self.get(sid)

    def permissions(self, skill_id: str) -> dict[str, bool]:
        base = {"files_read": False, "files_write": False, "shell": False, "git": False,
                "network": False, "docker": False, "secrets": False}
        base.update(_SKILL_PERMS.get(skill_id, {}))
        return base


def compute_effective_permissions(skill_id: str, execution_policy: str) -> dict[str, bool]:
    """Intersect skill request with execution policy ceiling."""
    req = SkillResolver().permissions(skill_id)
    policy = (execution_policy or "NORMAL").upper()
    if policy == "SAFE":
        # SAFE: no network, no docker, no secrets; git read-only-ish (allow git but no push enforced elsewhere)
        req["network"] = False
        req["docker"] = False
        req["secrets"] = False
    elif policy == "NORMAL":
        req["docker"] = False
        req["secrets"] = False
    # POWER still never grants secrets implicitly
    req["secrets"] = False
    return req
