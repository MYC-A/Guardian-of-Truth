#!/usr/bin/env python3
"""Download Mistral-7B-Instruct-v0.3 into a writable persistent dir (FULL_21 local Mistral channel)."""
import json
import os
import time

TARGET = "/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3"
os.makedirs(os.path.dirname(TARGET), exist_ok=True)

from huggingface_hub import snapshot_download

t0 = time.time()
path = snapshot_download(
    repo_id="mistralai/Mistral-7B-Instruct-v0.3",
    local_dir=TARGET,
    allow_patterns=["*.json", "*.safetensors", "tokenizer.model", "tokenizer*",
                    "*.txt", "*.jinja", "LICENSE*", "README*"],
)
dt = time.time() - t0
size = 0
for root, _, files in os.walk(TARGET):
    for f in files:
        try:
            size += os.path.getsize(os.path.join(root, f))
        except OSError:
            pass
print(json.dumps({
    "path": path, "seconds": round(dt, 1), "bytes": size,
    "gb": round(size / 1e9, 2),
    "files": sorted(os.listdir(TARGET)),
}, indent=1))
