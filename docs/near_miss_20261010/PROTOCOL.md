# Near-Miss (policy-derived read-before-write) — pre-registered protocol

Committed BEFORE any map is generated or evaluated. Based on Near-Miss (arXiv 2603.29665):
a state-changing call is suspicious if no earlier successful read covered the information the
policy requires for it.

## Universality constraints
- No domain knowledge in code or prompts. The tool map is produced at runtime by the model from the
  row's own policy text and `[AVAILABLE TOOLS]` catalog, once per unique pair (sha256 of policy+catalog).
  42 unique pairs exist across all pools (incl. synthetic clinic/carrier/etc. policies), so unseen
  test policies are handled the same way.
- Code never sets label 0; a finding only adds a positive (OR-arm) or evidence.
- Contamination: valid46 FNs were inspected before; valid46 is report-only.

## Step A — map (model, `build_map.py`, Qwen3.8-27B-FP8 via vLLM 0.19.1 offline engine)
Prompt: `policy.py:SYSTEM` (generic). Output per tool: `mutating`, `requires[{need, satisfied_by, entity_arg, policy_quote}]`.
Validation (code, `policy.validate`): tool and every `satisfied_by` in the catalog; `satisfied_by` tools
classified non-mutating in the same sample and ≠ the tool; `entity_arg` null or a parameter of the tool;
`policy_quote` ≥15 chars and a verbatim substring of the policy (whitespace/case-normalised). Else dropped.
Sampling: temperature 0.7, top_p 0.95, thinking off; replicate A seeds 1–3, replicate B seeds 4–6.
Vote (`policy.vote`, quorum 2/3): tool is mutating if ≥2 samples say so; requirement key
(tool, entity_arg) kept if ≥2 samples have it; `satisfied_by` = union of the agreeing samples (lenient).
Stability: per policy Jaccard of requirement keys A vs B, and agreement of fired rows A vs B.

## Step B — detector (code, `detect.near_miss`)
For each call of the current turn to a mutating tool with requirements: a requirement is satisfied if
an earlier call (history or earlier in this turn) to one of `satisfied_by` did not fail and, when
`entity_arg` is set, the argument's value occurs in that call's arguments or response body.
Missing/empty argument, unknown pairing → satisfied (lenient). Otherwise finding `NEAR_MISS` with evidence.

## Evaluation (`evaluate.py`, offline on stored B2 Q8 rep1 binaries)
Arm `B2|NEAR_MISS`; rows de-duplicated across pools as in contract lint.
Decision pools: ext_tau2, hold_tau2h, hold_holdout2, lb_long, lb2_long, lb3_long, contrast, dev, devT, frozen.
Rule (same as contract lint): HARD if new FP = 0 and ≥3 fires; EVIDENCE_ONLY if new FP 1–2;
REJECT if new FP ≥3 or raw fire precision <0.8; else INSUFFICIENT_FIRES.
Stability requirement: the rule is applied with map A and with map B; if the outcomes differ the check
is NOT adopted. No threshold, prompt or rule is changed after seeing results; changes need a new protocol version.
