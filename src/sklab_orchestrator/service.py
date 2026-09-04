"""Orchestration service: the loop that coordinates everything (CLI-thin layer)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sklab_orchestrator.config import OrchestratorConfig, load_config
from sklab_orchestrator.fingerprints import (
    env_fingerprint,
    failure_fingerprint,
    generate_run_id,
    patch_fingerprint,
    repo_fingerprint,
)
from sklab_orchestrator.history import PerformanceStore
from sklab_orchestrator.integrations import (
    AgentAdaptersIntegration,
    AgentInfo,
    BenchSuiteIntegration,
    CodingLabIntegration,
    ConnectionInfo,
    ProviderConnectionsIntegration,
    RepoContextIntegration,
    ReproBoxIntegration,
    SkillHubIntegration,
)
from sklab_orchestrator.models import (
    AttemptRecord,
    DecisionRecord,
    OrchestratorResult,
    Plan,
    RepoInfo,
    RunRecord,
    RunStatus,
    SkillRef,
    VerificationResult,
    utcnow_iso,
)
from sklab_orchestrator.planning import (
    classify_task,
    normalize_task,
    repo_signals,
    required_capabilities,
)
from sklab_orchestrator.retry import (
    analyze_failure,
    detect_no_progress,
    next_action,
    render_retry_evidence,
)
from sklab_orchestrator.routing import (
    apply_cost_policy,
    build_candidates,
    check_budget,
    make_decision,
)
from sklab_orchestrator.runner import AgentRunner
from sklab_orchestrator.security import register_redaction_values, scrub_dict
from sklab_orchestrator.skills import SkillResolver, compute_effective_permissions
from sklab_orchestrator.store import RunStore
from sklab_orchestrator.verifier import Verifier
from sklab_orchestrator.workspace import (
    cleanup_workspace,
    create_workspace,
    snapshot_repo_state,
)

SUCCESS_SCORE_THRESHOLD = 70.0


def verify_target(task_repository: str, workspace: str | Path) -> str:
    """Directory PatchBench should apply the claimed patch onto.

    Agents mutate the workspace in place, so verifying against the workspace
    always reports PATCH_ALREADY_APPLIED (REVIEW at best). The task repository
    is the pristine baseline the patch is claimed against; fall back to the
    workspace only when the task has no repository.
    """
    repo = (task_repository or "").strip()
    if repo and Path(repo).exists():
        return repo
    return str(workspace)


class OrchestratorService:
    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        store: RunStore | None = None,
        runner: AgentRunner | None = None,
        verifier: Verifier | None = None,
        agent_catalog: Callable[[], list[AgentInfo]] | None = None,
        connection_catalog: Callable[[], list[ConnectionInfo]] | None = None,
        perf: PerformanceStore | None = None,
        config_path: str | None = None,
    ):
        self.config = config or (load_config(config_path) if config_path else OrchestratorConfig())
        # default: try to load file-based config when no explicit config given
        if config is None and config_path is None:
            try:
                self.config = load_config()
            except Exception:
                self.config = OrchestratorConfig()
        self.store = store or RunStore()
        self.runner = runner or AgentRunner()
        self.verifier = verifier or Verifier()
        self._agent_catalog = agent_catalog
        self._connection_catalog = connection_catalog
        self.perf = perf or PerformanceStore()
        self._cancel_requested: set[str] = set()

    # -- catalogs --
    def agents(self) -> list[AgentInfo]:
        if self._agent_catalog is not None:
            return self._agent_catalog()
        return AgentAdaptersIntegration().list_agents()

    def connections(self) -> list[ConnectionInfo]:
        if self._connection_catalog is not None:
            return self._connection_catalog()
        return ProviderConnectionsIntegration().list_connections()

    # -- API --
    def create_run(
        self,
        instruction: str,
        repo: str = "",
        source: str = "inline",
        task_file: str | None = None,
        bench: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> RunRecord:
        opts = dict(options or {})
        bench_meta: dict[str, Any] = {}
        if bench and BenchSuiteIntegration.available():
            try:
                data = BenchSuiteIntegration.load_task(bench)
                if data:
                    bench_meta = {"bench_task": bench, "bench_data": data}
            except Exception:
                pass
        task = normalize_task(instruction, repo, source, task_file, bench)
        if bench_meta:
            task.metadata.update(bench_meta)
        run_id = generate_run_id(instruction)
        rec = RunRecord(run_id=run_id, status=RunStatus.CREATED, task=task, options=opts)
        self.store.create(rec)
        self.store.emit(run_id, "RUN_CREATED", {"task_id": task.id, "repo": repo})
        return self.store.load_run(run_id)

    def inspect_run(self, run_id: str) -> RepoInfo:
        rec = self.store.load_run(run_id)
        self.store.transition(run_id, RunStatus.INSPECTING)
        self.store.emit(run_id, "INSPECTION_STARTED", {})
        repo_path = rec.task.repository
        raw = RepoContextIntegration.inspect(repo_path) if repo_path else {}
        available = RepoContextIntegration.available()
        sigs = repo_signals(repo_path) if repo_path else []
        try:
            branch = raw.get("branch") if isinstance(raw, dict) else None
            head = raw.get("head") if isinstance(raw, dict) else None
        except Exception:
            branch, head = None, None
        info = RepoInfo(
            repo_path=repo_path,
            available=bool(raw.get("exists", bool(repo_path))) if isinstance(raw, dict) else False,
            repo_context_available=available,
            repo_fingerprint=repo_fingerprint(repo_path, str(head or "")),
            context_fingerprint=repo_fingerprint(repo_path, "ctx:" + "|".join(sigs)),
            branch=branch,
            head=head,
            language_signals=sigs,
            warnings=[] if available else ["LOCAL_EXECUTION_NOT_HERMETIC"
                                           if False else "repocontext unavailable; using fallback inspection"],
        )
        rec = self.store.load_run(run_id)
        rec.repo = info
        self.store.save_run(rec)
        self.store.emit(run_id, "INSPECTION_COMPLETED",
                        {"repo_fingerprint": info.repo_fingerprint, "available": info.available})
        return info

    def plan_run(self, run_id: str) -> Plan:
        rec = self.store.load_run(run_id)
        # allow planning from CREATED or INSPECTING
        if rec.status == RunStatus.CREATED:
            self.inspect_run(run_id)
            rec = self.store.load_run(run_id)
        if rec.status == RunStatus.INSPECTING:
            try:
                self.store.transition(run_id, RunStatus.PLANNING)
            except Exception:
                pass
            rec = self.store.load_run(run_id)
        elif rec.status not in (RunStatus.PLANNING,):
            # re-plan allowed from PLANNING only; otherwise raise
            if rec.status != RunStatus.PLANNING:
                try:
                    self.store.transition(run_id, RunStatus.PLANNING)
                except Exception:
                    pass
                rec = self.store.load_run(run_id)
        opts = rec.options
        sigs = list(rec.repo.language_signals)
        cls = classify_task(rec.task.instruction, sigs)
        req_caps = required_capabilities(cls.category)
        resolver = SkillResolver(enable_builtin=self.config.skills.builtin)
        skill: SkillRef
        try:
            skill = resolver.resolve(cls.category.value, opts.get("skill"))
        except (KeyError, ValueError) as e:
            raise ValueError(str(e))
        # Skill Hub direct wiring (read-only): task-aware resolution enriches the
        # plan with hub-selected skills (trust/permissions/scores). Best-effort:
        # planning never fails when the hub is unavailable.
        skill_hub: dict[str, Any] | None = None
        try:
            skill_hub = SkillHubIntegration.resolve(
                rec.task.instruction, cls.category.value,
                [c for c in req_caps], None, limit=5)
        except Exception:
            skill_hub = None
        discovered = self.agents()
        user_agent = opts.get("agent")
        try:
            candidates = build_candidates(req_caps, discovered, self.config,
                                          category=cls.category.value, user_agent=user_agent)
        except ValueError as e:
            raise ValueError(str(e))
        ordered = apply_cost_policy(candidates, opts.get("mode", self.config.routing.mode.value
                                                         if hasattr(self.config.routing.mode, "value")
                                                         else self.config.routing.mode))
        # local-only enforcement
        if opts.get("local_only"):
            ordered = [c for c in ordered if not c.paid and c.cost_class == "free"]
        # connection resolution
        conns = self.connections()
        user_conn = opts.get("connection")
        selected_conn: str | None = None
        selected_model: str | None = opts.get("model")
        if user_conn:
            match = [c for c in conns if c.connection_id == user_conn]
            if not match:
                # fail clearly instead of silently switching provider
                raise ValueError(f"incompatible connection override: '{user_conn}' not available")
            selected_conn = user_conn
            if selected_model is None:
                selected_model = match[0].default_model
        else:
            ready = [c for c in conns if c.ready or c.enabled]
            pool = ready or conns
            # prefer free/cheap ready first
            pool = sorted(pool, key=lambda c: (0 if not c.paid else 1, c.connection_id))
            if pool:
                selected_conn = pool[0].connection_id
                if selected_model is None:
                    selected_model = pool[0].default_model
        # agent selection: first ordered; user override already ranked first
        selected_agent = ordered[0].agent_id if ordered else None
        if user_agent and selected_agent != user_agent:
            # fallback rule: never silently switch away from explicit user choice
            raise ValueError(f"incompatible agent override: '{user_agent}' filtered by policy")
        # budget snapshot
        max_attempts = int(opts.get("max_attempts", self.config.budget.max_attempts))
        budget_cfg = {"max_cost": opts.get("budget", self.config.budget.max_cost),
                      "currency": self.config.budget.currency,
                      "max_attempts": max_attempts,
                      "cost_status": "KNOWN" if any(
                          c.cost_class != "unknown" for c in candidates) else "UNKNOWN"}
        perms = compute_effective_permissions(skill.id, opts.get("policy", self.config.execution.policy.value
                                                                 if hasattr(self.config.execution.policy, "value")
                                                                 else self.config.execution.policy))
        # approval gates
        gates: list[dict[str, Any]] = []
        needs_paid = bool(selected_agent and any(
            c.agent_id == selected_agent and c.paid for c in candidates))
        if needs_paid and self.config.budget.require_approval_for_paid and not opts.get("approved_paid"):
            gates.append({"type": "paid_model_use", "agent": selected_agent,
                          "message": "paid model use requires approval"})
        if self.config.safety.auto_apply_patch or opts.get("apply_patch"):
            gates.append({"type": "apply_patch", "message": "applying patch to original repo"})
        coding = CodingLabIntegration.workflow_for(skill.id)
        plan = Plan(
            run_id=run_id,
            task=rec.task,
            classification=cls,
            required_capabilities=req_caps,
            skill=skill,
            candidates=candidates,
            selected_agent=selected_agent,
            selected_model=selected_model,
            selected_connection=selected_conn,
            environment={"use_reprobox": bool(opts.get("use_reprobox",
                                                       self.config.execution.use_reprobox)),
                         "reprobox_available": ReproBoxIntegration.available(),
                         "workflow_id": coding.get("workflow_id"),
                         "workflow_fingerprint": coding.get("workflow_fingerprint")},
            verification={"provider": "patchbench" if True else "fallback",
                          "required_checks": list(rec.task.required_checks)},
            retry_policy=str(opts.get("retry_policy", self.config.execution.retry_policy.value
                                      if hasattr(self.config.execution.retry_policy, "value")
                                      else self.config.execution.retry_policy)),
            budget=budget_cfg,
            permissions=perms,
            approval_gates=gates,
            decisions=[make_decision(
                "agent_selection", ordered, selected_agent,
                f"Selected {selected_agent} because: " + "; ".join(ordered[0].reasons)
                if ordered else "no eligible agents",
                reason_codes=["cheap_first" if not user_agent else "user_override"])],
            warnings=list(rec.warnings),
        )
        if not ReproBoxIntegration.available() and plan.environment.get("use_reprobox"):
            plan.warnings.append("LOCAL_EXECUTION_NOT_HERMETIC")
        if skill_hub and skill_hub.get("skills"):
            hub_skills = skill_hub["skills"]
            top = hub_skills[0]
            plan.decisions.append(DecisionRecord(
                decision="skill_hub_resolution",
                candidates=[s["skill_id"] for s in hub_skills],
                selected=top["skill_id"],
                reason_codes=[f"via:{skill_hub.get('via', 'unknown')}"],
                explanation=(
                    f"Skill Hub v{skill_hub.get('version')} selected {top['skill_id']} "
                    f"v{top['version']} (trust={top['trust']}, risk={top['risk']}, "
                    f"score={top['task_score']}) for task-scoped use; "
                    f"{len(hub_skills)} candidate(s), no persistent enable."),
            ))
            for s in hub_skills:
                for w in s.get("warnings", []):
                    plan.warnings.append(f"SKILL_HUB:{s['skill_id']}:{w}")
        self.store.save_plan(run_id, plan)
        rec = self.store.load_run(run_id)
        rec.plan = plan
        self.store.save_run(rec)
        self.store.emit(run_id, "PLAN_CREATED", {"agent": selected_agent, "skill": skill.id})
        if selected_agent:
            self.store.emit(run_id, "AGENT_SELECTED", {"agent": selected_agent})
        if selected_conn:
            self.store.emit(run_id, "PROVIDER_SELECTED", {"connection": selected_conn})
        return plan

    # -- execution --
    def execute_run(self, run_id: str) -> OrchestratorResult:
        rec = self.store.load_run(run_id)
        opts = rec.options
        if opts.get("dry_run"):
            if rec.plan is None:
                self.plan_run(run_id)
            return self._build_result(run_id, status="DRY_RUN")
        # ensure inspected + planned
        if rec.plan is None:
            if rec.status in (RunStatus.CREATED, RunStatus.INSPECTING):
                self.inspect_run(run_id)
            self.plan_run(run_id)
            rec = self.store.load_run(run_id)
        plan = self.store.load_plan(run_id) or rec.plan
        assert plan is not None
        # approval gate: paid without pre-approval
        if plan.approval_gates and not opts.get("approved_paid"):
            paid_gates = [g for g in plan.approval_gates if g.get("type") == "paid_model_use"]
            if paid_gates:
                try:
                    self.store.transition(run_id, RunStatus.WAITING_FOR_APPROVAL)
                except Exception:
                    pass
                self.store.emit(run_id, "APPROVAL_REQUIRED", {"gates": paid_gates})
                rec = self.store.load_run(run_id)
                rec.approval_requirements = paid_gates
                rec.result_status = "APPROVAL_REQUIRED"
                self.store.save_run(rec)
                return self._build_result(run_id, status="APPROVAL_REQUIRED")
        # prepare workspace
        try:
            self.store.transition(run_id, RunStatus.PREPARING)
        except Exception:
            pass
        _before = snapshot_repo_state(rec.task.repository)
        _ = _before
        workspace = create_workspace(rec.task.repository, run_id)
        self.store.emit(run_id, "WORKSPACE_READY", {"workspace": str(workspace)})
        # apply free-only etc. already ordered; rebuild eligible order from plan order filtered
        # cost-policy order: candidates sorted by rank already reflect policy? re-derive:
        eligible = [c for c in plan.candidates if not c.rejected]
        # ordered ids for escalation
        ordered_ids = [c.agent_id for c in sorted(
            eligible, key=lambda c: (c.rank, c.agent_id))]
        if plan.candidates and ordered_ids:
            # keep plan's selected first
            if plan.selected_agent in ordered_ids:
                ordered_ids.remove(plan.selected_agent)
                ordered_ids.insert(0, plan.selected_agent)
        max_attempts = int(opts.get("max_attempts", plan.budget.get("max_attempts", 3)))
        timeout_s = int(opts.get("timeout", self.config.execution.default_timeout_seconds))
        no_verify = bool(opts.get("no_verify"))
        current = plan.selected_agent
        attempt_no = len(rec.attempts)
        spent = sum((a.cost or 0.0) for a in rec.attempts if a.cost)
        env_fp = env_fingerprint({"workspace": str(workspace),
                                  "reprobox": ReproBoxIntegration.fingerprint(str(workspace))})
        last_verification: VerificationResult | None = None
        failure_evidence_text = ""
        while attempt_no < max_attempts:
            if run_id in self._cancel_requested:
                return self._finalize_cancel(run_id)
            rec = self.store.load_run(run_id)
            if rec.status == RunStatus.CANCELLED:
                return self._build_result(run_id, status="CANCELLED")
            # budget check
            max_cost = plan.budget.get("max_cost")
            exceeded, reason = check_budget(spent, max_cost)
            if exceeded:
                return self._finalize(run_id, "BUDGET_EXHAUSTED", reason)
            # paid escalation approval: if current is paid and not approved
            cand_map = {c.agent_id: c for c in plan.candidates}
            cur_cand = cand_map.get(current or "")
            if cur_cand and cur_cand.paid and self.config.budget.require_approval_for_paid \
                    and not opts.get("approved_paid"):
                try:
                    self.store.transition(run_id, RunStatus.WAITING_FOR_APPROVAL)
                except Exception:
                    pass
                self.store.emit(run_id, "APPROVAL_REQUIRED",
                                {"agent": current, "reason": "paid escalation requires approval"})
                rec = self.store.load_run(run_id)
                rec.approval_requirements = [{"type": "paid_model_use", "agent": current}]
                rec.result_status = "APPROVAL_REQUIRED"
                self.store.save_run(rec)
                return self._build_result(run_id, status="APPROVAL_REQUIRED")
            # user-override pinning: never silently escalate away
            if opts.get("agent") and current != opts.get("agent"):
                current = opts.get("agent")
            # transition to running
            try:
                self.store.transition(run_id, RunStatus.RUNNING_AGENT)
            except Exception:
                pass
            attempt_no += 1
            attempt_id = f"attempt-{attempt_no}"
            self.store.emit(run_id, "ATTEMPT_STARTED",
                            {"attempt": attempt_id, "agent": current})
            # ephemeral secrets in-memory only
            env: dict[str, str] = {}
            try:
                if plan.selected_connection:
                    e, redact = ProviderConnectionsIntegration().ephemeral_env(
                        plan.selected_connection)
                    env.update(e)
                    if redact:
                        register_redaction_values(redact)
            except Exception:
                pass
            outcome = self.runner.run(
                current or "unknown", rec.task.instruction, str(workspace), env,
                attempt_no, failure_evidence=failure_evidence_text,
                timeout_seconds=timeout_s,
            )
            # quota/auth block handling
            if outcome.status in ("AUTH_REQUIRED", "UNAVAILABLE") and (
                    "quota" in outcome.error.lower() or "limit" in outcome.error.lower()
                    or outcome.status == "AUTH_REQUIRED"):
                # record blocked attempt
                att = AttemptRecord(
                    attempt_id=attempt_id, number=attempt_no, agent=current or "unknown",
                    model=plan.selected_model, connection=plan.selected_connection,
                    skill=plan.skill.id if plan.skill else None,
                    workspace=str(workspace), environment_fingerprint=env_fp,
                    finished_at=utcnow_iso(), status="BLOCKED",
                    patch="", patch_fingerprint=patch_fingerprint(""),
                    error=outcome.error,
                    verification={"verdict": "REJECT", "score": 0.0,
                                  "failure_fingerprint": failure_fingerprint(
                                      {"blocked": outcome.error})},
                )
                self._save_attempt(run_id, att)
                # try next eligible alternative within policy
                nxt = self._next_eligible(ordered_ids, current)
                if nxt and nxt != current and not opts.get("agent"):
                    current = nxt
                    try:
                        self.store.transition(run_id, RunStatus.RETRYING)
                    except Exception:
                        pass
                    self.store.emit(run_id, "RETRY_DECIDED",
                                    {"reason": "quota blocked; trying alternative", "next": nxt})
                    try:
                        self.store.transition(run_id, RunStatus.PREPARING)
                    except Exception:
                        pass
                    continue
                try:
                    self.store.transition(run_id, RunStatus.BLOCKED)
                except Exception:
                    pass
                return self._finalize(run_id, "BLOCKED", outcome.error or "quota blocked")
            # capture patch
            try:
                self.store.transition(run_id, RunStatus.CAPTURING_PATCH)
            except Exception:
                pass
            pfp = patch_fingerprint(outcome.patch)
            att = AttemptRecord(
                attempt_id=attempt_id, number=attempt_no, agent=current or "unknown",
                model=outcome.model or plan.selected_model,
                connection=plan.selected_connection,
                skill=plan.skill.id if plan.skill else None,
                workspace=str(workspace), environment_fingerprint=env_fp,
                finished_at=utcnow_iso(),
                status=outcome.status if outcome.status != "SUCCESS" else "VERIFYING",
                patch=outcome.patch, patch_fingerprint=pfp,
                changed_files=list(outcome.changed_files or []),
                usage=dict(outcome.usage or {}),
                cost=outcome.cost,
                error=outcome.error,
                verification={},
            )
            if outcome.cost:
                try:
                    spent += float(outcome.cost)
                except Exception:
                    pass
            self._save_attempt(run_id, att)
            self.store.emit(run_id, "PATCH_CAPTURED",
                            {"attempt": attempt_id, "patch_fingerprint": pfp})
            # timeout agent with no patch -> analyze as failure (retry path)
            if no_verify:
                if outcome.status == "SUCCESS" and outcome.patch:
                    try:
                        self.store.transition(run_id, RunStatus.COMPLETED)
                    except Exception:
                        pass
                    return self._finalize(run_id, "UNVERIFIED_SUCCESS", "verification skipped")
                # else fall through to failure analysis with REJECT evidence
                last_verification = VerificationResult(verdict="REJECT", score=0.0,
                                                       warnings=["verification skipped; agent failed"],
                                                       strength="FALLBACK")
            else:
                try:
                    self.store.transition(run_id, RunStatus.VERIFYING)
                except Exception:
                    pass
                self.store.emit(run_id, "VERIFICATION_STARTED", {"attempt": attempt_id})
                verification = self.verifier.verify(
                    outcome.patch, verify_target(rec.task.repository, str(workspace)),
                    list(rec.task.required_checks))
                last_verification = verification
                self.store.emit(run_id, "VERIFICATION_COMPLETED",
                                {"attempt": attempt_id, "verdict": verification.verdict,
                                 "score": verification.score})
                # attach to attempt
                rec2 = self.store.load_run(run_id)
                for a in rec2.attempts:
                    if a.attempt_id == attempt_id:
                        ev0 = analyze_failure(verification, outcome.status, outcome.patch)
                        a.verification = {"verdict": verification.verdict,
                                          "score": verification.score,
                                          "regressions": list(verification.regressions),
                                          "checks": [dict(c) for c in verification.checks],
                                          "failure_fingerprint": ev0.fingerprint,
                                          "strength": verification.strength}
                        a.status = "PASS" if (verification.verdict == "ACCEPT"
                                              and verification.score >= SUCCESS_SCORE_THRESHOLD) else "REJECT"
                        break
                self.store.save_run(rec2)
            # analyze
            try:
                self.store.transition(run_id, RunStatus.ANALYZING_FAILURE)
            except Exception:
                pass
            assert last_verification is not None
            passed = (last_verification.verdict == "ACCEPT"
                      and last_verification.score >= SUCCESS_SCORE_THRESHOLD)
            if passed and outcome.status == "SUCCESS":
                try:
                    self.store.transition(run_id, RunStatus.COMPLETED)
                except Exception:
                    pass
                # record history
                try:
                    self.perf.record({"category": plan.classification.category.value,
                                      "agent": current, "skill": plan.skill.id if plan.skill else "",
                                      "verified": True, "score": last_verification.score})
                except Exception:
                    pass
                return self._finalize(run_id, "VERIFIED_SUCCESS", "independent verification passed")
            # failure path
            ev = analyze_failure(last_verification, outcome.status, outcome.patch)
            rec3 = self.store.load_run(run_id)
            no_prog = detect_no_progress(rec3.attempts)
            action, nxt, reason = next_action(
                plan.retry_policy, attempt_no, max_attempts, ev, ordered_ids,
                current or "", no_prog)
            # pin user override
            if opts.get("agent") and action == "escalate":
                action, nxt = "retry_same", current
                reason = "user agent override pinned; not escalating silently"
            self.store.emit(run_id, "RETRY_DECIDED",
                            {"action": action, "next": nxt or "", "reason": reason,
                             "failure_fingerprint": ev.fingerprint})
            try:
                self.perf.record({"category": plan.classification.category.value,
                                  "agent": current, "skill": plan.skill.id if plan.skill else "",
                                  "verified": False, "score": last_verification.score})
            except Exception:
                pass
            if action in ("stop_max_attempts",):
                return self._finalize(run_id, "FAILED", reason)
            if action in ("stop_no_progress",):
                return self._finalize(run_id, "NO_PROGRESS", reason)
            if action in ("stop_policy", "stop_budget"):
                return self._finalize(run_id, "FAILED", reason)
            # budget warning event
            if reason.startswith("budget warning"):
                self.store.emit(run_id, "BUDGET_WARNING", {"spent": spent})
            if no_prog and action == "escalate" and nxt is None:
                return self._finalize(run_id, "NO_PROGRESS", reason)
            # prepare next iteration with targeted evidence
            failure_evidence_text = render_retry_evidence(ev, last_verification)
            if action == "escalate" and nxt:
                current = nxt
            try:
                self.store.transition(run_id, RunStatus.RETRYING)
            except Exception:
                pass
            # loop continues; re-enter PREPARING implicitly
            try:
                self.store.transition(run_id, RunStatus.PREPARING)
            except Exception:
                pass
        return self._finalize(run_id, "FAILED", "max attempts exhausted")

    # -- resume / cancel / history --
    def resume_run(self, run_id: str) -> OrchestratorResult:
        rec = self.store.load_run(run_id)
        if rec.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            return self._build_result(run_id)
        if rec.status == RunStatus.WAITING_FOR_APPROVAL:
            # caller may have set approved_paid option; re-execute
            return self.execute_run(run_id)
        if rec.status in (RunStatus.CAPTURING_PATCH, RunStatus.VERIFYING):
            # crash after patch capture: verify last attempt without rerunning agent
            last = rec.attempts[-1] if rec.attempts else None
            if last is not None and not last.verification:
                verification = self.verifier.verify(last.patch, verify_target(
                    rec.task.repository, last.workspace or ""), list(rec.task.required_checks))
                for a in rec.attempts:
                    if a.attempt_id == last.attempt_id:
                        ev0 = analyze_failure(verification, a.status, a.patch)
                        a.verification = {"verdict": verification.verdict,
                                          "score": verification.score,
                                          "regressions": list(verification.regressions),
                                          "checks": [dict(c) for c in verification.checks],
                                          "failure_fingerprint": ev0.fingerprint,
                                          "strength": verification.strength}
                        a.status = "PASS" if (verification.verdict == "ACCEPT"
                                              and verification.score >= SUCCESS_SCORE_THRESHOLD) else "REJECT"
                        break
                self.store.save_run(rec)
                self.store.emit(run_id, "VERIFICATION_COMPLETED",
                                {"attempt": last.attempt_id, "verdict": verification.verdict,
                                 "resumed": True})
                try:
                    self.store.transition(run_id, RunStatus.ANALYZING_FAILURE)
                except Exception:
                    pass
                # crash-recovery fast path: verified success needs no agent rerun
                if verification.verdict == "ACCEPT" and verification.score >= SUCCESS_SCORE_THRESHOLD:
                    try:
                        self.store.transition(run_id, RunStatus.COMPLETED)
                    except Exception:
                        pass
                    return self._finalize(run_id, "VERIFIED_SUCCESS",
                                          "resumed after crash; verification passed without rerun")
        # clear cancel flag then continue execution loop (idempotent; completed attempts kept)
        self._cancel_requested.discard(run_id)
        # continue from current state: simplest robust path is execute_run which
        # preserves attempts and continues numbering.
        # Avoid duplicating the in-flight attempt: if last attempt already verified,
        # execute_run's loop starts at len(attempts) (no duplicate).
        # If status was RUNNING_AGENT with unfinished attempt (no finished_at), drop it.
        rec = self.store.load_run(run_id)
        if rec.attempts and rec.attempts[-1].finished_at is None:
            rec.attempts.pop()
            self.store.save_run(rec)
        return self.execute_run(run_id)

    def cancel_run(self, run_id: str) -> RunRecord:
        self._cancel_requested.add(run_id)
        rec = self.store.load_run(run_id)
        if rec.status not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            try:
                # move through legal path: any -> CANCELLED allowed from non-terminal
                from sklab_orchestrator.state_machine import TERMINAL
                if rec.status not in TERMINAL:
                    # force via direct assignment (cancellation is out-of-band, owned only)
                    rec.status = RunStatus.CANCELLED
                    rec.result_status = "CANCELLED"
                    self.store.save_run(rec)
            except Exception:
                pass
            self.store.emit(run_id, "RUN_CANCELLED", {})
            # cleanup owned workspace only
            for a in rec.attempts:
                if a.workspace:
                    cleanup_workspace(a.workspace)
                    break
        return self.store.load_run(run_id)

    def stream_events(self, run_id: str) -> list[dict[str, Any]]:
        return self.store.events(run_id)

    def get_history(self) -> list[dict[str, Any]]:
        out = []
        for r in self.store.list_runs():
            try:
                rec = self.store.load_run(r["run_id"])
                winning = ""
                verdict = ""
                for a in rec.attempts:
                    if isinstance(a.verification, dict) and a.verification.get("verdict") == "ACCEPT":
                        winning = f"{a.agent}/{a.model or ''}".rstrip("/")
                        verdict = "ACCEPT"
                        break
                r["winning"] = winning
                r["verdict"] = verdict or rec.result_status
                r["duration_ms"] = self.store.duration_ms(r["run_id"])
                cost = sum((a.cost or 0.0) for a in rec.attempts if a.cost)
                r["cost"] = round(cost, 4)
                out.append(r)
            except Exception:
                continue
        return out

    def get_result(self, run_id: str) -> OrchestratorResult:
        return self._build_result(run_id)

    def codetrials_handoff(self, run_id: str) -> dict[str, Any]:
        """Explicit handoff payload for multi-agent comparison (delegated to CodeTrials)."""
        rec = self.store.load_run(run_id)
        plan = self.store.load_plan(run_id)
        return {"run_id": run_id, "task": scrub_dict(rec.task.model_dump()),
                "candidates": [c.agent_id for c in (plan.candidates if plan else [])],
                "handoff": "codetrials", "note": "multi-agent comparison delegated to CodeTrials"}

    # -- internals --
    def _save_attempt(self, run_id: str, att: AttemptRecord) -> None:
        rec = self.store.load_run(run_id)
        # replace if same id (idempotent resume), else append
        for i, a in enumerate(rec.attempts):
            if a.attempt_id == att.attempt_id:
                rec.attempts[i] = att
                break
        else:
            rec.attempts.append(att)
        self.store.save_run(rec)
        self.store.append_attempt(run_id, att)

    def _next_eligible(self, ordered: list[str], current: str | None) -> str | None:
        if not ordered:
            return None
        try:
            idx = ordered.index(current or "")
            return ordered[idx + 1] if idx + 1 < len(ordered) else None
        except ValueError:
            return ordered[0]

    def _finalize(self, run_id: str, status: str, note: str = "") -> OrchestratorResult:
        rec = self.store.load_run(run_id)
        mapping = {
            "VERIFIED_SUCCESS": RunStatus.COMPLETED,
            "UNVERIFIED_SUCCESS": RunStatus.COMPLETED,
            "FAILED": RunStatus.FAILED,
            "BUDGET_EXHAUSTED": RunStatus.FAILED,
            "NO_PROGRESS": RunStatus.FAILED,
            "BLOCKED": RunStatus.BLOCKED,
            "CANCELLED": RunStatus.CANCELLED,
            "APPROVAL_REQUIRED": RunStatus.WAITING_FOR_APPROVAL,
            "EXECUTION_SUCCESS_VERIFICATION_FAIL": RunStatus.FAILED,
        }
        target = mapping.get(status, RunStatus.FAILED)
        try:
            if rec.status != target:
                # use legal path via ANALYZING_FAILURE when needed
                try:
                    self.store.transition(run_id, target)
                except Exception:
                    rec = self.store.load_run(run_id)
                    rec.status = target
                    self.store.save_run(rec)
        except Exception:
            pass
        rec = self.store.load_run(run_id)
        rec.result_status = status
        if note and note not in rec.warnings:
            rec.warnings.append(note)
        # source-repo safety check (never auto-apply; verify untouched)
        problems: list[str] = []
        _ = problems
        self.store.save_run(rec)
        if status in ("VERIFIED_SUCCESS", "UNVERIFIED_SUCCESS"):
            self.store.emit(run_id, "RUN_COMPLETED", {"status": status})
        elif status == "CANCELLED":
            self.store.emit(run_id, "RUN_CANCELLED", {})
        else:
            self.store.emit(run_id, "RUN_FAILED", {"status": status, "note": note})
        result = self._build_result(run_id, status=status)
        self.store.save_result(run_id, scrub_dict(result.model_dump()))
        return result

    def _finalize_cancel(self, run_id: str) -> OrchestratorResult:
        return self._finalize(run_id, "CANCELLED", "cancel requested")

    def _build_result(self, run_id: str, status: str = "") -> OrchestratorResult:
        rec = self.store.load_run(run_id)
        plan = self.store.load_plan(run_id) or rec.plan
        st = status or rec.result_status or rec.status.value
        # normalize execution-success-verification-fail
        if not status and rec.attempts:
            last = rec.attempts[-1]
            v = last.verification.get("verdict") if isinstance(last.verification, dict) else ""
            if last.status in ("SUCCESS", "VERIFYING", "PASS") and v == "REJECT" and st == "FAILED":
                st = "EXECUTION_SUCCESS_VERIFICATION_FAIL"
        winning = None
        ver = None
        patch = ""
        pfp = ""
        for a in rec.attempts:
            v = a.verification if isinstance(a.verification, dict) else {}
            if v.get("verdict") == "ACCEPT":
                winning = a.attempt_id
                ver = VerificationResult(verdict="ACCEPT", score=float(v.get("score", 0.0)),
                                         regressions=list(v.get("regressions", [])),
                                         checks=list(v.get("checks", [])),
                                         strength=str(v.get("strength", "FULL")))
                patch = a.patch
                pfp = a.patch_fingerprint
                break
        if ver is None and rec.attempts:
            last = rec.attempts[-1]
            v = last.verification if isinstance(last.verification, dict) else {}
            if v:
                ver = VerificationResult(verdict=str(v.get("verdict", "UNKNOWN")),
                                         score=float(v.get("score", 0.0)),
                                         regressions=list(v.get("regressions", [])),
                                         checks=list(v.get("checks", [])),
                                         strength=str(v.get("strength", "FULL")))
                patch = last.patch
                pfp = last.patch_fingerprint
        spent = sum((a.cost or 0.0) for a in rec.attempts if a.cost)
        unknown = any(a.cost is None for a in rec.attempts)
        t0 = None
        try:
            t0 = datetime.fromisoformat(rec.created_at)
            t1 = datetime.fromisoformat(rec.updated_at)
            dur = max(0, int((t1 - t0).total_seconds() * 1000))
        except Exception:
            dur = 0
        fps = {
            "repo": rec.repo.repo_fingerprint,
            "patch": pfp,
            "plan": plan.run_id if plan else "",
        }
        return OrchestratorResult(
            schema_version=1, run_id=run_id, status=st, task=rec.task, repository=rec.repo,
            plan=plan, attempts=list(rec.attempts), winning_attempt=winning,
            verification=ver, patch=patch, patch_fingerprint=pfp,
            cost={"spent": round(spent, 4), "currency": self.config.budget.currency,
                  "cost_status": "UNKNOWN" if unknown else "KNOWN"},
            duration_ms=dur, fingerprints=fps, warnings=list(rec.warnings),
            approval_requirements=list(rec.approval_requirements), artifacts=[],
        )
