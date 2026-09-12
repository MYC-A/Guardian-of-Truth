# Experiment results

## End-to-end decision

| Arm | Data | TP | FP | FN | TN | Precision | Recall | F1 | Decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| X0 CURRENT_V5_3 | internal dev, 46 | 12 | 0 | 11 | 23 | 1.0000 | 0.5217 | 0.6857 | KEEP |
| X4 VIGIL_LIKE | internal dev, 46 | 12 | 0 | 11 | 23 | 1.0000 | 0.5217 | 0.6857 | REJECT as replacement |
| X5 PROPOSED_MIN | internal dev, 46 | 12 | 0 | 11 | 23 | 1.0000 | 0.5217 | 0.6857 | REVISE / shadow only |
| X0 CURRENT_V5_3 | external trajectory proxy, 144 | 0 | 0 | 83 | 61 | 0 | 0 | 0 | diagnostic only |
| X5 PROPOSED_MIN | external trajectory proxy, 144 | 0 | 0 | 83 | 61 | 0 | 0 | 0 | diagnostic only |

The internal comparison has zero discordant predictions, exact McNemar p=1,
delta F1=0, and a degenerate hierarchical-bootstrap delta interval at zero.
`valid.parquet` is development data, not an independent test. External reward
labels denote trajectory success/failure and are explicitly non-equivalent to a
localized Guardian error.

## Representation arms

- P0 compiled 5 of 523 unique policy segments; 518 remain UNKNOWN. Compilation
  is trace-independent, keyed by four policy hashes, with 42 cache hits.
- The full frozen 16-case Groq comparison kept P1/P2 budgets equal. P0 was
  schema-valid on 16/16 and semantically exact on 6/16. P1 direct transported and
  validated 5/16, with 1/16 exact. P2 typed transported 3/16, validated 2/16,
  and was exact on 0/16. P3 transported 1/16, validated 0/16, exact 0/16. Most
  failures were rate limits. Under the predeclared simplicity rule, P1 >= P2 and
  P1 is simpler, so typed IR v1 is rejected as the semantic frontend.
- P4/P5/P6 candidate-pool, pairwise aggregation, semantic-mutant and
  distinguishing-world machinery is implemented and tested offline, but no
  live candidate pool passed the prerequisite P2 gate; no performance claim is
  made for those arms.
- T0 found 55 unique tool names and deliberately assigned zero guaranteed
  effects. T1 contains seven reviewed high-confidence contracts and yielded five
  confirmed-effect records, zero confirmed-no-effect records.
- C0 extracted 9 claims: six bound TRUE and three UNKNOWN. Claim-span coverage
  is 5.33%; 136 audited spans remain UNKNOWN. Groq C1 passed local validation on
  only part of its bounded probe, so it is not in the runtime.

## Long context

The controlled assembly test contains ten placements/lengths. L0 full and L2
exhaustive compile-once both retain all required evidence (recall 1.0, silent
omission 0). L1 top-k has normative-span recall 0.75, reference-edge recall 0,
all-required recall 0, and silent omission rate 1.0. Semantic accuracy is null
because the test measures assembly, not model understanding.

## Live model gates

- Groq `openai/gpt-oss-120b`: 4/4 initial role smoke, but the full policy run
  was capacity-limited; still the most usable experiment route, not production.
- OpenRouter Nex free: 4/4 role smoke, but claim runs were slow/truncated.
- Gemini 3 Flash Preview: 2/4 role smoke.
- Mistral: 0/4, rate-limited; policy P1/P2/P3 also rate-limited.
- Cerebras: 0/4, request/access rejection.
- NVIDIA DeepSeek V4 Flash: 2/4; NVIDIA Kimi K3: 2/4 with 41–53 s
  successful latency; NVIDIA Gemma 4 31B: 0/4 timeouts.
- TokenHarbor DeepSeek V4 Flash free: 1/1 transport, 0/1 exact local schema,
  therefore 0/1 correct under the role contract.

Transport success, local schema validity, semantic correctness, latency, and
abstention are reported separately. Failed transport is never scored as model
semantics.

## External diagnostics

The readiness gate verified all pinned commits/files before parsing artifacts.
Predictions were hashed before the harness joined labels. ToolSandbox: 8 modules,
34 registered functions discovered, first 32 evaluated statically. BFCL: 30 rows,
49 inline function schemas, 134 properties, 98 required parameters. AgentDojo
had no frozen recorded TraceLogger output and remained documented unavailable.
