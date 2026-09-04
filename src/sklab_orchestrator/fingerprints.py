"""Deterministic fingerprints + run-id generation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from sklab_orchestrator.security import scrub_text


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def normalize_patch(patch: str) -> str:
    # Normalize line endings + trailing whitespace for stable fingerprint.
    lines = patch.replace("\r\n", "\n").split("\n")
    norm = [ln.rstrip() for ln in lines]
    # drop trailing empty lines
    while norm and norm[-1] == "":
        norm.pop()
    return "\n".join(norm) + ("\n" if norm else "")


def patch_fingerprint(patch: str) -> str:
    if not patch:
        return sha256_hex("EMPTY_PATCH")
    return sha256_hex(normalize_patch(patch))


def failure_fingerprint(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(evidence, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def repo_fingerprint(path: str, extra: str = "") -> str:
    return hashlib.sha256(f"{path}|{extra}".encode()).hexdigest()[:16]


def env_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _slugify(text: str, max_words: int = 4) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    # small stop-word filter
    stop = {"the", "a", "an", "in", "on", "of", "to", "and", "fix", "add"}
    kept = [w for w in words if w not in stop][:max_words]
    if not kept:
        kept = words[:max_words] or ["task"]
    return "-".join(kept)[:40]


def generate_run_id(instruction: str = "", now: datetime | None = None) -> str:
    ts = now or datetime.now(UTC)
    stamp = ts.strftime("%Y%m%d-%H%M%S")
    # Slug from the scrubbed instruction: run_id becomes directory names and URL
    # segments, so a pasted secret must never land in it (live leak-test finding).
    slug = _slugify(scrub_text(instruction or "task"))
    fp = hashlib.sha256(f"{instruction}|{ts.isoformat()}".encode()).hexdigest()[:6]
    return f"{stamp}-{slug}-{fp}"
