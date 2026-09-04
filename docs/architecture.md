# Architecture

`OrchestratorService` (`service.py`) coordinates; CLI (`cli.py`) is thin.

Modules: `models` (TaskSpec/Plan/Attempt/Result), `state_machine` (explicit
transitions), `store` (`.sklab/runs/<id>/`), `planning` (normalize/classify/
capabilities), `routing` (candidates/cost/budget), `skills` (resolver),
`integrations` (optional adapters), `workspace` (isolated copy), `runner`
(agent exec), `verifier` (PatchBench/fallback), `retry` (analyze/policy),
`history` (PerformanceStore), `security` (redaction/injection boundary).

Flow: intake → inspect → plan → approval/budget gate → prepare workspace →
attempt loop (run → capture → verify → analyze → retry/escalate/stop) →
finalize result. All decisions persisted as `DecisionRecord` with reasons.
Secrets only in-memory at execution boundary.
