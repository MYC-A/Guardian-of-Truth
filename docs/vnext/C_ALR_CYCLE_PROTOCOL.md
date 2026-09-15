# C-ALR — C-Anchored Local Refinement (Policy frontend) — one narrow experimental cycle

Status: **STAGE_0_ARTIFACTS_PENDING** — sealed V5/V6 artifacts (arms C / B4 / B5) are NOT
present in this environment (verified: repo tree, full git history of all branches,
`upload/`, project tree greps). Stage A cannot start until they are supplied per the
input contract below. Nothing has been computed; preregistration is complete and frozen
in `C_ALR_PREREG_GATES_V1.json` (hash-stamped by git at registration commit).

Research question:

> Can a Policy frontend be made robustly stronger by using Arm C as the conservative
> primary parser and applying the strong B4 mechanisms ONLY as local, textually
> supported corrections — without any SAPC/slot-card primary?

This is a hypothesis, not a conclusion. The experiment must be able to demonstrate
that local refinement does NOT pay off and that Arm C should remain unchanged.

## 1. Historical basis (user-reported, pending machine re-verification)

- P1 (single-program semantic parse): limited accuracy, systematic semantic failures.
- Arm C = P1 + fence/transport repair + deterministic permission/admission marker gate: large, stable improvement.
- SAPC/B4 = slot-card primary + deterministic compile + local mutations + span-grounded admission: richer, but no reproducible advantage over C.
- V5 (sealed): C 78.1%, B4 84.7%, Δ +6.8 pp, McNemar p ≈ 0.093, benchmark 142 cases.
- V6 (sealed): B4 − C ≈ −1.65 pp, p ≈ 0.84.
- B5 structural adjudicator: worse than B4 — rejected.
- Failure decomposition (V6): B4's weak part is the SAPC/slot-card PRIMARY (it injects
  errors); the strong part is span-grounded admission (~93% precision when primary is
  correct; ~6 of 7 false admissions were downstream of an already-wrong slot primary).

## 2. Arms

| arm | definition |
|-----|------------|
| H0 | frozen Arm C (baseline, unchanged) |
| H1 | C + ALL catalog mutations applicable to the representation + span-grounded admission (ablation: is a conservative verifier alone enough?) |
| H2 | C + deterministic risk detector + only risk-relevant local mutations + span-grounded admission + patches (main candidate) |
| B4 | frozen B4 comparison arm (optional but default-on; unchanged) |

Explicitly NOT an arm: C/B4 voting, agreement gating, majority/judge hybrids (§19 of
the source spec — different hypothesis, different experiment).

## 3. Prohibited (enforced by prereg gates file)

- Φ-style "generate N complete readings, keep all plausible".
- Full SAPC slot-card primary anywhere in the candidate (primary must come from frozen Arm C).
- Verifier: full reparse, new slot-cards, new complete programs, new actions/entities,
  changes outside the inspected mutation, unrestricted alternative interpretations,
  final Guardian verdicts, trajectory/history, world state for Policy meaning.
- Multi-agent debate, self-consistency, challenger, critic, whole-policy judge.
- Risk detector trained on gold V6 case IDs (surface triggers + φ_C structure only).
- Semantic prompt / mutation-rule changes after smoke (smoke covers transport, schema,
  serialization, API integration only).

## 4. Stage A — offline deterministic decomposition of sealed V6 (BLOCKED ON INPUT)

Run BEFORE any new inference call. Tool: `scripts/c_alr_stage_a.py`. No LLM, no network,
no manual rescoring. Inputs are sealed artifacts only.

### 4.1 Input contract — `v6_sealed_bundle.json`

```json
{
  "experiment": "policy_semantics_v6 (or v5)",
  "benchmark_name": "...",
  "case_count": N,
  "cases": [
    {
      "case_id": "family::NN",
      "family": "scope | only_if | exceptions | temporal | actor | cardinality | coordination | ...",
      "risk_tier": "simple | hard (optional)",
      "gold": {
        "semantic_fields": { "modality": "...", "actor": "...", "scope_attachment": "...",
                             "exception_attachment": "...", "temporal": "...",
                             "quantification": "...", "target_clauses": [...], "...": "..." },
        "worlds": [ { "world_id": "...", "expected": "VIOLATION|NO_VIOLATION|PERMITTED" } ]
      },
      "c":  { "semantic_fields": {...}, "case_correct": true|false,
              "world_results": [ { "world_id": "...", "expected": "...", "predicted": "...", "correct": bool } ] },
      "b4": { "semantic_fields": {...}, "case_correct": true|false,
              "world_results": [...],
              "stage_logs": {
                "declared_error_stage": "slot_primary | mutation_generation | admission | compiler | gold_benchmark_issue | other (optional)",
                "admissions": [ { "mutation_type": "...", "decision": "SUPPORTED|CONTRADICTED|INSUFFICIENT_SUPPORT",
                                  "source_span": "..." } ]
              } }
    }
  ]
}
```

Field names follow the repo's existing `structural_fields` vocabulary
(modality, actor, regulated_kind, facet, target_clauses, relation, condition_literals,
exception_literals, temporal, identity, provenance, quantification) plus the three
attachment fields the mutation catalog needs (scope_attachment, exception_attachment,
actor). `case_correct` values must be the SEALED per-case behavioral scores, joined
with gold before Stage A (never re-derived here).

### 4.2 Stage A outputs (per case and aggregate)

1. Quadrant: C✓/B4✓, C✓/B4✗, C✗/B4✓, both✗ (+ per-family table).
2. B4 failure stage attribution (C✓/B4✗ only): from `stage_logs.declared_error_stage`;
   absent logs → `UNATTRIBUTED_NO_LOGS`. No LLM classification, ever.
3. B4 gain recoverability (C✗/B4✓ only), deterministic typed-field diff φ_C vs GOLD:
   - all diffs map to frozen catalog mutation types AND ≤ 2 mutations → `LOCAL_PATCH_RECOVERABLE`
   - any diff outside the catalog (regulated_kind, facet, relation, condition_literals, identity, provenance…) or > 2 mutations → `REQUIRES_GLOBAL_REPARSE`
   - field-level representations absent → `UNCERTAIN`
   - gold absent → `NOT_RECOVERABLE`
4. Oracle upper bound: `Oracle(C + all recoverable local corrections)` — diagnostic only,
   never a system. `oracle_gain = share of LOCAL_PATCH_RECOVERABLE among ALL cases`.

### 4.3 STOP gate (preregistered, frozen in `C_ALR_PREREG_GATES_V1.json` BEFORE computation)

STOP / REJECT_EARLY if `recoverable C-errors < 5% of corpus` OR `oracle gain < 4 pp`.
On STOP: no C-ALR implementation, no V7 benchmark; Arm C remains the integration
baseline and standalone Policy research halts (§44).

## 5. C-ALR pipeline (only if Stage A passes)

```
POLICY → ARM C → primary φ_C → deterministic risk analysis
       → deterministic local mutations (typed catalog, frozen v1 in prereg file)
       → span-grounded narrow verifier (LLM, ≤ N calls, N budgeted in prereg)
       → admitted local semantic patches → final φ_H
```

The LLM verifier NEVER builds a Policy representation. Its only question:
"Does the text positively support THIS specific local change relative to φ_C?"
Verdicts: `SUPPORTED | CONTRADICTED | INSUFFICIENT_SUPPORT`; `SUPPORTED` requires an
exact source span + short structural justification. "Nothing contradicts it" and
"this reading is possible" are insufficient — especially for permission mutations.

Default rule: `CONTRADICTED` or `INSUFFICIENT_SUPPORT` → `φ_H = φ_C` for that field.
Genuine local ambiguity is allowed ONLY with positive textual evidence for BOTH
readings, represented as a local field-level set (e.g. `scope ∈ {A, B}`), never as
multiple whole-policy programs.

Permission invariant: `NO_VIOLATION ≠ PERMITTED` stays; explicit permission requires
positive textual evidence (no permission from absence of prohibition).

Provenance per accepted patch: `source_span, mutation_type, old_value, new_value,
admission_decision`. No trajectory/history input to any Policy frontend arm.

## 6. V7 benchmark (built only after Stage A pass; frozen before first external call)

- 140–180 cases, balanced across: simple policies, permissions/prohibitions,
  necessary vs sufficient conditions, exceptions, scope attachment, actor/bearer,
  temporal constraints, cardinality/choice, coordination, multi-clause policies,
  prose/NL stress, genuine ambiguity, unsupported-ambiguity traps.
- A substantial simple/low-risk block — the hybrid must prove it does not break what
  C already does right (§23, §32 hard safety requirement).
- Gold discipline: logically conceivable ≠ textually licensed; every ambiguous case
  carries `explicit linguistic_source`; every negative mutation trap carries
  `reason_unsupported`. No automatic OR↔AND / IF↔IFF ambiguity without independent
  linguistic basis.
- Development results on V6 remain DEV/diagnostic only; superiority is decided ONLY
  on the new frozen V7 (§20–21).

## 7. Metrics, statistics, verdicts

Metrics (minimum): behavioral policy accuracy; C→H recoveries; C→H regressions; net
corrections; unsupported mutation admission rate; mutation precision/recall; false
ambiguity rate; wrong agreement rate; mean worlds/local alternatives; schema validity;
LLM calls per case; tokens per case; latency.

```
Correction Precision = C_wrong→H_right / (C_wrong→H_right + C_right→H_wrong)   [gate ≥ 0.75]
Regression rate on C-correct cases                                          [gate ≤ 0.03]
```

Primary comparison: H2 vs C, paired exact McNemar (gate: ≥ +4 pp AND p < 0.05;
registered underpowered fallback: 95% paired CI excludes 0 with lower bound ≥ +1.5 pp).
Secondary: H2 vs frozen B4. Family-level Δ vs C, especially scope, only-if, exceptions,
temporal, actor, cardinality, coordination.

Verdicts: KEEP / REVISE / REJECT / REJECT_EARLY (definitions in source spec §41–44).
KEEP requires reproducible superiority on blind/frozen V7 with low regression rate and
concrete local semantic corrections as the mechanism.

## 8. Freeze checklist (§38; all frozen before first V7 external call)

benchmark, gold, case IDs, Arm C, B4 baseline, risk detector, mutation catalog,
mutation generator, verifier prompt, schema, compiler, scorer, behavioral worlds,
gates, model/provider/config, retry policy. Predictions sealed before gold join. If
scoring breaks after seal: independent post-seal scorer, frozen predictions unchanged.

## 9. Required inputs (current blockers)

1. `v6_sealed_bundle.json` per §4.1 (SEALED V6 per-case C/B4 results + gold; plus
   `stage_logs` wherever they exist) → unblocks Stage A + oracle + STOP decision.
2. Sealed V5 B4 admission logs → machine cross-check of the §2 claim (~93% precision,
   6/7 false admissions downstream of slot primary) before it drives design.
3. Frozen Arm C and frozen B4 implementations (code or runnable specs + prompts) →
   required for H0/H1/H2/B4 arms on V7; without them the arms would be
   reimplementations and historical continuity with V5/V6 numbers would be lost.

## 10. Stage status

| stage | status |
|-------|--------|
| Preregistration of STOP + V7 gates | DONE (before any computation) |
| Stage A tooling (`scripts/c_alr_stage_a.py` + synthetic selftest) | DONE |
| Stage A execution on sealed V6 | BLOCKED — artifacts pending |
| Oracle + STOP decision | BLOCKED — follows Stage A |
| C-ALR implementation (H1/H2) | NOT STARTED (gated on Stage A pass) |
| V7 benchmark + freeze + run | NOT STARTED (gated on Stage A pass) |
