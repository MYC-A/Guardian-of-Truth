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

## Re-provisioning addendum (2026-10-01, second stand migration)

The instance hosting this branch's runs became unreachable; the stand was
rebuilt on a new Vast machine (RTX 3090 24 GB, driver 595.84, CUDA 12.8
toolkit, 64 cores, 251 GiB RAM, hostname e0d16af6cec4). Everything below was
re-measured on THIS instance; the worktree lives at
`/workspace/guardian/repos/hybrid-assistants-worktree` (the path the launch
scripts expect) at branch HEAD 871293c9.

Re-verified on the new stand:

- venv: torch 2.10.0+cu128 (CUDA matmul+autograd OK), transformers 5.16.1,
  huggingface-hub 1.33.0 (pinned <2.0 for transformers 5.16.1), nltk + punkt
  (required by factcg_native.py), guardian-truth editable.
- granite-guardian-4.1-8b re-downloaded at pinned revision
  ab01ccca5dcfb80246369a086a4a87a29198f5af (16 G); bf16 local channel via
  llm.py: cold load ~10 s, greedy generation ~2 s, VRAM freed on exit.
- MiniCheck-Flan-T5-Large re-fetched from lytang/MiniCheck-Flan-T5-Large.
  Disk-dedup note: the hub cache held BOTH the original pytorch_model.bin
  and the HF auto-conversion model.safetensors (3.13 G each). The two were
  proven functionally IDENTICAL on the branch's 15-case native bank
  (same per-example probabilities to 3 decimals, acc .867, misses exactly
  on the two policy-interpretation cases — bit-consistent with the smoke
  recorded on the previous stand). To keep both load paths
  (main-ref bin / device_map conversion ref) resolving to the same bytes
  without re-downloading, the conversion blob was replaced by a hardlink to
  the original (freed 3.13 G; disk now ~3.7 G free).
- FactCG-DeBERTa-v3-Large re-fetched at pinned revision
  0430e3509dbd28d2dff7a117c0eae25359ff3e80; the redundant
  pytorch_lightning_ckpt (~1.7 G) is deliberately NOT downloaded
  (model.safetensors is the only weights path factcg_native.py loads);
  native-format load + score verified on GPU (435M params, 1.64 GiB VRAM).
- Bespoke-MiniCheck-7B and PRT-Qwen-7B remain BLOCKED:disk (unchanged
  protocol decision — ~15 GB weights each do not fit alongside granite).
- All five API channels re-smoked through llm.py: mistral 0.7 s, ollama
  gemma4:31b 0.7 s, ollama gpt-oss:20b 0.9 s, ukisai swift 1.0 s, vireonix
  auto 2.6 s — all answered the standard prompt.
- Branch test suite: 42 passed (hybrid_service_v1: archive_dsp,
  formal_advisory, specialist_bank, structural_v02, v2_boundaries;
  tests/: fresh_suite_v1, hybrid_campaign, hybrid_service_fixes).
- service/test_service_smoke.py in its script mode (as on the previous
  stand): 7/7 passed, including the batch CLI + JSONL audit path. In the
  isolated smoke environment the v6-judges config reached the live judge
  channels (provisioned here) and returned a valid verdict.
- Native checker bank reproduction (the numbers the protocol's Stage A
  recorded): MiniCheck-Flan-T5-Large 15/15 format, acc .867, misses
  idx {3, 13} = the two policy-applicability cases — identical to the
  previous stand's smoke. FactCG and Granite BYOC load and answer in their
  native formats on this stand.

No committed outputs were modified by the re-provisioning; the smoke
reproductions above were run as ad-hoc probes (not written into
outputs/native_smoke*), preserving the recorded results.

## New free channels addendum (2026-10-02, third-stand session)

User-supplied additional free API models were probed (one short real chat
probe per channel; probes are counted attempts):

- ollama.com/v1 now also answers: glm-5.3-flash -> HTTP 402 "not included
  in your free usage" (channel OFF, quota-blocked; do not re-probe until
  quota/config changes), gpt-oss:120b (reasoning model — empty content at
  tiny max_tokens; needs larger output budgets), nemotron-3-nano:30b,
  nemotron-3-super, nemotron-3-ultra (all OK, 0.6-1.5 s).
  gpt-oss:20b/gemma4:31b and ukisai/swift + vireonix/auto re-confirmed.
- NEW provider aihorde (oai.aihorde.net/v1, anonymous public key
  "0000000000", crowdsourced: latency/availability vary): google/
  gemma-4-31b OK (7.1 s via llm.py), koboldcpp/Llama-3.2-3B-Instruct OK
  (2.9 s). koboldcpp/Qwen/Qwen3.5-0.8B timed out at 150 s (worker offline;
  not retried — low value). response_format/json_object is NOT sent to
  aihorde (compat not guaranteed), same guard as ukisai/swift.
- Family accounting: google/gemma-4-31b is the SAME gemma family as
  gemma4:31b (transport redundancy only, never an independent family
  vote); koboldcpp/Llama-3.2-3B-Instruct is the small llama family;
  nemotron-3-* sizes are one nemotron family; gpt-oss:20b/120b one family.
- llm.py registry extended accordingly (aihorde provider + two models);
  verified through the real llm.py transport path with cache disabled.
