"""Disk cache for eCFR responses.

eCFR updates at most daily, and historical point-in-time content never changes
at all. Caching is the whole reason this server can be a good citizen against
an API that publishes no rate limit and has no key to identify us politely.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_TTL = 24 * 60 * 60  # eCFR updates daily


def _default_dir() -> Path:
    env = os.environ.get("CFR_MCP_CACHE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "cfr-mcp"


class Cache:
    def __init__(self, directory: Path | None = None, ttl: int = DEFAULT_TTL) -> None:
        self.dir = directory or _default_dir()
        self.ttl = ttl
        self.dir.mkdir(parents=True, exist_ok=True)

    def key(self, path: str, params: dict[str, Any] | None = None) -> str:
        blob = path + "?" + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.dir / f"{key}.body", self.dir / f"{key}.meta"

    def get(self, key: str) -> str | None:
        body_path, meta_path = self._paths(key)
        if not (body_path.exists() and meta_path.exists()):
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if (
            not meta.get("immutable")
            and time.time() - meta.get("stored_at", 0) > self.ttl
        ):
            return None
        try:
            return body_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def set(self, key: str, body: str, *, immutable: bool = False) -> None:
        body_path, meta_path = self._paths(key)
        try:
            # Write body first; a torn write leaves no meta and reads as a miss.
            body_path.write_text(body, encoding="utf-8")
            meta_path.write_text(
                json.dumps({"stored_at": time.time(), "immutable": immutable})
            )
        except OSError:
            pass  # cache failures must never break a lookup

    def clear(self) -> int:
        removed = 0
        for f in self.dir.glob("*.*"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        return removed // 2
