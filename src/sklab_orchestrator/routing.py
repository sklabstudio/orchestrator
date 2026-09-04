"""Routing: deterministic candidate scoring, cost policy, budget enforcement."""

from __future__ import annotations

from sklab_orchestrator.config import OrchestratorConfig, RoutingMode
from sklab_orchestrator.integrations import AgentInfo
from sklab_orchestrator.models import AgentCandidate, DecisionRecord, utcnow_iso

COST_ORDER = {"free": 0, "low": 1, "medium": 2, "high": 3, "unknown": 4}


def build_candidates(
    required: list[str],
    discovered: list[AgentInfo],
    config: OrchestratorConfig,
    category: str = "",
    user_agent: str | None = None,
) -> list[AgentCandidate]:
    """Merge discovered agents with configured preferences into scored candidates."""
    cands: list[AgentCandidate] = []
    pref = list(config.routing.preferred_agents)
    cat_cfg = config.routing.categories.get(category.lower(), None)
    cat_pref: list[str] = list(cat_cfg.preferred_agents) if cat_cfg else []
    # order map for preference rank
    order: dict[str, int] = {}
    for i, a in enumerate(cat_pref + pref):
        order.setdefault(a, i)
    for info in discovered:
        caps = list(info.capabilities)
        missing = [c for c in required if c not in caps] if caps else []
        # if capabilities unknown (empty), assume capable but note it (fixture agents have caps)
        reasons: list[str] = []
        rejected = False
        reject_reason = ""
        if missing and caps:
            rejected = True
            reject_reason = f"missing capabilities: {', '.join(missing)}"
        if not info.installed:
            rejected = True
            reject_reason = (reject_reason + "; not installed").strip("; ")
        if not info.auth_ready:
            # not auto-rejected: auth-required agents are kept but ranked last;
            # quota/auth failures handled at execution with BLOCKED semantics.
            reasons.append("auth not ready")
        if info.cost_class in ("", None):
            info.cost_class = "unknown"
        rank = COST_ORDER.get(info.cost_class, 4) * 100
        if info.agent_id in order:
            rank -= (50 - order[info.agent_id])
        if user_agent and info.agent_id == user_agent:
            rank = -1000
            reasons.append("explicit user choice")
        elif cat_pref and info.agent_id in cat_pref:
            reasons.append(f"category preference rank #{cat_pref.index(info.agent_id) + 1}")
        elif pref and info.agent_id in pref:
            reasons.append(f"global preference rank #{pref.index(info.agent_id) + 1}")
        if info.cost_class == "free":
            reasons.append("free/local eligible")
        if not rejected and info.auth_ready:
            reasons.append("installed; auth READY; satisfies required capabilities")
        cands.append(AgentCandidate(
            agent_id=info.agent_id, installed=info.installed, auth_ready=info.auth_ready,
            capabilities=caps, cost_class=info.cost_class, paid=info.paid,
            rank=rank, reasons=reasons, rejected=rejected, reject_reason=reject_reason,
        ))
    # If user explicitly requested an agent not in discovered list -> incompatible error candidate
    if user_agent and not any(c.agent_id == user_agent for c in cands):
        raise ValueError(f"incompatible agent override: '{user_agent}' is not available")
    cands.sort(key=lambda c: (c.rejected, c.rank, c.agent_id))
    # assign final rank order
    for i, c in enumerate(cands):
        if not c.rejected:
            c.rank = i
    return cands


def apply_cost_policy(
    candidates: list[AgentCandidate], mode: RoutingMode | str
) -> list[AgentCandidate]:
    m = str(mode).lower() if not isinstance(mode, RoutingMode) else mode.value
    eligible = [c for c in candidates if not c.rejected]
    if m in ("free_only", "free-only"):
        return [c for c in eligible if c.cost_class == "free" and not c.paid]
    if m in ("cheap_first", "cheap-first"):
        return sorted(eligible, key=lambda c: (COST_ORDER.get(c.cost_class, 4), c.rank))
    if m in ("balanced",):
        return sorted(eligible, key=lambda c: (c.rank, COST_ORDER.get(c.cost_class, 4)))
    if m in ("quality_first", "quality-first"):
        # stronger (higher cost) first — still deterministic
        return sorted(eligible, key=lambda c: (-COST_ORDER.get(c.cost_class, 0), c.rank))
    if m in ("manual",):
        return eligible
    return sorted(eligible, key=lambda c: (COST_ORDER.get(c.cost_class, 4), c.rank))


def check_budget(
    spent: float, max_cost: float | None, cost_unknown: bool = False
) -> tuple[bool, str]:
    """Return (exceeded, reason). Unknown costs handled conservatively."""
    if max_cost is None:
        return False, ""
    if cost_unknown:
        return False, "cost_status UNKNOWN"
    if spent > max_cost:
        return True, f"budget exceeded: spent {spent:.2f} > max {max_cost:.2f}"
    if spent >= 0.8 * max_cost:
        return False, "budget warning at 80%"
    return False, ""


def make_decision(
    decision: str, ordered: list[AgentCandidate], selected: str | None, explanation: str,
    reason_codes: list[str] | None = None,
) -> DecisionRecord:
    rej = {c.agent_id: c.reject_reason for c in ordered if c.rejected and c.reject_reason}
    return DecisionRecord(
        decision=decision,
        candidates=[c.agent_id for c in ordered],
        selected=selected,
        rejected=rej,
        reason_codes=reason_codes or [],
        explanation=explanation,
        timestamp=utcnow_iso(),
    )
