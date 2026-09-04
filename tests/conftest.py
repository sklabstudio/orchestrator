"""Shared fixtures: isolated store + service with fake stack."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ensure src importable without install
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
TESTS = Path(__file__).resolve().parents[0]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from fake_stack.fakes import (  # noqa: E402
    catalog_full,
    connections_free,
    fake_agent_fn,
    fake_verifier_fn,
)

from sklab_orchestrator.config import OrchestratorConfig  # noqa: E402
from sklab_orchestrator.history import PerformanceStore  # noqa: E402
from sklab_orchestrator.runner import AgentRunner  # noqa: E402
from sklab_orchestrator.service import OrchestratorService  # noqa: E402
from sklab_orchestrator.store import RunStore  # noqa: E402
from sklab_orchestrator.verifier import Verifier  # noqa: E402


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    root = tmp_path / ".sklab" / "runs"
    monkeypatch.chdir(tmp_path)
    return RunStore(root=root)


@pytest.fixture()
def svc(tmp_store, tmp_path):
    return OrchestratorService(
        config=OrchestratorConfig(),
        store=tmp_store,
        runner=AgentRunner(agent_fn=fake_agent_fn),
        verifier=Verifier(verifier_fn=fake_verifier_fn),
        agent_catalog=catalog_full,
        connection_catalog=connections_free,
        perf=PerformanceStore(path=tmp_path / ".sklab" / "perf.jsonl"),
    )
