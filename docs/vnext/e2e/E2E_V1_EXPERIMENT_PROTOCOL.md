# E2E V1 — Experiment Protocol (frozen before inference)

## 1. Prediction protocol (spec 155-159)

1. Architecture frozen at commit `4d7fdfb` (components, prompts, schemas,
   model config, repairs, world budget, arms, gates) —
   `outputs/vnext/e2e_v1_architecture_freeze.json`.
2. Corpus frozen before inference: 112 trajectory-level cases
   (`e2e_v1_holdout_corpus.json`), structurally fresh vs the 32-case
   development corpus (new domains: clinic/HR/telecom/insurance/logistics/
   cloud/university/utility; new tool names and entities; **zero shared
   meaningful 8-grams**, checked deterministically).
3. Gold (`e2e_v1_holdout_gold.json`) authored by construction from the case
   design (deterministic from environment/policy, spec 133) and joined ONLY
   after prediction sealing.
4. Candidate execution receives no gold, family-derived answers or paired
   case identities (the runner passes `E2ECaseInput` without gold fields).
5. One semantic attempt per candidate/case input: the memoized backend
   (content-addressed cache) makes exactly one live proposal per distinct
   (task, payload, schema); replays are deterministic. Registered
   transport-level repairs only (receipted); no semantic retries; escalation
   OFF; temperature 0.
6. Sealing: after each arm, predictions are saved and sealed
   (`prediction_seal`, `gold_joined=false`, architecture commit +
   configuration hash) — `outputs/vnext/e2e_v1_prediction_seals/`.
7. Bug protocol: any post-seal issue is classified REPORTING_ONLY /
   SCORER_ONLY / INTEGRATION_EXECUTION / SEMANTIC_BEHAVIOR; semantic bugs are
   not fixed and not re-run quietly.

## 2. Primary causal arms

E0 (H0+Conservative, conservative integrated baseline), E1 (GRS policy),
E2 (RuleFrames goal), E3 (strongest singleton), E4 (retained-interpretation
multi-frontend). Lower layers identical. B0 (untouched baseline
`core.analyze`) was not re-run on the holdout (resource constraint); E0 is
the causal baseline per spec 136-138 (B0 is an engineering reference only).

## 3. Oracle diagnostics (post-seal, spec 169)

Gold Policy (behavioral rows substituted as the only policy readings), Gold
Goal, Gold Both — measured as definitive-correct counts vs actual E0.

## 4. Metrics and statistics

Certified definitive coverage/accuracy, correct-definitive coverage, unsafe
definitive rate, PROVED_ERROR / PROVED_NO_ERROR recall, UNRESOLVED rate,
INCONSISTENT correctness, world metrics (mean/p95/max, required), runtime;
exact two-sided McNemar for paired arm comparisons; disagreement metrics
(agreement/disagreement/decisive/absorbed); failure taxonomy per spec 171.

## 5. Promotion gates (preregistered)

* uncertified_definitive = 0 (hard).
* false certified NO_ERROR must not increase vs E0; target 0 on the closed
  safety cohort.
* predictions sealed before gold = 100% (enforced by `prediction_seal` +
  write-once seal files).
