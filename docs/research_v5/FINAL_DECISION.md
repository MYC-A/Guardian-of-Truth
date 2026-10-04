# Decision: NEEDS_MORE_EVIDENCE

**Do not adopt the current automatic grounding variant. No binary F1 improvement
on the original Guardian task has been demonstrated.** The cheap gates produced
a useful methodological correction and two concrete deterministic mechanisms,
but the model pilot failed target/role selection and policy interpretation.
Production, V4 gold and historical predictions remain unchanged. No large run
or fresh holdout follows this negative gate.

## Original-task evidence

Rescoring the same Gemma A0 predictions under the separate complete-process
contract confirms TP10/FP0/FN3 and F1=0.8696, versus original TP7/FP3/FN0 and
F1=0.8235. The three remaining FN are all chronology cases. Gemma actually says
the checks at t1/t2 precede t0, although the trace puts them after it. This is
missed order, not a false-accusation problem. Contract changes are not a model win.

The source-aligned archived Guardian OR Granite valid46 score is still
TP20/FP2/FN3/TN21, F1=0.8889. One-shot 0.6667 was located as an aggregate report;
its per-case snapshot was not recovered. R0 0.9714 belongs to sealed160, not valid46.
The unchanged current R0 service returns 11 ERROR/35 UNKNOWN on valid46 without
network, F1=0.6471 under UNKNOWN→0, because all clean cases exceed its model guard.
Increasing only the outer limit would retain the inner explicit head/tail trim.
A full-source R0 transfer has not been measured.

Under source-grounded oracle annotations, one of the three OR FN is conditionally
recoverable with complete-process closure and a human relevance relation; zero
are recovered under incomplete logs. The hypothetical oracle augmentation is
0.9130, not an automatic result or a global ceiling. The other two annotations
remain unknown because the supplied gold rationales depend on unsupported or
contradicted intent/arguments, plus evidence/query-scope gaps. Other source-grounded
oracle formulations might differ; original labels were not changed.

Separately, an oracle alias/entity receipt view repairs a real expired-line native
fact query and produces the correct violation. This case is already detected by
the archived OR, so it is not another OR FN recovery. The fix is a research view,
with strict original receipt checks retained, not a production patch.

The fresh same-model, same-source pilot has two executed pairs. D0 binary F1=1
but its positive cause is wrong; P3 F1=0 because both replies are UNKNOWN after
invalid target IDs. Both P3 JSON objects pass shape validation and neither passes
candidate admission. It also selects wrong field roles and misses the explicit
expired-contract prohibition. Four HTTP calls cost 72,543 tokens. Full-valid46
automatic quality and independent holdout advantage remain unmeasured.

The combined P3 prompt may also ambiguously restrict native state rules through
its appended process-only instructions. That possible interface flaw has not
been isolated experimentally. The negative result concerns this frozen variant;
it is not a universal verdict on the model or semantic grounding.

## Answers to the 15 V5 questions

1. **Can witness-path errors disappear by construction?** The active wire has no
   recursive Formula/witness path fields; code creates paths. The old path error
   is absent from this interface. That does not remove other structural errors:
   invalid target IDs reject both executed P3 replies.
2. **Can non-policy Formula citations be prevented without relaxing sources?**
   Policy IDs are checked against original policy windows before execution. No
   non-policy citation is admitted. This verifies source role, not entailment;
   P3 cites valid policy lists while contradicting their meaning.
3. **How many correct new relations does the model extract?** Zero automatically
   admitted, applicable native norms in the two executed cases. The one required
   expired-contract norm has recall 0/1. Four raw rule objects are not four correct
   relations. Oracle successes are separate.
4. **Does AND/OR survive?** Code preserves fixed OR-of-AND groups in tests. Model
   Boolean/norm scope correctness is not established; the negative reply attaches
   unsupported account requirements to a request. General NOT is outside this
   active pilot.
5. **Are exceptions preserved?** Code retains scoped exemption uncertainty and
   does not turn permission into prohibition. Automatic scope is not reliable:
   P3 treats bill payment as the sole authorization, missing a prohibition that
   explicitly remains after payment.
6. **Does the model distinguish reading from action?** Not reliably demonstrated.
   The negative has no current native action, but P3 selects a USER source as an
   opening action. The native reply also chooses an argument from the write
   declaration in place of the read alias.
7. **Does it match unknown terms/parameters?** Oracle alias/rename tests work.
   The real automatic alias selection fails. No unseen-domain success is measured.
8. **Does it use other entities as confirmation?** Code rejects mismatched typed
   joins and unrelated result lineage. The model reverses target/result roles and
   invents selectors; rejection is protective, not correct semantic selection.
9. **Late approval versus late immutable observation?** Prior-process chronology
   is correctly checked under both log contracts. The active state checker rejects
   future evidence; the late-immutable exception is unimplemented here. The earlier
   horizon prototype is not evidence of correctness.
10. **Fewer false ERROR on gold UNKNOWN?** No such new metric: valid46 gold is
    binary. P3's UNKNOWN on a negative avoids an accusation but its UNKNOWN on the
    positive creates FN. The six V4 labels have a separate contract sidecar; no
    original gold UNKNOWN was rewritten.
11. **P3 versus D0 on the same data?** On two transport-executed cases including
    admission failures: D0 TP1/TN1, P3 FN1/TN1. Zero fully admitted pairs. D0's TP
    cause is wrong. Neither result is an improvement claim for all 46 rows.
12. **Less semantic complexity or relocation?** Technical tree/path construction
    moved into code; target/field/argument selection and norm scope remain hard.
    The observed date-prohibition and action-scope errors persist independently
    of valid JSON. The current interface has relocated part of the burden rather
    than solving it.
13. **Cost per improvement?** No automatic improvement exists to price. D0 uses
    35,231 tokens, P3 37,312 (+5.91%), with P3 about twice summed HTTP time. Oracle
    code checks use zero model tokens; their annotations are human input, not free
    automatic grounding. No dollar cost is fabricated.
14. **Minimum components to keep?** Complete SourceStore, native target/actor
    inventory, typed joins and strict unique receipts, explicit log contract,
    whole-move coverage/UNKNOWN handling, bounded durable transport, source-hashed
    replay and gold-independent inference. Keep the entity receipt view as a
    tested research component; do not promote the failed automatic mapper.
15. **Independent new-domain confirmation?** None. valid46 is known development;
    V4 fixtures and all oracle controls are disclosed author-controlled data. A
    fresh independently labeled holdout is still required before final advantage
    claims, but this pilot gives no reason to spend its budget now.

## Practical next boundary

Any next version should assign the regulated target in code and constrain candidate
selection, then recheck actual norm scope and roles on source-clear real errors.
That would be a new experiment, not a repair of these replies. It must not invent
the Latin name, substitute the rejected hose, blanket-require every search tool,
or score a proposal as execution. Correct causal recovery and calibrated abstention
take priority over intermediate JSON success. The full atom architecture stays on
hold; current evidence supports neither its adoption nor a universal impossibility
claim about semantic grounding.

Entry points: [binary audit](BINARY_METHOD_AUDIT.md), [oracle results](ORACLE_PROCESS_RESULTS.md),
[model results and costs](MODEL_RESULTS.md), [runbook](RUNBOOK.md).
