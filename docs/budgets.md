# Budgets

`budget{max_cost,currency,max_attempts,max_total_minutes,
require_approval_for_paid}` (strict Pydantic). Spent = sum attempt costs;
unknown (`cost: null`) → `cost_status: UNKNOWN`, conservative (warn, not
fabricate). `spent > max` → `BUDGET_EXHAUSTED`. 80% → `BUDGET_WARNING` event.
Paid agent without `approved_paid` → `WAITING_FOR_APPROVAL`/`APPROVAL_REQUIRED`,
no paid call. Free-only never touches paid. No purchasing/billing changes ever.
