"""Agent execution via Agent Adapters (or injected fake runner for tests)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sklab_orchestrator.security import build_agent_prompt, quarantine_repo_text

# Type for injected agent function: (agent_id, prompt, workspace, env, attempt_no) -> dict
AgentFn = Callable[[str, str, str, dict[str, str], int], dict[str, Any]]


@dataclass
class AgentOutcome:
    status: str  # SUCCESS | AGENT_FAILED | TIMEOUT | AUTH_REQUIRED | UNAVAILABLE | NO_CHANGES | ...
    patch: str = ""
    changed_files: list | None = None
    usage: dict | None = None
    cost: float | None = None
    error: str = ""
    model: str | None = None

    def __post_init__(self) -> None:
        if self.changed_files is None:
            self.changed_files = []
        if self.usage is None:
            self.usage = {}


def default_agent_fn(
    agent_id: str, prompt: str, workspace: str, env: dict[str, str], attempt_no: int
) -> dict[str, Any]:
    """Fallback when no real adapter/fake injected: deterministic no-op (safe, offline)."""
    return {
        "status": "UNAVAILABLE",
        "patch": "",
        "changed_files": [],
        "usage": {},
        "cost": None,
        "error": f"agent '{agent_id}' unavailable (no adapter installed)",
    }


class AgentRunner:
    def __init__(self, agent_fn: AgentFn | None = None):
        self.agent_fn = agent_fn or default_agent_fn

    def run(
        self,
        agent_id: str,
        instruction: str,
        workspace: str,
        env: dict[str, str],
        attempt_no: int,
        failure_evidence: str = "",
        repo_excerpt: str = "",
        timeout_seconds: int = 1800,
    ) -> AgentOutcome:
        prompt = build_agent_prompt(instruction, failure_evidence, quarantine_repo_text(repo_excerpt))
        started = datetime.now(UTC)
        try:
            raw = self.agent_fn(agent_id, prompt, workspace, dict(env), attempt_no)
        except TimeoutError as e:
            return AgentOutcome(status="TIMEOUT", error=str(e))
        except Exception as e:  # noqa: BLE001
            return AgentOutcome(status="AGENT_FAILED", error=f"agent crash: {e}")
        _ = started, timeout_seconds
        return AgentOutcome(
            status=str(raw.get("status", "AGENT_FAILED")),
            patch=str(raw.get("patch", "")),
            changed_files=list(raw.get("changed_files", [])),
            usage=dict(raw.get("usage", {})),
            cost=raw.get("cost"),
            error=str(raw.get("error", "")),
            model=raw.get("model"),
        )
