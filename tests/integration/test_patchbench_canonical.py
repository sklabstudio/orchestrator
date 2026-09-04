"""L4 regression: canonical PatchBench contract (good->ACCEPT, bad->REJECT).

Primary path is the typed Python API (``run_evaluation``); the machine-readable
``patchbench evaluate --json`` CLI is the explicit fallback. The ``via`` key
records which path produced the result.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sklab_orchestrator.integrations import PatchBenchIntegration

GOOD_DIFF = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,3 @@
 def add(a, b):
+    \"\"\"Add two numbers.\"\"\"
     return a + b
"""

BAD_DIFF = """diff --git a/calc.py b/calc.py
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a - b
"""


@pytest.fixture()
def calc_repo(tmp_path: Path) -> Path:
    root = tmp_path / "calc-demo"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"calc-demo\"\nversion = \"0.1.0\"\n\n"
        "[tool.pytest.ini_options]\ntestpaths = [\".\"]\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    return root


def test_canonical_python_api_good_accept_bad_reject(calc_repo: Path) -> None:
    good = PatchBenchIntegration.verify(GOOD_DIFF, str(calc_repo), timeout=60)
    bad = PatchBenchIntegration.verify(BAD_DIFF, str(calc_repo), timeout=60)
    assert good is not None and bad is not None
    assert good["via"] == "patchbench-python-api", good
    assert bad["via"] == "patchbench-python-api", bad
    assert good["verdict"] == "ACCEPT", good
    assert bad["verdict"] == "REJECT", bad


def test_cli_json_fallback_contract(calc_repo: Path, tmp_path: Path) -> None:
    patch_file = tmp_path / "good.diff"
    patch_file.write_text(GOOD_DIFF, encoding="utf-8")
    out = subprocess.run(
        ["patchbench", "evaluate", "--patch", str(patch_file), "--repo", str(calc_repo),
         "--json", "--offline", "--timeout", "60", "--no-lint", "--no-typecheck", "--no-build"],
        capture_output=True, text=True, timeout=180,
    )
    payload: dict | None = None
    try:
        whole = json.loads(out.stdout or "")
        if isinstance(whole, dict) and "verdict" in whole:
            payload = whole
    except Exception:
        pass
    if payload is None:
        for line in reversed((out.stdout or "").strip().splitlines()):
            try:
                candidate = json.loads(line)
            except Exception:
                continue
            if isinstance(candidate, dict) and "verdict" in candidate:
                payload = candidate
                break
    assert payload is not None, out.stdout[-2000:] + out.stderr[-2000:]
    assert str(payload["verdict"]).upper() == "ACCEPT", payload
