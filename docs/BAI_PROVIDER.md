# B.AI Qwen provider

This integration lives on `experiment/bai-qwen-replication`, branched from the
sealed Cycle 2 commit `0199bf9`. It does not rewrite Cycle 2 predictions or promote
a new production verifier.

The explicit profile is `bai`, endpoint `https://api.b.ai/v1`, default model
`qwen3.8-flash`. Credentials are loaded only from the specified ignored env file.
Accepted names are `BAI_API_KEY`, `B_AI_API_KEY`, and the user's `b_ai_api_key`.
No other provider key is used as fallback and cross-host endpoints are rejected.

The Chat Completions request uses `max_tokens` and temperature 0 for reproducible
verification. The connection probe embeds its JSON schema in prompt text and
omits native `response_format`. It makes one request with a 180-second timeout
and zero retries; subsequent admission calls are sequential under the unchanged
Cycle 2 model-gate-v2 contract.

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
python scripts/probe_bai.py --env-file "C:\Users\Igor\Desktop\Guardian of Truth\.env"
python -m guardian_truth.cycle2.evaluate model-gate --candidate bai=qwen3.8-flash `
  --env-file "C:\Users\Igor\Desktop\Guardian of Truth\.env" `
  --contract contracts/cycle2_model_gate_v2.json --output outputs/bai/model_gate.json
```

The first live probe returned HTTP 200, served model `qwen3.8-flash`, and valid
JSON in 4.57 seconds using 154 reported tokens. The provider integration passed
568 offline tests. Detailed credential-free results are in `outputs/bai`.

Official sources: [API reference](https://docs.b.ai/llmservice/api/) and
[Qwen3.8-Flash model page](https://docs.b.ai/llmservice/models/qwen3-8-flash/).
The model page lists a temporary zero-credit API offer; future prices and actual
settlement must be checked before assuming continued free access.
