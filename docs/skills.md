# Skills

`SkillResolver` (builtin only in v0.1.0): 9 skills — repo-understand, bug-fix,
feature-build, test-first, debug-test-failure, code-review, refactor-safe,
ci-fix, release-check. Each: `id/version/category/required_capabilities/risk/
instructions/source`. Category→skill map; `--skill` override validated.
`permissions(skill)` → `{files_read/write,shell,git,network,docker,secrets}`;
`compute_effective_permissions()` intersects with `SAFE/NORMAL/POWER`
(`SAFE`: no network/docker/secrets; `NORMAL`: no docker/secrets; secrets never
granted). Coding Lab workflows recorded as id/fingerprint. Hub trust
(`BUILTIN/VERIFIED/COMMUNITY`) + auto-install (`OFF/SAFE/SMART/FULL`) are
interfaces only — no remote install in v0.1.0.
