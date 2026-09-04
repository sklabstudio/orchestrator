"""Local historical performance store (evidence only, no auto-RL)."""

from __future__ import annotations

import json
from pathlib import Path


class PerformanceStore:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or Path.cwd() / ".sklab" / "performance.jsonl")

    def record(self, entry: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # strip anything sensitive defensively
        safe = {k: v for k, v in entry.items() if "secret" not in k.lower() and "token" not in k.lower()}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe, default=str) + "\n")

    def stats(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        # aggregate by (category, agent, skill)
        agg: dict[tuple, dict] = {}
        for r in rows:
            key = (r.get("category", "?"), r.get("agent", "?"), r.get("skill", "?"))
            a = agg.setdefault(key, {"category": key[0], "agent": key[1], "skill": key[2],
                                     "attempts": 0, "verified": 0, "total_score": 0.0})
            a["attempts"] += 1
            if r.get("verified"):
                a["verified"] += 1
            try:
                a["total_score"] += float(r.get("score", 0.0))
            except Exception:
                pass
        out = []
        for a in agg.values():
            a["avg_score"] = round(a["total_score"] / max(1, a["attempts"]), 2)
            del a["total_score"]
            out.append(a)
        return sorted(out, key=lambda x: (-x["verified"], -x["avg_score"]))
