# Changelog

## 0.1.0

Implemented:

- `sklab-run` CLI (`task, inspect, plan, execute, resume, status, history,
  show, cancel, doctor, clean, retry, explain`) with `--json` machine output.
- Explicit persisted state machine with crash/quota resume.
- Task normalization, deterministic classification, capability mapping.
- Agent selection with cheap-first routing, user overrides, budget/approval gates.
- Lightweight skill resolver with 9 built-in core skills + permission model.
- Isolated workspaces (original repo untouched), ReproBox integration with fallback.
- Agent execution via Agent Adapters; Provider Connections ephemeral secrets
  (never persisted).
- PatchBench verification with explicit fallback; evidence-driven retry,
  escalation, NO_PROGRESS loop prevention, fingerprints.
- Events JSONL, history/performance store, Python service API (Web-UI ready).
- Deterministic fake stack + 39 tests; Ruff/mypy/build green.

Not claimed: real-agent benchmarks, remote Skill Hub auto-install, auto-push.
