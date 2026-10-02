# RUN_PLAN — all methods, no finetuning cycle (2026-10-02)

Branch research/modular-step2-4-20261002, base SHA fb94edf3. Budget phase
`modular_all_noft_20261002` (1600 attempts / 4M known / 6M logical / 200k
unknown-upper / 76,800 model-seconds — ceilings, not a spending goal).
dev2 and reviewer_repair are CLOSED. This plan is written BEFORE any paid
inference of the cycle (assignment §13): every listed method gets RUN, an
equivalent prior reused with proven compatibility, or a concrete BLOCKED.

Reserve split (assignment §15): connectivity ≤20; GEPA ≤220; remainder
across model/role pilots, module pilots, dev shortlist, sealed (sealed
reserve never spent on old-pilot retries). Local inference is tracked
separately (calls/tokens/GPU-time) and never consumes the API ceiling.

| # | Method | Prior status | New hypothesis | Sources | Minimum pilot | Budget (attempts) | Continue criterion | Artifacts |
|---|---|---|---|---|---|---|---|---|
| 1 | P0 §3.1 judgment contract V2 | DIRECT_V1≠CHECKER (calibration asymmetry), frequency prior present | Same core for D and E→J removes the instruction confound; both-classes-allowed + per-tool status vocabulary cuts B-FP families (T8/T15) | role_prompts.py, REPAIR_CAUSE_AUDIT.md | offline tests + paired payload audit | 0 (code) | payload parity test + auditor gate PASS | judgment_contract.py, test_judgment_contract.py (20 tests) |
| 2 | P0 §3.2 proposal binding | observed_facts unvalidated (task counterexample passes) | mechanical binding turns invented facts into UNKNOWN, cutting hallucinated-evidence FPs | atomic_check_v2.py | offline counterexample regression | 0 (code) | task repro demoted, not established | bind_proposal + N1-1..N1-6 regressions |
| 3 | P0 §3.3 counterevidence contract | shape-only validation, old enum | enum+consistency+bucket checks make INVALID explicit; strategies frozen later | role_pilot.py | offline counterexample regression | 0 (code) | task repro INVALID | counterevidence_validator_v2 |
| 4 | P0 §3.4 gold + 6 deferred misses | def_mixed::01 fabricated quote; 18/24 triples measured | provenance repair (label kept) + completion of 24/24 on the frozen rules | deferred bank v2 | 6 cases × 3 systems | ≤36 | full 24-case dual-F1 table + wording re-check | repair_deferred_gold_v2.py, deferred_completion_pilot.py, score_deferred_completion.py |
| 5 | Prompt variants (§7) | V1 calibrated = best prior (1.0 on role bank) | V2 (no prior, per-tool status) / V2-evidence-first / V2+few-shot ≥ V1 on paired_dev without sealed | prompt_train/paired_dev | 4 variants × one model × 24-case dev subset | ≤120 (+few-shot reuse) | best variant by dual-F1 + explanation audit | role_prompts V2 constants, variant runner |
| 6 | GEPA offline (§7) | NOT_RUN | prompt optimization on prompt_train beats manual V2 on dev | dspy GEPA, prompt_train | ≤6 candidates, internal val by groups | ≤220 (hard cap incl. reflection/metric/repair) | beats manual V2 on paired_dev after freeze | gepa receipts, selected prompt |
| 7 | gpt-oss:20b judge/E (control) | 1.0 dual-F1 role+deferred banks | regression anchor for new banks | prior role matrix | reuse + new-bank regression | cache mostly | stays anchor | prior receipts |
| 8 | gpt-oss-safeguard-20b (§6) | NOT_RUN (new model) | safety-trained BYO-policy J/checker transfers to business preconditions | HF openai/gpt-oss-safeguard-20b + cookbook | native harmony final parser + 2 sanity + 24-case bank | local GPU (12.1G MXFP4, disk-gated) | dual-F1 vs gpt-oss:20b on same cases | safeguard adapter + receipts |
| 9 | PRT qwen2.5-7b (§6) | BLOCKED:disk previously | policy-compliance specialist adds TP on hard cases | HF josephimperial/qwen2.5_7b_all_finetuned_generalist_withpol + repo | native author inference, compliance→ERROR mapping on both labels | local GPU (4-bit ~5G) | any TP gain without FP loss on dev | prt adapter + receipts |
| 10 | CANOE (§6) | NOT_RUN | context-grounded E or J fixes source-conflict FNs | github S1s-Z/CANOE released checkpoint | 12-case diagnostic bank | local GPU | FN repaired on b:true→false family | canoe adapter + receipts |
| 11 | LettuceDetect v2 mmbert + qwen-2b (§11) | NOT_RUN | span-level unsupported/wrong-value localization adds explanation precision | github KRLabsOrg/LettuceDetect, HF lettuceedect-v2-* | 12-case bank + ≥24 claims | local GPU (0.7G + 4.4G) | added value over best chain (with/without graph) | lettuce adapters + span receipts |
| 12 | Bespoke-MiniCheck-7B (§6/§11) | BLOCKED:disk previously | stronger than measured Flan-T5 for Step3/A4 | HF Bespoke-MiniCheck-7B | ≥24 claims from the 12-case bank | local GPU (4-bit in VRAM; disk churn) | claim-level P/R beats Flan-T5 | bespoke adapter + receipts |
| 13 | FactCG + MiniCheck-Flan-T5 (§11) | PILOT_COMPLETE (6-claim bank) | rerun on new bank with INVALID=0 | cached weights | ≥24 claims | local GPU | same-bank comparison vs Bespoke | native_claim_pilot v2 receipts |
| 14 | Granite Guardian native (§11) | granite-local channel used as JSON judge previously | native <score> risk/grounding contract adds independent signal | local granite-guardian-4.1-8b BF16 | 2 sanity (both labels) + 24-case bank + score distribution + threshold frozen on dev | local GPU (16G on disk now; delete after) | any independent-family gain in bundles | granite native adapter + receipts |
| 15 | Graph arms G0–G4 (§8) | §7.B: all 4 arms = C0 on 24 rows | G2 vs G2-linear isolates representation; G4 measures context economy with coverage | evidence_views.py, GraphAPI | 12+12 paired cases incl. countercases | ≤80 | any arm wins dual-F1 or saves context without exception loss | graph arm runner + per-case deltas |
| 16 | Text C1 vs M1/M2/M3 (§9) | M1 = C0 exactly; CCG 19/20 sensitive | partial formalization M3 + explicit fallback beats text on supported fragments | system_v2_pilot.py, ccg_bounds.py | paired cases on supported coverage | ≤60 + offline | M3 ≥ C1 on supported, UNKNOWN honest elsewhere | formal runner receipts |
| 17 | AMR/amrlib (§9) | NOT_RUN | AMR preserves negation/roles/modality on minimal pairs | github bjascob/amrlib | 12 minimal pairs + Step2/Step3 hookup | local GPU/CPU | representation preserves semantics ≥ 10/12 | amr pilot receipts |
| 18 | Z3/Clingo + temporal (§9) | temporal module arithmetic exact, verdicts unchanged | verified applicable-condition + computation separates rule choice from arithmetic | typed_calculations.py | replay 18-case temporal bank + new arms | offline | any verdict change with correct arithmetic only | temporal arms v2 |
| 19 | LPS/action reachability (§9) | NOT_RUN (availability unknown) | bounded trace/goal check for Step4 refusals | project availability check | only if actually installable | offline | refusal coverage gain | lps pilot or BLOCKED note |
| 20 | Sensitivity/refutation (§10) | formal_sensitivity.py partial | competing translations + witness + exception search cuts FP | §10 protocol | paired candidates on dev FPs | ≤60 | FP removed with witness, no TP loss | sensitivity receipts |
| 21 | Atomization A1–A4 (§11) | v2 PILOT_COMPLETE (honest negative advisory) | A4 explanation audit with Lettuce spans upgrades explanation quality | atomic_check_v2.py | 12 cases + claims | ≤40 | explanation factual errors reduced | a4 receipts |
| 22 | FActScore adapted (§11) | NOT_RUN | fine-grained grounding vs our source bank | github shmsw25/FActScore (adapted pipeline, honestly named) | 12 cases | local | grounding signal adds to A4 | factscore adapter receipts |
| 23 | SelfCheckGPT (§12) | bank 3 cases, judge agreement 1.0 | expanded bank: consistent-wrong / diverging / consistent-right cases | selfcheck_bank.py | ≥9 cases × 3 modes | ≤60 | uncertainty flags OUR J errors better than random | selfcheck v2 receipts |
| 24 | RAG-Triad/TruLens (§12) | triad_bank 3 cases (adapter) | context/answer relevance + groundedness on reduced graph inputs diagnoses loss | triad_adapter.py | 6 cases full vs G2/G2-linear/G4 | ≤40 | identifies which reductions lose context | triad v2 receipts |
| 25 | Bundles 1–6 (§13) | NOT_RUN | module interactions: J→R, graph+atom+fact-checker chains, formal+sensitivity, A4 audit | best modules after pilots | per bundle: 12–24 cases same inputs | ≤240 | end-to-end F1 or explanation gain at bounded cost | bundle runner + per-module contribution |
| 26 | Service verification (§16) | R0 default unchanged | experimental configs on POST /v1/check + /health + /ready + JSONL audit | modular service | HTTP/CLI/outage/recovery + resource tests | ≤20 connectivity | honest module trace + UNKNOWN reasons | service receipts |
| 27 | Sealed protocol (§5/§13) | sealed vault built (56 cases, 14 groups, PA-1) | one-pass final measurement of frozen shortlist (≤4 systems) | sealed_vault (keeper-held) | 56 cases × shortlist | ≤224 + reserve | frozen metrics reported once | sealed receipt + limits |
| 28 | BARRED slice (§5) | NOT_RUN | external asymmetric-dispute cases surface annotation defects | github plurai-ai/BARRED | small diagnostic slice with mapping | ≤40 | defect findings on our banks | barred slice receipts |
| 29 | ProverGen/ProverQA slice (§5) | NOT_RUN | proof-skeleton bridge tests NL↔formula semantics | github opendatalab/ProverGen | limited slice + paired counterexamples | offline + ≤20 | bridge mistakes identified | proven receipts |

Execution order (assignment §17): P0 (done, audited AUDIT-N1 PASS_WITH_LIMITS
with N1-1..N1-6 fixed) → 6 deferred misses + raw journal publication →
data banks (prompt_train ≥40, paired_dev ≥48/24 pairs/12 groups) →
model/prompt pilots on identical new inputs → module pilots → bundles →
freeze shortlist → sealed one pass → final audit + push.

Sealed governance: vault /workspace/guardian/results/modular_steps_20261002/
sealed_vault (chmod 700/600, keeper protocol_auditor PA-1, access log
active, soft separation documented in dataset/sealed_manifest.json; the
builder lives in the vault only). Main agent sees metadata only until
freeze. Scorer opens gold only after outputs complete.

Honest-stop rules: a method that cannot run gets BLOCKED:disk/API/runtime
with the concrete blocker and a safe resolution attempt; BLOCKED is never
reported as a negative quality result. No method is closed by "not needed".
