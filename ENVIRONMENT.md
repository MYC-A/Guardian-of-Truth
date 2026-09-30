# ENVIRONMENT — research/three-architectures-24gb-20260930

Snapshot taken 2026-09-30 (new instance after migration). No secrets inside.

## Hardware (measured)

- GPU: NVIDIA GeForce RTX 3090 — 24576 MiB (24 GB class; prompt constraint assumed 24 GB VRAM)
- GPU driver: 580.159.03; CUDA Version: 13.0
- CUDA toolkit in image: 12.8 (nvcc V12.8.93); torch runs cu128 wheels
- CPU cores: 24
- Host RAM visible: 61 GiB; cgroup memory.max: 42.0 GiB
- Disk (overlay): 32G total, 11G free
- Container: Docker (vast.ai image, kernel 6.8.0-124-generic), hostname 24a8e939b2cc

**Design constraint per directive:** 24 GB GPU VRAM / 31 GB system RAM.
Measured limits are LOOSER (42 GiB cgroup RAM, 61 GiB host). All experiment
sizing in this branch is done against the stricter directive numbers
(24 GB / 31 GB); measured headroom is documented but not relied upon.

## Workspace layout

```
/workspace/guardian/
  venv/                    research venv (Python 3.12.3, uv)
  repos/Guardian-of-Truth/  repo, research branch checked out
  models/granite-guardian-4.1-8b/   (16G, Apache 2.0, rev recorded in .download_meta.json)
  hf_cache/                HF_HOME
  secrets/                 mistral.env, github_pat, api_keys.env (chmod 600/700, never printed)
  results/  logs/
```

## Python stack (venv, proven stack from previous stand)

torch 2.10.0+cu128+cu128 (CUDA on RTX 3090 verified: matmul+autograd OK),
transformers 5.16.1, sentence-transformers 6.0.1, peft 0.21.0, accelerate,
langextract 1.7.0, compressed-tensors 0.15.0, pandas, pyarrow, numpy,
requests, openai, pytest/pytest-asyncio, clingo, fastapi, uvicorn,
jsonschema, pydantic, hypothesis; guardian-truth editable install.

## API channels (smoke-tested 2026-09-30, statuses only)

| channel | endpoint | status | notes |
|---|---|---|---|
| Mistral | api.mistral.ai | 200 OK (chat completion) | key in secrets/mistral.env, model ministral-14b-latest |
| ollama.com free | ollama.com/v1 | 200 OK | gemma4:31b responded "OK"; also gpt-oss:20b/120b, nemotron-3-nano:30b/-super/-ultra worked in prior session; glm-5.3-flash is 402 paywalled |
| ukisai swift | ukisai.com/api/swift/v1 | 200 OK | reasoning model: allow higher max_tokens, content may trail reasoning_content |
| vireonix auto | vireonix.ai/v1 | 200 OK | model "auto" answered "OK"; actual backing family unverifiable — do not claim family independence |

Local GPU model: granite-guardian-4.1-8b (bf16 ≈ 15.6 GiB VRAM when loaded;
measured on the previous stand; sequential load/unload discipline).

## Provenance of environment facts

- Migration from previous vast stand (171.5.185.194:44479, RTX 3090 24G,
  125G RAM) — that stand is no longer reachable; all facts above were
  re-measured on THIS instance, not copied.
- Free-API provider credentials originate from the user's previous-session
  handoff (chat history), stored in secrets/api_keys.env; never printed.
