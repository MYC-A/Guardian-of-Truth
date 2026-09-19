# Failure analysis — 2026-09-19

## Confirmed first losses

1. **Unsupported closure in competition adaptation.** The `codex-update-run` fix2 path promoted a parsed available-tools listing into a closed tool universe, and a listed object schema into `additionalProperties=false`. The input did not establish either premise. The first loss occurs **before** proof evaluation, at the adapter's premise construction; a valid downstream certificate cannot repair that. `4639b46` removes that promotion. On the viewed 46, TP drops from 10 to 3 at FP0; the other 7 were not certified from trusted premises. Relevant primary artifact: `outputs/vnext/hidden_assumptions_audit/closure_ablation.json`.

2. **Legacy offline semantic gap.** The `923bb445` entrypoint runs `guardian_truth.cli.Detector` with `--backend none`. Its 11 false negatives on viewed public46 include text claims, arguments and tool/policy cases. The first missing stage is a semantic decision after structural parsing: 34 cases use fallback 0, and no semantic model was called. This is a coverage diagnosis, not a justification to label every unresolved case 1. Per-case audit is at `outputs/research_offline_20260919/baseline_dev46_audit.jsonl`.

## FullArch N5 false-positive source-to-verdict trace

A single historical replay from tracked frozen Mistral `phi.jsonl` with Clingo 5.8.2 at `923bb445` reproduced N5: TP4 FP2 FN19 TN21, F1=.2759. Prediction file: `outputs/research_fullarch_replay_20260919/full/predictions__N5.jsonl`; witness inspection: `outputs/research_fullarch_replay_20260919/false_rule_audit.json`. This is **not** a fresh offline frontend.

| Viewed-dev case (gold 0) | Target action | First lost premise | Formal consequence |
|---|---|---|---|
| `banking_knowledge__task_063::t8` | `transfer_to_human_agents` for a specialist question | Source policy gives a four-request permission and allows scenario-specific KB override. Mistral proposed conditional `FORBID` with an `AT_MOST 3` request condition and a KB-guidance exception. Both condition and exception were unrepresentable, then dropped during lowering. | NeutralRule became unconditional `FORBID transfer_to_human_agents`. All 64 worlds marked it false; checker-valid certificate proved the altered rule. |
| `banking_knowledge__task_081::t35` | repeated transfer to a human after service actions | Same extracted rule and lost condition/exception; the context also has earlier human-transfer attempts and a repeat request. | Same unconditional rule was the only false obligation in all 64 worlds. |

For both, the false obligation is `unit:0002:mistral:2`; each neutral rule has `conditions=None, exceptions=()` despite the source-backed RuleIR carrying both. The compiler's marker strings (`card-subject-unbound`, `atom-not-representable`) did **not** block `PROVED_ERROR`. The first causal failure was `experiments/full_architecture_v1/policy/compiler.py` dropping unknown leaves, followed by an invalid strong rule. The certificate checker correctly replayed the weakened formal premise; it did not verify that lowering preserved NL meaning.

Commit `36d4b58` now omits an obligation when any guard or exception cannot be lowered, preserves supported temporal relations, abstains on unsupported temporal relations and explicit unresolved content, and prevents certification from a capped interpretation subset. Six focused compiler tests pass. Replaying the identical 46 rows changed N5 from TP4/FP2/F1=.2759 to TP3/FP0/F1=.2308. The two false positives became `UNRESOLVED`; `airline__23::t10` (gold 1) also became `UNRESOLVED`, which is the expected recall cost of refusing a weakened premise. Corrected prediction SHA-256: `5f3e6f9c940b6614211efe7475b920017e81f90a4712ae2c839c3996ff4b958b`.
