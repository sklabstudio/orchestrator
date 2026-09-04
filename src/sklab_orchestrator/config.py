"""Strict configuration model (sklab-orchestrator.yaml)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class RoutingMode(StrEnum):
    FREE_ONLY = "free_only"
    CHEAP_FIRST = "cheap_first"
    BALANCED = "balanced"
    QUALITY_FIRST = "quality_first"
    MANUAL = "manual"


class ExecutionPolicy(StrEnum):
    SAFE = "SAFE"
    NORMAL = "NORMAL"
    POWER = "POWER"


class RetryPolicyName(StrEnum):
    NONE = "NONE"
    SAME_AGENT = "SAME_AGENT"
    ESCALATE = "ESCALATE"
    ADAPTIVE = "ADAPTIVE"


class RoutingCategoryConfig(BaseModel):
    preferred_agents: list[str] = Field(default_factory=list)


class RoutingConfig(BaseModel):
    mode: RoutingMode = RoutingMode.CHEAP_FIRST
    preferred_agents: list[str] = Field(default_factory=list)
    categories: dict[str, RoutingCategoryConfig] = Field(default_factory=dict)


class ExecutionConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1, le=20)
    default_timeout_seconds: int = Field(default=1800, ge=1, le=86400)
    use_reprobox: bool = True
    policy: ExecutionPolicy = ExecutionPolicy.NORMAL
    retry_policy: RetryPolicyName = RetryPolicyName.ADAPTIVE
    auto_apply_patch: bool = False


class VerificationConfig(BaseModel):
    provider: str = "patchbench"


class BudgetConfig(BaseModel):
    max_cost: float | None = Field(default=1.00, ge=0)
    currency: str = "USD"
    max_attempts: int = Field(default=3, ge=1, le=20)
    max_total_minutes: int = Field(default=30, ge=1, le=1440)
    require_approval_for_paid: bool = True


class SkillsConfig(BaseModel):
    builtin: bool = True
    coding_lab: bool = True
    extra_dirs: list[str] = Field(default_factory=list)


class SafetyConfig(BaseModel):
    auto_apply_patch: bool = False
    auto_push: bool = False
    deployment: bool = False


class OrchestratorConfig(BaseModel):
    schema_version: int = 1
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @field_validator("schema_version")
    @classmethod
    def _check_schema(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unsupported schema_version: {v}")
        return v


DEFAULT_CONFIG = OrchestratorConfig()


def load_config(path: str | Path | None = None) -> OrchestratorConfig:
    """Load config from YAML file; return defaults when missing."""
    if path is None:
        # search order: cwd, .sklab, home
        candidates = [
            Path.cwd() / "sklab-orchestrator.yaml",
            Path.cwd() / ".sklab" / "sklab-orchestrator.yaml",
        ]
        for c in candidates:
            if c.exists():
                path = c
                break
        else:
            return OrchestratorConfig()
    p = Path(path)
    if not p.exists():
        return OrchestratorConfig()
    data: Any = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # normalize routing.mode case-insensitively
    if isinstance(data, dict) and isinstance(data.get("routing"), dict):
        mode = data["routing"].get("mode")
        if isinstance(mode, str):
            data["routing"]["mode"] = mode.lower()
    return OrchestratorConfig.model_validate(data)


def find_config_file(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    for c in [Path.cwd() / "sklab-orchestrator.yaml"]:
        if c.exists():
            return c
    return None
