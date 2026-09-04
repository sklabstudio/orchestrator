"""Independent verification: PatchBench when available, else explicit fallback checks."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sklab_orchestrator.integrations import PatchBenchIntegration
from sklab_orchestrator.models import VerificationResult

VerifierFn = Callable[[str, str], dict[str, Any]]


def _fallback_checks(workspace: str, required_checks: list[str] | None = None) -> VerificationResult:
    """Run only explicit project checks supported by evidence (never invent commands)."""
    checks: list[dict[str, Any]] = []
    candidates: list[list[str]] = []
    ws = Path(workspace)
    # Evidence-based detection only:
    if (ws / "pytest.ini").exists() or (ws / "pyproject.toml").exists() or list(ws.glob("test_*.py")) or list(ws.glob("tests")):
        # only claim pytest if config suggests it; run quickly with -x -q on collection?
        candidates.append(["python", "-m", "pytest", "-q", "-x", "--co", "-q"])
    if (ws / "package.json").exists():
        candidates.append(["npm", "test", "--", "--passWithNoTests"])
    if required_checks:
        for c in required_checks:
            parts = c.split()
            if parts and parts not in candidates:
                candidates.append(parts)
    if not candidates:
        return VerificationResult(
            verdict="UNKNOWN", score=0.0, warnings=["no verifiable checks detected"],
            strength="FALLBACK",
            checks=[{"name": "none", "passed": None, "detail": "no evidence for checks"}],
        )
    all_pass = True
    for cmd in candidates[:3]:
        try:
            out = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True, timeout=120)
            passed = out.returncode == 0
            all_pass = all_pass and passed
            checks.append({"name": " ".join(cmd), "passed": passed,
                           "detail": (out.stdout[-500:] + out.stderr[-500:])[-1000:]})
        except FileNotFoundError:
            checks.append({"name": " ".join(cmd), "passed": None, "detail": "tool not installed"})
        except subprocess.TimeoutExpired:
            all_pass = False
            checks.append({"name": " ".join(cmd), "passed": False, "detail": "timeout"})
        except Exception as e:  # noqa: BLE001
            checks.append({"name": " ".join(cmd), "passed": None, "detail": str(e)})
    verdict = "ACCEPT" if all_pass and checks else "REJECT"
    score = 75.0 if verdict == "ACCEPT" else 40.0
    return VerificationResult(verdict=verdict, score=score, checks=checks,
                              warnings=["verification_strength: FALLBACK"], strength="FALLBACK")


class Verifier:
    def __init__(self, verifier_fn: VerifierFn | None = None):
        self.verifier_fn = verifier_fn

    def verify(self, patch: str, workspace: str,
               required_checks: list[str] | None = None) -> VerificationResult:
        if self.verifier_fn is not None:
            try:
                raw = self.verifier_fn(patch, workspace)
                return VerificationResult(
                    verdict=str(raw.get("verdict", "UNKNOWN")),
                    score=float(raw.get("score", 0.0)),
                    regressions=list(raw.get("regressions", [])),
                    checks=list(raw.get("checks", [])),
                    warnings=list(raw.get("warnings", [])),
                    strength=str(raw.get("strength", "FULL")),
                    raw=dict(raw),
                )
            except Exception as e:  # noqa: BLE001
                return VerificationResult(verdict="REJECT", score=0.0,
                                          warnings=[f"verifier error: {e}"], strength="FALLBACK")
        # Try real PatchBench (canonical Python API, else machine-readable JSON CLI), else fallback
        try:
            data = PatchBenchIntegration.verify(patch, workspace)
            if isinstance(data, dict) and data:
                warnings = list(data.get("warnings", []))
                if data.get("via"):
                    warnings.append(f"verification_via: {data['via']}")
                if data.get("verdict_reason"):
                    warnings.append(f"patchbench: {data['verdict_reason']}")
                return VerificationResult(
                    verdict=str(data.get("verdict", data.get("result", "UNKNOWN"))).upper(),
                    score=float(data.get("score", 0.0)),
                    regressions=list(data.get("regressions", [])),
                    checks=list(data.get("checks", [])),
                    warnings=warnings,
                    strength="FULL", raw=data,
                )
        except Exception:
            pass
        return _fallback_checks(workspace, required_checks)
