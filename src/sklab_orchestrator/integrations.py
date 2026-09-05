"""Integration shims: optional SKLab components via Python API or CLI probe.

Never hard-depend. All integrations degrade gracefully to fixture/local behavior.
Secrets are only held in memory; never persisted (see security.py).
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _try_import(mod: str) -> Any | None:
    try:
        return importlib.import_module(mod)
    except Exception:
        return None


def _cli_available(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@dataclass
class AgentInfo:
    agent_id: str
    installed: bool = False
    auth_ready: bool = False
    auth_state: str = "AUTH_UNKNOWN"
    version: str | None = None
    capabilities: list[str] = field(default_factory=list)
    cost_class: str = "unknown"
    paid: bool = False
    supports_model_selection: bool = False
    supports_resume: bool = False


@dataclass
class ConnectionInfo:
    connection_id: str
    enabled: bool = False
    ready: bool = False
    default_model: str | None = None
    cost_class: str = "unknown"
    paid: bool = False


class AgentAdaptersIntegration:
    """Query installed agents via real adapter package when present, else empty."""

    def list_agents(self) -> list[AgentInfo]:
        mod = _try_import("sklab_agent_adapters")
        if mod is not None:
            try:
                via_python = self._via_python(mod)
                if via_python:
                    return via_python
            except Exception:
                pass
        # CLI probe (zero-cost): list agents if sklab-agents CLI exists
        if _cli_available("sklab-agents"):
            try:
                out = subprocess.run(
                    ["sklab-agents", "list", "--json"], capture_output=True,
                    text=True, timeout=15,
                )
                if out.returncode == 0:
                    data = json.loads(out.stdout or "[]")
                    items = data if isinstance(data, list) else data.get("agents", data.get("adapters", []))
                    result = []
                    for a in items:
                        # Only installed adapters are usable candidates; reporting
                        # known-but-absent agents caused routing to dead ends.
                        if not isinstance(a, dict) or not a.get("installed"):
                            continue
                        agent_id = str(a.get("id", a.get("agent_id", "unknown")))
                        health: dict[str, Any] = {}
                        capabilities: list[str] = list(a.get("capabilities", []))
                        try:
                            detail = self._run_json(["show", agent_id, "--json"])
                            if isinstance(detail, dict):
                                raw_health = detail.get("health")
                                if isinstance(raw_health, dict):
                                    health = raw_health
                        except Exception:
                            pass
                        try:
                            raw_caps = self._run_json(["capabilities", agent_id, "--json"])
                            matrix = raw_caps.get("capabilities") if isinstance(raw_caps, dict) else None
                            if isinstance(matrix, dict):
                                capabilities = [
                                    str(name) for name, info in matrix.items()
                                    if isinstance(info, dict) and info.get("supported") is True
                                ]
                        except Exception:
                            pass
                        auth_state = str(health.get("auth_state", a.get("auth", "AUTH_UNKNOWN"))).upper()
                        result.append(AgentInfo(
                            agent_id=agent_id,
                            installed=True,
                            auth_ready=auth_state == "READY",
                            auth_state=auth_state,
                            version=str(health.get("version") or a.get("version") or "") or None,
                            capabilities=capabilities,
                            cost_class=str(a.get("cost_class", "unknown")),
                            paid=bool(a.get("paid", False)),
                            supports_model_selection="MODEL_SELECTION" in capabilities,
                            supports_resume="SESSION_RESUME" in capabilities,
                        ))
                    if result:
                        return result
            except Exception:
                pass
        return []

    @staticmethod
    def _run_json(args: list[str]) -> Any:
        out = subprocess.run(
            ["sklab-agents", *args], capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout or "null")

    def _via_python(self, mod: Any) -> list[AgentInfo]:
        # Best-effort: try known registry helpers without importing heavy submodules.
        for attr in ("list_agents", "installed_agents", "registry"):
            if hasattr(mod, attr):
                try:
                    fn = getattr(mod, attr)
                    data = fn() if callable(fn) else fn
                    if isinstance(data, list) and data:
                        out = []
                        for a in data:
                            if isinstance(a, dict):
                                out.append(AgentInfo(
                                    agent_id=str(a.get("id", "unknown")),
                                    installed=True,
                                    auth_ready=True,
                                    auth_state="READY",
                                    capabilities=list(a.get("capabilities", [])),
                                    cost_class=str(a.get("cost_class", "unknown")),
                                ))
                        if out:
                            return out
                except Exception:
                    continue
        # Try detection submodule
        det = _try_import("sklab_agent_adapters.detection")
        if det is not None and hasattr(det, "detect_agents"):
            try:
                data = det.detect_agents()  # type: ignore[attr-defined]
                if isinstance(data, list):
                    return [
                        AgentInfo(
                            agent_id=str(getattr(a, "agent_id", a)),
                            installed=True,
                            auth_ready=True,
                            auth_state="READY",
                        )
                        for a in data
                    ]
            except Exception:
                pass
        return []


class ProviderConnectionsIntegration:
    """Inspect provider connections; resolve ephemeral secrets in-memory only."""

    def list_connections(self) -> list[ConnectionInfo]:
        mod = _try_import("sklab_provider_connections")
        if mod is not None:
            try:
                # best effort attribute probe
                for attr in ("list_connections", "installed_connections"):
                    if hasattr(mod, attr):
                        fn = getattr(mod, attr)
                        data = fn() if callable(fn) else fn
                        if isinstance(data, list) and data:
                            return [ConnectionInfo(
                                connection_id=str(getattr(c, "id", c)),
                            ) for c in data]
            except Exception:
                pass
        if _cli_available("sklab-connect"):
            try:
                out = subprocess.run(
                    ["sklab-connect", "list", "--json"], capture_output=True,
                    text=True, timeout=15,
                )
                if out.returncode == 0:
                    import json
                    data = json.loads(out.stdout or "[]")
                    items = data if isinstance(data, list) else data.get(
                        "connections", data.get("data", []))
                    res = []
                    for c in items:
                        status = str(c.get("status", "")).upper()
                        res.append(ConnectionInfo(
                            connection_id=str(c.get("id", "unknown")),
                            enabled=bool(c.get("enabled", False)),
                            ready=bool(c.get("ready", False)) or status == "READY",
                            default_model=c.get("default_model"),
                        ))
                    if res:
                        return res
            except Exception:
                pass
        return []

    def ephemeral_env(self, connection_id: str) -> tuple[dict[str, str], list[str]]:
        """Return (env, redaction_values). Real impl delegates; default empty (no secrets)."""
        mod = _try_import("sklab_provider_connections")
        if mod is not None:
            try:
                secrets_mod = _try_import("sklab_provider_connections.secrets")
                if secrets_mod is not None and hasattr(secrets_mod, "ephemeral_env"):
                    return secrets_mod.ephemeral_env(connection_id)  # type: ignore[no-any-return]
            except Exception:
                pass
        return {}, []


class RepoContextIntegration:
    @staticmethod
    def available() -> bool:
        return _try_import("repocontext") is not None or _cli_available("repocontext")

    @staticmethod
    def inspect(repo_path: str) -> dict[str, Any]:
        if _cli_available("repocontext"):
            try:
                out = subprocess.run(
                    ["repocontext", "inspect", repo_path, "--json"],
                    capture_output=True, text=True, timeout=30,
                )
                if out.returncode == 0:
                    import json
                    data = json.loads(out.stdout or "{}")
                    if isinstance(data, dict) and data:
                        return data
            except Exception:
                pass
        # minimal git/project fallback (no duplication of full RepoContext)
        info: dict[str, Any] = {"available": False}
        try:
            p = Path(repo_path)
            info["exists"] = p.exists()
            if (p / ".git").exists():
                out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(p),
                                     capture_output=True, text=True, timeout=10)
                if out.returncode == 0:
                    info["head"] = out.stdout.strip()
                out2 = subprocess.run(["git", "branch", "--show-current"], cwd=str(p),
                                      capture_output=True, text=True, timeout=10)
                if out2.returncode == 0:
                    info["branch"] = out2.stdout.strip()
        except Exception:
            pass
        return info


class ReproBoxIntegration:
    @staticmethod
    def available() -> bool:
        return _try_import("reprobox") is not None or _cli_available("reprobox")

    @staticmethod
    def fingerprint(workspace: str) -> str:
        if _cli_available("reprobox"):
            try:
                out = subprocess.run(
                    ["reprobox", "fingerprint", "--workspace", workspace],
                    capture_output=True, text=True, timeout=15,
                )
                if out.returncode == 0 and out.stdout.strip():
                    return out.stdout.strip()[:64]
            except Exception:
                pass
        import hashlib
        return hashlib.sha256(f"local|{workspace}".encode()).hexdigest()[:16]


class PatchBenchIntegration:
    """Canonical PatchBench verification contract (v0.1).

    Primary: typed Python API ``patchbench.commands.evaluate.run_evaluation``
    (returns ``EvaluationResult`` with ``verdict`` ACCEPT/REVIEW/REJECT/
    INCONCLUSIVE and ``score``). Fallback: machine-readable
    ``patchbench evaluate --json`` CLI. The ``via`` key records which path
    produced the result, so a broken primary is never silently hidden.
    Returns None only when PatchBench is absent or both paths fail, letting
    the caller use its local fallback explicitly.
    """

    @staticmethod
    def available() -> bool:
        return _try_import("patchbench") is not None or _cli_available("patchbench")

    @staticmethod
    def verify(patch: str, workspace: str, timeout: int = 120) -> dict[str, Any] | None:
        import tempfile

        if not patch or not patch.strip():
            # Nothing to verify: let the caller use its explicit fallback.
            return None
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
            f.write(patch)
            pf = f.name
        try:
            via_python = PatchBenchIntegration._verify_python_api(pf, workspace, timeout)
            if via_python is not None:
                return via_python
            return PatchBenchIntegration._verify_cli(pf, workspace, timeout)
        finally:
            try:
                Path(pf).unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass

    @staticmethod
    def _verify_python_api(patch_file: str, workspace: str, timeout: int) -> dict[str, Any] | None:
        try:
            from patchbench.commands.evaluate import run_evaluation
            from patchbench.core.config import PatchBenchConfig
        except Exception:
            return None
        try:
            cfg = PatchBenchConfig()
            cfg = cfg.apply_cli_overrides(timeout=timeout, offline=True)
            result, baseline_log, candidate_log, _ = run_evaluation(
                repo=workspace, patch=patch_file, config=cfg,
            )
        except Exception:
            return None
        try:
            verdict = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
            return {
                "verdict": str(verdict).upper(),
                "score": float(getattr(result, "score", 0) or 0),
                "verdict_reason": str(getattr(result, "verdict_reason", "")),
                "new_regressions": getattr(result, "new_regressions", 0) or 0,
                "baseline_failures": getattr(result, "baseline_failures", 0) or 0,
                "via": "patchbench-python-api",
            }
        except Exception:
            return None

    @staticmethod
    def _verify_cli(patch_file: str, workspace: str, timeout: int) -> dict[str, Any] | None:
        if not _cli_available("patchbench"):
            return None
        try:
            import json
            out = subprocess.run(
                ["patchbench", "evaluate", "--patch", patch_file,
                 "--repo", workspace, "--json", "--offline",
                 "--timeout", str(timeout)],
                capture_output=True, text=True, timeout=timeout + 60,
            )
            if not out.stdout.strip():
                return None
            data: dict[str, Any] | None = None
            try:
                whole = json.loads(out.stdout)
                if isinstance(whole, dict) and "verdict" in whole:
                    data = whole
            except Exception:
                data = None
            if data is None:
                for line in reversed(out.stdout.strip().splitlines()):
                    try:
                        candidate = json.loads(line)
                        if isinstance(candidate, dict) and "verdict" in candidate:
                            data = candidate
                            break
                    except Exception:
                        continue
            if data is None:
                return None
            return {
                "verdict": str(data.get("verdict", "UNKNOWN")).upper(),
                "score": float(data.get("score", 0) or 0),
                "verdict_reason": str(data.get("verdict_reason", "")),
                "new_regressions": data.get("new_regressions", 0) or 0,
                "baseline_failures": data.get("baseline_failures", 0) or 0,
                "schema_version": data.get("schema_version"),
                "via": "patchbench-cli-json",
            }
        except Exception:
            return None


class BenchSuiteIntegration:
    @staticmethod
    def available() -> bool:
        return _cli_available("benchsuite") or _try_import("benchsuite") is not None

    @staticmethod
    def load_task(task_id: str) -> dict[str, Any] | None:
        if _cli_available("benchsuite"):
            try:
                import json
                out = subprocess.run(
                    ["benchsuite", "show", task_id, "--json"],
                    capture_output=True, text=True, timeout=15,
                )
                if out.returncode == 0 and out.stdout.strip():
                    return json.loads(out.stdout)
            except Exception:
                pass
        return None


class SkillHubIntegration:
    """Typed Skill Hub adapter: task-aware skill resolution for plans.

    Primary: ``sklab_skill_hub.service.resolve_for_task`` (deterministic,
    machine-readable). Fallback: ``sklab-skills search --json`` CLI
    (typed skill records — never human/Rich output; limit applied client-side).
    Read-only: never installs, enables, or auto-executes skills. The hub's own
    resolver excludes QUARANTINED/BLOCKED/DISABLED records, so unsafe community
    skills are never selected automatically. Returns None when unavailable so
    planning falls back to the builtin skill resolver gracefully.
    """

    @staticmethod
    def available() -> bool:
        return _try_import("sklab_skill_hub") is not None or _cli_available("sklab-skills")

    @staticmethod
    def version() -> str | None:
        mod = _try_import("sklab_skill_hub")
        if mod is not None:
            ver = getattr(mod, "__version__", None)
            return str(ver) if ver else "unknown"
        return None

    @staticmethod
    def resolve(task: str, category: str = "",
                required_capabilities: list[str] | None = None,
                agent_capabilities: list[str] | None = None,
                limit: int = 5) -> dict[str, Any] | None:
        via_python = SkillHubIntegration._resolve_python_api(
            task, category, required_capabilities, agent_capabilities, limit)
        if via_python is not None:
            return via_python
        return SkillHubIntegration._resolve_cli(
            task, category, required_capabilities, limit)

    @staticmethod
    def _normalize(records: list[Any], via: str, version: str | None) -> dict[str, Any] | None:
        skills: list[dict[str, Any]] = []
        for h in records:
            if not isinstance(h, dict):
                continue
            skills.append({
                "skill_id": str(h.get("skill_id", h.get("id", "unknown"))),
                "version": str(h.get("version", "0.1.0")),
                "trust": str(h.get("trust", "UNKNOWN")),
                "risk": str(h.get("risk", "UNKNOWN")),
                "permissions": h.get("permissions", {}),
                "compatibility": h.get("compatibility", h.get("category", "")),
                "warnings": list(h.get("warnings", []) or []),
                "task_score": float(h.get("task_score", h.get("score", 0.0)) or 0.0),
                "category": str(h.get("category", "")),
            })
        if not skills:
            return None
        return {"available": True, "version": version, "via": via, "skills": skills}

    @staticmethod
    def _resolve_python_api(task: str, category: str,
                            required_capabilities: list[str] | None,
                            agent_capabilities: list[str] | None,
                            limit: int) -> dict[str, Any] | None:
        try:
            from sklab_skill_hub import service
            from sklab_skill_hub.store import resolve_data_dir
        except Exception:
            return None
        try:
            data_dir = resolve_data_dir()
            hits = service.resolve_for_task(
                data_dir, task, category, required_capabilities, agent_capabilities, limit)
        except Exception:
            return None
        if not isinstance(hits, list) or not hits:
            return None
        return SkillHubIntegration._normalize(
            hits, "skill-hub-python-api", SkillHubIntegration.version())

    _SEARCH_STOPWORDS = frozenset(
        "with that this from into over under after before between through "
        "have has had will would should could been were what when where "
        "which their there then than them they your yours ours only also "
        "very just need needs using used make made many much such each other "
        "failing fail error issue problem please help".split()
    )

    @staticmethod
    def _search_hub(query: str) -> list[dict[str, Any]]:
        """One machine-readable hub search; [] on any failure (never raises)."""
        try:
            import json
            out = subprocess.run(
                ["sklab-skills", "search", query, "--json"],
                capture_output=True, text=True, timeout=30)
            if out.returncode != 0 or not out.stdout.strip():
                return []
            data = json.loads(out.stdout)
            items = data if isinstance(data, list) else data.get("skills", data.get("data", []))
            return [h for h in items] if isinstance(items, list) else []
        except Exception:
            return []

    @staticmethod
    def _resolve_cli(task: str, category: str,
                     required_capabilities: list[str] | None,
                     limit: int) -> dict[str, Any] | None:
        if not _cli_available("sklab-skills"):
            return None
        try:
            import re
            # NOTE: there is no `resolve` subcommand; `search --json` emits the
            # typed builtin+installed registry but matches substrings only, so a
            # full-sentence task rarely hits. Keyword fallback keeps the CLI path
            # task-aware (python API remains primary where importable).
            seen: dict[str, dict[str, Any]] = {}
            for h in SkillHubIntegration._search_hub(task):
                if isinstance(h, dict):
                    seen.setdefault(str(h.get("skill_id", h.get("id", "unknown"))), h)
            if not seen and task:
                tokens = [t for t in re.findall(r"[a-z0-9]+", task.lower())
                          if len(t) >= 4 and t not in SkillHubIntegration._SEARCH_STOPWORDS][:5]
                for tok in tokens:
                    for h in SkillHubIntegration._search_hub(tok):
                        if isinstance(h, dict):
                            seen.setdefault(str(h.get("skill_id", h.get("id", "unknown"))), h)
                    if seen:
                        break
            items = list(seen.values())
            if not items:
                return None
            if category:
                wanted = category.strip().lower()
                filtered = [h for h in items
                            if str(h.get("category", "")).strip().lower() == wanted]
                if filtered:
                    items = filtered
            items = items[: max(1, limit)]
            return SkillHubIntegration._normalize(items, "skill-hub-cli-json", None)
        except Exception:
            return None


class CodingLabIntegration:
    @staticmethod
    def available() -> bool:
        return _cli_available("coding-lab") or Path("coding-lab").exists()

    @staticmethod
    def workflow_for(skill_id: str) -> dict[str, Any]:
        # Record workflow id/fingerprint without hard dependency.
        import hashlib
        fp = hashlib.sha256(f"coding-lab|{skill_id}".encode()).hexdigest()[:16]
        return {"workflow_id": skill_id, "workflow_fingerprint": fp,
                "available": CodingLabIntegration.available()}
