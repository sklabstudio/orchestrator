"""sklab-run CLI — thin layer over OrchestratorService."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from sklab_orchestrator import __version__
from sklab_orchestrator.config import OrchestratorConfig, load_config
from sklab_orchestrator.integrations import (
    AgentAdaptersIntegration,
    BenchSuiteIntegration,
    CodingLabIntegration,
    PatchBenchIntegration,
    ProviderConnectionsIntegration,
    RepoContextIntegration,
    ReproBoxIntegration,
)
from sklab_orchestrator.service import OrchestratorService
from sklab_orchestrator.store import RunStore

app = typer.Typer(add_completion=False, help="SKLab Orchestrator — task to verified result.",
                    no_args_is_help=False, invoke_without_command=True)
console = Console()
err = Console(stderr=True)


def _svc(config: str | None = None) -> OrchestratorService:
    cfg = load_config(config) if config else None
    try:
        cfg = cfg or load_config()
    except Exception:
        cfg = OrchestratorConfig()
    return OrchestratorService(config=cfg, store=RunStore())


def _print_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


@app.command()
def task(
    repo: str = typer.Option("", "--repo", help="Target repository path"),
    instruction: str = typer.Option("", "--instruction", "--ins", help="Task instruction"),
    task_file: str | None = typer.Option(None, "--task-file", help="File with instruction"),
    bench: str | None = typer.Option(None, "--bench", help="BenchSuite task id"),
    agent: str | None = typer.Option(None, "--agent"),
    model: str | None = typer.Option(None, "--model"),
    connection: str | None = typer.Option(None, "--connection"),
    skill: str | None = typer.Option(None, "--skill"),
    workflow: str | None = typer.Option(None, "--workflow"),
    budget: float | None = typer.Option(None, "--budget"),
    max_attempts: int | None = typer.Option(None, "--max-attempts"),
    timeout: int | None = typer.Option(None, "--timeout"),
    no_reprobox: bool = typer.Option(False, "--no-reprobox"),
    no_verify: bool = typer.Option(False, "--no-verify"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    apply_patch: bool = typer.Option(False, "--apply-patch", help="Allow patch application gate"),
    approved_paid: bool = typer.Option(False, "--approved-paid", help="Pre-approve paid inference"),
    mode: str | None = typer.Option(None, "--mode", help="FREE_ONLY|CHEAP_FIRST|BALANCED|QUALITY_FIRST|MANUAL"),
    policy: str | None = typer.Option(None, "--policy", help="SAFE|NORMAL|POWER"),
    config: str | None = typer.Option(None, "--config"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Create, plan, and execute a task end-to-end."""
    if not instruction and not task_file and not bench:
        err.print("error: provide --instruction, --task-file, or --bench")
        raise typer.Exit(2)
    svc = _svc(config)
    opts: dict = {}
    if agent:
        opts["agent"] = agent
    if model:
        opts["model"] = model
    if connection:
        opts["connection"] = connection
    if skill:
        opts["skill"] = skill
    if workflow:
        opts["workflow"] = workflow
    if budget is not None:
        opts["budget"] = budget
    if max_attempts is not None:
        opts["max_attempts"] = max_attempts
    if timeout is not None:
        opts["timeout"] = timeout
    if no_reprobox:
        opts["use_reprobox"] = False
    if no_verify:
        opts["no_verify"] = True
    if dry_run:
        opts["dry_run"] = True
    if apply_patch:
        opts["apply_patch"] = True
    if approved_paid:
        opts["approved_paid"] = True
    if mode:
        opts["mode"] = mode
    if policy:
        opts["policy"] = policy
    try:
        rec = svc.create_run(instruction or (bench or ""), repo=repo, task_file=task_file,
                             bench=bench, options=opts)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    try:
        result = svc.execute_run(rec.run_id)
    except ValueError as e:
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json(result.model_dump())
    else:
        console.print(f"[bold]run:[/] {result.run_id}  [bold]status:[/] {result.status}")
        if result.verification:
            console.print(f"verdict={result.verification.verdict} score={result.verification.score}")
        if result.status == "APPROVAL_REQUIRED":
            console.print("[yellow]approval required before paid inference[/]")


@app.command()
def inspect(
    run_id: str | None = typer.Argument(None),
    repo: str = typer.Option("", "--repo"),
    instruction: str = typer.Option("inspect", "--instruction"),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Inspect repository (creates ephemeral run when run-id omitted)."""
    svc = _svc(config)
    rid = run_id
    if rid is None:
        rec = svc.create_run(instruction, repo=repo, options={})
        rid = rec.run_id
    try:
        info = svc.inspect_run(rid)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json({"run_id": rid, **info.model_dump()})
    else:
        console.print(f"run: {rid}")
        console.print(f"repo_fingerprint: {info.repo_fingerprint}")
        console.print(f"context_fingerprint: {info.context_fingerprint}")
        console.print(f"repocontext: {info.repo_context_available}")


@app.command()
def plan(
    repo: str = typer.Option("", "--repo"),
    instruction: str = typer.Option("", "--instruction"),
    task_file: str | None = typer.Option(None, "--task-file"),
    bench: str | None = typer.Option(None, "--bench"),
    agent: str | None = typer.Option(None, "--agent"),
    model: str | None = typer.Option(None, "--model"),
    connection: str | None = typer.Option(None, "--connection"),
    skill: str | None = typer.Option(None, "--skill"),
    budget: float | None = typer.Option(None, "--budget"),
    max_attempts: int | None = typer.Option(None, "--max-attempts"),
    run_id: str | None = typer.Option(None, "--run-id"),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Read-only planning (no model inference, no mutation)."""
    svc = _svc(config)
    try:
        if run_id:
            p = svc.plan_run(run_id)
            rid = run_id
        else:
            if not instruction and not task_file and not bench:
                err.print("error: provide --instruction, --task-file, or --bench")
                raise typer.Exit(2)
            opts: dict = {}
            if agent:
                opts["agent"] = agent
            if model:
                opts["model"] = model
            if connection:
                opts["connection"] = connection
            if skill:
                opts["skill"] = skill
            if budget is not None:
                opts["budget"] = budget
            if max_attempts is not None:
                opts["max_attempts"] = max_attempts
            rec = svc.create_run(instruction or (bench or ""), repo=repo,
                                 task_file=task_file, bench=bench, options=opts)
            rid = rec.run_id
            svc.inspect_run(rid)
            p = svc.plan_run(rid)
    except ValueError as e:
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json({"run_id": rid, **p.model_dump()})
    else:
        console.print(f"[bold]run:[/] {rid}")
        console.print(f"classification: {p.classification.category.value} ({p.classification.confidence.value})")
        console.print(f"capabilities: {', '.join(p.required_capabilities)}")
        console.print(f"skill: {p.skill.id if p.skill else '-'}")
        console.print(f"agent: {p.selected_agent}  model: {p.selected_model}  connection: {p.selected_connection}")
        console.print(f"retry: {p.retry_policy}  budget: {p.budget}")
        if p.approval_gates:
            console.print(f"[yellow]approval gates: {p.approval_gates}[/]")


@app.command()
def execute(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Execute (or continue) a planned run."""
    svc = _svc(config)
    try:
        result = svc.execute_run(run_id)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json(result.model_dump())
    else:
        console.print(f"run: {result.run_id}  status: {result.status}")


@app.command()
def resume(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Resume from last safe incomplete stage (idempotent)."""
    svc = _svc(config)
    try:
        result = svc.resume_run(run_id)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json(result.model_dump())
    else:
        console.print(f"run: {result.run_id}  status: {result.status}")


@app.command(name="retry")
def retry_cmd(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retry a failed/blocked run (alias for resume with retry semantics)."""
    svc = _svc(config)
    try:
        result = svc.resume_run(run_id)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json(result.model_dump())
    else:
        console.print(f"run: {result.run_id}  status: {result.status}")


@app.command()
def status(
    run_id: str | None = typer.Argument(None),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Show run status (or latest run when omitted)."""
    store = RunStore()
    rid = run_id
    if rid is None:
        runs = store.list_runs()
        if not runs:
            err.print("no runs found")
            raise typer.Exit(1)
        rid = runs[0]["run_id"]
    try:
        rec = store.load_run(rid)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    payload = {"run_id": rid, "status": rec.status.value, "result_status": rec.result_status,
               "attempts": len(rec.attempts), "updated_at": rec.updated_at}
    if json_out:
        _print_json(payload)
    else:
        console.print(f"run: {rid}  status: {rec.status.value}  result: {rec.result_status or '-'}")


@app.command()
def history(
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """List runs (no secrets)."""
    svc = _svc(config)
    rows = svc.get_history()
    if json_out:
        _print_json(rows)
    else:
        t = Table(title="Runs")
        t.add_column("run-id")
        t.add_column("status")
        t.add_column("attempts")
        t.add_column("winning")
        t.add_column("verdict")
        t.add_column("task")
        for r in rows[:30]:
            t.add_row(r["run_id"], str(r.get("verdict") or r.get("status")),
                      str(r.get("attempts")), str(r.get("winning", "")),
                      str(r.get("verdict", "")), str(r.get("task", ""))[:60])
        console.print(t)


@app.command()
def show(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Show full run detail (secrets redacted)."""
    svc = _svc(config)
    try:
        result = svc.get_result(run_id)
        events = svc.stream_events(run_id)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json({**result.model_dump(), "events": events})
    else:
        console.print(f"[bold]run:[/] {result.run_id}  [bold]status:[/] {result.status}")
        if result.task:
            console.print(f"task: {result.task.instruction[:200]}")
        for a in result.attempts:
            console.print(f" - {a.attempt_id} {a.agent} status={a.status} fp={a.patch_fingerprint[:12]}")
        if result.verification:
            console.print(f"verdict={result.verification.verdict} score={result.verification.score}")
        console.print(f"events: {len(events)}")


@app.command()
def explain(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Explain routing/retry decisions for a run."""
    store = RunStore()
    try:
        plan = store.load_plan(run_id)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    decisions = [d.model_dump() for d in (plan.decisions if plan else [])]
    if json_out:
        _print_json({"run_id": run_id, "decisions": decisions})
    else:
        for d in decisions:
            console.print(f"[bold]{d['decision']}:[/] {d['explanation']}")


@app.command()
def cancel(
    run_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Cancel only processes/workspaces owned by that run."""
    svc = _svc(config)
    try:
        rec = svc.cancel_run(run_id)
    except Exception as e:  # noqa: BLE001
        err.print(f"error: {e}")
        raise typer.Exit(1)
    if json_out:
        _print_json({"run_id": run_id, "status": rec.status.value})
    else:
        console.print(f"run: {run_id} cancelled ({rec.status.value})")


@app.command()
def doctor(
    json_out: bool = typer.Option(False, "--json"),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Zero-cost integration checks (no paid inference)."""
    checks = {
        "repocontext": RepoContextIntegration.available(),
        "agent_adapters": bool(AgentAdaptersIntegration().list_agents()),
        "provider_connections": bool(ProviderConnectionsIntegration().list_connections()),
        "reprobox": ReproBoxIntegration.available(),
        "patchbench": PatchBenchIntegration.available(),
        "benchsuite": BenchSuiteIntegration.available(),
        "coding_lab": CodingLabIntegration.available(),
        "python": True,
    }
    payload = {"ok": True, "checks": checks, "version": __version__}
    if json_out:
        _print_json(payload)
    else:
        for k, v in checks.items():
            console.print(f"{k}: {'available' if v else 'unavailable (fixture fallback)'}")
        console.print(f"version: {__version__}")


@app.command()
def clean(
    run_id: str | None = typer.Argument(None),
    all_tmp: bool = typer.Option(False, "--all-tmp"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Clean only project-owned temporary artifacts (never unrelated files)."""
    removed: list[str] = []
    tmp = Path(tempfile.gettempdir())
    # Only dirs starting with sklab- (project-owned)
    if run_id:
        for ws in [tmp / f"sklab-{run_id}", tmp / f"sklab-{run_id}" / "work"]:
            if ws.exists() and ws.name.startswith("sklab-") or ws.name == "work":
                try:
                    parent = ws if ws.name.startswith("sklab-") else ws.parent
                    if parent.name.startswith("sklab-"):
                        shutil.rmtree(parent, ignore_errors=True)
                        removed.append(str(parent))
                        break
                except Exception:
                    pass
    elif all_tmp:
        for d in tmp.iterdir():
            if d.is_dir() and d.name.startswith("sklab-"):
                shutil.rmtree(d, ignore_errors=True)
                removed.append(str(d))
    if json_out:
        _print_json({"removed": removed})
    else:
        console.print(f"removed {len(removed)} project-owned temp dir(s)")


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Show version", is_eager=True),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit()


if __name__ == "__main__":
    app()
