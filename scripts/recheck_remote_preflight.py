"""Read-only server preflight. Prints no credential values."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "public46": "outputs/full21/input/public46_label_free.csv",
    "control": "outputs/full21/control_repro_percase.csv",
    "pgjudge": "outputs/big_researh/p_api/pgjudge/records.jsonl",
    "pcards": "outputs/big_researh/p_api/extract/cards.jsonl",
    "q_divergences": "outputs/searh_23/q_v2/divergences.jsonl",
    "s7_suspicions": "outputs/research_granite_guardian/full21_s7_plain/records.jsonl",
    "c2_proposals": "outputs/cycle2/claim_proposals_checkpoint.json",
    "c2_sources": "outputs/cycle2/claim_cases.json",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    model = Path("/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda")
    candidates = (Path("/mnt/data/guardian/secrets/mistral.env"),
                  Path("/mnt/data/guardian/agent-workspace/.mistral.env"))
    secret = next((path for path in candidates
                   if os.access(path, os.R_OK) and path.is_file()), candidates[0])
    try:
        secret_lines = secret.read_text(encoding="utf-8").splitlines()
        key_present = any(line.strip().removeprefix("export ").startswith("MISTRAL_API_KEY=")
                          and len(line.partition("=")[2].strip()) > 0
                          for line in secret_lines)
        model_present = any(line.strip().removeprefix("export ").startswith("MISTRAL_MODEL=")
                            for line in secret_lines)
    except (OSError, UnicodeError):
        key_present = model_present = False
    try:
        import torch
        cuda = torch.cuda.is_available()
        gpu = torch.cuda.get_device_name(0) if cuda else None
        torch_version = torch.__version__
    except Exception as exc:
        cuda = False
        gpu = None
        torch_version = f"unavailable:{type(exc).__name__}"
    result = {
        "python": sys.version.split()[0], "torch": torch_version,
        "cuda": cuda, "gpu": gpu,
        "modules": {name: importlib.util.find_spec(name) is not None
                    for name in ("clingo", "openai", "transformers", "accelerate", "pytest")},
        "inputs": {name: {"exists": (path := ROOT / relative).is_file(),
                           "sha256": sha(path) if path.is_file() else None}
                   for name, relative in INPUTS.items()},
        "mistral_secret_file_readable": os.access(secret, os.R_OK),
        "mistral_secret_file": str(secret),
        "mistral_key_present": key_present,
        "mistral_model_present": model_present,
        "granite_model_config": (model / "config.json").is_file(),
        "granite_weight_files": len(list(model.glob("*.safetensors"))),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
