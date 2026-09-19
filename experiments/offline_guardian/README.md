# Granite Guardian 3.3 8B offline probe

An isolated experiment runner for IBM Granite Guardian 3.3 8B. It accepts a
fresh CSV with `id,prompt,response`, writes only a new
`outputs/research_granite_guardian/...` namespace, and does not import or
change the production prediction path.

The runner requires a pre-existing local model directory. It sets
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` before importing model
libraries; a Hugging Face model id is not accepted as `--model-path`.

## Smoke without a model

```powershell
python experiments/offline_guardian/run_granite_guardian.py `
  --input experiments/offline_guardian/fixtures/smoke_input.csv `
  --criteria groundedness function_call `
  --tools-json experiments/offline_guardian/fixtures/smoke_tools.json `
  --output-dir outputs/research_granite_guardian/smoke_dry_run `
  --dry-run
```

## Real local run

Run this only on the prepared machine where the model is already present:

```powershell
python experiments/offline_guardian/run_granite_guardian.py `
  --input fresh_input.csv `
  --model-path D:\models\granite-guardian-3.3-8b `
  --criteria groundedness `
  --output-dir outputs/research_granite_guardian/run_001
```

`groundedness` presents `prompt` as the sole document context and `response`
as the assistant message. `function_call` additionally requires declared tool
schemas from `--tools-json` or an optional CSV `tools` column containing a JSON
list. The runner deliberately does not invent tool schemas by parsing natural
language in `prompt`.

`records.jsonl` contains one record per criterion and case. `risk_token` and
`probabilistic_score` are only a Granite model assessment. Every record keeps
`formal_proof_status: "UNRESOLVED"`; the score never becomes a proof result.
The runner records the input hash, immutable execution configuration, latency,
character counts, and explicit head/tail truncation reasons. `think=False` is
always passed, therefore model reasoning traces are not requested or retained.
