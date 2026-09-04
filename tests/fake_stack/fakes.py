"""Deterministic fake stack: agents, verifier, catalogs (no network, no cost, no creds)."""

from __future__ import annotations

from typing import Any

from sklab_orchestrator.integrations import AgentInfo, ConnectionInfo

GOOD_PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 # GOOD_PATCH
+fixed = True
"""

BAD_PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 # BAD_PATCH
+broken = True
"""

RETRY_PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,3 @@
 # RETRY_PATCH fixed with evidence
+fixed_retry = True
"""

FULL_CAPS = ["FILES_READ", "FILES_WRITE", "SHELL", "GIT", "NON_INTERACTIVE"]
READ_CAPS = ["FILES_READ", "SHELL", "NON_INTERACTIVE"]


def fake_agent_fn(agent_id: str, prompt: str, workspace: str,
                  env: dict[str, str], attempt_no: int) -> dict[str, Any]:
    """Simulate fixture agents. Prompt contains trusted evidence from attempt>=2 paths."""
    if agent_id in ("good-agent", "free-agent", "hermes"):
        return {"status": "SUCCESS", "patch": GOOD_PATCH, "changed_files": ["app.py"],
                "usage": {"input_tokens": 10}, "cost": 0.0, "model": "fixture-free"}
    if agent_id == "bad-agent":
        return {"status": "SUCCESS", "patch": BAD_PATCH, "changed_files": ["app.py"],
                "usage": {}, "cost": 0.0, "model": "fixture-free"}
    if agent_id == "fix-on-retry-agent":
        # attempt 1 fails; attempt 2+ (which carries failure evidence in prompt) passes
        if attempt_no <= 1:
            return {"status": "SUCCESS", "patch": BAD_PATCH, "changed_files": ["app.py"],
                    "usage": {}, "cost": 0.0, "model": "fixture-free"}
        # require evidence marker to prove evidence-driven retry
        if "Failed checks" in prompt or "fix ONLY" in prompt or "fix only" in prompt.lower():
            return {"status": "SUCCESS", "patch": RETRY_PATCH, "changed_files": ["app.py"],
                    "usage": {}, "cost": 0.0, "model": "fixture-free"}
        return {"status": "SUCCESS", "patch": BAD_PATCH, "changed_files": ["app.py"],
                "usage": {}, "cost": 0.0}
    if agent_id == "timeout-agent":
        return {"status": "TIMEOUT", "patch": "", "changed_files": [],
                "usage": {}, "cost": 0.0, "error": "agent timed out"}
    if agent_id == "no-change-agent":
        return {"status": "NO_CHANGES", "patch": "", "changed_files": [],
                "usage": {}, "cost": 0.0, "error": "no changes produced"}
    if agent_id in ("expensive-agent", "premium-agent", "codex"):
        return {"status": "SUCCESS", "patch": GOOD_PATCH, "changed_files": ["app.py"],
                "usage": {}, "cost": 0.80, "model": "fixture-premium"}
    if agent_id == "auth-required-agent":
        return {"status": "AUTH_REQUIRED", "patch": "", "changed_files": [],
                "usage": {}, "cost": None, "error": "free-limit quota exceeded (auth required)"}
    if agent_id == "claude_code":
        return {"status": "SUCCESS", "patch": GOOD_PATCH, "changed_files": ["docs.md"],
                "usage": {}, "cost": 0.0, "model": "fixture-free"}
    return {"status": "UNAVAILABLE", "patch": "", "changed_files": [],
            "usage": {}, "cost": None, "error": f"unknown fixture agent {agent_id}"}


def fake_verifier_fn(patch: str, workspace: str) -> dict[str, Any]:
    if not patch:
        return {"verdict": "REJECT", "score": 10.0, "regressions": ["no_patch"],
                "checks": [{"name": "pytest login_timeout", "passed": False,
                            "detail": "no patch produced"}], "strength": "FULL"}
    if "RETRY_PATCH" in patch:
        return {"verdict": "ACCEPT", "score": 92.0, "regressions": [],
                "checks": [{"name": "pytest login_timeout", "passed": True,
                            "detail": "pass after retry"}], "strength": "FULL"}
    if "GOOD_PATCH" in patch:
        return {"verdict": "ACCEPT", "score": 95.0, "regressions": [],
                "checks": [{"name": "pytest login_timeout", "passed": True,
                            "detail": "ok"}], "strength": "FULL"}
    return {"verdict": "REJECT", "score": 40.0, "regressions": ["login_timeout"],
            "checks": [{"name": "pytest login_timeout", "passed": False,
                        "detail": "AssertionError: timeout not fixed"}], "strength": "FULL"}


def catalog_cheap_first() -> list[AgentInfo]:
    return [
        AgentInfo(agent_id="free-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False,
                  supports_model_selection=True, supports_resume=True),
        AgentInfo(agent_id="premium-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="high", paid=True,
                  supports_model_selection=True, supports_resume=True),
    ]


def catalog_full() -> list[AgentInfo]:
    return [
        AgentInfo(agent_id="good-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="bad-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="fix-on-retry-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="timeout-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="no-change-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="expensive-agent", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="high", paid=True),
        AgentInfo(agent_id="auth-required-agent", installed=False, auth_ready=False,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="hermes", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
        AgentInfo(agent_id="codex", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="high", paid=True),
        AgentInfo(agent_id="claude_code", installed=True, auth_ready=True,
                  capabilities=list(FULL_CAPS), cost_class="free", paid=False),
    ]


def catalog_single(agent_id: str, paid: bool = False, cost: str = "free") -> list[AgentInfo]:
    return [AgentInfo(agent_id=agent_id, installed=True, auth_ready=True,
                      capabilities=list(FULL_CAPS), cost_class=cost, paid=paid)]


def connections_free() -> list[ConnectionInfo]:
    return [ConnectionInfo(connection_id="local-free", enabled=True, ready=True,
                           default_model="fixture-free", cost_class="free", paid=False)]


def connections_paid_only() -> list[ConnectionInfo]:
    return [ConnectionInfo(connection_id="paid-conn", enabled=True, ready=True,
                           default_model="fixture-premium", cost_class="high", paid=True)]


def secret_env() -> tuple[dict[str, str], list[str]]:
    return ({"FAKE_SECRET_TOKEN": "do-not-leak-value-12345"},
            ["do-not-leak-value-12345"])
