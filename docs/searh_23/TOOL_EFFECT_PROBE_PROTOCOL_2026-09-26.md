# Tool-effect counterfactual probe

## Question

Does checking the *meaning* of a catalogued tool before checking results stop
the replacement-versus-audit mapping error? A `DIRECT` relation means that a
successful result of this one tool, for the same entity, would itself establish
the assistant's completed-action claim. `NON_ENTAILING` means the tool could
succeed while the claim remains false. `UNKNOWN` means the description is too
weak. The model sees only one claim and one exact catalog line per request; it
does not see observed results or gold.

## Frozen inputs and gates

- `experiments/searh_23/tool_effect_v1/dev.jsonl`: 3 previously inspected
  action families, 6 result variants each. It is development data.
- `experiments/searh_23/tool_effect_v1/fresh.jsonl`: 6 newly authored action
  families, 6 variants each. Its `fresh.gold.json` is opened only by `score`
  after the prediction JSONL is SHA-256 sealed. This is an authored diagnostic,
  not an independent contest holdout.
- The six variants are: matching successful result, successful preparatory
  result, successful audit result, failed direct result, successful direct
  result for a different entity, and no result. The same three tool effects are
  evaluated for each variant; request hashing caches identical model calls.
- Action-state, entity ID, and the relevant policy quote are supplied as
  **oracles** to isolate the tool-effect question. The result checker remains
  `completion_witness.validate_v2`. These inputs do not constitute a deployable
  whole-case verifier.
- A result verdict requires exactly one `DIRECT` tool and no `UNKNOWN`
  competitors. Ambiguous mappings abstain. Score mapping separately from the
  result verdict because a wrong tool can yield a coincidentally correct
  unsupported verdict.

## Decision criterion

Do not add this component to C1 unless every development and fresh family's
direct tool is selected, every valid result is accepted, and no preparatory or
audit result is accepted as proof. Even a clean result on these small authored
families would justify a larger unseen multi-clause, paraphrase and real-trace
test, not deployment or a claim of general soundness. Report abstentions and
per-family errors, not only aggregate accuracy.

## Reproduction on Vast

Use the existing environment and API secrets; no new dependency is needed.
The runner writes only proposal JSON, relation labels, hashes and token usage
if supplied by the API, never the key. Do not pass a key on the command line.

```bash
cd /workspace/guardian/repos/Guardian-of-Truth
PY=/workspace/guardian/venv/bin/python
OUT=outputs/searh_23/tool_effect_probe_2026-09-26
mkdir -p "$OUT"
$PY experiments/searh_23/tool_effect_probe.py run \
  --input experiments/searh_23/tool_effect_v1/dev.jsonl \
  --output "$OUT/dev.jsonl" \
  --env-file /workspace/guardian/secrets/mistral.env
$PY experiments/searh_23/tool_effect_probe.py score \
  --input experiments/searh_23/tool_effect_v1/dev.jsonl \
  --output "$OUT/dev.jsonl" \
  --gold experiments/searh_23/tool_effect_v1/dev.gold.json
$PY experiments/searh_23/tool_effect_probe.py run \
  --input experiments/searh_23/tool_effect_v1/fresh.jsonl \
  --output "$OUT/fresh.jsonl" \
  --env-file /workspace/guardian/secrets/mistral.env
$PY experiments/searh_23/tool_effect_probe.py score \
  --input experiments/searh_23/tool_effect_v1/fresh.jsonl \
  --output "$OUT/fresh.jsonl" \
  --gold experiments/searh_23/tool_effect_v1/fresh.gold.json
```
