#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python - <<'PY'
import sys
import torch

print("Python:", sys.version.split()[0])
print("PyTorch:", torch.__version__)
print("CUDA runtime:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())
print("CUDA device count:", torch.cuda.device_count())
if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
    raise SystemExit("Semantic Pipeline V1 setup requires a Colab GPU runtime; stock PyTorch was left unchanged.")
print("GPU:", torch.cuda.get_device_name(0))
PY

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
python -m pip install --dry-run --report "$TMP_DIR/pip-report.json" \
  -e '.[data,semantic-v1-colab]'
python - "$TMP_DIR/pip-report.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
forbidden = {"torch", "torchvision", "torchaudio"}
planned = {item.get("metadata", {}).get("name", "").lower() for item in report.get("install", [])}
bad = sorted(forbidden & planned)
if bad:
    raise SystemExit("Refusing dependency plan that would install/replace stock Colab packages: " + ", ".join(bad))
print("Dependency plan preserves stock PyTorch/CUDA.")
PY

python -m pip install --upgrade-strategy only-if-needed -e '.[data,semantic-v1-colab]'
python - <<'PY'
import langextract
import sentence_transformers
import transformers
import guardian_truth.semantic_pipeline_v1

print("transformers:", transformers.__version__)
print("sentence-transformers:", sentence_transformers.__version__)
print("Semantic Pipeline V1 imports: OK")
print("Large checkpoints were NOT downloaded. Use scripts/preload_semantic_models_v1.py when desired.")
PY
