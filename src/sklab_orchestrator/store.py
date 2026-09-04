"""Persistent run store under .sklab/runs/<run-id>/ (no secrets ever)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sklab_orchestrator.models import AttemptRecord, Plan, RunRecord, RunStatus, utcnow_iso
from sklab_orchestrator.security import scrub_dict
from sklab_orchestrator.state_machine import check_transition


def _runs_root(base: Path | str | None = None) -> Path:
    return Path(base or Path.cwd() / ".sklab" / "runs")


class RunStore:
    def __init__(self, root: Path | str | None = None):
        self.root = _runs_root(root)

    # -- paths --
    def run_dir(self, run_id: str) -> Path:
        return self.root / run_id

    def create(self, record: RunRecord) -> Path:
        d = self.run_dir(record.run_id)
        d.mkdir(parents=True, exist_ok=False)
        (d / "artifacts").mkdir(exist_ok=True)
        self.save_run(record)
        (d / "events.jsonl").write_text("", encoding="utf-8")
        (d / "attempts.jsonl").write_text("", encoding="utf-8")
        return d

    def save_run(self, record: RunRecord) -> None:
        record.updated_at = utcnow_iso()
        d = self.run_dir(record.run_id)
        d.mkdir(parents=True, exist_ok=True)
        payload = scrub_dict(record.model_dump())
        (d / "run.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def load_run(self, run_id: str) -> RunRecord:
        p = self.run_dir(run_id) / "run.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        return RunRecord.model_validate(data)

    def exists(self, run_id: str) -> bool:
        return (self.run_dir(run_id) / "run.json").exists()

    def transition(self, run_id: str, to: RunStatus) -> RunRecord:
        rec = self.load_run(run_id)
        check_transition(rec.status, to)
        rec.status = to
        self.save_run(rec)
        return rec

    def save_plan(self, run_id: str, plan: Plan) -> None:
        d = self.run_dir(run_id)
        (d / "plan.json").write_text(
            json.dumps(scrub_dict(plan.model_dump()), indent=2, default=str), encoding="utf-8")

    def load_plan(self, run_id: str) -> Plan | None:
        p = self.run_dir(run_id) / "plan.json"
        if not p.exists():
            return None
        return Plan.model_validate(json.loads(p.read_text(encoding="utf-8")))

    def emit(self, run_id: str, event: str, data: dict[str, Any] | None = None) -> None:
        d = self.run_dir(run_id)
        line = json.dumps({"ts": utcnow_iso(), "event": event, **scrub_dict(data or {})},
                          default=str)
        with (d / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def events(self, run_id: str) -> list[dict[str, Any]]:
        p = self.run_dir(run_id) / "events.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    def append_attempt(self, run_id: str, attempt: AttemptRecord) -> None:
        # attempts.jsonl is append-only log; run.json holds authoritative list
        d = self.run_dir(run_id)
        with (d / "attempts.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(scrub_dict(attempt.model_dump()), default=str) + "\n")

    def save_result(self, run_id: str, result: dict[str, Any]) -> None:
        d = self.run_dir(run_id)
        (d / "result.json").write_text(
            json.dumps(scrub_dict(result), indent=2, default=str), encoding="utf-8")

    def load_result(self, run_id: str) -> dict[str, Any] | None:
        p = self.run_dir(run_id) / "result.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        out = []
        for d in sorted(self.root.iterdir()):
            rp = d / "run.json"
            if rp.exists():
                try:
                    data = json.loads(rp.read_text(encoding="utf-8"))
                    out.append({
                        "run_id": data.get("run_id", d.name),
                        "status": data.get("status", ""),
                        "result_status": data.get("result_status", ""),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "attempts": len(data.get("attempts", [])),
                        "task": (data.get("task") or {}).get("instruction", "")[:120],
                        "repository": (data.get("task") or {}).get("repository", ""),
                    })
                except Exception:
                    continue
        return sorted(out, key=lambda r: r["run_id"], reverse=True)

    def duration_ms(self, run_id: str) -> int:
        try:
            rec = self.load_run(run_id)
            t0 = datetime.fromisoformat(rec.created_at)
            t1 = datetime.fromisoformat(rec.updated_at)
            return max(0, int((t1 - t0).total_seconds() * 1000))
        except Exception:
            return 0
