# Repository audit — integrated v1 (2026-10-05)

## Base and branch
- **New branch:** `research/guardian-integrated-v1-20261005`, created from `research/integration-handoff-20261005` @ `5c31da6e`. That ref is the verified base `8a9aa56d` (whole-move v1) plus 2 docs/scripts commits, with no runtime change. Verified with `git merge-base --is-ancestor`.
- **Already in the base:** V4 `f77e76c5`, V5 `ba248421`, Telecom `6035918c`, hybrid `f89d271b`, bakeoff `8e135f55`, corrections `49d887bd`, U2 packer `daba0b39`, multipacket `a7a113e7`, whole-move `8a9aa56d`.
- **Not in the base:** coverage-v2 `98b7fd2b` (side branch, not merged; the base's own corrected selector is used).
- After `git fetch`: 61 remote refs. Inventory snapshot: `docs/integration_handoff_20261005/branch_inventory.json` (60 refs, 24 worktrees on the user's machine; that machine's worktrees cannot be seen from here).
- **Environment:** Linux sandbox, Python 3.13. The Windows paths in the handoff are not available. The SSH host `new` (178.223.71.173:16389) closed the connection during key exchange (`kex_exchange_identification`). One bounded preflight was made, as the handoff prescribes. The server and its raw caches (`/workspace/guardian/...`) are therefore **not accessible**. Mistral and Ollama (Gemma) are reachable directly (smoke test: `ministral-14b-2512` 200, `gemma4:31b` 200).

## Public entry points (before this branch)
| Entry | Path | Status |
|---|---|---|
| `guardian-predict` | `guardian_truth.cli:main` → `pipeline.py`/`decision.py` | old Detector, has domain `resume_line` gate in `checks.py`; not universal |
| service | `service/`, `integration/system_runtime.py` | separate guards/assumptions |
| U2 baseline | `experiments/evidence_packer_v2/llm_eval.py` (prepare/run/judge) | research-only, writes outputs, not installable |
| mechanical guard | `experiments/whole_move_v1/mechanical.py` | research-only |
| compact reviewer | `experiments/whole_move_compact_v2/reviewer.py`, `bridge.py` | builds FULL packet; not selected (known6 F1 0.33) |

`experiments/*` is not part of the setuptools package (`where=["src"]`). Nothing outside `src/` is importable after `pip install`.

## Execution graph used by the new path
`valid row / any {prompt,response}` → `parsing.parse_events` → `source_search.SourceStore` → `evidence_packer.pack(20k)` + `resolve` → I4 reviewer (Mistral strict schema / Gemma JSON mode) → `admit` → ledger → result. The mechanical declaration guard runs over the full original source, independently of the packet. Details: ARCHITECTURE.md.

## Defects (status after reproduction on this base)
| # | Defect | Class | Reproduced | Reached by real data? |
|---|---|---|---|---|
| D1 | `← TOOL_RESPONSE x [ERROR]:` not a marker → receipt glued into the previous call | reproduced bug | yes | **yes: 21 receipts in 13/46 valid rows; 20 history calls became invalid JSON; 13/46 U2_20k packets change after the fix** |
| D2 | `: [ERROR] {...}` → status lost, JSON undecodable | reproduced bug | yes | 0 in valid46 |
| D3 | call JSON + trailing prose → one invalid call, prose target lost | reproduced bug | yes | 0 in valid46 responses/history |
| D4 | unescaped `⟦SYSTEM⟧` inside a body read as a real header | framing ambiguity (text transport) | yes | 0 (every prompt has exactly 1 SYSTEM header, first) |
| D5 | `resolve`: target inventory by set equality (duplicates pass) | reproduced bug | yes | 0 duplicates in 138 real packets |
| D6 | `FactLedger.at_time` ignores observation time | reproduced bug in exported API | yes | no caller in the repo (latest(as_of) is used) |
| D7 | `SourceStore.snapshot()` exposes mutable internals | reproduced bug | yes | not reached by the packer (fresh resolve) |
| D8 | lowering drops value/field/entity, collapses distinct rules; alternatives vs joint norms; partial policy promoted (`oracle_policy=True`) | reproduced (operands) + static (trust) | yes | semantic_pipeline_v1 only; not in the new path |
| D9 | controller `Question.key` = text only; gathered evidence ≠ resolved | static, reproduced by test | yes | multipacket arms only |
| D10 | compact v2 FORBID/SATISFIED polarity; parent target not counted as evidence | semantic limitation of that interface | per handoff | compact reviewer is **not** in the new path |
| D11 | native checker: later bill receipt of the same polymorphic tool supersedes an earlier line receipt | semantic limitation (research_v5 native grounding) | per handoff | not in the new path; left documented |
| D12 | research code not installable | integration gap | yes | fixed for the new path (see RUNBOOK) |

Fix details, checks and effects: ISSUES_AND_FIXES.md.
