# Architecture audit (Phase 0)

Base: `research/universal-evidence-packer-20261004` @ `daba0b39` (latest commit on that branch when this work started). Work branch: `research/multipacket-gap-controller-v1-20261004`. I searched all 57 remote branches for gap/sufficiency/question/planner/recursion/obligation/claim-verification code before writing anything new.

## Inventory

| Component | Exists | Works | Tested with an LLM | Reused here |
|---|---|---|---|---|
| U2 evidence packer (`src/guardian_truth/evidence_packer/`) | yes | yes (17 tests, deterministic across hash seeds) | yes: 46 rows × 3 runs (evidence_packer_v2) | **yes**: every packet here is a U2 packet. I added three opt-in hooks (`extra_queries`, `exclude_uids`, `shared_anchors`); with the defaults all 138 frozen U2/FULL requests stay byte-identical |
| SourceStore / native IDs (`source_search/store.py`) | yes | yes | indirectly | yes: row-global quote registry (`multipacket.unify`) |
| Qualified call/result pairing (`policy_table_v11.provenance`) | yes | yes | via U2 | yes (controller `find_call_results`) |
| Evidence graph (`src/guardian_truth/evidence_graph/`: bidirectional policy search, 3-valued logic, typed facts) | yes | the interface runs | only on single development cases in earlier branches (`evidence-graph-probe`, `bidirectional-evidence-graph`); no F1 effect established | no. Its contracts are bound to the policy-table IR. Instead I wrote a minimal span-keyed ledger (`multipacket/ledger.py`) with the edge statuses this study requires |
| Gap controller, S2G-inspired (`experiments/retrieval_bakeoff_v1/gaps.py`) | yes | partly: 1 of 3 gap plans failed on an ID namespace error | 3 cases only; it recovered the decisive receipts once, with no admitted improvement | the idea was reused (G1≈ D2: the model's own stated gaps drive the next packet). The code was not reused, because it depends on the bakeoff corpus IDs |
| Bounded recursive retrieval (`docs/hybrid_mechanisms_v1/RECURSIVE_RETRIEVAL.md`) | yes | yes; stops at READ_LIMIT | 1 known case; R1 adaptive planner rejected (namespace) | the design rules were reused: complete sources only, repeated reads add nothing, a sufficiency claim by the model is a hypothesis |
| Uncertainty router (`src/guardian_truth/uncertainty.py`) | yes | yes | earlier `uncertainty_experiment.md` (small) | no. It routes only "missing source → local read" and "rejected → recheck"; both are subsumed by D2/G2 |
| Claim verifier (`src/guardian_truth/claim_verifier.py`, full21 s7) | yes | shadow audit only, never changes labels | earlier small audits | the concept was reused as R1 (`ledger.programmatic_check`) |
| Obligation ledger (`policy_table_v11/obligations.py`, `next/obligations.py`) | yes | runs as an extraction/representability ledger | v11 cycles | no. Independent norm search here is the verdict-free stage-A semantic assessment from `hybrid_mechanisms.interfaces` (it already existed and was tested in hybrid_mechanisms) |
| Question tree (`experiments/searh_23/tq_questions*.py`) | yes | offline question generation | hotel/renamed synthetic suites (short dialogs) | no (domain-specific question templates) |

## What was added (research-only, not production)

- `src/guardian_truth/multipacket/packets.py`: complementary, gap-directed, specialized (NORM/EVIDENCE) and oracle packets. Also `unify` (one row-global SourceStore so that one span has one ID in every packet), `resolve_global` and coverage helpers.
- `multipacket/ledger.py`: typed nodes (Norm, Condition, Exception, Entity, Event, ToolCall, ToolResult, CurrentTarget, EvidenceSource, Question, VerificationResult, Claim). Edges carry the status EXACT / SEMANTIC_HYPOTHESIS / VERIFIED_SEMANTIC / UNKNOWN / REFUTED. Only a code check can create EXACT; promoting a semantic edge to EXACT raises an error. Includes cycle detection and R1 `programmatic_check` (target, norm existence, actor, accusations backed only by history).
- `multipacket/controller.py`: deterministic tools (`retrieve_relevant`, `read_policy_neighbors`, `lookup_entity`, `find_call_results`) over stored units only. BFS / DFS (depth-limited) / PRIORITY order; question dedupe; cycle-skipped repeated invocations; hop and char budgets; stop reasons.
- `experiments/multipacket_v1/`: arms, cached resumable calls, runner, report, synthetic suite builder, freeze manifest.
- `tests/test_multipacket.py`: 14 tests (packet complementarity, no-new-information, global IDs and tamper rejection, hash-seed determinism, REFUTED actor edges, no EXACT promotion, cycles, historical-only accusation, dedupe/cycle/budget, DFS depth, synthetic rename consistency).

## Interface facts that constrain the design
- The I4 reply already has `open_questions`, so D2 needs no new contract.
- `stage='A'` (verdict-free norm assessments) and `stage='B'` (decide using assessments) already exist. C2 and G3 use them unchanged.
- Admission (`admit`) checks the target, norm IDs and evidence actor. It never checks semantic truth.
- 12 of 46 valid rows fit completely in 20k (FULL_INPUT). There, every retrieval arm is identical to A by construction (rule `degenerate`).
