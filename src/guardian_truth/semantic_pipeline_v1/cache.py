"""Small content-addressed JSON cache with atomic writes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def content_key(*, stage: str, model: str, config: dict, payload) -> str:
    envelope = {"stage": stage, "model": model, "config": config, "payload": payload}
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()


class ContentAddressedCache:
    def __init__(self, root: str | Path, *, resume: bool = True):
        self.root = Path(root)
        self.resume = resume

    def path(self, stage: str, key: str) -> Path:
        return self.root / stage / key[:2] / f"{key}.json"

    def get(self, stage: str, key: str):
        path = self.path(stage, key)
        if not self.resume or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, stage: str, key: str, value) -> Path:
        path = self.path(stage, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(canonical_json(value), encoding="utf-8")
        temporary.replace(path)
        return path
