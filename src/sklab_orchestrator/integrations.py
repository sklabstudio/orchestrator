"""Integration shims: optional SKLab components via Python API or CLI probe.

Never hard-depend. All integrations degrade gracefully to fixture/local behavior.
Secrets are only held in memory; never persisted (see security.py).
"""

from __future__ import annotations

import importlib
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
                return self._via_python(mod)
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
                    import json
                    data = json.loads(out.stdout or "[]")
                    items = data if isinstance(data, list) else data.get("agents", [])
                    result = []
                    for a in items:
                        result.append(AgentInfo(
                            agent_id=str(a.get("id", a.get("agent_id", "unknown"))),
                            installed=True,
                            auth_ready=str(a.get("auth", "")).upper() == "READY",
                            capabilities=list(a.get("capabilities", [])),
                            cost_class=str(a.get("cost_class", "unknown")),
                            paid=bool(a.get("paid", False)),
                        ))
                    if result:
                        return result
            except Exception:
                pass
        return []

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
                    return [AgentInfo(agent_id=str(getattr(a, "agent_id", a)), installed=True)
                            for a in data]
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
        if _cli_available("sklab-connections"):
            try:
                out = subprocess.run(
                    ["sklab-connections", "list", "--json"], capture_output=True,
                    text=True, timeout=15,
                )
                if out.returncode == 0:
                    import json
                    data = json.loads(out.stdout or "[]")
                    items = data if isinstance(data, list) else data.get("connections", [])
                    res = []
                    for c in items:
                        res.append(ConnectionInfo(
                            connection_id=str(c.get("id", "unknown")),
                            enabled=bool(c.get("enabled", False)),
                            ready=bool(c.get("ready", False)),
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
        return _try_import("repocontext") is not None or _cli_available("repo-context")

    @staticmethod
    def inspect(repo_path: str) -> dict[str, Any]:
        if _cli_available("repo-context"):
            try:
                out = subprocess.run(
                    ["repo-context", "inspect", "--repo", repo_path, "--json"],
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
    @staticmethod
    def available() -> bool:
        return _try_import("patchbench") is not None or _cli_available("patchbench")

    @staticmethod
    def verify(patch: str, workspace: str) -> dict[str, Any] | None:
        if _cli_available("patchbench"):
            try:
                import json
                import tempfile
                with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
                    f.write(patch)
                    pf = f.name
                out = subprocess.run(
                    ["patchbench", "verify", "--patch", pf, "--workspace", workspace, "--json"],
                    capture_output=True, text=True, timeout=120,
                )
                try:
                    Path(pf).unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
                if out.returncode in (0, 1, 2) and out.stdout.strip():
                    # find last JSON object in stdout
                    txt = out.stdout.strip().splitlines()
                    for line in reversed(txt):
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict):
                                return data
                        except Exception:
                            continue
            except Exception:
                pass
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
