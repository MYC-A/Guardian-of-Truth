#!/bin/bash
set -euo pipefail
root=/workspace/guardian-lab-20261018
export UV_CACHE_DIR="$root/uv-cache"
export UV_LINK_MODE=copy
uv pip install --python "$root/venv/bin/python" \
  --torch-backend=cu128 --index-strategy=unsafe-best-match \
  'vllm==0.19.1' 'torch==2.10.0+cu128' 'triton==3.6.0' 'transformers==5.8.0' \
  'pandas==2.3.2' 'pyarrow==21.0.0' \
  --extra-index-url https://download.pytorch.org/whl/cu128
"$root/venv/bin/python" -m pip freeze > "$root/runtime-freeze.txt" 2>/dev/null || \
  uv pip freeze --python "$root/venv/bin/python" > "$root/runtime-freeze.txt"
"$root/venv/bin/python" - <<'PY'
import json,torch,importlib.metadata as m
from pathlib import Path
result={n:m.version(n) for n in ('vllm','torch','triton','transformers','huggingface_hub')}
result.update(gpu=torch.cuda.get_device_name(),cuda=torch.version.cuda,capability=torch.cuda.get_device_capability())
x=torch.ones(8,device='cuda'); assert x.sum().item()==8
Path('/workspace/guardian-lab-20261018/RUNTIME_READY.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
