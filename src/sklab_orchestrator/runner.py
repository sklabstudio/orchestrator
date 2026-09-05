"""Agent execution via Agent Adapters (or injected fake runner for tests)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
    """Run the selected real adapter through its normalized Python API."""
    return _run_real_agent(agent_id, prompt, workspace, env, attempt_no, 1800, None)


def _run_real_agent(
    agent_id: str,
    prompt: str,
    workspace: str,
    env: dict[str, str],
    attempt_no: int,
    timeout_seconds: int,
    on_event: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    try:
        from sklab_agent_adapters.adapters.registry import get_adapter
        from sklab_agent_adapters.core.models import AgentRunRequest
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "patch": "",
            "changed_files": [],
            "usage": {},
            "cost": None,
            "error": f"agent adapter unavailable: {exc}",
        }
    patch_path = Path(workspace).parent / f".sklab-agent-patch-{attempt_no}.diff"
    try:
        adapter = get_adapter(agent_id)
        request = AgentRunRequest(
            agent_id=agent_id,
            workspace=Path(workspace),
            instruction=prompt,
            timeout_seconds=timeout_seconds,
            environment=dict(env),
            stream=True,
            metadata={"patch_out": str(patch_path)},
        )
        result = adapter.run(request, on_event=on_event)
    except Exception as exc:
        return {
            "status": "AGENT_FAILED",
            "patch": "",
            "changed_files": [],
            "usage": {},
            "cost": None,
            "error": f"agent adapter error: {exc}",
        }
    patch = ""
    if result.patch_path:
        try:
            patch = Path(result.patch_path).read_text(encoding="utf-8")
        except OSError:
            patch = ""
    usage: dict[str, Any] = {}
    if result.token_usage is not None:
        usage["tokens"] = result.token_usage.model_dump(mode="json")
    if result.cost_usage is not None:
        usage["cost"] = result.cost_usage.model_dump(mode="json")
    error = ""
    if result.error:
        error = str(result.error.get("message", result.error))
    status = getattr(result.status, "value", result.status)
    cost = result.cost_usage.amount if result.cost_usage is not None else None
    return {
        "status": str(status),
        "patch": patch,
        "changed_files": list(result.changed_files),
        "usage": usage,
        "cost": cost,
        "error": error,
        "model": result.model,
    }


class AgentRunner:
    def __init__(self, agent_fn: AgentFn | None = None):
        self.agent_fn = agent_fn
        self._use_real_adapter = agent_fn is None

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
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentOutcome:
        prompt = build_agent_prompt(instruction, failure_evidence, quarantine_repo_text(repo_excerpt))
        started = datetime.now(UTC)
        try:
            if self._use_real_adapter:
                raw = _run_real_agent(
                    agent_id, prompt, workspace, dict(env), attempt_no, timeout_seconds, on_event
                )
            else:
                assert self.agent_fn is not None
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
