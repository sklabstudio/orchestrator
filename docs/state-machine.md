# State Machine

States: `CREATED, INSPECTING, PLANNING, WAITING_FOR_APPROVAL, PREPARING,
RUNNING_AGENT, CAPTURING_PATCH, VERIFYING, ANALYZING_FAILURE, RETRYING,
COMPLETED, FAILED, CANCELLED, BLOCKED`.

`state_machine.py` defines `ALLOWED` transitions; `store.transition()`
enforces them and persists to `run.json`. Terminal: completed/failed/
cancelled/blocked. Cancellation is out-of-band (owned workspaces only).
Resume is idempotent: `CAPTURING_PATCH/VERIFYING` with unverified attempt →
verify without rerun; `RUNNING_AGENT` with unfinished attempt → drop and
continue; otherwise continue numbering from `len(attempts)`.
Events mirror transitions in `events.jsonl`.
