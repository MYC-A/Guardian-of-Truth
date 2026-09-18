"""Dependency-isolated GLiNER2.5 subprocess adapter.

The Guardian process intentionally never imports gliner2 or its Transformers
4.x dependency tree. The sidecar accepts/returns plain JSON only.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


class GLiNER2SidecarError(RuntimeError):
    pass


class GLiNER2Sidecar:
    ENTITY_LABELS = {
        "action": "an action or operation",
        "state": "a state or property",
        "value": "a constrained value",
        "entity": "an object or identifier",
        "claim": "an asserted claim",
    }
    RELATION_LABELS = ("before", "after", "unless", "requires", "prohibits", "allows",
                       "condition_for", "exception_to")

    def __init__(self, *, model_name: str, python_executable: str,
                 timeout_seconds: float = 600.0, worker_path: str | Path | None = None,
                 run=None):
        self.model_name = model_name
        self.python_executable = python_executable
        self.timeout_seconds = timeout_seconds
        self.worker_path = Path(worker_path) if worker_path else (
            Path(__file__).resolve().parents[4] / "scripts" / "gliner2_semantic_sidecar.py")
        self._run = run or subprocess.run

    def extract_batch(self, items: list[dict], *, device: str = "cuda") -> dict:
        request = {
            "model": self.model_name,
            "device": device,
            "quantize": device.startswith("cuda"),
            "entity_labels": self.ENTITY_LABELS,
            "relation_labels": list(self.RELATION_LABELS),
            "items": items,
        }
        try:
            completed = self._run(
                [self.python_executable, str(self.worker_path)],
                input=json.dumps(request, ensure_ascii=False), text=True,
                capture_output=True, timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise GLiNER2SidecarError(str(error)) from error
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "sidecar failed").strip()
            raise GLiNER2SidecarError(message[-2000:])
        try:
            response = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise GLiNER2SidecarError("sidecar did not return one JSON object") from error
        if response.get("status") != "EXECUTED":
            raise GLiNER2SidecarError(str(response.get("error") or "sidecar unavailable"))
        return response


# Compatibility alias for callers that imported the old optional adapter.
GLiNEREvidenceExtractor = GLiNER2Sidecar
