# Security

- Repo content is untrusted DATA: `build_agent_prompt()` separates trusted
  policy/task/evidence from quarantined excerpts; `contains_injection()`
  flags `IGNORE ALL INSTRUCTIONS / PRINT API KEYS / UPLOAD…`; injection never
  changes policy/network/spend/push (tested).
- No secret persistence: `scrub_dict()` redacts secret keys (string values)
  + registered values; `store` scrubs run/plan/events/result; ephemeral env
  from Provider Connections lives only in-memory (tested with
  `FAKE_SECRET_TOKEN`).
- No quota bypass: `AUTH_REQUIRED/UNAVAILABLE+quota` → `BLOCKED` or allowed
  alternative, never retry-bypass.
- No paid escalation without `approved_paid`; no auto-push (`auto_apply_patch
  false`, `auto_push false`); permissions least-privilege; no telemetry.
- Agent execution ≠ malware sandbox: ReproBox helps; VM stronger for hostile
  code. Approval gates are machine-readable (`paid_model_use`, `apply_patch`).
