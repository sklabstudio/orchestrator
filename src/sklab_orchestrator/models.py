"""Core data models: TaskSpec, RunState, Plan, Attempt, Verification, Result."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


SCHEMA_VERSION = 1


class RunStatus(StrEnum):
    CREATED = "CREATED"
    INSPECTING = "INSPECTING"
    PLANNING = "PLANNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    PREPARING = "PREPARING"
    RUNNING_AGENT = "RUNNING_AGENT"
    CAPTURING_PATCH = "CAPTURING_PATCH"
    VERIFYING = "VERIFYING"
    ANALYZING_FAILURE = "ANALYZING_FAILURE"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class TaskCategory(StrEnum):
    BUG_FIX = "BUG_FIX"
    FEATURE = "FEATURE"
    REFACTOR = "REFACTOR"
    TESTING = "TESTING"
    CI = "CI"
    DEPENDENCY = "DEPENDENCY"
    DOCUMENTATION = "DOCUMENTATION"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    PERFORMANCE = "PERFORMANCE"
    MIGRATION = "MIGRATION"
    API = "API"
    FRONTEND = "FRONTEND"
    BACKEND = "BACKEND"
    FULLSTACK = "FULLSTACK"
    SMART_CONTRACT = "SMART_CONTRACT"
    UNKNOWN = "UNKNOWN"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ResultStatus(StrEnum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    UNVERIFIED_SUCCESS = "UNVERIFIED_SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NO_PROGRESS = "NO_PROGRESS"
    CANCELLED = "CANCELLED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    EXECUTION_SUCCESS_VERIFICATION_FAIL = "EXECUTION_SUCCESS_VERIFICATION_FAIL"


class TaskSpec(BaseModel):
    id: str
    instruction: str
    source: str = "inline"
    repository: str = ""
    bench_task: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    required_checks: list[str] = Field(default_factory=list)
    priority: str = "normal"
    risk_level: str = "medium"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Classification(BaseModel):
    category: TaskCategory = TaskCategory.UNKNOWN
    confidence: Confidence = Confidence.LOW
    reasons: list[str] = Field(default_factory=list)


class RepoInfo(BaseModel):
    repo_path: str = ""
    available: bool = False
    repo_context_available: bool = False
    repo_fingerprint: str = ""
    context_fingerprint: str = ""
    branch: str | None = None
    head: str | None = None
    language_signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SkillRef(BaseModel):
    id: str
    version: str = "0.1.0"
    category: str = "general"
    required_capabilities: list[str] = Field(default_factory=list)
    risk: str = "low"
    instructions: str = ""
    source: str = "builtin"


class AgentCandidate(BaseModel):
    agent_id: str
    installed: bool = False
    auth_ready: bool = False
    capabilities: list[str] = Field(default_factory=list)
    cost_class: str = "unknown"  # free | low | medium | high | unknown
    paid: bool = False
    rank: int = 999
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False
    reject_reason: str = ""


class DecisionRecord(BaseModel):
    decision: str
    candidates: list[str] = Field(default_factory=list)
    selected: str | None = None
    rejected: dict[str, str] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str = ""
    timestamp: str = Field(default_factory=utcnow_iso)


class Plan(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str = ""
    task: TaskSpec | None = None
    classification: Classification = Field(default_factory=Classification)
    required_capabilities: list[str] = Field(default_factory=list)
    skill: SkillRef | None = None
    candidates: list[AgentCandidate] = Field(default_factory=list)
    selected_agent: str | None = None
    selected_model: str | None = None
    selected_connection: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    retry_policy: str = "ADAPTIVE"
    budget: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, bool] = Field(default_factory=dict)
    approval_gates: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow_iso)


class AttemptRecord(BaseModel):
    attempt_id: str
    number: int
    agent: str
    model: str | None = None
    connection: str | None = None
    skill: str | None = None
    workflow: str | None = None
    workspace: str = ""
    environment_fingerprint: str = ""
    started_at: str = Field(default_factory=utcnow_iso)
    finished_at: str | None = None
    status: str = "PENDING"
    patch: str = ""
    patch_fingerprint: str = ""
    changed_files: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    cost: float | None = None
    error: str = ""
    verification: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    verdict: str = "UNKNOWN"  # ACCEPT | REJECT | UNKNOWN
    score: float = 0.0
    regressions: list[str] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    strength: str = "FULL"  # FULL | FALLBACK
    raw: dict[str, Any] = Field(default_factory=dict)


class FailureEvidence(BaseModel):
    new_regressions: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    timeout: bool = False
    scope_violation: bool = False
    build_failure: bool = False
    type_failure: bool = False
    test_failure: bool = False
    no_patch: bool = False
    agent_crash: bool = False
    fingerprint: str = ""


class RunRecord(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    status: RunStatus = RunStatus.CREATED
    task: TaskSpec
    repo: RepoInfo = Field(default_factory=RepoInfo)
    plan: Plan | None = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    result_status: str = ""
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    options: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    approval_requirements: list[dict[str, Any]] = Field(default_factory=list)


class OrchestratorResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    run_id: str
    status: str = ""
    task: TaskSpec | None = None
    repository: RepoInfo | None = None
    plan: Plan | None = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    winning_attempt: str | None = None
    verification: VerificationResult | None = None
    patch: str = ""
    patch_fingerprint: str = ""
    cost: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    fingerprints: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    approval_requirements: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


EventName = Literal[
    "RUN_CREATED",
    "INSPECTION_STARTED",
    "INSPECTION_COMPLETED",
    "PLAN_CREATED",
    "AGENT_SELECTED",
    "PROVIDER_SELECTED",
    "WORKSPACE_READY",
    "ATTEMPT_STARTED",
    "AGENT_EVENT",
    "PATCH_CAPTURED",
    "VERIFICATION_STARTED",
    "VERIFICATION_COMPLETED",
    "RETRY_DECIDED",
    "BUDGET_WARNING",
    "APPROVAL_REQUIRED",
    "RUN_COMPLETED",
    "RUN_FAILED",
    "RUN_CANCELLED",
]
