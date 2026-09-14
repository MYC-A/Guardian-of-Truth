# PHV1 — Policy H0 Prospective Holdout V1: Results and Boundaries

Experiment: `policy_phv1_holdout_v1` (registered: `docs/vnext/PHV1_PREREG_GATES_V1.json`,
frozen at commit `12bec0b` before any request; H0 identity continuity vs the sealed
C-ALR freeze machine-verified at freeze time).

Terminology: **prospective frozen holdout** (not blind: the same researcher authored the
corpus; H0 was frozen before inference; cases are new; gold was frozen and hashed before
the first H0 request; predictions were sealed before gold join).

Cycle rule obeyed: **VALIDATE, DO NOT IMPROVE.** No architecture changes, no mutation
catalog use, no C-ALR verifier requests (0 sent), no LLM judges, no repairs of the six
observed V5 residuals, no re-runs on the viewed holdout.

---

## 1. Headline result

| Metric | Value |
|---|---|
| Overall behavioral accuracy | **59/80 = 73.75%** (Wilson 95% CI [63.18%, 82.14%]) |
| Schema/compile validity | 79/80 = 98.75% (77 ok, 2 ok via the frozen repair re-ask, 1 parse failure) |
| Simple controls | 19/20 = 95.0% (gate ≥95% — PASS) |
| Structural aggregate (structural + multi-clause) | 29/40 = 72.5% (gate ≥85% — FAIL) |
| NL stress | 6/12 = 50.0% (gate ≥80% — FAIL; family floor 60% breached — COLLAPSE) |
| Ambiguity (report-only) | 5/8 = 62.5% |
| Invented explicit permission | 8/80 = 10.0% (safety gate ≤2% — FAIL) |
| Unsupported restrictive readings | 3/80 = 3.75% (gate ≤5% — PASS) |
| Collapsed families (N≥8, <60%) | `nl_stress` (6/12 = 50%) |
| **Preregistered verdict** | **REOPEN_POLICY_RESEARCH** |

Trigger: overall 73.75% < 0.85 reopen threshold (a ~22 pp fall vs the controlled result),
plus one major family collapse.

## 2. Answer to the main research question

> Is H0 = 136/142 = 95.77% a stable semantic capability of the conservative Policy
> frontend, or predominantly an effect of the known controlled/dev distribution?

**Predominantly an in-development-distribution effect.** On 80 prospectively authored,
gold-by-construction, 8-gram-disjoint policy texts with fresh constructions and domains,
the byte-identical frozen H0 (prompt/schema/config/engine machine-verified identical to
the sealed C-ALR run) retains excellent ordinary-language baseline behavior (simple
95%) but loses the structural and prose phenomena: overall 73.75% [63.2, 82.1], NL
stress 50%, multi-axis 65%.

Strict historical separation (per prereg; NOT a learning curve):
- historical Arm C ≈78.1% — user-reported, sealed artifacts lost, absence-attested,
  different implementation/prompt/input contract; not numerically comparable;
- current H0 on recovered V5 = 95.77% — machine-verified, controlled dev distribution;
- PHV1 prospective holdout = 73.75% — machine-verified, new texts (this study).

## 3. Research questions (machine answers)

- **Q1** Reproduce >90% on new texts? **No** — 73.75% [63.18, 82.14].
- **Q2** NL stress quality? **50%** — the single largest collapse; prose length,
  cross-sentence reference and parentheticals break the parse.
- **Q3** Families with sharp degradation? Collapsed: `nl_stress`. Below their cohort
  gate: ambiguity (62.5%), exception (66.7%), modality (66.7%), multi_axis (65%),
  negation (33.3%), nl_stress (50%). Negation is the worst small-N family (1/3).
- **Q4** Does the conservative permission bias generalize? **No.** 8 cases (10%) of
  invented explicit permission (PERMITTED where every admissible gold says
  NO_VIOLATION/VIOLATION) — the gate was ≤2%. The NO_VIOLATION ≠ PERMITTED invariant,
  stable on the dev distribution, does not survive contact with new phrasings.
- **Q5** Unsupported semantic additions? invented_permission 10.0%, invented_requirement
  1.25%, invented_exception 1.25%, invented_condition 0%, unsupported restrictive scope
  3.75%, third readings on ambiguous cases 3.75%, wrong polarity 3.75%.
- **Q6** Residual errors local or structural? Deterministic post-seal classification of
  the 21 errors: relation 9, multi_axis 6, negation_polarity 2, scope_shape 2,
  modality 1, representation_gap 1. The dominant axis is **relation binding**
  (IF/ONLY_IF/UNLESS/IFF on new constructions) — structural, consistent with the C-ALR
  Stage A' finding (0/6 catalog-recoverable), not locally patchable.
- **Q7** Mature for composition with Binder/Core? **No** (verdict-gated).
- **Q8** Continue standalone Policy research? **Yes** — the preregistered decision rule
  fires REOPEN_POLICY_RESEARCH.

## 4. Secondary structural metrics (valid parses only, n=79)

modality 96.2%, relation 73.4%, condition_mode 98.7%, exception_mode 87.3%, temporal
89.9%, target_clauses 94.9%, condition_literals 92.4%, exception_literals 98.7%,
actor literals 15/18 = 83.3%. NOT_MEASURED (carried-inert, not prompt-instructed):
regulated_kind, facet, identity, provenance, quantification.

The relation field is the weakest measured axis, matching the audit's dominant error
class. Exception-mode and temporal show mid-range degradation under compositional load.

## 5. Error inventory (deterministic, post-seal; no LLM judge)

| case | cohort | class | closest-gold diffs |
|---|---|---|---|
| ambiguity::am01 | ambiguity | representation_gap | transport/schema failure (both attempts) |
| ambiguity::am02 | ambiguity | modality | modality |
| ambiguity::am06 | ambiguity | multi_axis | relation + condition/exception binding |
| exception::e03 | structural | relation | relation |
| modality::m02 | structural | multi_axis | modality + temporal |
| multi_axis::x04 | multi_clause | relation | relation |
| multi_axis::x05 | multi_clause | relation | relation |
| multi_axis::x06 | multi_clause | relation | relation |
| multi_axis::x14 | multi_clause | relation | relation |
| multi_axis::x18 | multi_clause | negation_polarity | polarity |
| multi_axis::x19 | multi_clause | relation | relation |
| multi_axis::x20 | multi_clause | relation | relation |
| negation::n01 | structural | scope_shape | clause shape |
| negation::n03 | structural | negation_polarity | polarity |
| nl_stress::nl01 | nl_stress | multi_axis | modality+relation+conds+excs+mode |
| nl_stress::nl02 | nl_stress | relation | relation |
| nl_stress::nl04 | nl_stress | multi_axis | conds+targets+temporal |
| nl_stress::nl05 | nl_stress | relation | relation |
| nl_stress::nl08 | nl_stress | multi_axis | relation+conds+exc_mode+targets |
| nl_stress::nl10 | nl_stress | scope_shape | clause shape |
| simple::s06 | simple | multi_axis | relation + exception_mode |

## 6. Efficiency

83 requests (80 primary + 2 frozen repairs + 1 smoke), 110,699 tokens, median latency
7.3 s, p95 18.2 s. Zero verifier requests (C-ALR stays closed per prereg).

## 7. Post-result discipline (frozen rules now in force)

- The viewed PHV1 corpus is **development data** from this point.
- H0 may not be patched and re-run on this holdout; any repaired candidate requires a
  NEW holdout corpus and a new experiment namespace.
- The 6 observed V5 residuals were not repaired in this cycle; the 21 PHV1 residuals
  are now additional development evidence.
- Recommended next cycle (for a future preregistration, not this one): representation-
  level work on relation binding (exception vs condition vs exclusivity) and
  multi-axis composition under prose, plus restoration of the conservative permission
  invariant on unseen phrasings — or a decision to change the frontend model/class.

## 8. Artifact map

- `outputs/vnext/policy_phv1_holdout_v1_freeze.json` — freeze (gates, H0 identity,
  continuity vs sealed C-ALR freeze, source hashes)
- `outputs/vnext/policy_phv1_holdout_v1_benchmark.json` — frozen gold corpus (80 cases)
- `outputs/vnext/policy_phv1_holdout_v1_predictions.json` + `_prediction_seal.json` —
  sealed predictions (gold_joined=false at seal time)
- `outputs/vnext/policy_phv1_holdout_v1_results.json` — full machine-verified report
- `outputs/vnext/policy_phv1_holdout_v1_failure_audit.json` — deterministic residual
  taxonomy
- `outputs/vnext/policy_phv1_holdout_v1_case_*.json`, `..._h0_*_request_*.json` —
  per-case rows and persisted request/response payloads
- `outputs/vnext/policy_phv1_holdout_v1_smoke.json` — pre-inference transport smoke
