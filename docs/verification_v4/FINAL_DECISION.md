# Verification V4 — final decision (revised after Amendment 2)

**Default stays `guard_adm2` (arm A).** Reason: there is no valid blinded external evidence for any V4 component —
not "V4 lost the external test". The commit-5 verdict "Combined V4 → REJECT" is **withdrawn**: gold v1 of `ext_tau2` equated
tau2 task success with Guardian compliance (≥ 19 of 35 NO_ERROR rows violate an explicit policy rule; causes were tau2 action
diffs). The rescoring on Guardian-compliance gold v2 (Amendment 2) is exploratory because the gold audit was unblinded.

| component | status |
|---|---|
| guard_adm2 (A) | production default (unchanged) |
| DF4 (code extracts → LLM binds operands → code computes) | promising on dev (+1…+3 cc, 0 FP); **external transfer not tested** (τ² never triggers it) |
| typed proof executor (`proof.py`) | architecturally sound (per-leaf verification, code-derived result, UNRESOLVED not ERROR); **not tested externally** |
| Ems deterministic path | insufficient data; SEMANTIC-mode fallbacks produce FP-prone confirmation claims |
| All-target coverage | **structurally useful**: complete coverage, later-call recall 9/9 vs 6–7/9 |
| AT semantic judgement | **noisy**: on v2 +6…+8 binary TP / 0 FP, but only ≈1–3 per rep for the right reason; false confirmation claims (ext_air_043, ext_ret_019) |
| narrow verifier | does not reliably filter semantic FP / wrong-cause accusations |
| V4_mechanical / V4_mech_strict | identical to V4 externally; §5 not met |
| `ext_tau2` gold v1 | invalid for Guardian verdicts; v2 frozen (commit `1c5f7b37`) |

## Next step (not started)
A new blinded external set built from policy-compliance labels (not task success), with prose/computation-heavy moves so DF and
Ems are actually exercised, and with right-reason scoring for AT. No V5 until then.

## Audit (post-processing invariants §11, external runs)
* Inv. 1–4: no violations. Downgrades listed for manual audit (Ems raw VIOLATED → EVIDENCE_NOT_VERIFIED / UNKNOWN_OPERATION /
  NO_TARGET_OPERAND; verifier SUPPORTED → QUOTE_NOT_VERIFIED; AT raw ERROR on ext_air_032 r1 not admitted because no evidence quote
  verified, as inv. 4 requires).
* No V4 code change after commit 3.

## Review process
No subagent tool was available: independent self-review passes were done instead (oracle/selection review, gold-v2 policy
relabelling with per-row facts check, manual reading of every V4 gain accusation against the judge verdicts).
