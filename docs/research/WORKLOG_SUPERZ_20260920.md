# SuperZ full-cycle research log — 2026-09-20

Agent identity: `superz` (worktree `agent-workspace/Guardian-superz-fullcycle`,
branch `research/independent-fullcycle-20260920-superz`, base `origin/research/offline-20260919` @ `1755838`).

## Environment facts established this cycle

- Gateway jobs: timeout 1–14400 s, stdout cap 256 KB, Files API ≤512 KB/file, relative
  paths only (cwd = agent-workspace). Jobs run as `guardianagent`.
- `/mnt/data/guardian/secrets/` is root-only → **Mistral API key unavailable to this agent**.
  Independent keyless OpenAI-compatible APIs reachable from the server:
  llm7.io (`default` selector — model rotates: minimax-m2.7 / codestral-latest; ~500K tokens/day),
  pollinations.ai (`openai-fast` = gpt-oss-20b, ~1 req/15 s), blockrun.ai (pool-substituted
  nemotron/llama models, 300 req/hour/IP hard cap). All limits measured, not assumed.
- Local GPU stack validated: Granite Guardian 3.3-8B (16.7 GiB VRAM), NuExtract3-W4A16,
  GLiNER2.5, NLI DeBERTa, BGE-M3 all cached; venv has clingo 5.8.2, langextract, gliner.
- GitHub push unavailable (token redacted in directive; no credentials on server).
  Publishing = commits in the server repo + `git bundle` + local mirror; user must supply
  a token to actually publish to `MYC-A/Guardian-of-Truth`.

## Experiments (public46 = PUBLIC_SEEN unless noted; gold joined post-hoc)

- **E1 offline baseline reproduction** — `--backend none` at my worktree:
  TP12 FP0 FN11 TN23, F1 .6857 — EXACT match with the historical result. Runner works.
- **E3a A1R post-hoc re-anchor** — the frozen Codex A1 records (120 suspicions, 0 anchored
  under the broken offset contract) were re-anchored by a strict but robust anchor
  (unique verbatim quote in exactly one document; document misattribution repaired;
  emphasis-tolerant second pass; model-emitted offsets ignored):
  **95/120 anchored**; case labels TP20 FP19 FN3 TN4, F1 .6452.
  Finding: the anchoring CONTRACT was the defect, not the model signal; but quote
  existence alone does not discriminate TP from FP (19 FP survive anchoring);
  11/19 FP are telecom-domain cases.
- **E2 A0 cross-model judges** (same label-free input, same prompt semantics as the
  Mistral A0 runner):
  - pollinations / gpt-oss-20b: TP17 FP6 FN5 TN11, **F1 .7556** (n=39; 7 long-telecom
    cases FAILED — long-context fragility of the 20B judge);
  - blockrun pool: TP19 FP19 FN3 TN2, F1 .6333 (n=43; high-recall/low-precision profile);
  - llm7 / codestral-latest: TP6 FP2 FN9 TN13, F1 .5217 (n=30 partial; daily token quota
    exhausted mid-run; conservative judge).
  Judge variance across independent models is large; catalog rotation on llm7 means the
  responded model identity must be recorded per call (done in records.jsonl).
- **E7 Granite Guardian local reproduction** (offline candidate):
  standalone TP8 FP0 FN15 TN23, F1 .5161; **OR-baseline TP13 FP0 FN10 TN23, F1 .7222**
  (+1 TP, 0 FP) — EXACT match with history. The offline candidate works from local
  weights in my worktree; `granite_input.csv` prepared by the standard adapter
  (23 eligible, 23 missing-tools abstentions). `run_granite_guardian.py` patched for
  csv field size limit (46-row parquet-derived input).
- **E5 ensemble/agreement analysis** (preliminary, before verification arms):
  - Best single: judge_pollinations F1 .7391 (with missing→0), judge_mistral_codex .7213.
  - **AND (agreement) of two INDEPENDENT judges Mistral × gpt-oss-20b: TP16 FP4 FN7 TN19,
    F1 .7442, precision .80 — beats every single judge.**
  - k-of-3 judges (≥2 positive): TP23 FP16 FN0, F1 .7419 — perfect recall.
  - Correlated-error structure: **FN overlap between any judge pair = 0** (fully
    complementary recall); FP overlap mistral∩pollinations = 4 only (most independent
    pair), blockrun∩mistral = 14 (correlated high-alarm judges).
  - Conclusion so far: judge INDEPENDENCE drives AND-rule gains more than judge strength.
- **E4a fragment-scoped verification (A3)**: 94 positive suspicions verified against the
  anchored ±800-char fragment only (pollinations verifier):
  verdicts 6 CONFIRMED / 18 REFUTED / 69 UNCERTAIN → TP2 FP1 FN21 TN22, F1 .1538.
  **REJECTED as designed**: fragment-only evidence is insufficient to verify violations;
  the gate suppresses almost everything (same failure shape as the original A1 gate).
- E4b full-context cross-model verification (A4): running.
- E6 external AgentHallu DEV (488): blockrun judge in flight (~30% done).
- E3b live A1R generation (offset-free schema): queued after E4b.
- E8 B-direction mutual critique with two full generative models: queued.
- E9 counterfactual robustness (rename/renumber): queued after E6-blockrun.

## Failure analysis additions (this cycle)

- A1's historical failure decomposed: (1) producer contract forced model-computed offsets
  (114/120 wrong) — fixed generically by offset-free schema + system-side unique-quote
  anchoring (E3a/E3b); (2) anchoring is necessary but not sufficient — quote existence
  does not filter FP (19/39 positive cases still FP); (3) fragment-only verification
  starves the verifier (69/94 UNCERTAIN) — full-context verification (A4) is required.
- Keyless-API operational failures: llm7 daily token quota; blockrun 300 req/hour/IP cap
  (min_interval now 13 s); pollinations 7 FAILED long-telecom cases (context length);
  llm7 catalog rotation (model identity varies between sessions).

## 2026-09-21 — session 2 (directive: continue A4/E4 and new architectures)

- **E4/A4 COMPLETED** (full-context cross-model verification, verifier pollinations/gpt-oss-20b,
  producer = frozen Mistral A1R suspicions): verdicts 33 CONFIRMED / 52 REFUTED / 9 tech-fail;
  case-level TP14 FP8 FN9 TN15, precision .6364, recall .6087, F1 .6222.
  Delta vs E3a (unverified anchored suspicions, F1 .6452): eliminated 11 FP, lost 6 TP,
  0 new FP, 0 gained TP. Per-suspicion correctness (case-gold approximation):
  60 likely-correct, 10 wrongly-confirmed, 15 refuted-in-error-case (suspicion itself
  wrong or verifier miss), 9 technical failures. 31 cases carry multiple suspicions;
  10 cases got MIXED verdicts (some confirmed, some refuted) — the verifier discriminates
  suspicions within one case, confirming the CONFIRMED/REFUTED/UNRESOLVED/NO_ERROR
  distinction required by the directive. The earlier "7 CONFIRMED / 9 REFUTED" snapshot
  was a partial state of this same run.
  Conclusion: A4 is a precision filter, not a recall booster: it never invents new
  positives (0 new FP) but refutes 6 true-error cases along with 11 false alarms.
  Full table: outputs/superz_fullcycle/e4_a34_verify/a4_analysis.json.
- Control architectures fixed for this cycle: E1 offline baseline (.6857),
  E3a anchored-unverified (.6452), A0 mistral (.7213), E2 pollinations judge (.7556),
  E5 AND-ensemble (.7442), E7 granite OR-baseline (.7222), E4/A4 (.6222).
- E3b (producer-dependence arm): live offset-free A1R generation on blockrun pool — RUNNING.
- P-extract (policy requirement cards, llm7): RUNNING.
- Next: G (a4g/gjudge), P (pjudge/pgjudge), combos (a4p/a4gp), Q, robustness.

## 2026-09-21 — session 2 (directive: continue A4/E4 and new architectures)

- **E4/A4 COMPLETED** (full-context cross-model verification, verifier pollinations/gpt-oss-20b,
  producer = frozen Mistral A1R suspicions): verdicts 33 CONFIRMED / 52 REFUTED / 9 tech-fail;
  case-level TP14 FP8 FN9 TN15, precision .6364, recall .6087, F1 .6222.
  Delta vs E3a (unverified anchored suspicions, F1 .6452): eliminated 11 FP, lost 6 TP,
  0 new FP, 0 gained TP. Per-suspicion correctness (case-gold approximation):
  60 likely-correct, 10 wrongly-confirmed, 15 refuted-in-error-case (suspicion itself
  wrong or verifier miss), 9 technical failures. 31 cases carry multiple suspicions;
  10 cases got MIXED verdicts (some confirmed, some refuted) — the verifier discriminates
  suspicions within one case, confirming the CONFIRMED/REFUTED/UNRESOLVED/NO_ERROR
  distinction required by the directive. The earlier "7 CONFIRMED / 9 REFUTED" snapshot
  was a partial state of this same run.
  Conclusion: A4 is a precision filter, not a recall booster: it never invents new
  positives (0 new FP) but refutes 6 true-error cases along with 11 false alarms.
  Full table: outputs/superz_fullcycle/e4_a34_verify/a4_analysis.json.
- Control architectures fixed for this cycle: E1 offline baseline (.6857),
  E3a anchored-unverified (.6452), A0 mistral (.7213), E2 pollinations judge (.7556),
  E5 AND-ensemble (.7442), E7 granite OR-baseline (.7222), E4/A4 (.6222).
- E3b (producer-dependence arm): live offset-free A1R generation on blockrun pool — RUNNING.
- P-extract (policy requirement cards, llm7): RUNNING.
- Next: G (a4g/gjudge), P (pjudge/pgjudge), combos (a4p/a4gp), Q, robustness.
