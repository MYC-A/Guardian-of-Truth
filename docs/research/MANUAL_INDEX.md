# Manual index — 2026-09-19

Read-only audit completed before any design, installation, or experiment work.
This index records documentation status only; historical metrics remain scoped to
their stated commit, data, model, and artifact provenance.

| Path | Format / status | Role and key requirements | Related refs / artifacts |
|---|---|---|---|
| `manual/guardian_new_agent_start_2026-09-19.md` | Markdown, fully read (34 logical lines) | Original start directive: preserve active work; inventory Git/worktrees/outputs before mutation; distinguish the unrelated `semantic-pipeline-v1` and FullArch lines; do not treat corrected closure-off C3, FullArch N5, legacy V7, or E2E as comparable scores. Requires an offline `scripts/predict.py` CSV entrypoint and no precomputed Phi for known cases. | `4639b46` (closure correction), `300dc2e` (witness principle), `0c2bda7` (FullArch N5). |
| `manual/guardian_master_handoff_2026-09-19.md` | Markdown, fully read (283 logical lines) | Evidence register and branch map. Public46 is viewed development data. Formal core must retain `PROVED_ERROR`, `PROVED_NO_ERROR`, `UNRESOLVED`, and `INCONSISTENT` separately from a probabilistic contest decision. Source catalog and object closure require explicit premises. Final package: offline, `id,label`, under 40 GB and about 30 minutes. | Branch tips and reports listed in sections 2, 4, and 8; FullArch source under `experiments/full_architecture_v1/`; historical local outputs under `outputs/full_architecture_v1/`. |
| `manual/connect_server.md` | Markdown, fully read (249 logical lines) | Branch-specific ModelScope operating notes: SSH alias `guardian-modelscope`; remote A10; existing venvs, caches, and model paths; do not alter SSH, keys, environments, or redownload models. It permits only a one-case A5 smoke before any full benchmark and forbids mass Mistral calls without approval. Secrets must only be tested for presence. | `/mnt/data/guardian/Guardian-of-Truth`; `/mnt/data/guardian/venv`; GLiNER sidecar; semantic pipeline sources and `scripts/run_semantic_pipeline_v1.py`. |
| `manual/guardian_new_agent_start_v2_manual_remote.md` (copied from `A:/GIS_Загрузки/`) | Markdown, fully read (72 logical lines) | Later expanded handoff. Requires a manual index, durable research records, remote read-only inventory, no destructive work, offline baseline before new engines, explicit experiment hypothesis/stop rule, and source-to-verdict audit. It makes FullArch frozen-Phi/API dependence and legacy `predict.py` routing priority checks. | Same branch map as master; proposes MiniCheck/LettuceDetect/Granite, Declare/LTLf, Z3, local extraction, and calibrated fallback as unimplemented ablations. |
| `manual/guardian_codex_architectures_v2_2026-09-20.md` | Markdown, fully read; 61,482 bytes; SHA-256 `a12eb81f27f3b7debfdb6cea15b9baaf00b48f429ad94157333454e6457d3bbb` | Defines the controlled BASE/A/B/C comparison. A must emit atomic suspicions with exact source grounding before review. B must compare independently extracted policy theories, preserve unsupported clauses, and use RuleIR/Clingo only after source checks. C is eligible only after separate A/B gains. Requires a common variant/config contract, raw per-case outputs, manifests, PUBLIC_SEEN marking for public46, independently frozen adversarial pairs and a one-time lockbox. | Current Granite and NLI probes are BASE components, not A/B implementations. `620dfa0` adds only the shared exact-span grounding gate; A model generation and B0-B5 comparisons remain not run. |
| `A:/GIS_Загрузки/guardian_master_handoff_2026-09-19.md` | Markdown, fully read; byte-identical SHA-256 to `manual/guardian_master_handoff_2026-09-19.md` | External duplicate of the master handoff; no additional requirements. | SHA-256 prefix `0C32CADCC…`. |

## Confirmed negative or bounded results

- `codex-update-run` F1 `.6061` uses unsupported catalog/object closure. The
  closure-off C3 reconstruction is `TP=3, FP=0, F1=.23077`; it is not a new live
  run. Keep closure off unless a source-backed contract explicitly closes it.
- FullArch `0c2bda7` reports `N0: TP=3, FP=0` and `N5: TP=4, FP=2`. Valid
  certificates only establish the conclusion under the emitted premises, not
  faithful natural-language formalization. Published FullArch depends on frozen
  Mistral-generated Phi and is not a standalone offline hidden-input pipeline.
- The `4e6d200` semantic-pipeline experiment improved relevant retrieval but its
  fresh-cache A8 end-to-end result was `TP=1, FP=0, F1=.0833`; do not promote the
  whole pipeline on retrieval quality alone. The separate `semantic-pipeline-v1`
  branch A5 still requires Mistral in its core.
- Clingo, s(CASP), and Drools each solve 43/43 neutral formal scenarios; this
  does not validate NL extraction or contest F1. SafePyramid log-only results
  include `TP=5, FP=43` over 466 pairs. FOLIO/ProofWriter measure adapter
  representability rather than contest performance.
- ClaimGraph typed gain, Policy-Phi, and Goal frontends failed their stated
  gates; the old decomposition path also failed coverage. Do not retry unchanged.

## Conflicts and precedence notes

- `connect_server.md` is a narrower, older procedure for the separate
  `semantic-pipeline-v1` A5/Mistral smoke. The later v2/master requirements make
  a local/offline final entrypoint mandatory and forbid treating frozen Phi or
  remote API as a final solution. Both remain useful within their scopes.
- The handoff reports a 19 September remote snapshot; it is not evidence of the
  current local checkout, current remote tips, ignored artifacts, or server
  state. Those require read-only verification.
- Server A10 capacity is a research-environment fact. The official 2026 PDF specifies H100 for task one, while the previously viewed task page indicated A100. The task page currently returns HTTP 403; budget for A100 conservatively.
- The original checkout exposes `src/guardian_truth/semantic_pipeline_v1/`. The isolated research worktree from FullArch contains `experiments/full_architecture_v1/`; neither local worktree nor the new server clone has `outputs/full_architecture_v1/`.

## Next independently testable hypotheses

1. Evaluate a compact local claim detector (MiniCheck, LettuceDetect, or Granite
   Guardian) as a calibrated `UNRESOLVED` fallback, separately on claim-only and
   complete contest-shaped input. It must never be rebranded as a proof.
2. Compare Declare/LTLf to the existing formal core only for policy traces with
   time/count/order semantics; record a per-class difference against Clingo.
3. Compare Z3 on numeric/provenance constraints only, preserving source scope
   and allowed transformations. Run imports/license/VRAM checks, 1–3 smoke cases,
   then an independent balanced set before any full run.

## 2026-09-20 architecture-v2 scope correction

- BASE comprises the exact offline detector plus separately measured local
  probabilistic detectors. Granite yes/no output and the claim NLI classifier do
  not satisfy Architecture A because neither emits a reviewed, atomic,
  source-grounded error reason.
- Architecture B is not the existing frozen-Phi N5 path. It requires independent
  theory extraction, exact source spans, clause coverage, disagreement analysis,
  and targeted repair before RuleIR/Clingo. The clean N5 replay being entirely
  `UNRESOLVED` is evidence for keeping this boundary strict.
- No confirmed local Mistral checkpoint exists in the prepared cache. B0 and the
  Mistral BASE judge are therefore `NOT_RUN`; old API-derived Phi is not a local
  substitute. Cached NuExtract3 and GLiNER are candidates for bounded B1/B2
  experiments after a fixed external/adversarial evaluation slice is frozen.
