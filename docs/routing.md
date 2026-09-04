# Routing

Score = capabilities satisfied + installed/auth + category preference +
cost class + user rank. Ranks deterministic; ties by agent id.

Cost policies: `FREE_ONLY` (free only), `CHEAP_FIRST` (free→paid, default),
`BALANCED`, `QUALITY_FIRST` (strong first), `MANUAL`. User `--agent/--model/
--connection` pins selection; incompatible pin fails clearly. `local_only`
filters to free; `free_only` never escalates to paid. Escalation order is the
planned `ordered_ids` with selected first; user pin disables silent escalation.

Every selection/escalation emits `DecisionRecord{decision,candidates,selected,
rejected,reason_codes,explanation}` and `RETRY_DECIDED` events.
