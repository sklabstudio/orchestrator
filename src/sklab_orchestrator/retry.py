"""Failure analysis + retry/escalation policy + loop prevention."""

from __future__ import annotations

from sklab_orchestrator.fingerprints import failure_fingerprint
from sklab_orchestrator.models import AttemptRecord, FailureEvidence, VerificationResult


def analyze_failure(
    verification: VerificationResult, agent_status: str = "", patch: str = ""
) -> FailureEvidence:
    failed = [c.get("name", "check") for c in verification.checks
              if isinstance(c, dict) and c.get("passed") is False]
    ev = FailureEvidence(
        new_regressions=list(verification.regressions),
        failed_checks=failed,
        timeout=(agent_status == "TIMEOUT"),
        build_failure=any("build" in f.lower() for f in failed),
        type_failure=any("mypy" in f.lower() or "type" in f.lower() for f in failed),
        test_failure=any("test" in f.lower() or "pytest" in f.lower() for f in failed) or verification.verdict == "REJECT",
        no_patch=(not patch),
        agent_crash=(agent_status in ("AGENT_FAILED", "INTERNAL_ERROR")),
    )
    ev.fingerprint = failure_fingerprint({
        "regressions": sorted(ev.new_regressions),
        "failed": sorted(ev.failed_checks),
        "timeout": ev.timeout, "no_patch": ev.no_patch, "crash": ev.agent_crash,
    })
    return ev


def render_retry_evidence(evidence: FailureEvidence, verification: VerificationResult) -> str:
    lines = ["Fix ONLY the confirmed failures below. Do not make unrelated changes."]
    if evidence.failed_checks:
        lines.append(f"Failed checks: {', '.join(evidence.failed_checks)}")
    if evidence.new_regressions:
        lines.append(f"Regressions: {', '.join(evidence.new_regressions)}")
    for c in verification.checks:
        if isinstance(c, dict) and c.get("passed") is False and c.get("detail"):
            lines.append(f"- {c.get('name')}: {str(c.get('detail'))[:800]}")
    if evidence.timeout:
        lines.append("Previous attempt timed out: produce a smaller, faster patch.")
    if evidence.no_patch:
        lines.append("Previous attempt produced no patch: emit an actual diff.")
    return "\n".join(lines)


def detect_no_progress(attempts: list[AttemptRecord]) -> bool:
    """Identical patch twice, identical failure twice, repeated crash/timeout/no-change."""
    if len(attempts) < 2:
        return False
    fps = [a.patch_fingerprint for a in attempts if a.patch_fingerprint]
    if len(fps) >= 2 and len(set(fps[-2:])) == 1 and fps[-1]:
        return True
    ffps = [a.verification.get("failure_fingerprint", "") for a in attempts
            if isinstance(a.verification, dict)]
    ffps = [f for f in ffps if f]
    if len(ffps) >= 2 and len(set(ffps[-2:])) == 1:
        return True
    statuses = [a.status for a in attempts[-3:]]
    if len(statuses) == 3 and len(set(statuses)) == 1 and statuses[0] in (
        "TIMEOUT", "AGENT_FAILED", "NO_CHANGES", "REJECT"):
        return True
    return False


def next_action(
    policy: str,
    attempt_no: int,
    max_attempts: int,
    evidence: FailureEvidence,
    ordered_agents: list[str],
    current_agent: str,
    no_progress: bool,
) -> tuple[str, str | None, str]:
    """Return (action, next_agent, reason). action in {retry_same, escalate, stop_* }."""
    policy = (policy or "ADAPTIVE").upper()
    if attempt_no >= max_attempts:
        return "stop_max_attempts", None, f"max attempts ({max_attempts}) reached"
    if no_progress and policy in ("ADAPTIVE", "ESCALATE"):
        # escalate to next eligible agent
        try:
            idx = ordered_agents.index(current_agent)
            nxt = ordered_agents[idx + 1] if idx + 1 < len(ordered_agents) else None
        except ValueError:
            nxt = ordered_agents[0] if ordered_agents else None
        if nxt:
            return "escalate", nxt, "no-progress threshold reached; escalating"
        return "stop_no_progress", None, "NO_PROGRESS: identical patch/failure repeated"
    if no_progress:
        return "stop_no_progress", None, "NO_PROGRESS: identical patch/failure repeated"
    if policy == "NONE":
        return "stop_policy", None, "retry policy NONE"
    if policy == "SAME_AGENT":
        return "retry_same", current_agent, "retrying same agent with failure evidence"
    if policy == "ESCALATE":
        try:
            idx = ordered_agents.index(current_agent)
            nxt = ordered_agents[idx + 1] if idx + 1 < len(ordered_agents) else current_agent
        except ValueError:
            nxt = current_agent
        return "escalate", nxt, "escalation policy: next eligible agent"
    # ADAPTIVE: fixable verifier failure -> same agent; capability/crash -> escalate
    if evidence.agent_crash or evidence.timeout or evidence.no_patch:
        try:
            idx = ordered_agents.index(current_agent)
            nxt = ordered_agents[idx + 1] if idx + 1 < len(ordered_agents) else None
        except ValueError:
            nxt = None
        if nxt and nxt != current_agent:
            return "escalate", nxt, "capability failure; trying next eligible agent"
        return "retry_same", current_agent, "retrying same agent with failure evidence"
    return "retry_same", current_agent, "fixable verifier failure; same agent + targeted evidence"
