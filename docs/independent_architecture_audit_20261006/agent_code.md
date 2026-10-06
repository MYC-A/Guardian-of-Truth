# Independent V4 implementation audit (2026-10-06)

Scope: HEAD `32ede180`, `verification/{proof,df4,ems,alltarget,v4,verifier}.py`. Read-only production and archive review. No API/SSH/model calls. All input counterexamples below were converted with `verification.pipeline.packet_for(row, 20000)` from the original SYSTEM/ASSISTANT and TOOL_CALL/TOOL_RESPONSE format, not fabricated source IDs disconnected from parsing. Model-stage probes use a deterministic fake client with schema-shaped JSON; this measures admission safety, not a real model's failure rate.

Verification: global Python 3.13, `PYTHONPATH=src`, `python -m pytest tests/test_verification_v4.py -q`: **31 passed**. The recommended old `.venv/Scripts/python.exe` path no longer exists in this environment. The unit suite passing does not test the adversarial semantic bindings below.

## What is reusable

* A bounded typed expression interpreter with independently grounded leaves is a sound way to remove arithmetic/date computation from an LLM. Unknown operands/operations must remain unresolved. Keep this layer as **arithmetic execution**, not a semantic violation certificate.
* Code-owned source and target IDs, source quote/value checking, and complete all-target ID coverage are useful structural admission controls.
* Separate ordinary, raw, mechanical and strict arm projections on one execution record make ablation reproducible. But mechanical certificate strength is overstated below.
* Narrow verification is a useful error filter. It remains a model assessment and should preserve independently uncertain conditions/closure, rather than turn quote presence into proof.

## P1: `code_proven` conflates correct computation with policy truth

`proof.py:130-176` checks typed roles, quote/value presence and at least one current-target operand. It does not require identity/field bindings, guards/exceptions, action applicability, success of observations, freshness or exhaustive operand collection. `ems.py:214` nevertheless marks the resulting accusation `code_proven=True`; `v4.py:115` allows mechanical arms to accept it even when the verifier says **REFUTED**, not just UNRESOLVED.

Parser-compatible reproduced case:

```text
SYSTEM: Use the latest observed address of the same order.
history: TOOL_RESPONSE get_order: {"order_id":"A", "address":"Alpha"}
history: TOOL_RESPONSE get_order: {"order_id":"B", "address":"Beta"}
current: TOOL_CALL ship: {"order_id":"A", "address":"Alpha"}
```

The model plan uses the two literal address leaves as `observed`, and the current address as `value`. `proof.execute(LATEST_VALUE_EQ, ...)` returns `VIOLATED`, detail `latest observed value (h2) = beta; used alpha`. `ems.run` accepts an `origin=Ems, kind=STRUCTURED_PROOF, code_proven=True` candidate. Supplying an explicitly REFUTED verifier gives `A_Ems=0`, **`A_Ems_mech=1`, `V4_mechanical=1`**. Actual same-order requirement is satisfied; the other order's observation is irrelevant. Code checks the selected list's last value, not the latest applicable observation.

Second reproduced case:

```text
SYSTEM: Except when supervisor_override is true, the amount must not exceed 1000.
current: TOOL_CALL transfer: {"amount":1300,"supervisor_override":true}
```

Plan `LE(left=current amount, right=policy 1000)` produces an admitted code_proven violation despite the exact quoted exception. `polarity_error` protects only some comparator direction errors; it does not evaluate the guard.

Fix universally: carry separate statuses for leaf grounding, operand role/entity/field/time binding, exhaustive set selection, applicability/exception checks and expression truth. An arithmetic result is eligible for decisive enforcement only after the other prerequisites have their own supported evidence. Never let `code_proven` overwrite a REFUTED semantic verifier. A deterministic executor cannot establish that an LLM-selected expression is the rule's expression.

## P1: duplicate fact counted twice by changing its quote

`proof.py:148-150` identifies duplicate operands by `(source_id, quote, value)`. Two quotes of the same JSON leaf are treated as two independent amounts.

Reproduced with policy `The total amount must not exceed 1000.` and one current call `TOOL_CALL transfer: {"amount":600}`. Two `term` operands both refer to `t0`, value `600`; one quote is `"amount":600`, the other is the whole tool-call text. Both pass leaf admission. The executor returns **VIOLATED**, `600 + 600 = 1200; 1200 LE 1000 required`. Actual total is 600.

Fix: give atomic observations a code-issued stable identity, e.g. `(event/source, JSON pointer, occurrence)`, and deduplicate aggregation by that identity. Deduplicating only values would wrongly collapse two legitimate transfers of equal amounts. Also prove aggregation completeness and the grouping key (same entity/day/unit/status).

## P1: DF4's copy suppression uses global accidental value matches

`df4.py:200-217`, `df4.py:360`: any date or any number >=10 in any historical tool result makes a current claim `SKIP / CLAIM_VALUE_IN_TOOL_RESULT`. The helper has no field, entity, operation, semantic copy relation or latestness input. A number in an unrelated ID/age/error payload therefore silences a real derivation mismatch.

Reproduced:

```text
SYSTEM: Report subtotal plus tax.
history: TOOL_RESPONSE invoice: {"invoice_id":"A","subtotal":10,"tax":10}
history: TOOL_RESPONSE profile: {"customer_id":"B","age":30}
current prose: Total is 30 EUR.
```

For the correctly grounded binding `ARITHMETIC a+b`, subtotal=10 and tax=10, `evaluate_binding(..., results=[])` returns **MISMATCH**, computed 20. Passing the exact historical tool-result list returns **SKIP** because the unrelated profile includes 30. This is a recall failure unrelated to U2/model arithmetic.

Fix: accept NOT_DERIVED only with a validated source claim-copy relation (same meaning/field/entity/unit/time), or keep both copy and derivation hypotheses for source adjudication. Presence of a value somewhere is not evidence it was copied correctly. Remove the >=10 threshold as a semantic decision; it is a development heuristic.

## P1: strict DF self-checks do not establish that the assistant asserted the expression

`df4.py:118-161` extracts arithmetic/weekday/date patterns without speech-act scope. `df4.py:329-332` turns first mismatch into `code_proven=True, relation_by_code=True`. `v4.py:115` therefore admits it into the strict mechanical arm without semantic verifier support.

Reproduced parser-compatible current prose: **`I reject the incorrect claim 2 + 2 = 5 EUR.`** `df4.run` executes with **zero fake client calls**, emits `INLINE_ARITHMETIC` and reason `The move states "2 + 2 = 5 EUR" ...`. The assistant actually rejects that equality. Quoted examples, user-claim refutations and counterfactual explanations have the same risk.

Fix: separate occurrence of an expression from current assertive claim ownership. Require an assertion/negation/quotation scope certificate, or retain this as a hypothesis for semantic verification. An incorrect equation inside a rejection is not an incorrect assertion.

## P2: real computation bugs

1. **Seconds/timezones lost:** `proof.py:72-77` accepts ISO datetime text but constructs only the date and HH:MM; seconds and UTC offsets are discarded. Parser-compatible policy deadline `2025-01-01T10:00:30`, current call `when=2025-01-01T10:00:10`, exact datetime operands, operation BEFORE returns **VIOLATED**, detail `2025-01-01T10:00:00 BEFORE 2025-01-01T10:00:00`. Actual event is before deadline. Use full precision/timezone-aware parsing; absent timezone is uncertainty when ordering depends on it, not an implicit identical timezone.
2. **ADD/SUB/MUL with zero right operand spuriously fail:** `proof.py:203` constructs a dict containing all four computed operations eagerly, including `a / b`. With verified sources `Use numbers 7 and 0.`, move `7 + 0 = 7 EUR.`, ADD returns **UNRESOLVED / EXEC_ERROR:ZeroDivisionError**. This also affects SUB and MUL when right=0. Select the operation function first and evaluate only that branch.

## Coverage and selection limitations

* DF4 silently slices claims to the first 10 (`df4.py:334`). Ems trusts model requirement extraction and does not enforce one unique plan per admitted requirement. Missing/duplicated requirement assessments do not produce explicit completeness failure. This limits recall even with a good expression executor.
* The executor's target gate is only `any operand.source_id in all current target IDs` (`proof.py:151`). A plan naming t1 can use exclusively t0 current operands and then accuse t1 (`ems.py:213`). At least one current-source leaf is necessary, not sufficient to bind the regulated action.
* LATEST_VALUE_EQ (`proof.py:239-247`) knows only the supplied observations; omission of a newer applicable observation is invisible. Tool results with `ok=false` are not excluded by this interpreter. Source existence never establishes observation success or current truth.
* `df4.py:285-290` permits arbitrary numeric literals in a model expression. It logs them; `df4.py:370` correctly avoids calling such a candidate code_proven, but the literals still lack independent source provenance. A model can invent the equation while quoting genuine unrelated operands. Closed operator enums alone do not solve this.
* `ems.py:181-182` demotes even a correctly grounded arithmetic violation when the plan's extra model status says SATISFIED. This is an intentional conservative binding-disagreement gate, not a computation bug; the resulting binary 0 can become FN. Report that category separately instead of saying the executor failed to compute. Remove model result computation only after operation/applicability binding is independently validated.
* AT coverage validates target IDs but not full obligations for each target. `alltarget.py:58` accepts any one valid evidence piece and silently drops failed pieces. `alltarget.py:61-69` chooses only the first admitted accusation. Ems likewise chooses only `proofs[0]` or `sems[0]` (`ems.py:212/219`). If verifier refutes that candidate, later independently supported candidates are never checked. Fix with an explicit candidate collection and bounded adjudication, and validate every decisive premise while keeping irrelevant unsupported pieces out of the proof.
* The narrow verifier's evidence quote can match any selected source/current target/declaration (`verifier.py:87-95`); matching is not a claim-to-premise relation. Recent history cap4 and nearby-policy cap2 (`verifier.py:26-38`) can omit the actual exception/latest state. Preserve explicit source-closure gaps.

## Interpretation

These are admission counterexamples, not evidence that a live model chooses these plans at a particular rate. They prove the current mechanical certificates are not universal semantic guarantees, and that some deterministic protections themselves cause FP/FN. Improving operands alone is insufficient: evaluate relation binding and assertion/applicability scope separately. Fix the pure computation errors and accidental value suppression first, then replay frozen model plans and measure paired original-task binary changes without reinterpreting old gold. A new holdout with contrasts (unrelated entity, newer value, failure receipt, quote/negation, exception, equal-valued distinct operations, changed time precision) is needed before promoting any mechanical arm.

## Reproduction artifacts and independent replay-script review

Seven asserted counterexamples are saved in `agent_code_probes.py`, with exact parser input, proof/binding plans, execution/candidate outputs in `agent_code_probe_results.json`. Run `python -X utf8 docs/independent_architecture_audit_20261006/agent_code_probes.py --output NEW.json`. This script blocks socket connections/connect_ex and urllib network calls before importing runtime. It uses explicit UTF-8 output and refuses existing report paths. The refusal was rerun against the saved JSON: exit2, report hash unchanged.

Read-only review of root `scripts/independent_architecture_replay.py`:

* Its row input API receives only ID, prompt and response, not gold; metrics load labels after runtime decisions. Existing source inputs, saved model records and gold are read only. No Transport is instantiated and no original experiment CLI is run; only the supplied `StoredReplyClient` handles reviewer calls. The output uses exclusive creation. Existing-output refusal was independently run: exit2, saved `raw_replay.json` hash unchanged.
* The resulting raw report contains472 rows across eight dataset/repetition combinations, including all46 valid rows, and no decision/accusation differences. This is consistent with its assertions and with the stated **raw-reply/request-hash replay** scope.
* Reply collection keys omit transport/provider/attempt indexes, so this does not independently authenticate provider exact-key caches. The report correctly disclaims that stronger claim. Independently scanning these specific472 records found14 repeated request-hash appearances, all with identical raw contents, zero conflicting-content collisions. A future stronger runner should reject conflicting collisions or use an ordered tag/attempt mapping, rather than silently overwrite them.
* The format diagnostic uses exact limited renderer policy phrases and original production-parsed call/prose events. It is intentionally a bounded oracle-rule feasibility test, not automatic semantic grounding. It uses post-hoc gold-v2 and clearly labels this; its F1 cannot be represented as hidden-test improvement.
* The imported legacy `inputs()` uses locale-default `read_text()`. The script documents the need for `PYTHONUTF8=1`; `python -X utf8` also makes this deterministic. A future self-contained runner can read those files with explicit encoding itself. Current confirmed execution used UTF-8 mode.

No blocking correctness issue found in the replay's present bounded claims. Do not strengthen them into fresh-model performance, universal rule detection, independent holdout gains or provider-cache authentication.
