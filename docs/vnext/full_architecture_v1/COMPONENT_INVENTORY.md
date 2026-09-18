# FULL-ARCHITECTURE-V1 — Component Inventory (Phase A)

Branch: `full-architecture-v1` · Base: `bf972b0` (core_engine_bakeoff_v1 final).
Method: file survey of `src/guardian_truth/vnext/**` + `experiments/semantic_pipeline_v1/**`
+ `experiments/core_engine_bakeoff_v1/**`, read of execution-path docs
(REAL_COMPETITION_VALID_CODEX.md, SEMANTIC_PIPELINE_CURRENT_FLOW.md,
CORE_ENGINE_BAKEOFF_V1.md). LOC from `wc -l` at base commit.

Categories:
**A** SAFE GENERIC MECHANISM — strong candidate for replacement by a mature library.
**B** GUARDIAN SEMANTICS — meaning is ours; mechanism may be replaced, semantics stays.
**C** EXPERIMENTAL — replacement requires equivalence testing.
**D** KEEP CUSTOM — small or genuinely unique.

## 1. Pipeline map (competition path, arm at 4639b46 soundness-corrected)

```
raw prompt/response
  → competition_adapter_v1.py (183)          catalog/schema/premises extraction
  → source_adapter_v1.py (114)               trace events (roles, calls, results)
  → policy frontend: policy_h0_v1 (142) + policy_historical_v1 (456)
      + policy_composition_v1 (263) + policy_grs_* (3 modules, 430)
  → goal frontend: goal_composition_v1 (164) + goal_rule_frames_v1 (239)
      + goal_lowering_v1 (268) + goal_conservative_v1 + goal_e5_v1
  → claim_adapter_v1.py (153)                response claims
  → json_extract_backend_v1.py (113)         T2 tool-payload LLM extraction
  → schema_validation_v1.py (98)             custom JSON-schema subset validator
  → core_v1.py (786) + world_integration_v1.py (540) + policy_lowering_v1 (249)
      → vnext: ledger (187) tools (184) proof_evidence proof_records (194)
        solver (68) types/consensus (234) decision (72) integrity (73)
  → certificate_context_v1.py (438) + vnext/certificates.py (268)
  → independent checker (e2e tests + experiment_v1.py 294, real_valid_v1.py 318)
```

## 2. Inventory

| # | Module (LOC) | Responsibility | Custom impl. today | Candidate library/model | Cat | Repl. changes Guardian semantics? | Risk |
|---|---|---|---|---|---|---|---|
| 1 | e2e/competition_adapter_v1 (183) | prompt→E2ECaseInput; tool catalog; declared schemas; closed/open premises | hand parser | none (D) | **D** | — | — |
| 2 | e2e/source_adapter_v1 (114) | lossless trace events | hand parser | none | **D** | — | — |
| 3 | experiments/semantic_pipeline_v1/source_segments (435) | SourceTimeline: segments+fragments, byte-exact spans, FIFO pairing, ERROR-response split | custom (B by §4 of directive) | none — directive §4 mandates keep-custom-small | **D** | — | — |
| 4 | e2e/policy_h0_v1 + policy_historical_v1 + policy_composition_v1 (861) | policy text → PolicyFlatStructure | regex+heuristics H0/H1 parse | Mistral/NuExtract extraction (semantic_pipeline_v1) | **C** | no (frontend swap, same target IR) | high (provenance/spans) |
| 5 | e2e/goal_* frontend (1000+) | last-user goal → obligations | regex lowering | same extractors | **C** | no | high |
| 6 | e2e/claim_adapter_v1 (153) | response → claim atoms | regex | same extractors | **C** | no | medium |
| 7 | e2e/json_extract_backend_v1 (113) | T2 payload LLM extraction | Mistral JSON mode | keep Mistral | **D** | — | — |
| 8 | e2e/schema_validation_v1 (98) | validate tool args vs declared schemas | custom subset validator | **jsonschema** (§5) | **A** | no if diagnostics mapped 1:1 | low |
| 9 | vnext/ledger (187) + proof_evidence + proof_records (194) | evidence classification, four-valued truth, witness records | custom | Clingo evidence module (§13) | **B** | semantics stay; mechanism → ASP rules | medium (must fence ASP closed world) |
| 10 | vnext/solver (68) + e2e/world_integration_v1 (540) + core_v1 (786) | worlds, condition eval, obligations, consensus | procedural Python | Clingo policy engine (§15): choice rules=worlds, recursion=condition folds, #count/#max, brave/cautious=consensus | **B** | semantics stay (bake-off proved 43/43 equivalence) | medium |
| 11 | vnext/types consensus (234) + decision (72) | verdict algebra, must-act abstention | custom tables | part of 10 | **B** | stays | medium |
| 12 | vnext/tools (184) TrustedContract/evaluate_t1 | trusted effect contracts | custom | jsonschema + Clingo joins (§14); TRUSTED promotion stays ours | **B** | trusted-declaration meaning stays | low |
| 13 | e2e/certificate_context_v1 (438) + vnext/certificates (268) | source-backed certificate | custom | keep; Clingo model→witness bridge (§17) | **B** | stays (Clingo model ≠ certificate) | medium |
| 14 | independent checker | verify certificate w/o LLM | custom (small) | keep (§18) | **D** | — | — |
| 15 | semantic_pipeline_v1/retrieval (299) | union deterministic+lexical+embeddings+KB | custom | keep; reduced model MiniLM → future BGE-M3 | **A** | routing only, no truth | low |
| 16 | semantic_pipeline_v1/rule_ir (302) | RuleIR typed AST | custom pydantic | keep-small (§11) | **D** | — | — |
| 17 | extractors: Mistral (362) NuExtract (316) | typed candidates + spans | model prompts | keep | **C** | no | low |
| 18 | extractors_gliner (244) | GLiNER2 typed spans | GLiNER2.5-small | keep; extend to relations/schema (§8) | **C** | no | medium |
| 19 | nli_check (≈150) | NLI firewall (contradiction/entailment/neutral) | cross-encoder DeBERTa | keep reduced; future base model | **A** | admission signal only | low |
| 20 | semantic_pipeline_v1/binding (169) | concept→tool/field binding | exact→embed→rerank | keep; future BGE-reranker | **A** | no (ambiguity preserved) | medium |
| 21 | semantic_pipeline_v1/phi (≈150) | interpretation candidates | custom dedupe | keep + §16 compact local choices | **C** | no | medium |
| 22 | bake-off neutral_types (798) + backends | NeutralCoreInput + engine adapters | done | **REUSE as the NeutralCoreInput contract of §3** | **B** | — | — |
| 23 | bake-off clingo_backend (1030) | NeutralCoreInput→ASP | done | **REUSE as evidence+policy engine core (§13/§15)** | **B** | — | — |
| 24 | Invariant guardrails (not installed) | trace matching comparator | — | invariantlabs-ai/invariant (§12 probe) | **C** | comparator only, never authoritative | unknown |

## 3. Deletion targets if N5 is adopted (initial, to be finalized in §38)

* e2e/world_integration_v1.py world enumeration + option contracts → Clingo choice rules
* core_v1 condition/obligation group evaluation folds → ASP recursion
* vnext/decision consensus tables → brave/cautious derivation (keep the algebra as oracle for tests)
* schema_validation_v1 custom walk → jsonschema (keep thin adapter for typed diagnostics)
* custom comparison/cardinality plumbing → Clingo #count/arithmetic

## 4. Explicitly NOT touched (directive guardrails)

Retrieval recall tuning, extraction prompts, Mistral params, valid.parquet labels,
gold labels, competition adapter semantics, existing evidence rule semantics,
production branches. FrozenCoreInput stays an experimental fixture, not
architectural truth.
