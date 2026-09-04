"""Explicit run state machine with persisted transitions."""

from __future__ import annotations

from sklab_orchestrator.models import RunStatus

ALLOWED: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {
        RunStatus.INSPECTING,
        RunStatus.PLANNING,
        RunStatus.CANCELLED,
        RunStatus.BLOCKED,
    },
    RunStatus.INSPECTING: {
        RunStatus.PLANNING,
        RunStatus.BLOCKED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.WAITING_FOR_APPROVAL,
    },
    RunStatus.PLANNING: {
        RunStatus.PREPARING,
        RunStatus.WAITING_FOR_APPROVAL,
        RunStatus.BLOCKED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.WAITING_FOR_APPROVAL: {
        RunStatus.PREPARING,
        RunStatus.CANCELLED,
        RunStatus.BLOCKED,
        RunStatus.FAILED,
    },
    RunStatus.PREPARING: {
        RunStatus.RUNNING_AGENT,
        RunStatus.BLOCKED,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.WAITING_FOR_APPROVAL,
    },
    RunStatus.RUNNING_AGENT: {
        RunStatus.CAPTURING_PATCH,
        RunStatus.ANALYZING_FAILURE,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
    },
    RunStatus.CAPTURING_PATCH: {
        RunStatus.VERIFYING,
        RunStatus.ANALYZING_FAILURE,
        RunStatus.CANCELLED,
        RunStatus.FAILED,
    },
    RunStatus.VERIFYING: {
        RunStatus.ANALYZING_FAILURE,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.ANALYZING_FAILURE: {
        RunStatus.RETRYING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.BLOCKED,
        RunStatus.CANCELLED,
        RunStatus.WAITING_FOR_APPROVAL,
    },
    RunStatus.RETRYING: {
        RunStatus.PREPARING,
        RunStatus.RUNNING_AGENT,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.BLOCKED,
        RunStatus.WAITING_FOR_APPROVAL,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
    RunStatus.BLOCKED: set(),
}

TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.BLOCKED}


class IllegalTransition(ValueError):
    pass


def check_transition(frm: RunStatus, to: RunStatus) -> None:
    if frm == to:
        return
    allowed = ALLOWED.get(frm, set())
    if to not in allowed:
        raise IllegalTransition(f"illegal transition {frm} -> {to}")


def is_terminal(status: RunStatus) -> bool:
    return status in TERMINAL
