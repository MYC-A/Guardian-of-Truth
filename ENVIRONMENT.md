# ENVIRONMENT — research/three-architectures-24gb-20260930

Snapshot taken 2026-10-01 (stand re-provisioned on a new Vast instance after
the previous one became unreachable). No secrets inside.

## Hardware (measured on this stand)

- GPU: NVIDIA GeForce RTX 3090 — 24576 MiB (24 GB class; prompt constraint assumed 24 GB VRAM)
- GPU driver: 595.84; CUDA Version: 13.2
- CUDA toolkit in image: 12.8 (nvcc V12.8.93); torch runs cu128 wheels
- CPU cores: 64
- Host RAM visible: 251 GiB
- Disk (overlay): 32G total; ~24G used after full provisioning (repo + venv +
  granite model + hf_cache), ~8.6G free
- Container: Docker (vast.ai image), hostname e0d16af6cec4
- Persistence: workspace_is_volume = FALSE — recycle/destroy wipes the
  filesystem; results must leave the box via git push immediately after runs.

**Design constraint per directive:** 24 GB GPU VRAM / 31 GB system RAM.
All experiment sizing in this branch is done against the stricter directive
numbers (24 GB / 31 GB); measured headroom is documented but not relied upon.

## Workspace layout

```
/workspace/guardian/
  venv/                    research venv (Python 3.12.3, uv)
  repos/Guardian-of-Truth/  repo, research branch checked out
  models/granite-guardian-4.1-8b/   (16G, Apache 2.0, pinned revision
                                     ab01ccca5dcfb80246369a086a4a87a29198f5af,
                                     provenance in download_info.json)
  hf_cache/                HF_HOME
  secrets/                 mistral.env, api_keys.env, github_pat (chmod 600/700, never printed)
  results/  logs/
```

## Python stack (venv, proven stack from previous stand)

torch 2.10.0+cu128 (CUDA on RTX 3090 verified on this stand: matmul+autograd
OK), transformers 5.16.1, huggingface-hub 1.33.0, sentence-transformers 6.0.1,
peft 0.21.0, accelerate 1.15.0, langextract 1.7.0, compressed-tensors 0.15.0,
pandas 3.0.6, pyarrow 25.0.1, numpy 2.5.3, requests 2.34.2, openai 3.22.1,
pytest 8.4.2 / pytest-asyncio 0.26.0, clingo 5.8.2, fastapi 0.142.2,
uvicorn 0.54.0, jsonschema 4.26.0, pydantic 2.13.5, hypothesis 6.168.3;
guardian-truth 0.2.0 editable install.

## API channels (re-smoke-tested 2026-10-01 on THIS stand, statuses only)

| channel | endpoint | status | notes |
|---|---|---|---|
| Mistral | api.mistral.ai | 200 OK ('OK', 0.7 s) | key in secrets/mistral.env, model ministral-14b-latest |
| ollama.com free | ollama.com/v1 | 200 OK | gemma4:31b 'OK' 0.7 s; gpt-oss:20b 'OK' 0.9 s |
| ukisai swift | ukisai.com/api/swift/v1 | 200 OK ('OK', 1.0 s) | reasoning model: allow higher max_tokens |
| vireonix auto | vireonix.ai/v1 | 200 OK ('OK', 2.6 s) | family UNVERIFIABLE — never counted as an independent family |

Local GPU model: granite-guardian-4.1-8b (bf16 ≈ 15.6 GiB VRAM when loaded;
verified on this stand: cold load ~10 s, greedy generation ~2 s for 40 tokens;
VRAM fully freed on process exit — sequential load/unload discipline).

## Environment-equivalence evidence (post-migration integrity check)

- Repo re-cloned from origin; branch research/three-architectures-24gb-20260930
  at 4df13b97 (same HEAD as the last push from the previous stand).
- V6 dev-pilot v2 re-scored from the committed outputs with the fresh venv:
  TP6 FP1 FN0 TN3 P=.8571 R=1.0000 F1=.9231 — identical to the recorded numbers.
- All five API channels answered the standard smoke prompt on this stand.
- granite-local channel exercised end-to-end through llm.py (load + generation).

## Provenance of environment facts

- Migration from the previous stand (RTX 3090 24G, hostname 24a8e939b2cc) —
  no longer reachable; all facts above were re-measured on THIS instance,
  not copied.
- Free-API provider credentials originate from the user's previous-session
  handoff (chat history), stored in secrets/api_keys.env; never printed.
