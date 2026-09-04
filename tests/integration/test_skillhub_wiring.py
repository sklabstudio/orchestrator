"""L3 regression: Orchestrator -> Skill Hub direct wiring (read-only, deterministic)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fake_stack.fakes import (  # noqa: E402
    catalog_full,
    connections_free,
    fake_agent_fn,
    fake_verifier_fn,
)

from sklab_orchestrator import integrations as integ  # noqa: E402
from sklab_orchestrator.config import OrchestratorConfig  # noqa: E402
from sklab_orchestrator.history import PerformanceStore  # noqa: E402
from sklab_orchestrator.integrations import SkillHubIntegration  # noqa: E402
from sklab_orchestrator.runner import AgentRunner  # noqa: E402
from sklab_orchestrator.service import OrchestratorService  # noqa: E402
from sklab_orchestrator.store import RunStore  # noqa: E402
from sklab_orchestrator.verifier import Verifier  # noqa: E402


def _svc(tmp_path, monkeypatch, catalog=catalog_full, conns=connections_free,
         agent_fn=fake_agent_fn, verifier_fn=fake_verifier_fn):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    store = RunStore(root=tmp_path / ".sklab" / "runs")
    return OrchestratorService(
        config=OrchestratorConfig(), store=store,
        runner=AgentRunner(agent_fn=agent_fn),
        verifier=Verifier(verifier_fn=verifier_fn),
        agent_catalog=catalog, connection_catalog=conns,
        perf=PerformanceStore(path=tmp_path / ".sklab" / "perf.jsonl"),
    )


def test_hub_resolve_returns_typed_skills():
    res = SkillHubIntegration.resolve("Fix the failing FastAPI health-check test",
                                      category="bug-fix", limit=3)
    assert res is not None, "Skill Hub should be available in integration env"
    assert res["via"] in ("skill-hub-python-api", "skill-hub-cli-json"), res
    assert res["skills"], res
    top = res["skills"][0]
    for key in ("skill_id", "version", "trust", "risk", "permissions",
                "compatibility", "warnings", "task_score", "category"):
        assert key in top, (key, top)
    assert top["trust"] not in ("BLOCKED", "QUARANTINED"), top


def test_plan_records_hub_selected_skills(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    rec = svc.create_run("Fix the failing FastAPI health-check test", repo="", options={})
    plan = svc.plan_run(rec.run_id)
    hub_decisions = [d for d in plan.decisions if d.decision == "skill_hub_resolution"]
    assert hub_decisions, [d.decision for d in plan.decisions]
    dec = hub_decisions[0]
    assert dec.selected, dec
    assert dec.candidates, dec
    assert any("skill-hub-" in c for c in dec.reason_codes), dec


def test_hub_unavailable_falls_back_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(SkillHubIntegration, "resolve", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(SkillHubIntegration, "available", staticmethod(lambda: False))
    svc = _svc(tmp_path, monkeypatch)
    rec = svc.create_run("Fix the failing FastAPI health-check test", repo="", options={})
    plan = svc.plan_run(rec.run_id)
    assert plan.skill is not None  # builtin resolver still provides a skill
    assert not [d for d in plan.decisions if d.decision == "skill_hub_resolution"]


def test_no_public_to_private_dependency():
    src = (Path(integ.__file__).read_text(encoding="utf-8"))
    assert "sklab_appsec_lab" not in src
    assert "sklab_protocol_intelligence" not in src
    assert "sklab_skill_hub" in src  # PUBLIC -> PUBLIC allowed
    assert "sklab-skills" in src  # CLI fallback is machine-readable JSON


def test_cli_fallback_uses_search_subcommand(monkeypatch):
    """Live-VPS finding: the CLI fallback called a nonexistent `resolve` command."""
    import shutil
    import sys

    if shutil.which("sklab-skills") is None:
        pytest.skip("sklab-skills binary not installed")
    monkeypatch.setitem(sys.modules, "sklab_skill_hub", None)
    res = SkillHubIntegration.resolve("Fix the failing test", category="", limit=3)
    assert res is not None, "search-based CLI fallback must resolve"
    assert res["via"] == "skill-hub-cli-json", res
    assert res["skills"], res
    top = res["skills"][0]
    assert top["skill_id"] and top["trust"] not in ("BLOCKED", "QUARANTINED")
    assert len(res["skills"]) <= 3


def test_uninstalled_adapters_are_not_candidates(monkeypatch):
    """Known-but-absent agents must not become plan candidates (dead-end routing)."""
    import json
    import subprocess

    from sklab_orchestrator.integrations import AgentAdaptersIntegration

    payload = json.dumps({"adapters": [
        {"agent_id": "ghost", "installed": False, "compatibility": "UNAVAILABLE"},
        {"agent_id": "real", "installed": True, "compatibility": "READY"},
    ]})

    class _Out:
        returncode = 0
        stdout = payload
        stderr = ""

    monkeypatch.setattr(integ, "_try_import", lambda *a, **k: None)
    monkeypatch.setattr(integ, "_cli_available", lambda cmd: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Out())
    agents = AgentAdaptersIntegration().list_agents()
    assert [a.agent_id for a in agents] == ["real"]
