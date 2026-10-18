# Six-question submission protocol — 18.10.2026

Base: 4a2f38e2892ef26160ac72799a217903b20827aa. User selected six questions after
an unchanged platform score from the blind ZIP. No platform logs or per-row
predictions are available; overall fallback is a hypothesis, not an established cause.

One candidate is fixed before new model results: `submission/JUDGE_6Q_SUBMISSION.json`.
Same legacy context/hints/response per row, unchanged questions from prompting.py,
all six `@on` keys, equal-weight `mean_z`, population standard deviation across
primary-scored rows. Zero variance uses std=1. This is an exploratory untrained
aggregation rule, not a fitted/calibrated probability. No coefficient or threshold
selection from valid46 or the leaderboard. No extra models, blind, shuffle, retry
ensemble, result cache, or question rewriting. `tool_use` checks performed calls;
it is not a detector of every omitted required action.

The model remains cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit at revision
00fcea2d3bcf5389b518d4fc082e5590e0ba4844. Current local verified weights are used.
Runtime source: guardian-judge-qwen36-awq-6540dc50UP1.zip, SHA256
f54329f9c8fd7779fe31a66fdeca76f520de699c2969421355d29d45182c56c7.
Python 3.12.3, vLLM .19.1, Torch 2.10.0+cu128, Triton 3.6.0, Transformers 5.8.0;
no library upgrades. Config pins max_model_len 49152, max_num_seqs 64,
max_num_batched_tokens 16384, memory .90, prefix cache/chunked prefill enabled.
Chunk=16, per_chunk schedule; one scoring token at T=1.0, finite exact scores only.

Primary is durable before extras. New extras records preserve actual prompt hashes
and exact/inexact/missing/error status. Malformed extra output costs its own score,
not primary or already obtained other scores. Existing global primary fallback
remains if any primary-scored row lacks any of the six inputs. Missing primary rows
keep the technical fallback. No per-row mixture of primary and aggregate scales.
The requested algorithm cannot be guaranteed to finish on the unknown platform
input or to produce different binary labels; a quota-preserving top set may agree.

Acceptance of the build: real-profile fixture proves all six calls and shared
contexts; actual mean_z changes exported labels in a discriminating fixture;
missing/inexact extras trigger the documented global fallback; defaults unchanged;
Linux regression CI, real tokenizer cap check, complete ZIP manifest/size/hash/mode,
pinned model/runtime/import closure, public-entrypoint/full binary output checks.
These are technical gates, not algorithmic ACCEPT.

Quality/runtime status is GPU_UNTESTED unless measured. No independent dataset
comparison, F1/AUC/AP or 1800-second completion claim can be derived from fake-vLLM.
The original train/evaluation inventory and grouped experimental evaluation remain
unexecuted in this packaging task. The five remaining platform attempts are not
independent local evaluation data. Preserve the .30 rule, hard override and
1380/1530/1680-second guards (1800 seconds external, including startup).

Reproduce technical caps:

```powershell
$env:PYTHONPATH='C:/Users/Igor/Guardian-judge-6q-20261018/src'
& 'A:/Guardian-submissions/cascade-build-20261011/u2-build-venv/Scripts/python.exe' scripts/check_judge_6q_profile.py --model A:/Guardian-weights/qwen36-awq --input C:/Users/Igor/Guardian-judge-ci-v3-20261014/valid.parquet --out TOKENIZER_CHECK.json
```

Full build uses build_judge_submission.py with `--judge-config submission/JUDGE_6Q_SUBMISSION.json`,
the pinned runtime source/model revision, and the final code SHA via `--source-revision`.
Archive members record config/code provenance. Existing production config is unchanged.
