# Offline NLI DeBERTa diagnostic

This standalone runner evaluates claim pairs with an already-cached local
`cross-encoder/nli-deberta-v3-base` directory. `prompt` is the premise and
`response` is the hypothesis. It is not part of the competition CLI and it
does not provide a formal proof.

No model is downloaded: real execution requires an existing `--model-path`,
and sets `HF_HUB_OFFLINE=1` plus `TRANSFORMERS_OFFLINE=1` before loading.

```powershell
python experiments/offline_nli/run_nli_deberta.py `
  --input experiments/offline_nli/fixtures/smoke_claim_pairs.csv `
  --output-dir outputs/research_offline_nli/smoke_dry_run `
  --dry-run
```

On the prepared server, use the local cache snapshot as `--model-path`:

```powershell
python experiments/offline_nli/run_nli_deberta.py `
  --input claims.csv `
  --model-path /existing/cache/nli-deberta-v3-base `
  --output-dir outputs/research_offline_nli/run_001
```

`records.jsonl` preserves label IDs/names from the local model configuration,
raw logits, softmax probabilities, actual pair token counts, truncation traces,
latency, and the input hash/configuration. Each record has
`formal_proof_status: "UNRESOLVED"`.

To check library availability without opening weights:

```powershell
python experiments/offline_nli/run_nli_deberta.py --import-smoke
```
