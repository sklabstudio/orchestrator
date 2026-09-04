# SKLab Orchestrator

**Give SKLab a task. It coordinates the context, agent, provider, environment, retries, and verification.**

> Understand first. Choose deliberately. Execute safely. Verify independently.
> Retry from evidence. Spend only when needed. Return proof, not claims.

Quick example:

```bash
sklab-run plan \
  --repo ./project \
  --instruction "Fix the failing login timeout test"

sklab-run task \
  --repo ./project \
  --instruction "Fix the failing login timeout test"
```

## Why

The SKLab ecosystem already has specialized tools (RepoContext, Agent Adapters,
Provider Connections, ReproBox, PatchBench, CodeTrials, PromptBench, BenchSuite).
The user should not manually chain them. Orchestrator is the brain that:

1. inspects the repo, 2. classifies the task, 3. resolves capabilities/skills,
4. picks the cheapest capable agent, 5. runs it isolated, 6. verifies independently,
7. retries from evidence, 8. returns proof.

The agent proposes. SKLab decides, verifies, and controls the loop.

## Architecture

```
User Task -> Intake -> Inspect (RepoContext) -> Classify -> Capabilities
 -> Skills -> Agent candidates -> Provider/Connection -> Budget/Policy
 -> Workspace (ReproBox) -> Agent run -> Patch capture
 -> Verify (PatchBench) -> Analyze -> Retry/Escalate/Stop -> Verified result
```

See `docs/architecture.md`, `docs/state-machine.md`, `docs/routing.md`.

## Installation

```bash
pip install sklab-orchestrator
# or from source:
pip install -e ".[dev]"
sklab-run --version
sklab-run doctor
```

Requires Python 3.12+.

## Quick Start

```bash
sklab-run task --repo ./project --instruction "Fix the login timeout bug and add regression coverage"
sklab-run history
sklab-run show <run-id>
```

Safe defaults: isolated workspace, `auto_apply_patch: false`, `auto_push: false`,
`CHEAP_FIRST` routing, `max_attempts: 3`, verification on.

## Planning

```bash
sklab-run plan --repo ./project --instruction "Fix bug" --json
```

Read-only: no model inference, no repo mutation. Shows classification,
capabilities, skill, candidate agents, connection, environment, verification,
retry policy, budget, approval gates.

`--dry-run` on `task` does inspection+planning+budget only.

## Agent Routing

Deterministic scoring: required capabilities, installed/readiness, auth,
category preference, cost class, user preference, resume support.
Default `CHEAP_FIRST`: free/local first, verify, escalate only on evidence.
Policies: `FREE_ONLY, CHEAP_FIRST, BALANCED, QUALITY_FIRST, MANUAL`.
Explicit `--agent/--model/--connection/--skill` overrides auto-routing;
incompatible overrides fail clearly (never silent fallback).

## Provider Connections

Uses `provider-connections` when installed (list enabled/ready, default model,
ephemeral secret env). Secrets stay in-memory, never persisted; redaction
metadata scrubs logs/state. See `docs/security.md`.

## Cost Policies

```yaml
budget: {max_cost: 1.00, currency: USD, max_attempts: 3, max_total_minutes: 30}
```

Unknown costs → `cost_status: UNKNOWN` (conservative). Paid use without
`approved_paid` → `APPROVAL_REQUIRED`, no paid call. Never purchases
subscriptions or bypasses quotas.

## Skills/Workflows

Built-in: `repo-understand, bug-fix, feature-build, test-first,
debug-test-failure, code-review, refactor-safe, ci-fix, release-check`.
Resolver maps category → skill; Coding Lab workflows recorded as
`workflow_id/fingerprint` when available. Future Skill Hub trust states
(`BUILTIN/VERIFIED/COMMUNITY`) and auto-install (`OFF/SAFE/SMART/FULL`)
are interfaces only in v0.1.0 (no remote auto-install).

## ReproBox

Preferred hermetic env (fingerprint, limits, isolation). Fallback local
execution warns `LOCAL_EXECUTION_NOT_HERMETIC`. Workspaces are temp
copies; original repo never mutated; `auto_apply_patch: false` by default.

## Verification

PatchBench (machine JSON) when available, else explicit fallback checks only
(`pytest`, `npm test`, … detected from evidence; never invented).
`verification_strength: FALLBACK` when degraded. `VERIFIED_SUCCESS` requires
independent `ACCEPT`; agent "done" alone → `EXECUTION_SUCCESS_VERIFICATION_FAIL`.

## Retry Strategy

Policies `NONE/SAME_AGENT/ESCALATE/ADAPTIVE` (default `ADAPTIVE`):
fixable failure → same agent + exact evidence; capability/no-progress →
next agent; budget exhausted → stop. Loop prevention via patch/failure
fingerprints → `NO_PROGRESS`. Max attempts enforced. See `docs/retries.md`.

## Run State / Resume

```
.sklab/runs/<run-id>/{run.json,plan.json,events.jsonl,attempts.jsonl,result.json,artifacts/}
```

Explicit state machine (`CREATED…BLOCKED`), persisted transitions,
crash/quota/restart resumable via `sklab-run resume <run-id>`.
Events (`RUN_CREATED…RUN_CANCELLED`) are JSONL for future Web UI.

## Security Model

Repo content is untrusted data (injection quarantined, never policy).
No secret persistence, no quota bypass, no paid escalation without policy,
no auto-push, least-privilege permissions per skill/policy. See `docs/security.md`.

## Integrations

Optional adapters (all degrade gracefully): RepoContext, Agent Adapters,
Provider Connections, ReproBox, PatchBench, BenchSuite (`--bench`),
Coding Lab, CodeTrials handoff, PromptBench (out of loop). `sklab-run doctor`
does zero-cost detection. See `docs/integrations.md`.

## Web UI API

Python API: `create_run, inspect_run, plan_run, execute_run, stream_events,
cancel_run, resume_run, get_history, get_result` (`OrchestratorService`).
CLI is a thin layer. No Web UI built here.

## Limitations

- No remote Skill Hub auto-install; no auto-push/deploy; no RL learning
  (local stats only); hostile-code sandbox is ReproBox/container, VM stronger.
- Verification fallback is weaker than PatchBench; unknown costs conservative.

## Roadmap

Skill Hub verified registry, Contract/Cyber packs, richer cost telemetry,
Web UI, CodeTrials auto-escalation policies.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src
python -m build
```

## License

MIT — Copyright (c) 2026 SKLab Studio. See `LICENSE`.
