# Demo

```bash
sklab-run doctor
sklab-run plan --repo ./project --instruction "Fix the failing login timeout test"
sklab-run task --repo ./project --instruction "Fix the failing login timeout test" --json
sklab-run history --json
sklab-run show <run-id> --json
```

Dogfoods (fixture, offline): first-try success (1 attempt, premium untouched);
retry with evidence (attempt-2 prompt contains `pytest login_timeout`);
escalation (bad→premium with approval); approval gate (paid-only, no approval
→ `APPROVAL_REQUIRED`, zero calls); resume (crash after `PATCH_CAPTURED` →
verify without rerun). See `docs/progress.md`.
