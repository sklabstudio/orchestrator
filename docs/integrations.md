# Integrations

All optional, zero-cost detection, graceful fallback (never hard-depend):

- RepoContext: Python `repocontext` or `repo-context inspect --json`; fallback
  minimal git/project inspection; records `repo/context_fingerprint`.
- Agent Adapters: Python API probe or `sklab-agents list --json`; never call
  native CLIs directly when adapters available.
- Provider Connections: list enabled/ready, default model, `ephemeral_env()`
  → `(env, redact)` in-memory only.
- ReproBox: `reprobox fingerprint`; else local + `LOCAL_EXECUTION_NOT_HERMETIC`.
- PatchBench: `patchbench verify --json` (last JSON line); else evidence-based
  fallback checks (`pytest -q`, `npm test`, explicit `--required-checks`),
  marked `FALLBACK`.
- BenchSuite: `--bench <id>` via `benchsuite show --json`; preserves task/
  baseline fingerprints.
- Coding Lab: workflow id/fingerprint recorded, no hard dep.
- CodeTrials: `codetrials_handoff()` payload; comparison delegated.
- PromptBench: out of normal loop by design.
