"""Read-only final-delivery evidence inventory; never manufactures missing results.

This is a gate, not proof that the architecture works. A complete artifact set
still needs semantic, certificate, baseline and blind-promotion verification.
"""

from dataclasses import dataclass
import json
from pathlib import Path

from .integrity import file_digest


@dataclass(frozen=True)
class DeliveryAudit:
    requirements_sha256: str
    present: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]
    invalid: tuple[str, ...]
    not_established: tuple[str, ...]
    complete_artifact_inventory: bool
    scope: str = "REQUIRED_ARTIFACT_INVENTORY_NOT_SEMANTIC_OR_PROMOTION_PROOF"


def audit_delivery(root: Path, requirements_path: Path) -> DeliveryAudit:
    """Validate exact declared required outputs and their parseability.

    `final_manifest.json` is checked if already present, but cannot be required
    before it is created. Its own content/hash consistency is a later audit.
    Failure or missing file is reported, not auto-filled with a placeholder.
    """
    root = root.resolve()
    requirements_path = requirements_path.resolve()
    if not requirements_path.is_file() or not requirements_path.is_relative_to(root):
        raise ValueError("exact workspace-local requirements source required")
    requirements = json.loads(requirements_path.read_text(encoding="utf-8"))
    if requirements.get("schema_version") != "guardian-vnext-requirements-v1":
        raise ValueError("unknown requirements contract version")
    inventory = []
    for key, directory, extension in (("required_json", "outputs/vnext", ".json"),
            ("required_jsonl", "outputs/vnext", ".jsonl"), ("required_docs", "docs/vnext", ".md")):
        names = requirements.get(key)
        if not isinstance(names, list) or len(names) != len(set(names)) or not names:
            raise ValueError("nonempty unique required artifact names required")
        for name in names:
            if not isinstance(name, str) or Path(name).name != name or not name.endswith(extension):
                raise ValueError("unsafe required artifact path")
            inventory.append((root / directory / name, key))
    present, missing, invalid, not_established = [], [], [], []
    for path, kind in inventory:
        relative = path.relative_to(root).as_posix()
        if not path.is_file():
            missing.append(relative)
            continue
        raw = path.read_bytes()
        if not raw:
            invalid.append(relative + ":EMPTY")
            continue
        try:
            if kind == "required_json":
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, (dict, list)):
                    raise ValueError("top-level JSON must be object/array")
            elif kind == "required_jsonl":
                lines = raw.decode("utf-8").splitlines()
                if not lines or any(not line.strip() or not isinstance(json.loads(line), dict) for line in lines):
                    raise ValueError("nonempty JSONL object records required")
            else:
                text = raw.decode("utf-8")
                if not text.strip():
                    raise ValueError("nonempty document required")
                if path.name in {"END_TO_END_RESULTS.md", "FINAL_DECISION.md"} and "NOT_RUN" in text:
                    not_established.append(relative + ":NOT_RUN")
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            invalid.append(relative + ":INVALID_FORMAT")
            continue
        present.append((relative, file_digest(path)))
    # Inventory alone can be fully present while important model/semantic gates
    # fail. Consumers must not equate this flag with final promotion.
    complete = not missing and not invalid and not not_established
    return DeliveryAudit(file_digest(requirements_path), tuple(present), tuple(missing), tuple(invalid),
        tuple(not_established), complete)
