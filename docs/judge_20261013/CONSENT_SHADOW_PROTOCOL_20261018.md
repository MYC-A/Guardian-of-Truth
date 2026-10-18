# Confirmation refutation shadow — 18 October 2026

Research candidate only; no submission/runtime changes. Freeze before new model
inference. Inputs are the existing dev520 and seen397 source/receipt pairs.
valid46 is a seen397 subset, not a separate independent sample.

Eligibility is label-blind: original prepass VALID, notes actually DELIVERED,
at least one CONCERN, every CONCERN mentions confirmation/consent/authorization,
all other checks SUPPORTED and no unknowns. Current response must contain exactly
one structurally valid JSON tool call and no other text. Unknown, missing or
ineligible cases retain their baseline label. Recheck source identities against
the original durable primary spool. Neither gold nor baseline correctness selects
which model requests to generate.

Qwen3.6 AWQ pinned00fcea2d, same vLLM/eager/APC/batch16, generationT0 with384
output tokens, input cap49152. One focused verifier receives the complete original
source/current turn and the original allegation as a hypothesis. It must extract
the actual authorized call, quote the immediately preceding assistant offer and
latest user consent, bind IDs/quantities/prices, check revocation/changed plans,
and check other current violations. No field may be silently inferred by code
from a missing output. Invalid/truncated/unknown responses preserve baseline.

Code requires verbatim quotes in the correct source roles and exact typed JSON
equality of authorized vs executed call. It also requires model judgments EXACT,
MATCH or NOT_APPLICABLE for price, no revocation, and NONE_FOUND for other errors.
These semantic judgments remain MODEL HYPOTHESES; quote existence and JSON
equality do not prove that the model interpreted consent correctly. This is why
the experiment remains shadow-only even if the observed TP safety criterion passes.

Apply the veto AFTER the fixed baseline quota(.30/.40), allowing only1→0 and no
replacement positives. Protect all existing hard positives. Report number of FP
cleared, TP lost, untouched rows, effective positive fraction, paired metrics and
family distribution. A failure or UNKNOWN must never replace a result with overall
or a generated NO. Standalone model NO does not clear unrelated violations.

Primary acceptance criterion requested by the user: zero lost TP on dev520 and
removed FP in more than one task family. Check the same paired comparison on
seen397 and valid46. Explicit contrast controls must preserve violations involving
another object, changed amount/quantity, revoked consent, ambiguous approval,
different action, and an independent eligibility failure. These controls are
synthetic diagnostics; viewed examples cannot establish fresh generalization.
If TP loss occurs or FP correction is confined to one family, reject this candidate
and report the exact cases. No retuning on the observed errors in this experiment.

Historical comparison: commit4dda1dd4 contains
`outputs/searh_23/hotel_p/refute_layer_v4_hotel.json`, reporting9of12 FP removed
and0of14 TP lost. Its rule-card pipeline and cases differ; its score is not a
measurement of this candidate. No old script is imported or silently promoted.

Source-only feasibility check before new verifier inference:15 dev notes qualify,
but all15 current responses lack JSON tool calls, so this call-binding candidate
has zero coverage there. On seen397,30 notes qualify and20 meet the structural/
last-offer constraints. Zero TP lost on dev520 would therefore be vacuous; it cannot
establish acceptance. Do not extend the parser to text-only actions after seeing
quality results or report this candidate as universal. Test the20 actual cases and
98 frozen synthetic contrast controls (14 variants of scenario0 in7 domains).
Synthetic controls begin with an artificial suspicion on every row, not measured
Qwen baseline errors; report their TP preservation and correct-call coverage
separately. Skip/UNKNOWN controls keep the artificial positive. They are diagnostics,
not fresh real trajectories or evidence of competition quality. All seeds/controls
are newly authored templates; no dev/valid source or gold enters the seed corpus.
