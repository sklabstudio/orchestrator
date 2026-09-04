# Retries

`analyze_failure()` normalizes regressions/failed checks/timeout/scope/build/
type/test/no-patch/crash + `failure_fingerprint`. `render_retry_evidence()`
passes only trusted verifier output to the next attempt ("fix ONLY these").

`next_action(policy, n, max, evidence, ordered, current, no_progress)`:
`NONE`→stop; `SAME_AGENT`→retry; `ESCALATE`→next; `ADAPTIVE`→ same for fixable,
next for crash/timeout/no-patch. `detect_no_progress()`: identical patch fp,
identical failure fp, or 3× same terminal status → `NO_PROGRESS`. Max attempts
always enforced. Duplicate patch avoids wasted verification in future work
(recorded; currently still verified once for evidence).
