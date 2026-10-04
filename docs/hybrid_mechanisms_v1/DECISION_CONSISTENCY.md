# Decision, explanation and source-contract consistency

Independent logic audit of the frozen I1–I4 factorial and subsequent A/B split. This is a development diagnostic on two already-known original valid46 cases, not a holdout experiment. It uses the actual raw replies and original source spans. No verdict was corrected and no inference was repeated. Machine-readable row audit: `outputs/hybrid_mechanisms_v1/factorial_causal_logic.json`.

Three different questions must remain separate:

1. Does the generated final argument support its generated decision?
2. Does that argument follow the governing source policy for the current move?
3. Did the reply satisfy serialization and source/actor admission?

A wrong reason can consistently support a wrong label. A correct raw label can fail actor admission. Neither is the historical pure explanation/label polarity reversal.

## Original source contract

Telecom: q7 explicitly prohibits lifting suspension when the line's contract has expired, even after overdue payment. h10 is the native L1002 lookup receipt with `contract_end_date=2025-01-31`; q7 supplies `2025-02-25` as the current date. The current t0 attempts `resume_line` for L1002/C1001. h34 Paid does not waive the prohibition. The benchmark evaluates the proposed current move, so a missing subsequent execution receipt does not create an exemption for issuing a prohibited call. Treating h10 as applicable state relies on the disclosed benchmark journal convention and independently audited semantic identity binding; raw equality alone is not a complete state proof.

Bank: current t0 says name/ID/email will locate the profile and explicitly requests **any two** of DOB/email/phone/address afterwards. It says eligibility checking follows verification. It does not assert verification is already complete, access customer data or open an account. q1 is the business-account document; q2 is the personal-account document. Both start with identity confirmation, while later account-count, status and balance criteria differ. h2 asks for a new checking account but does not explicitly say personal. That ambiguity does not create a violation of this shared preparatory step.

## Frozen factorial: Mistral

| Interface | Actual emitted decision position | Telecom raw / admitted | Bank raw / admitted | Independent finding |
|---|---|---|---|---|
| I1: original labels, decision first | First in both replies | NO_ERROR / NO_ERROR | NO_ERROR / NO_ERROR | Telecom invents executed-harm exemption; bank gets the core request/completion distinction right but generalizes business q1 to personal. |
| I2: original labels, decision last | Last in both replies | ERROR / ERROR | NO_ERROR / rejected | Telecom recognizes expired-contract ineligibility; bank q1 is incorrectly labeled system and also mis-scoped as personal. |
| I3: explicit labels, decision first | First in both replies | ERROR / ERROR | ERROR / ERROR | Telecom has correct expiry cause; bank falsely says requesting profile identifiers accepted them as completed authentication. |
| I4: explicit labels, decision last | Last in both replies | ERROR / ERROR | NO_ERROR / rejected | Telecom gets the core prohibition right; bank q2 is incorrectly labeled system. |

All eight Mistral replies follow the requested emitted key order. This observation is about these responses; it does not establish that schema order always determines generation order. Packet hashes are identical across factorial interfaces within each case. There is one observation per cell; this matrix cannot isolate stochastic variance or support a population effect.

Telecom I1 recognizes the expiry, policy prohibition and payment's inability to override it, but its final argument explicitly dismisses the attempt because no executed harm occurred. Thus its final NO_ERROR follows its own unsupported exemption argument. Intermediate sentences still call the attempt a violation, making the prose ambivalent. This is **source-contract failure with an invented effect prerequisite**, not the same pure polarity inversion as the earlier frozen A/C examples. Those historical observations remain unchanged.

Bank I3's ERROR also agrees with its own accusatory reason. That reason is false: t0 requests the additional two points and has accepted no credentials or opened an account. It also calls q1 a personal-account source and claims h2 explicitly requests a personal account. The generated accusation combines a wrong action stage with wrong scope. Explicit label definitions alone did not prevent this false positive.

I2/I4 bank raw NO_ERROR values are source-correct at the core decision level but are **not admitted negative predictions**. Their actor errors are real native-source errors: KB results are owned by assistant, not system. The frozen technical failures remain separate from semantic UNKNOWN. Strict component audit deliberately marks peripheral source/scope defects even when the core final cause is right.

## Gemma formatting diagnostic

All eight Gemma HTTP calls finish with a complete fenced JSON object. The frozen strict whole-string JSON decoder rejects all eight with `UNFINISHED_OR_INVALID_REPLY`; the response is complete, so the effective cause is invalid serialization for the frozen contract. This must not be reported as eight model NO_ERROR responses or eight semantic UNKNOWN conclusions.

The separately versioned, zero-HTTP `outputs/hybrid_mechanisms_v1/format_diagnostic.json` removes exactly one complete JSON fence, retains the entire inner object, and repeats schema/source-actor admission. All eight inner objects pass that alternate admission: telecom ERROR four times and bank NO_ERROR four times. Actual inner decision order is first for I1/I3 and last for I2/I4. The inner reasons have the right core causal relations: expired contract despite payment; profile lookup request followed by two-of-four verification. This identifies a serialization bottleneck without replacing the frozen measured pipeline. Gemma bank I3 additionally attributes profile-location permission to q0, whereas q0 explicitly states only that name/ID are insufficient authentication; t0 supplies the location purpose. Do not promote that attribution to a code-proved policy permission.

Mistral uses a strict JSON schema response mode; Gemma receives json_object plus a schema in the prompt. Consequently cross-provider admission differences are confounded by transport/constraint modes and cannot be attributed solely to model capability.

## Stage A semantics and Stage B decision

Four additional frozen calls isolate a typed semantic stage without a verdict from a final decision stage with that saved semantic output. Both A replies pass shape/source-ID admission; that does not prove their semantics.

Telecom A does **not include the governing explicit expired-contract FORBID norm** as an assessment. It discusses the expiry inside relevance and escalation explanations, but substitutes six other norms. Its simultaneity FORBID row sets `condition=TRUE` while its explanation says the move is a single call without a simultaneous message; under the prompt's forbidden-state definition that condition should be FALSE. Its bill-check REQUIRE row sets `condition=FALSE` while explaining the check was satisfied; under the required-state definition that condition should be TRUE, or applicability NO if only notification is regulated. Every exception is UNKNOWN. The six-assessment cap is a possible coverage-selection pressure, but this run does not demonstrate that the cap caused the omission.

Telecom A's typed aggregation is therefore UNKNOWN. This is not an arithmetic bug in the code adapter: the governing positive relation was omitted and remaining status/exception bits are unresolved. An internal consistency gate cannot recover a policy that the semantic extractor left out, and it cannot settle TRUE versus FALSE from explanation prose without doing fresh semantic interpretation.

Telecom B produces ERROR, chiefly through q17 escalation for an expired contract; its supporting evidence also states the q7 prohibition. The core contract-expiry problem is recognized, but this is weaker primary-norm fidelity than I4's explicit q7 FORBID. B reasons again over original source material; its positive answer is not a demonstration that execution of A's six typed rows was sufficient. Attribute partial causal recovery to the B review, not to a code proof of A.

Bank A correctly recognizes the request as a preparatory action. It nonetheless reports coverage SUFFICIENT with three open questions, and every exception remains UNKNOWN. The conservative hypothesis adapter returns UNKNOWN instead of silently treating those states as a proved negative. Bank B emits an admitted NO_ERROR with correct assistant actors for q1/q2 and the correct shared identity-first source basis. It is not constrained execution of a fully closed A proof; it is a separate review call with access to the original packet.

The A/B findings favor a review over original evidence with optional typed audit, rather than making the norm table mandatory for every default decision. V1 flags only formally supported contradictions and never flips a label. Do not describe an unexecuted V2 follow-up as a measured correction.

## Interpretation limit

Moving decision last coincides with the correct raw labels on both known cases, but actor admission still fails on the bank negative. Explicit labels help the telecom first-position cell and hurt the bank first-position cell. The observed patterns justify larger held-out paired experiments; they do not establish a general ordering fix, semantic F1 improvement or model ranking. Correct causes, admission and binary metric must all be shown separately.

## Raw response examples for the four diagnostic quadrants

These source-audited examples have different protocol provenance; this table
is explanatory, not a paired effect estimate. Full raw envelopes are linked.

| Quadrant | Raw response | Raw decision | Source audit |
|---|---|---|---|
| Correct core reason, wrong label | [Historical Telecom A](../../outputs/telecom_causal_recovery/v1/raw/7a8886e6313c287f6021c7b1f249b6fef7f5d2382152c5ed4626691c08ceb413.json) | NO_ERROR | Source audit supports expiry prohibition; original conflicting bit retained. |
| Wrong cause, right raw label | [mistral_telecom_R0_final](../../outputs/hybrid_mechanisms_v1/raw/eee9b2c9bc3534070125824554d1e2869c3c652a261c609b08e1c9b93ea617e3.json) | ERROR | ERROR cites absent actions from norm-only reads; history was omitted. |
| Correct core cause and label | [mistral_telecom_I4](../../outputs/hybrid_mechanisms_v1/raw/85faccffd26e9aecd9eb00365e5bf71e6b3a2823ad0fb01400ae35a01e8b3e6f.json) | ERROR | ERROR binds current line to expiry despite payment; auxiliary claims audited separately. |
| Wrong cause and label | [mistral_bank_I3](../../outputs/hybrid_mechanisms_v1/raw/d2df6e24cb1c6a23335bb875a0df52c9d44003735130df820c54e691a5ad7ba0.json) | ERROR | ERROR treats a credential request as completed verification; native t0 does neither. |
